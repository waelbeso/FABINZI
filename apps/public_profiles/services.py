from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from apps.audit.services import record_audit_event
from apps.organizations.models import Membership, OnboardingApplication, Organization, PublicProfileRevision
from apps.organizations.services import require_org_access
from apps.storefront.models import StoreProduct, Storefront
from .models import ManufacturerCapabilityVerification, ManufacturerPublicProductApproval, ProfessionalPublicState


MANAGE_ROLES = [Membership.Role.OWNER, Membership.Role.MANAGER]


def _approved_application_exists(organization):
    try:
        return organization.onboarding_application.status == OnboardingApplication.Status.APPROVED
    except OnboardingApplication.DoesNotExist:
        return False


def _base_slug(organization):
    value = slugify(organization.display_name or "", allow_unicode=False).strip("-")
    return value[:180] or f"partner-{organization.pk}"


def ensure_public_state(organization):
    try:
        return organization.public_state
    except ProfessionalPublicState.DoesNotExist:
        base = _base_slug(organization)
        candidate = base
        counter = 2
        while ProfessionalPublicState.objects.filter(slug=candidate).exists():
            suffix = f"-{counter}"
            candidate = f"{base[:220-len(suffix)]}{suffix}"
            counter += 1
        return ProfessionalPublicState.objects.create(
            organization=organization,
            slug=candidate,
            public_name_en=organization.display_name,
        )


def is_public_professional(organization, *, kind=None):
    if kind and organization.kind != kind:
        return False
    if organization.verification_status != Organization.VerificationStatus.ACTIVE:
        return False
    if not _approved_application_exists(organization):
        return False
    try:
        state = organization.public_state
    except ProfessionalPublicState.DoesNotExist:
        return False
    return state.visibility == ProfessionalPublicState.Visibility.VISIBLE


def public_professional_queryset(*, kind):
    qs = Organization.objects.filter(
        kind=kind,
        verification_status=Organization.VerificationStatus.ACTIVE,
        onboarding_application__status=OnboardingApplication.Status.APPROVED,
        public_state__visibility=ProfessionalPublicState.Visibility.VISIBLE,
    ).select_related("public_state", "onboarding_application")
    if kind == Organization.Kind.DESIGNER:
        return qs.select_related("designer_profile")
    if kind == Organization.Kind.MANUFACTURER:
        return qs.select_related("manufacturer_profile", "marketplace_listing")
    return qs.none()


@transaction.atomic
def hide_public_profile(*, organization, actor, request=None):
    require_org_access(actor, organization, roles=MANAGE_ROLES)
    state = ensure_public_state(organization)
    previous = state.visibility
    if previous != ProfessionalPublicState.Visibility.HIDDEN:
        state.visibility = ProfessionalPublicState.Visibility.HIDDEN
        state.save(update_fields=["visibility", "updated_at"])
        record_audit_event(
            actor=actor,
            action="public_profile.visibility.hidden",
            instance=state,
            metadata={"organization_id": organization.pk, "previous_visibility": previous},
            request=request,
        )
    return state


@transaction.atomic
def request_public_profile_visibility(*, organization, actor, request=None):
    if (
        organization.verification_status != Organization.VerificationStatus.ACTIVE
        or not _approved_application_exists(organization)
    ):
        raise ValidationError(
            "Only an approved active professional organization may request public visibility."
        )
    require_org_access(actor, organization, roles=MANAGE_ROLES)
    state = ensure_public_state(organization)
    if state.visibility == ProfessionalPublicState.Visibility.VISIBLE:
        return state

    from apps.organizations.public_profile_services import current_public_profile_data, save_public_profile_revision, submit_public_profile_revision

    revision = organization.public_profile_revisions.filter(
        status__in=PublicProfileRevision.EDITABLE_STATUSES
    ).first()
    if revision is None:
        revision = save_public_profile_revision(
            organization=organization,
            actor=actor,
            proposed_data=current_public_profile_data(organization),
            request=request,
        )
    state.visibility = ProfessionalPublicState.Visibility.PENDING_APPROVAL
    state.save(update_fields=["visibility", "updated_at"])
    if revision.status in PublicProfileRevision.EDITABLE_STATUSES:
        submit_public_profile_revision(
            revision=revision,
            actor=actor,
            request=request,
            allow_unchanged_for_visibility=True,
        )
    record_audit_event(
        actor=actor,
        action="public_profile.visibility.requested",
        instance=state,
        metadata={"organization_id": organization.pk, "revision_id": revision.pk},
        request=request,
    )
    return state


def manufacturer_product_approval_is_public(approval):
    from apps.artwork.models import DesignedProduct

    if approval.status != ManufacturerPublicProductApproval.Status.APPROVED or not approval.is_visible:
        return False
    if not is_public_professional(approval.manufacturer, kind=Organization.Kind.MANUFACTURER):
        return False
    product = approval.store_product
    return bool(
        product.status == StoreProduct.Status.PUBLISHED
        and product.storefront.status == Storefront.Status.PUBLISHED
        and product.designed_product.status == DesignedProduct.Status.PUBLISHED
    )


