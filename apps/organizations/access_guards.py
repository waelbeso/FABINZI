from functools import wraps

from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect

from apps.artwork.models import Artwork, DesignedProduct
from apps.artwork.services import require_artwork_access
from apps.checkout.models import CustomerOrder
from apps.design.models import GarmentDesign
from apps.design.services import require_design_access
from apps.manufacturer_marketplace.models import ManufacturerQuote, RFQ, RFQInvitation
from apps.media.models import MediaAsset
from apps.operations.models import ProductionJob
from apps.operations.services import require_manufacturer_job_access
from apps.public_inquiries.models import PublicInquiry, PublicInquiryAttachment
from apps.storefront.models import StoreProduct

from .designer_context import (
    DESIGNER_MANAGE_ROLES,
    designer_context,
)
from .manufacturer_context import (
    MANUFACTURER_MANAGE_ROLES,
    MANUFACTURER_PRODUCTION_ROLES,
    MANUFACTURER_QC_ROLES,
    MANUFACTURER_QUOTE_ROLES,
    MANUFACTURER_TECHNICAL_VIEW_ROLES,
    manufacturer_context,
)
from .models import Membership, Organization
from .services import require_org_access


TRUSTED_PROFESSIONAL_ORGANIZATION_ATTR = "_fabinzi_trusted_professional_organization"
SAFE_METHODS = {"GET", "HEAD"}


def _portal_name(kind):
    return "designer" if kind == Organization.Kind.DESIGNER else "manufacturer"


def _session_key(kind):
    return (
        "designer_organization_id"
        if kind == Organization.Kind.DESIGNER
        else "manufacturer_organization_id"
    )


def _inactive_response(request, organization, *, media=False):
    if media:
        raise Http404
    if request.method in SAFE_METHODS:
        return redirect(f"/{_portal_name(organization.kind)}/?org={organization.pk}")
    raise PermissionDenied("Professional workspace actions require an active Organization.")


def _membership(user, organization, *, roles=None):
    if not user or not user.is_authenticated:
        raise PermissionDenied("Authentication required.")
    qs = Membership.objects.filter(
        user=user,
        organization=organization,
        is_active=True,
    )
    if roles:
        qs = qs.filter(role__in=set(roles))
    membership = qs.first()
    if not membership:
        raise PermissionDenied("Professional Organization access denied.")
    return membership


def _set_trusted_organization(request, organization):
    setattr(request, TRUSTED_PROFESSIONAL_ORGANIZATION_ATTR, organization)
    if Membership.objects.filter(
        user=request.user,
        organization=organization,
        is_active=True,
    ).exists():
        request.session[_session_key(organization.kind)] = organization.pk


def _authorized_resource_guard(
    view,
    *,
    resolver,
    kind,
    authorizer,
    privacy="404",
    media=False,
    privileged_active_bypass=None,
):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        # Preserve the existing login_required behavior without probing the resource.
        if not getattr(request.user, "is_authenticated", False):
            return view(request, *args, **kwargs)

        resource, organization = resolver(kwargs)
        if not organization or organization.kind != kind:
            raise Http404

        base_membership = Membership.objects.filter(
            user=request.user,
            organization=organization,
            is_active=True,
        ).first()
        privileged = bool(
            privileged_active_bypass and privileged_active_bypass(request.user)
        )

        # A legitimate member of the resource Organization reaches Application
        # Mode before any role-specific operational authorization can execute.
        # This keeps inactive GET/HEAD requests safe and mutation requests blocked
        # before the wrapped professional view can produce business side effects.
        if (
            base_membership
            and not privileged
            and organization.verification_status
            != Organization.VerificationStatus.ACTIVE
        ):
            return _inactive_response(request, organization, media=media)

        try:
            authorizer(request, resource, organization)
        except PermissionDenied as exc:
            # Preserve route privacy for foreign tenants, while retaining the
            # historical 403 semantic for a legitimate same-tenant member whose
            # role is insufficient for the requested professional operation.
            if privacy == "404" and base_membership is None:
                raise Http404 from exc
            raise

        # Authorizers may legitimately grant staff/superuser access without a
        # professional membership. Apply the inactive-state rule only after that
        # authorization succeeds, and preserve explicit privileged bypasses.
        if (
            base_membership is None
            and not privileged
            and organization.verification_status
            != Organization.VerificationStatus.ACTIVE
        ):
            return _inactive_response(request, organization, media=media)

        _set_trusted_organization(request, organization)
        return view(request, *args, **kwargs)

    return wrapped


