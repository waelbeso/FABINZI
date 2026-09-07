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

DESIGNER_ROUTE_SECTIONS = {
    "designer": "overview",
    "designer-profile": "profile",
    "designer-public-profile": "public-profile",
    "designer-public-inquiries": "public-inquiries",
    "designer-public-inquiry-detail": "public-inquiries",
    "designer-team": "team",
    "designer-design-list": "designs",
    "designer-design-detail": "designs",
    "designer-design-technical-v2-4": "designs",
    "designer-artworks": "artwork",
    "designer-artwork-detail": "artwork",
    "designer-artwork-technical-v2-4": "artwork",
    "designer-products": "products",
    "designer-product-detail": "products",
    "designer-ready-product-composer-v2-4": "products",
    "designer-ready-product-composer-detail-v2-4": "products",
    "designer-rfqs": "rfqs",
    "designer-rfq-detail": "rfqs",
    "designer-store": "store",
    "designer-store-product": "store",
    "designer-fulfillment": "fulfillment",
    "designer-finance": "finance",
    "designer-subscription": "subscription",
    "designer-notifications": "notifications",
}


def designer_active_section(request):
    match = getattr(request, "resolver_match", None)
    return DESIGNER_ROUTE_SECTIONS.get(getattr(match, "url_name", None))


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

    trusted = getattr(
        request,
        "_fabinzi_trusted_professional_organization",
        None,
    )
    if trusted is not None:
        if trusted.kind != Organization.Kind.DESIGNER:
            raise PermissionDenied("Trusted professional Organization type mismatch.")
        selected = next(
            (
                membership
                for membership in memberships
                if membership.organization_id == trusted.pk
            ),
            None,
        )
        if selected is None:
            raise PermissionDenied(
                "Trusted Designer resource Organization membership is required."
            )
    else:
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
                    (
                        membership
                        for membership in memberships
                        if membership.organization_id == requested_id
                    ),
                    None,
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
        "designer_active_section": designer_active_section(request),
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
