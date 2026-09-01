from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from apps.audit.services import record_audit_event
from apps.media.designer_services import require_private_designer_asset
from .models import Membership, OnboardingApplication, Organization, VerificationDocument
from .public_profile_services import (
    current_public_profile_data,
    propose_and_submit_public_profile_update,
)
from .services import require_org_access


@transaction.atomic
def update_active_designer_profile(*, organization, actor, organization_data, profile_data, request=None):
    if organization.kind != Organization.Kind.DESIGNER:
        raise ValidationError("Designer profile updates require a Designer organization.")
    require_org_access(actor, organization, roles=[Membership.Role.OWNER, Membership.Role.MANAGER])
    if organization.verification_status != Organization.VerificationStatus.ACTIVE:
        raise ValidationError("Only an active Designer organization may update its profile here.")

    private_org_fields = {"email", "phone", "address_line1", "address_line2"}
    for field, value in organization_data.items():
        if field in private_org_fields:
            setattr(organization, field, value)
    organization.full_clean(exclude=["created_by"])
    organization.save()

    proposed_public = current_public_profile_data(organization)
    for field in {"display_name", "website", "city", "region", "country"}:
        if field in organization_data:
            proposed_public["organization"][field] = organization_data[field]
    for field in {"studio_name", "portfolio_url", "social_links"}:
        if field in profile_data:
            proposed_public["profile"][field] = profile_data[field]

    revision = propose_and_submit_public_profile_update(
        organization=organization,
        actor=actor,
        proposed_data=proposed_public,
        request=request,
    )
    record_audit_event(
        actor=actor,
        action="designer.profile.updated",
        instance=organization,
        metadata={"organization_id": organization.pk, "public_revision_id": revision.pk if revision else None},
        request=request,
    )
    return organization


def _actor_membership(actor, organization):
    return Membership.objects.filter(organization=organization, user=actor, is_active=True).first()


def _assert_non_owner_team_capacity(*, organization, target):
    if target and target.is_active and target.role != Membership.Role.OWNER:
        return
    from apps.subscriptions.services import entitlement_summary

    summary = entitlement_summary(organization)
    if summary["team_used"] >= summary["team_limit"]:
        raise ValidationError(f"The current plan allows {summary['team_limit']} active/pending subaccount seat(s).")


@transaction.atomic
def secure_add_or_update_member(*, organization, actor, user, role, request=None):
    require_org_access(actor, organization, roles=[Membership.Role.OWNER, Membership.Role.MANAGER])
    actor_membership = _actor_membership(actor, organization)
    target = Membership.objects.filter(organization=organization, user=user).first()

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
def secure_deactivate_member(*, membership, actor, request=None):
    require_org_access(actor, membership.organization, roles=[Membership.Role.OWNER, Membership.Role.MANAGER])
    actor_membership = _actor_membership(actor, membership.organization)
    if membership.role == Membership.Role.OWNER:
        if actor_membership.role != Membership.Role.OWNER:
            raise PermissionDenied("Only an Owner may deactivate an Owner.")
        owner_count = Membership.objects.filter(
            organization=membership.organization,
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


@transaction.atomic
def attach_designer_verification_document(*, application, actor, media_asset, document_type, description="", request=None):
    organization = application.organization
    if organization.kind != Organization.Kind.DESIGNER:
        raise ValidationError("This attachment path is for Designer verification documents only.")
    require_org_access(actor, organization, roles=[Membership.Role.OWNER, Membership.Role.MANAGER])
    if application.status not in {OnboardingApplication.Status.DRAFT, OnboardingApplication.Status.REVISION_REQUIRED}:
        raise ValidationError("Verification documents cannot be changed in the current state.")
    require_private_designer_asset(asset=media_asset, organization=organization, actor=actor)
    document = VerificationDocument(
        application=application,
        media_asset=media_asset,
        document_type=document_type,
        description=description,
    )
    document.full_clean()
    document.save()
    record_audit_event(
        actor=actor,
        action="onboarding.verification_document.attached",
        instance=document,
        metadata={"organization_id": organization.pk, "media_asset_id": media_asset.pk},
        request=request,
    )
    return document
