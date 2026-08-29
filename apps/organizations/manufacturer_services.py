from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from apps.audit.services import record_audit_event
from .models import Membership, Organization
from .services import require_org_access


def _actor_membership(actor, organization):
    return Membership.objects.filter(
        organization=organization,
        user=actor,
        is_active=True,
    ).first()


@transaction.atomic
def update_active_manufacturer_profile(
    *, organization, actor, organization_data, profile_data, request=None
):
    if organization.kind != Organization.Kind.MANUFACTURER:
        raise ValidationError("Manufacturer profile updates require a Manufacturer organization.")
    require_org_access(
        actor,
        organization,
        roles=[Membership.Role.OWNER, Membership.Role.MANAGER],
    )
    if organization.verification_status != Organization.VerificationStatus.ACTIVE:
        raise ValidationError("Only an active Manufacturer organization may update its live profile here.")

    editable_org_fields = {
        "display_name",
        "email",
        "phone",
        "website",
        "address_line1",
        "address_line2",
        "city",
        "region",
        "country",
    }
    for field, value in organization_data.items():
        if field in editable_org_fields:
            setattr(organization, field, value)
    organization.full_clean(exclude=["created_by"])
    organization.save()

    profile = organization.manufacturer_profile
    editable_profile_fields = {
        "google_maps_url",
        "primary_contact_person",
        "contact_job_title",
        "whatsapp",
    }
    for field, value in profile_data.items():
        if field in editable_profile_fields:
            setattr(profile, field, value)
    profile.full_clean()
    profile.save()
    record_audit_event(
        actor=actor,
        action="manufacturer.profile.updated",
        instance=organization,
        metadata={"organization_id": organization.pk},
        request=request,
    )
    return organization


@transaction.atomic
def secure_manufacturer_member_upsert(
    *, organization, actor, user, role, request=None
):
    if organization.kind != Organization.Kind.MANUFACTURER:
        raise ValidationError("Manufacturer team actions require a Manufacturer organization.")
    require_org_access(
        actor,
        organization,
        roles=[Membership.Role.OWNER, Membership.Role.MANAGER],
    )
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
        metadata={
            "organization_id": organization.pk,
            "user_id": user.pk,
            "role": role,
        },
        request=request,
    )
    return membership


@transaction.atomic
def secure_manufacturer_member_deactivate(*, membership, actor, request=None):
    organization = membership.organization
    if organization.kind != Organization.Kind.MANUFACTURER:
        raise ValidationError("Manufacturer team actions require a Manufacturer organization.")
    require_org_access(
        actor,
        organization,
        roles=[Membership.Role.OWNER, Membership.Role.MANAGER],
    )
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
        metadata={
            "organization_id": membership.organization_id,
            "user_id": membership.user_id,
        },
        request=request,
    )
    return membership