def _context_guard(view, *, kind):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not getattr(request.user, "is_authenticated", False):
            return view(request, *args, **kwargs)

        context = (
            designer_context(request, required=True)
            if kind == Organization.Kind.DESIGNER
            else manufacturer_context(request, required=True)
        )
        organization = (
            context["designer_organization"]
            if kind == Organization.Kind.DESIGNER
            else context["manufacturer_organization"]
        )
        if organization.verification_status != Organization.VerificationStatus.ACTIVE:
            return _inactive_response(request, organization)
        return view(request, *args, **kwargs)

    return wrapped


def designer_context_guard(view):
    return _context_guard(view, kind=Organization.Kind.DESIGNER)


def manufacturer_context_guard(view):
    return _context_guard(view, kind=Organization.Kind.MANUFACTURER)


def designer_any_active_guard(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not getattr(request.user, "is_authenticated", False):
            return view(request, *args, **kwargs)

        active = Membership.objects.filter(
            user=request.user,
            is_active=True,
            organization__kind=Organization.Kind.DESIGNER,
            organization__verification_status=Organization.VerificationStatus.ACTIVE,
        ).exists()
        if active:
            return view(request, *args, **kwargs)

        context = designer_context(request, required=True)
        return _inactive_response(request, context["designer_organization"])

    return wrapped


def _design(kwargs):
    row = get_object_or_404(
        GarmentDesign.objects.select_related("organization"),
        pk=kwargs["pk"],
    )
    return row, row.organization


def _artwork(kwargs):
    row = get_object_or_404(
        Artwork.objects.select_related("organization"),
        pk=kwargs["pk"],
    )
    return row, row.organization


def _designed_product(kwargs):
    row = get_object_or_404(
        DesignedProduct.objects.select_related("organization"),
        pk=kwargs["pk"],
    )
    return row, row.organization


def _rfq(kwargs):
    row = get_object_or_404(
        RFQ.objects.select_related("designer_organization"),
        pk=kwargs["pk"],
    )
    return row, row.designer_organization


def _store_product(kwargs):
    row = get_object_or_404(
        StoreProduct.objects.select_related("storefront__organization"),
        pk=kwargs["pk"],
    )
    return row, row.storefront.organization


def _inquiry(kwargs):
    row = get_object_or_404(
        PublicInquiry.objects.select_related("target_organization"),
        pk=kwargs["pk"],
    )
    return row, row.target_organization


def _invitation(kwargs):
    row = get_object_or_404(
        RFQInvitation.objects.select_related("manufacturer"),
        pk=kwargs["pk"],
    )
    return row, row.manufacturer


def _quote(kwargs):
    row = get_object_or_404(
        ManufacturerQuote.objects.select_related("invitation__manufacturer"),
        pk=kwargs["pk"],
    )
    return row, row.invitation.manufacturer


def _job(kwargs):
    row = get_object_or_404(
        ProductionJob.objects.select_related("manufacturer"),
        pk=kwargs["pk"],
    )
    if not row.manufacturer_id:
        raise Http404
    return row, row.manufacturer


def _media_job(kwargs):
    row = get_object_or_404(
        ProductionJob.objects.select_related("manufacturer"),
        pk=kwargs["job_id"],
    )
    if not row.manufacturer_id:
        raise Http404
    return row, row.manufacturer


def _member_authorizer(*, roles=None):
    def authorize(request, resource, organization):
        _membership(request.user, organization, roles=roles)

    return authorize


def _design_technical_authorizer(request, design, organization):
    require_design_access(
        request.user,
        design,
        edit=request.method not in SAFE_METHODS,
    )


def _artwork_technical_authorizer(request, artwork, organization):
    require_artwork_access(
        request.user,
        artwork,
        edit=request.method not in SAFE_METHODS,
    )


def _ready_product_authorizer(request, product, organization):
    require_org_access(
        request.user,
        organization,
        roles=[
            Membership.Role.OWNER,
            Membership.Role.MANAGER,
            Membership.Role.DESIGNER,
            Membership.Role.DESIGN_MANAGER,
        ],
    )


def _manufacturer_media_authorizer(request, job, organization):
    require_manufacturer_job_access(
        request.user,
        job,
        roles=MANUFACTURER_TECHNICAL_VIEW_ROLES,
    )


def designer_design_resource_guard(view):
    return _authorized_resource_guard(
        view,
        resolver=_design,
        kind=Organization.Kind.DESIGNER,
        authorizer=_member_authorizer(),
        privacy="404",
    )


def designer_design_technical_resource_guard(view):
    return _authorized_resource_guard(
        view,
        resolver=_design,
        kind=Organization.Kind.DESIGNER,
        authorizer=_design_technical_authorizer,
        privacy="403",
        privileged_active_bypass=lambda user: bool(user.is_staff or user.is_superuser),
    )


def designer_artwork_resource_guard(view):
    return _authorized_resource_guard(
        view,
        resolver=_artwork,
        kind=Organization.Kind.DESIGNER,
        authorizer=_member_authorizer(),
        privacy="404",
    )


def designer_artwork_technical_resource_guard(view):
    return _authorized_resource_guard(
        view,
        resolver=_artwork,
        kind=Organization.Kind.DESIGNER,
        authorizer=_artwork_technical_authorizer,
        privacy="403",
        privileged_active_bypass=lambda user: bool(user.is_staff or user.is_superuser),
    )


def designer_product_resource_guard(view):
    return _authorized_resource_guard(
        view,
        resolver=_designed_product,
        kind=Organization.Kind.DESIGNER,
        authorizer=_member_authorizer(),
        privacy="404",
    )


def designer_ready_product_resource_guard(view):
    return _authorized_resource_guard(
        view,
        resolver=_designed_product,
        kind=Organization.Kind.DESIGNER,
        authorizer=_ready_product_authorizer,
        privacy="403",
        privileged_active_bypass=lambda user: bool(user.is_superuser),
    )


def designer_rfq_resource_guard(view):
    return _authorized_resource_guard(
        view,
        resolver=_rfq,
        kind=Organization.Kind.DESIGNER,
        authorizer=_member_authorizer(),
        privacy="404",
    )


def designer_store_product_resource_guard(view):
    return _authorized_resource_guard(
        view,
        resolver=_store_product,
        kind=Organization.Kind.DESIGNER,
        authorizer=_member_authorizer(),
        privacy="404",
    )


def designer_inquiry_resource_guard(view):
    return _authorized_resource_guard(
        view,
        resolver=_inquiry,
        kind=Organization.Kind.DESIGNER,
        authorizer=_member_authorizer(roles=DESIGNER_MANAGE_ROLES),
        privacy="404",
    )


def manufacturer_inquiry_resource_guard(view):
    return _authorized_resource_guard(
        view,
        resolver=_inquiry,
        kind=Organization.Kind.MANUFACTURER,
        authorizer=_member_authorizer(roles=MANUFACTURER_MANAGE_ROLES),
        privacy="404",
    )


def manufacturer_invitation_resource_guard(view):
    return _authorized_resource_guard(
        view,
        resolver=_invitation,
        kind=Organization.Kind.MANUFACTURER,
        authorizer=_member_authorizer(roles=MANUFACTURER_QUOTE_ROLES),
        privacy="404",
    )


def manufacturer_quote_resource_guard(view):
    return _authorized_resource_guard(
        view,
        resolver=_quote,
        kind=Organization.Kind.MANUFACTURER,
        authorizer=_member_authorizer(roles=MANUFACTURER_QUOTE_ROLES),
        privacy="404",
    )


def _manufacturer_job_guard(view, *, roles):
    return _authorized_resource_guard(
        view,
        resolver=_job,
        kind=Organization.Kind.MANUFACTURER,
        authorizer=_member_authorizer(roles=roles),
        privacy="404",
    )


def manufacturer_job_resource_guard(view):
    return _manufacturer_job_guard(view, roles=MANUFACTURER_TECHNICAL_VIEW_ROLES)


def manufacturer_qc_resource_guard(view):
    return _manufacturer_job_guard(view, roles=MANUFACTURER_QC_ROLES)


def manufacturer_production_resource_guard(view):
    return _manufacturer_job_guard(view, roles=MANUFACTURER_PRODUCTION_ROLES)


def manufacturer_media_resource_guard(view):
    return _authorized_resource_guard(
        view,
        resolver=_media_job,
        kind=Organization.Kind.MANUFACTURER,
        authorizer=_manufacturer_media_authorizer,
        privacy="404",
        media=True,
        privileged_active_bypass=lambda user: bool(user.is_staff),
    )


def private_designer_media_guard(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not getattr(request.user, "is_authenticated", False):
            return view(request, *args, **kwargs)

        asset = get_object_or_404(
            MediaAsset,
            pk=kwargs["pk"],
            access=MediaAsset.Access.PRIVATE,
        )
        metadata = asset.metadata or {}
        if not metadata.get("designer_private_upload"):
            raise Http404
        try:
            organization_id = int(metadata.get("organization_id"))
        except (TypeError, ValueError):
            raise Http404
        organization = get_object_or_404(
            Organization,
            pk=organization_id,
            kind=Organization.Kind.DESIGNER,
        )

        privileged = bool(request.user.is_staff or request.user.is_superuser)
        if not privileged:
            try:
                _membership(request.user, organization)
            except PermissionDenied as exc:
                raise Http404 from exc
            if (
                organization.verification_status
                != Organization.VerificationStatus.ACTIVE
                and str(metadata.get("purpose") or "") != "verification"
            ):
                raise Http404

        return view(request, *args, **kwargs)

    return wrapped


def order_operations_professional_guard(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not getattr(request.user, "is_authenticated", False):
            return view(request, *args, **kwargs)

        order = get_object_or_404(
            CustomerOrder.objects.select_related(
                "designer_organization",
                "production_job__manufacturer",
            ),
            pk=kwargs["pk"],
        )
        if request.user.is_staff or order.customer_id == request.user.pk:
            return view(request, *args, **kwargs)

        organization_ids = [order.designer_organization_id]
        try:
            manufacturer_id = order.production_job.manufacturer_id
        except ProductionJob.DoesNotExist:
            manufacturer_id = None
        if manufacturer_id:
            organization_ids.append(manufacturer_id)

        active_access = Membership.objects.filter(
            user=request.user,
            is_active=True,
            organization_id__in=organization_ids,
            organization__verification_status=Organization.VerificationStatus.ACTIVE,
        ).exists()
        if not active_access:
            raise PermissionDenied("Active professional Organization access is required.")
        return view(request, *args, **kwargs)

    return wrapped


def _session_inquiry_reference(request, inquiry):
    return str(inquiry.reference) in set(request.session.get("public_inquiry_refs") or [])


def public_inquiry_status_professional_guard(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        inquiry = get_object_or_404(
            PublicInquiry.objects.select_related("target_organization", "sender_user"),
            reference=kwargs["reference"],
        )
        user = getattr(request, "user", None)
        if user and user.is_authenticated:
            if user.is_staff or inquiry.sender_user_id == user.pk:
                return view(request, *args, **kwargs)
        if _session_inquiry_reference(request, inquiry):
            return view(request, *args, **kwargs)

        if user and user.is_authenticated:
            membership = Membership.objects.filter(
                user=user,
                organization=inquiry.target_organization,
                is_active=True,
                role__in=(
                    DESIGNER_MANAGE_ROLES
                    if inquiry.target_organization.kind == Organization.Kind.DESIGNER
                    else MANUFACTURER_MANAGE_ROLES
                ),
            ).first()
            if membership:
                organization = inquiry.target_organization
                if organization.verification_status != Organization.VerificationStatus.ACTIVE:
                    return _inactive_response(request, organization)
                return view(request, *args, **kwargs)
        raise Http404

    return wrapped


def public_inquiry_media_professional_guard(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        attachment = get_object_or_404(
            PublicInquiryAttachment.objects.select_related(
                "inquiry__target_organization",
                "inquiry__sender_user",
            ),
            pk=kwargs["pk"],
        )
        inquiry = attachment.inquiry
        user = getattr(request, "user", None)
        if user and user.is_authenticated:
            if user.is_staff or inquiry.sender_user_id == user.pk:
                return view(request, *args, **kwargs)
        if _session_inquiry_reference(request, inquiry):
            return view(request, *args, **kwargs)

        if user and user.is_authenticated:
            roles = (
                DESIGNER_MANAGE_ROLES
                if inquiry.target_organization.kind == Organization.Kind.DESIGNER
                else MANUFACTURER_MANAGE_ROLES
            )
            if Membership.objects.filter(
                user=user,
                organization=inquiry.target_organization,
                is_active=True,
                role__in=roles,
            ).exists():
                if (
                    inquiry.target_organization.verification_status
                    != Organization.VerificationStatus.ACTIVE
                ):
                    raise Http404
                return view(request, *args, **kwargs)
        raise Http404

    return wrapped
