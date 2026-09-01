from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from apps.organizations.models import Membership, Organization
from apps.platform_ops.seo import page_seo
from .models import ManufacturerListing, RFQ, RFQInvitation
from .services import MANUFACTURER_MANAGE_ROLES, get_or_create_listing


def _localized(request, en, ar):
    return ar if getattr(request, "LANGUAGE_CODE", "en") == "ar" else en


def _public_listings():
    return (
        ManufacturerListing.objects.filter(
            status=ManufacturerListing.Status.PUBLISHED,
            organization__verification_status=Organization.VerificationStatus.ACTIVE,
        )
        .select_related("organization")
        .prefetch_related("capabilities", "portfolio_assets__media_asset")
    )


def manufacturer_marketplace(request):
    qs = _public_listings()
    capability = request.GET.get("capability")
    if capability:
        qs = qs.filter(capabilities__capability_type=capability, capabilities__is_active=True).distinct()
    return render(
        request,
        "manufacturer_marketplace/marketplace.html",
        {
            "listings": qs,
            "capability_filter": capability or "",
            "page_seo": page_seo(
                title=_localized(request, "Manufacturers | FABINZI", "المصنّعون | FABINZI"),
                description=_localized(
                    request,
                    "Discover active FABINZI manufacturing partners through explicitly published capability information, without exposing private business contact, capacity or payout data.",
                    "استكشف شركاء التصنيع النشطين على FABINZI من خلال معلومات القدرات المنشورة صراحةً دون كشف بيانات الاتصال أو الطاقة أو الدفع الخاصة.",
                ),
            ),
        },
    )


def manufacturer_public_detail(request, pk):
    listing = get_object_or_404(_public_listings(), pk=pk)
    return render(
        request,
        "manufacturer_marketplace/public_detail.html",
        {
            "listing": listing,
            "page_seo": page_seo(
                title=f"{listing.organization.display_name} | FABINZI",
                description=_localized(
                    request,
                    listing.overview_en or "Published manufacturing capabilities on FABINZI.",
                    listing.overview_ar or listing.overview_en or "قدرات تصنيع منشورة على FABINZI.",
                ),
            ),
        },
    )


@login_required
def manufacturer_marketplace_dashboard(request):
    membership = Membership.objects.filter(user=request.user, is_active=True, organization__kind=Organization.Kind.MANUFACTURER).select_related("organization").first()
    if not membership:
        return render(request, "manufacturer_marketplace/manufacturer_dashboard.html", {"listing": None, "invitations": []})
    listing = get_or_create_listing(organization=membership.organization, actor=request.user) if membership.role in MANUFACTURER_MANAGE_ROLES else getattr(membership.organization, "marketplace_listing", None)
    invitations = RFQInvitation.objects.filter(manufacturer=membership.organization).select_related("rfq", "rfq__designer_organization").order_by("-sent_at")
    return render(request, "manufacturer_marketplace/manufacturer_dashboard.html", {"listing": listing, "invitations": invitations, "organization": membership.organization})


@login_required
def designer_rfq_dashboard(request):
    rfqs = RFQ.objects.filter(designer_organization__memberships__user=request.user, designer_organization__memberships__is_active=True).distinct().prefetch_related("invitations__quote")
    return render(request, "manufacturer_marketplace/designer_rfqs.html", {"rfqs": rfqs})
