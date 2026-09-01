from urllib.parse import urlparse

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from apps.media.models import MediaAsset
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


def _explicit_public_media_url(asset):
    """Return only an explicitly published delivery URL for a public MediaAsset."""
    if asset.access != MediaAsset.Access.PUBLIC:
        return ""
    value = str((asset.metadata or {}).get("public_url") or "").strip()
    if not value:
        return ""
    if value.startswith("/") and not value.startswith("//"):
        return value
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return value
    return ""


def manufacturer_marketplace(request):
    return render(
        request,
        "manufacturer_marketplace/marketplace.html",
        {
            "listings": _public_listings(),
            "page_seo": page_seo(
                title=_localized(request, "Manufacturers | FABINZI", "المصنّعون | FABINZI"),
                description=_localized(
                    request,
                    "Discover active FABINZI production partners through moderated published profile information, without exposing legacy capability taxonomy or private business data.",
                    "استكشف شركاء الإنتاج النشطين على FABINZI من خلال معلومات ملفات منشورة ومراجعة دون عرض تصنيف القدرات القديم أو بيانات الأعمال الخاصة.",
                ),
            ),
        },
    )


def manufacturer_public_detail(request, pk):
    listing = get_object_or_404(_public_listings(), pk=pk)
    public_portfolio = []
    for item in listing.portfolio_assets.all():
        public_url = _explicit_public_media_url(item.media_asset)
        if public_url:
            public_portfolio.append({"item": item, "url": public_url})
    return render(
        request,
        "manufacturer_marketplace/public_detail.html",
        {
            "listing": listing,
            "public_portfolio": public_portfolio,
            "page_seo": page_seo(
                title=f"{listing.organization.display_name} | FABINZI",
                description=_localized(
                    request,
                    listing.overview_en or "Published production-partner information on FABINZI.",
                    listing.overview_ar or listing.overview_en or "معلومات شريك إنتاج منشورة على FABINZI.",
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
