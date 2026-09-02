from django.http import Http404, HttpResponsePermanentRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from apps.artwork.models import DesignedProduct
from apps.artwork.public import decorate_public_artworks, public_artwork_queryset, public_media_path
from apps.organizations.models import OnboardingApplication, Organization
from apps.platform_ops.seo import absolute_url, page_seo
from apps.storefront.models import StoreProduct, Storefront
from .services import approved_manufacturer_products, public_professional_queryset, verified_canonical_capabilities


def _localized(request, en, ar):
    return ar if getattr(request, "LANGUAGE_CODE", "en") == "ar" else en


def _asset_path(asset):
    return public_media_path(asset) if asset else ""


def _public_products_for_designer(organization):
    return list(
        StoreProduct.objects.filter(
            storefront__organization=organization,
            storefront__status=Storefront.Status.PUBLISHED,
            status=StoreProduct.Status.PUBLISHED,
            designed_product__status=DesignedProduct.Status.PUBLISHED,
        )
        .select_related(
            "storefront",
            "designed_product__garment_version__design",
            "designed_product__artwork_version__artwork",
        )
        .prefetch_related("images__media_asset")
        .order_by("-featured", "-published_at", "-updated_at")[:24]
    )


def designer_directory(request):
    designers = list(public_professional_queryset(kind=Organization.Kind.DESIGNER).order_by("display_name"))
    items = []
    for index, organization in enumerate(designers, 1):
        state = organization.public_state
        name = state.public_name_ar if getattr(request, "LANGUAGE_CODE", "en") == "ar" and state.public_name_ar else state.public_name_en or organization.display_name
        items.append({
            "@type": "ListItem",
            "position": index,
            "name": name,
            "url": absolute_url(reverse("designer-public-detail", args=[state.slug])),
        })
    return render(request, "public_profiles/designer_directory.html", {
        "designers": designers,
        "page_seo": page_seo(
            title=_localized(request, "Designers | FABINZI", "المصممون | FABINZI"),
            description=_localized(request, "Discover FABINZI-approved public Designer profiles independently of Storefront publication.", "اكتشف ملفات المصممين العامة المعتمدة من FABINZI بشكل مستقل عن نشر المتجر."),
            json_ld={"@context": "https://schema.org", "@type": "CollectionPage", "name": _localized(request, "FABINZI Designer Directory", "دليل مصممي FABINZI"), "url": absolute_url(request.path), "mainEntity": {"@type": "ItemList", "itemListElement": items}},
        ),
    })


def designer_public_detail(request, slug):
    organization = get_object_or_404(
        public_professional_queryset(kind=Organization.Kind.DESIGNER),
        public_state__slug=slug,
    )
    state = organization.public_state
    products = _public_products_for_designer(organization)
    artworks = decorate_public_artworks(list(public_artwork_queryset().filter(organization=organization).order_by("-updated_at")[:12]))
    garments, ready_products, garment_ids, ready_ids = [], [], set(), set()
    for product in products:
        designed = product.designed_product
        if designed.pk not in ready_ids:
            ready_ids.add(designed.pk)
            ready_products.append(designed)
        design = designed.garment_version.design
        if design.pk not in garment_ids:
            garment_ids.add(design.pk)
            garments.append(design)
    name = state.public_name_ar if getattr(request, "LANGUAGE_CODE", "en") == "ar" and state.public_name_ar else state.public_name_en or organization.display_name
    bio = state.bio_ar if getattr(request, "LANGUAGE_CODE", "en") == "ar" and state.bio_ar else state.bio_en
    image = _asset_path(state.profile_image)
    return render(request, "public_profiles/designer_detail.html", {
        "designer": organization,
        "public_state": state,
        "public_products": products,
        "public_artworks": artworks,
        "public_garment_designs": garments,
        "public_ready_products": ready_products,
        "profile_image_url": image,
        "cover_image_url": _asset_path(state.cover_image),
        "page_seo": page_seo(
            title=f"{name} | FABINZI",
            description=(bio[:220] if bio else _localized(request, "Approved public Designer profile on FABINZI.", "ملف مصمم عام معتمد على FABINZI.")),
            image=image or None,
            json_ld=[
                {"@context": "https://schema.org", "@type": "Organization", "name": name, "url": absolute_url(request.path), **({"description": bio} if bio else {}), **({"image": absolute_url(image)} if image else {}), **({"address": {"@type": "PostalAddress", "addressLocality": organization.city, "addressRegion": organization.region, "addressCountry": organization.country}} if organization.city or organization.region else {})},
                {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [{"@type": "ListItem", "position": 1, "name": _localized(request, "Designers", "المصممون"), "item": absolute_url(reverse("designer-directory"))}, {"@type": "ListItem", "position": 2, "name": name, "item": absolute_url(request.path)}]},
            ],
        ),
    })


