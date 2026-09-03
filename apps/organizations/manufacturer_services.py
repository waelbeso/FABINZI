from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from apps.audit.services import record_audit_event
from apps.manufacturer_marketplace.models import ManufacturerCapability, ManufacturerListing
from .models import Membership, Organization
from .public_profile_services import (
    current_public_profile_data,
    propose_and_submit_public_profile_update,
)
from .services import require_org_access


def _actor_membership(actor, organization):
    return Membership.objects.filter(organization=organization, user=actor, is_active=True).first()


@transaction.atomic
def update_active_manufacturer_profile(*, organization, actor, organization_data, profile_data, request=None):
    if organization.kind != Organization.Kind.MANUFACTURER:
        raise ValidationError("Manufacturer profile updates require a Manufacturer organization.")
    require_org_access(actor, organization, roles=[Membership.Role.OWNER, Membership.Role.MANAGER])
    if organization.verification_status != Organization.VerificationStatus.ACTIVE:
        raise ValidationError("Only an active Manufacturer organization may update its profile here.")

    private_org_fields = {"email", "phone", "address_line1", "address_line2"}
    for field, value in organization_data.items():
        if field in private_org_fields:
            setattr(organization, field, value)
    organization.full_clean(exclude=["created_by"])
    organization.save()

    profile = organization.manufacturer_profile
    private_profile_fields = {"google_maps_url", "primary_contact_person", "contact_job_title", "whatsapp"}
    for field, value in profile_data.items():
        if field in private_profile_fields:
            setattr(profile, field, value)
    profile.full_clean()
    profile.save()

    proposed_public = current_public_profile_data(organization)
    for field in {"display_name", "website", "city", "region", "country"}:
        if field in organization_data:
            proposed_public["organization"][field] = organization_data[field]
    revision = propose_and_submit_public_profile_update(
        organization=organization,
        actor=actor,
        proposed_data=proposed_public,
        request=request,
    )
    record_audit_event(
        actor=actor,
        action="manufacturer.profile.updated",
        instance=organization,
        metadata={"organization_id": organization.pk, "public_revision_id": revision.pk if revision else None},
        request=request,
    )
    return organization


def _assert_non_owner_team_capacity(*, organization, target):
    if target and target.is_active and target.role != Membership.Role.OWNER:
        return
    from apps.subscriptions.services import entitlement_summary

    summary = entitlement_summary(organization)
    if summary["team_used"] >= summary["team_limit"]:
        raise ValidationError(f"The current plan allows {summary['team_limit']} active/pending subaccount seat(s).")


@transaction.atomic
def secure_manufacturer_member_upsert(*, organization, actor, user, role, request=None):
    if organization.kind != Organization.Kind.MANUFACTURER:
        raise ValidationError("Manufacturer team actions require a Manufacturer organization.")
    require_org_access(actor, organization, roles=[Membership.Role.OWNER, Membership.Role.MANAGER])
    actor_membership = _actor_membership(actor, organization)
    if not actor_membership:
        raise PermissionDenied("Active Manufacturer membership is required.")
    target = Membership.objects.filter(organization=organization, user=user).first()

    allowed_roles = {
        Membership.Role.OWNER,
        Membership.Role.MANAGER,
        Membership.Role.PRODUCTION_MANAGER,
        Membership.Role.OPERATOR,
        Membership.Role.QC,
        Membership.Role.ACCOUNTANT,
    }
    if role not in allowed_roles:
        raise ValidationError("This role is not valid for a Manufacturer organization.")
    if role == Membership.Role.OWNER and actor_membership.role != Membership.Role.OWNER:
        raise PermissionDenied("Only an Owner may grant the Owner role.")
    if target and target.role == Membership.Role.OWNER and role != Membership.Role.OWNER:
        if actor_membership.role != Membership.Role.OWNER:
            raise PermissionDenied("Only an Owner may change another Owner's role.")
        active_owner_count = Membership.objects.filter(
            organization=organization,
            role=Membership.Role.OWNER,
            is_active=True,
        ).count()
        if target.is_active and active_owner_count <= 1:
            raise ValidationError("The last active Owner cannot be changed to another role.")
    if role != Membership.Role.OWNER:
        _assert_non_owner_team_capacity(organization=organization, target=target)

    membership, _ = Membership.objects.get_or_create(
        organization=organization,
        user=user,
        defaults={"role": role, "is_active": True},
    )
    membership.role = role
    membership.is_active = True
    membership.full_clean()
    membership.save()
    record_audit_event(
        actor=actor,
        action="business.member.upserted",
        instance=membership,
        metadata={"organization_id": organization.pk, "user_id": user.pk, "role": role},
        request=request,
    )
    return membership