@transaction.atomic
def approve_manufacturer_product(*, manufacturer, store_product, reviewer, notes="", request=None):
    from apps.artwork.models import DesignedProduct

    if not reviewer.is_staff:
        raise PermissionDenied("Staff access required.")
    if (
        manufacturer.kind != Organization.Kind.MANUFACTURER
        or manufacturer.verification_status != Organization.VerificationStatus.ACTIVE
    ):
        raise ValidationError("An active Manufacturer organization is required.")
    if (
        store_product.status != StoreProduct.Status.PUBLISHED
        or store_product.storefront.status != Storefront.Status.PUBLISHED
        or store_product.designed_product.status != DesignedProduct.Status.PUBLISHED
    ):
        raise ValidationError(
            "Only a currently public Store Product backed by a published Ready Designed Product may receive approval."
        )
    approval, _ = ManufacturerPublicProductApproval.objects.get_or_create(
        manufacturer=manufacturer,
        store_product=store_product,
    )
    approval.status = ManufacturerPublicProductApproval.Status.APPROVED
    approval.is_visible = True
    approval.approved_by = reviewer
    approval.approved_at = timezone.now()
    approval.revoked_at = None
    approval.notes = str(notes or "").strip()
    approval.full_clean()
    approval.save()
    record_audit_event(
        actor=reviewer,
        action="public_profile.manufacturer_product.approved",
        instance=approval,
        metadata={"manufacturer_id": manufacturer.pk, "store_product_id": store_product.pk},
        request=request,
    )
    return approval


@transaction.atomic
def revoke_manufacturer_product(*, approval, reviewer, notes="", request=None):
    if not reviewer.is_staff:
        raise PermissionDenied("Staff access required.")
    approval.status = ManufacturerPublicProductApproval.Status.REVOKED
    approval.revoked_at = timezone.now()
    approval.notes = str(notes or approval.notes or "").strip()
    approval.save(update_fields=["status", "revoked_at", "notes", "updated_at"])
    record_audit_event(
        actor=reviewer,
        action="public_profile.manufacturer_product.revoked",
        instance=approval,
        metadata={"manufacturer_id": approval.manufacturer_id, "store_product_id": approval.store_product_id},
        request=request,
    )
    return approval


def approved_manufacturer_products(manufacturer):
    from apps.artwork.models import DesignedProduct

    if not is_public_professional(manufacturer, kind=Organization.Kind.MANUFACTURER):
        return ManufacturerPublicProductApproval.objects.none()
    return ManufacturerPublicProductApproval.objects.filter(
        manufacturer=manufacturer,
        status=ManufacturerPublicProductApproval.Status.APPROVED,
        is_visible=True,
        store_product__status=StoreProduct.Status.PUBLISHED,
        store_product__storefront__status=Storefront.Status.PUBLISHED,
        store_product__designed_product__status=DesignedProduct.Status.PUBLISHED,
    ).select_related(
        "manufacturer__public_state",
        "store_product",
        "store_product__storefront",
        "store_product__designed_product",
    )


@transaction.atomic
def verify_manufacturer_capability(*, capability, canonical_code, reviewer, notes="", request=None):
    if not reviewer.is_staff:
        raise PermissionDenied("Staff access required.")
    if canonical_code not in ManufacturerCapabilityVerification.CanonicalCode.values:
        raise ValidationError("Choose an explicit canonical V2 Manufacturer capability.")
    verification, _ = ManufacturerCapabilityVerification.objects.get_or_create(
        capability=capability,
        canonical_code=canonical_code,
    )
    verification.status = ManufacturerCapabilityVerification.Status.VERIFIED
    verification.verified_by = reviewer
    verification.verified_at = timezone.now()
    verification.revoked_at = None
    verification.notes = str(notes or "").strip()
    verification.full_clean()
    verification.save()
    record_audit_event(
        actor=reviewer,
        action="public_profile.manufacturer_capability.verified",
        instance=verification,
        metadata={
            "manufacturer_id": capability.listing.organization_id,
            "canonical_code": canonical_code,
        },
        request=request,
    )
    return verification


@transaction.atomic
def revoke_manufacturer_capability_verification(*, verification, reviewer, notes="", request=None):
    if not reviewer.is_staff:
        raise PermissionDenied("Staff access required.")
    verification.status = ManufacturerCapabilityVerification.Status.REVOKED
    verification.revoked_at = timezone.now()
    verification.notes = str(notes or verification.notes or "").strip()
    verification.save(update_fields=["status", "revoked_at", "notes", "updated_at"])
    record_audit_event(
        actor=reviewer,
        action="public_profile.manufacturer_capability.revoked",
        instance=verification,
        metadata={
            "manufacturer_id": verification.capability.listing.organization_id,
            "canonical_code": verification.canonical_code,
        },
        request=request,
    )
    return verification


def verified_canonical_capabilities(manufacturer):
    return ManufacturerCapabilityVerification.objects.filter(
        capability__listing__organization=manufacturer,
        capability__is_active=True,
        status=ManufacturerCapabilityVerification.Status.VERIFIED,
    ).select_related("capability").order_by("canonical_code", "id")