def manufacturer_directory(request):
    manufacturers = list(public_professional_queryset(kind=Organization.Kind.MANUFACTURER).order_by("display_name"))
    items = []
    for index, organization in enumerate(manufacturers, 1):
        state = organization.public_state
        name = state.public_name_ar if getattr(request, "LANGUAGE_CODE", "en") == "ar" and state.public_name_ar else state.public_name_en or organization.display_name
        items.append({"@type": "ListItem", "position": index, "name": name, "url": absolute_url(reverse("manufacturer-public-detail", args=[state.slug]))})
    return render(request, "public_profiles/manufacturer_directory.html", {
        "manufacturers": manufacturers,
        "page_seo": page_seo(
            title=_localized(request, "Manufacturers | FABINZI", "المصنّعون | FABINZI"),
            description=_localized(request, "Discover FABINZI-approved public production partners and explicitly verified canonical capabilities.", "اكتشف شركاء الإنتاج ذوي الملفات العامة المعتمدة والقدرات القياسية الموثقة صراحةً على FABINZI."),
            json_ld={"@context": "https://schema.org", "@type": "CollectionPage", "name": _localized(request, "FABINZI Manufacturer Directory", "دليل مصنّعي FABINZI"), "url": absolute_url(request.path), "mainEntity": {"@type": "ItemList", "itemListElement": items}},
        ),
    })


def manufacturer_public_detail(request, slug):
    organization = get_object_or_404(
        public_professional_queryset(kind=Organization.Kind.MANUFACTURER),
        public_state__slug=slug,
    )
    state = organization.public_state
    listing = getattr(organization, "marketplace_listing", None)
    capabilities = list(verified_canonical_capabilities(organization))
    products = list(approved_manufacturer_products(organization)[:24])
    name = state.public_name_ar if getattr(request, "LANGUAGE_CODE", "en") == "ar" and state.public_name_ar else state.public_name_en or organization.display_name
    overview = ""
    if listing:
        overview = listing.overview_ar if getattr(request, "LANGUAGE_CODE", "en") == "ar" and listing.overview_ar else listing.overview_en
    if not overview:
        overview = state.bio_ar if getattr(request, "LANGUAGE_CODE", "en") == "ar" and state.bio_ar else state.bio_en
    image = _asset_path(state.profile_image)
    return render(request, "public_profiles/manufacturer_detail.html", {
        "manufacturer": organization,
        "public_state": state,
        "listing": listing,
        "verified_capabilities": capabilities,
        "public_product_approvals": products,
        "profile_image_url": image,
        "cover_image_url": _asset_path(state.cover_image),
        "page_seo": page_seo(
            title=f"{name} | FABINZI",
            description=(overview[:220] if overview else _localized(request, "Approved FABINZI production partner profile.", "ملف شريك إنتاج معتمد على FABINZI.")),
            image=image or None,
            json_ld=[
                {"@context": "https://schema.org", "@type": "Organization", "name": name, "url": absolute_url(request.path), **({"description": overview} if overview else {}), **({"image": absolute_url(image)} if image else {}), **({"address": {"@type": "PostalAddress", "addressLocality": organization.city, "addressRegion": organization.region, "addressCountry": organization.country}} if organization.city or organization.region else {})},
                {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [{"@type": "ListItem", "position": 1, "name": _localized(request, "Manufacturers", "المصنّعون"), "item": absolute_url(reverse("manufacturer-marketplace"))}, {"@type": "ListItem", "position": 2, "name": name, "item": absolute_url(request.path)}]},
            ],
        ),
    })


def manufacturer_legacy_redirect(request, pk):
    """Compatibility for historical numeric Manufacturer URLs.

    Once a V2-5 public state is approved and visible, permanently redirect to
    the stable slug. Legacy published listings created before that state exists
    receive a deliberately noindex, minimum-public-data compatibility page so
    accepted pre-V2 URLs do not leak pending/private profile fields or break.
    """
    from apps.manufacturer_marketplace.models import ManufacturerListing

    listing = get_object_or_404(
        ManufacturerListing.objects.select_related("organization", "organization__onboarding_application"),
        pk=pk,
        status=ManufacturerListing.Status.PUBLISHED,
        organization__verification_status=Organization.VerificationStatus.ACTIVE,
        organization__onboarding_application__status=OnboardingApplication.Status.APPROVED,
    )
    organization = listing.organization
    if public_professional_queryset(kind=Organization.Kind.MANUFACTURER).filter(pk=organization.pk).exists():
        return HttpResponsePermanentRedirect(reverse("manufacturer-public-detail", args=[organization.public_state.slug]))
    return render(
        request,
        "public_profiles/manufacturer_legacy_compat.html",
        {"manufacturer": organization, "listing": listing},
    )
