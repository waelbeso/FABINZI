from django.core.exceptions import PermissionDenied

from .models import Membership, Organization


DESIGNER_ROLES = {
    Membership.Role.OWNER,
    Membership.Role.MANAGER,
    Membership.Role.DESIGNER,
    Membership.Role.DESIGN_MANAGER,
    Membership.Role.ACCOUNTANT,
}
DESIGNER_MANAGE_ROLES = {Membership.Role.OWNER, Membership.Role.MANAGER}
DESIGNER_CREATIVE_ROLES = {
    Membership.Role.OWNER,
    Membership.Role.MANAGER,
    Membership.Role.DESIGNER,
    Membership.Role.DESIGN_MANAGER,
}
DESIGNER_APPROVAL_ROLES = {
    Membership.Role.OWNER,
    Membership.Role.MANAGER,
    Membership.Role.DESIGN_MANAGER,
}
DESIGNER_FINANCE_ROLES = {
    Membership.Role.OWNER,
    Membership.Role.MANAGER,
    Membership.Role.ACCOUNTANT,
}


def designer_memberships(user):
    if not user or not user.is_authenticated:
        return Membership.objects.none()
    return (
        Membership.objects.filter(
            user=user,
            is_active=True,
            organization__kind=Organization.Kind.DESIGNER,
        )
        .select_related(
            "organization",
            "organization__designer_profile",
            "organization__onboarding_application",
        )
        .order_by("joined_at", "id")
    )


def resolve_designer_membership(request, *, required=False):
    memberships = list(designer_memberships(request.user))
    if not memberships:
        if required:
            raise PermissionDenied("A Designer organization membership is required.")
        return None, memberships

    requested = (
        request.POST.get("organization")
        or request.GET.get("org")
        or request.session.get("designer_organization_id")
    )
    selected = None
    if requested:
        try:
            requested_id = int(requested)
        except (TypeError, ValueError):
            requested_id = None
        if requested_id:
            selected = next(
                (m for m in memberships if m.organization_id == requested_id), None
            )
    if selected is None:
        selected = memberships[0]

    request.session["designer_organization_id"] = selected.organization_id
    return selected, memberships


def designer_context(request, *, required=False):
    membership, memberships = resolve_designer_membership(request, required=required)
    organization = membership.organization if membership else None
    application = (
        getattr(organization, "onboarding_application", None) if organization else None
    )
    return {
        "designer_membership": membership,
        "designer_memberships": memberships,
        "designer_organization": organization,
        "designer_application": application,
        "designer_is_active": bool(
            organization
            and organization.verification_status
            == Organization.VerificationStatus.ACTIVE
        ),
        "designer_can_manage": bool(
            membership and membership.role in DESIGNER_MANAGE_ROLES
        ),
        "designer_can_create": bool(
            membership and membership.role in DESIGNER_CREATIVE_ROLES
        ),
        "designer_can_approve": bool(
            membership and membership.role in DESIGNER_APPROVAL_ROLES
        ),
        "designer_can_finance": bool(
            membership and membership.role in DESIGNER_FINANCE_ROLES
        ),
    }


def require_active_designer_context(request, *, roles=None):
    context = designer_context(request, required=True)
    organization = context["designer_organization"]
    membership = context["designer_membership"]
    if organization.verification_status != Organization.VerificationStatus.ACTIVE:
        raise PermissionDenied("An approved active Designer organization is required.")
    if roles and membership.role not in set(roles):
        raise PermissionDenied("Your Designer role does not allow this action.")
    return context
