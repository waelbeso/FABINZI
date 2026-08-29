from django.core.exceptions import PermissionDenied

from .models import Membership, Organization


MANUFACTURER_ROLES = {
    Membership.Role.OWNER,
    Membership.Role.MANAGER,
    Membership.Role.PRODUCTION_MANAGER,
    Membership.Role.OPERATOR,
    Membership.Role.QC,
    Membership.Role.ACCOUNTANT,
}
MANUFACTURER_MANAGE_ROLES = {Membership.Role.OWNER, Membership.Role.MANAGER}
MANUFACTURER_QUOTE_ROLES = {
    Membership.Role.OWNER,
    Membership.Role.MANAGER,
    Membership.Role.PRODUCTION_MANAGER,
}
MANUFACTURER_PRODUCTION_ROLES = {
    Membership.Role.OWNER,
    Membership.Role.MANAGER,
    Membership.Role.PRODUCTION_MANAGER,
    Membership.Role.OPERATOR,
}
MANUFACTURER_QC_ROLES = {
    Membership.Role.OWNER,
    Membership.Role.MANAGER,
    Membership.Role.PRODUCTION_MANAGER,
    Membership.Role.QC,
}
MANUFACTURER_TECHNICAL_VIEW_ROLES = MANUFACTURER_PRODUCTION_ROLES | MANUFACTURER_QC_ROLES
MANUFACTURER_FINANCE_ROLES = {
    Membership.Role.OWNER,
    Membership.Role.MANAGER,
    Membership.Role.ACCOUNTANT,
}


def manufacturer_memberships(user):
    if not user or not user.is_authenticated:
        return Membership.objects.none()
    return (
        Membership.objects.filter(
            user=user,
            is_active=True,
            organization__kind=Organization.Kind.MANUFACTURER,
        )
        .select_related(
            "organization",
            "organization__manufacturer_profile",
            "organization__onboarding_application",
        )
        .order_by("joined_at", "id")
    )


def resolve_manufacturer_membership(request, *, required=False):
    memberships = list(manufacturer_memberships(request.user))
    if not memberships:
        if required:
            raise PermissionDenied("A Manufacturer organization membership is required.")
        return None, memberships

    requested = (
        request.POST.get("organization")
        or request.GET.get("org")
        or request.session.get("manufacturer_organization_id")
    )
    selected = None
    if requested:
        try:
            requested_id = int(requested)
        except (TypeError, ValueError):
            requested_id = None
        if requested_id:
            selected = next(
                (membership for membership in memberships if membership.organization_id == requested_id),
                None,
            )
    if selected is None:
        selected = memberships[0]

    request.session["manufacturer_organization_id"] = selected.organization_id
    return selected, memberships


def manufacturer_context(request, *, required=False):
    membership, memberships = resolve_manufacturer_membership(request, required=required)
    organization = membership.organization if membership else None
    application = getattr(organization, "onboarding_application", None) if organization else None
    return {
        "manufacturer_membership": membership,
        "manufacturer_memberships": memberships,
        "manufacturer_organization": organization,
        "manufacturer_application": application,
        "manufacturer_is_active": bool(
            organization
            and organization.verification_status == Organization.VerificationStatus.ACTIVE
        ),
        "manufacturer_can_manage": bool(
            membership and membership.role in MANUFACTURER_MANAGE_ROLES
        ),
        "manufacturer_can_quote": bool(
            membership and membership.role in MANUFACTURER_QUOTE_ROLES
        ),
        "manufacturer_can_production": bool(
            membership and membership.role in MANUFACTURER_PRODUCTION_ROLES
        ),
        "manufacturer_can_qc": bool(
            membership and membership.role in MANUFACTURER_QC_ROLES
        ),
        "manufacturer_can_view_technical": bool(
            membership and membership.role in MANUFACTURER_TECHNICAL_VIEW_ROLES
        ),
        "manufacturer_can_finance": bool(
            membership and membership.role in MANUFACTURER_FINANCE_ROLES
        ),
    }


def require_active_manufacturer_context(request, *, roles=None):
    context = manufacturer_context(request, required=True)
    organization = context["manufacturer_organization"]
    membership = context["manufacturer_membership"]
    if organization.verification_status != Organization.VerificationStatus.ACTIVE:
        raise PermissionDenied("An approved active Manufacturer organization is required.")
    if roles and membership.role not in set(roles):
        raise PermissionDenied("Your Manufacturer role does not allow this action.")
    return context