@transaction.atomic
def secure_manufacturer_member_deactivate(*, membership, actor, request=None):
    organization = membership.organization
    if organization.kind != Organization.Kind.MANUFACTURER:
        raise ValidationError("Manufacturer team actions require a Manufacturer organization.")
    require_org_access(actor, organization, roles=[Membership.Role.OWNER, Membership.Role.MANAGER])
    actor_membership = _actor_membership(actor, organization)
    if not actor_membership:
        raise PermissionDenied("Active Manufacturer membership is required.")
    if membership.role == Membership.Role.OWNER:
        if actor_membership.role != Membership.Role.OWNER:
            raise PermissionDenied("Only an Owner may deactivate an Owner.")
        owner_count = Membership.objects.filter(
            organization=organization,
            role=Membership.Role.OWNER,
            is_active=True,
        ).count()
        if membership.is_active and owner_count <= 1:
            raise ValidationError("The last active Owner cannot be removed.")
    membership.is_active = False
    membership.save(update_fields=["is_active"])
    record_audit_event(
        actor=actor,
        action="business.member.deactivated",
        instance=membership,
        metadata={"organization_id": membership.organization_id, "user_id": membership.user_id},
        request=request,
    )
    return membership


def _manufacturer_listing(organization, actor):
    if organization.kind != Organization.Kind.MANUFACTURER:
        raise ValidationError("Manufacturer capabilities require a Manufacturer organization.")
    require_org_access(actor, organization, roles=[Membership.Role.OWNER, Membership.Role.MANAGER])
    if organization.verification_status != Organization.VerificationStatus.ACTIVE:
        raise ValidationError("Only an active Manufacturer organization may manage capabilities.")
    listing, _ = ManufacturerListing.objects.get_or_create(organization=organization)
    return listing


@transaction.atomic
def create_manufacturer_capability(*, organization, actor, capability_type, name, description="", methods=None, min_quantity=None, max_quantity=None, lead_time_days=None, request=None):
    listing = _manufacturer_listing(organization, actor)
    capability = ManufacturerCapability(
        listing=listing,
        capability_type=capability_type,
        name=str(name or "").strip(),
        description=str(description or "").strip(),
        methods=methods or [],
        min_quantity=min_quantity,
        max_quantity=max_quantity,
        lead_time_days=lead_time_days,
        is_active=True,
    )
    capability.full_clean()
    capability.save()
    record_audit_event(actor=actor, action="manufacturer_marketplace.capability.added", instance=capability, metadata={"organization_id": organization.pk, "listing_id": listing.pk}, request=request)
    return capability


@transaction.atomic
def update_manufacturer_capability(*, capability, actor, data, request=None):
    organization = capability.listing.organization
    _manufacturer_listing(organization, actor)
    editable = {"capability_type", "name", "description", "methods", "min_quantity", "max_quantity", "lead_time_days"}
    for field, value in data.items():
        if field in editable:
            setattr(capability, field, value)
    capability.full_clean()
    capability.save()
    record_audit_event(actor=actor, action="manufacturer_marketplace.capability.updated", instance=capability, metadata={"organization_id": organization.pk}, request=request)
    return capability


@transaction.atomic
def deactivate_manufacturer_capability(*, capability, actor, request=None):
    organization = capability.listing.organization
    _manufacturer_listing(organization, actor)
    capability.is_active = False
    capability.save(update_fields=["is_active"])
    record_audit_event(actor=actor, action="manufacturer_marketplace.capability.deactivated", instance=capability, metadata={"organization_id": organization.pk}, request=request)
    return capability
