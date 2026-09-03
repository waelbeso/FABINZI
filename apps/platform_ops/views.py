import os
from xml.etree import ElementTree as ET

from django.core.exceptions import ImproperlyConfigured
from django.db import connection
from django.db.models import Prefetch
from django.db.utils import DatabaseError, OperationalError
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.templatetags.static import static
from django.urls import reverse

from config.release import APP_VERSION
from apps.artwork.models import Artwork, ArtworkAsset, ArtworkVersion
from apps.manufacturer_marketplace.models import ManufacturerCapability, ManufacturerListing
from apps.organizations.models import Organization
from apps.storefront.models import StoreProduct, Storefront
from .brand_assets import favicon_ico, icon_png, social_share_png
from .seo import absolute_url, localized_public_url


def _public_home_data():
    products = (
        StoreProduct.objects.filter(
            status=StoreProduct.Status.PUBLISHED,
            storefront__status=Storefront.Status.PUBLISHED,
        )
        .select_related("storefront", "storefront__organization", "designed_product")
        .prefetch_related("images__media_asset", "variants", "designed_product__placements")
        .order_by("-featured", "-published_at", "-updated_at")[:6]
    )
    stores = (
        Storefront.objects.filter(status=Storefront.Status.PUBLISHED)
        .select_related("organization", "logo")
        .order_by("-published_at", "name_en")[:4]
    )

    preview_assets = ArtworkAsset.objects.filter(
        kind=ArtworkAsset.Kind.PREVIEW,
        media_asset__access="public",
    ).select_related("media_asset")
    approved_versions = (
        ArtworkVersion.objects.filter(status=ArtworkVersion.Status.APPROVED)
        .prefetch_related(Prefetch("assets", queryset=preview_assets, to_attr="public_previews"))
        .order_by("-version_number")
    )
    artworks = list(
        Artwork.objects.filter(status=Artwork.Status.APPROVED)
        .select_related("organization")
        .prefetch_related(Prefetch("versions", queryset=approved_versions, to_attr="approved_versions"))
        .order_by("-updated_at")[:4]
    )
    for artwork in artworks:
        artwork.public_preview = None
        artwork.public_suitability = None
        for version in getattr(artwork, "approved_versions", []):
            previews = getattr(version, "public_previews", [])
            if artwork.public_preview is None and previews:
                artwork.public_preview = previews[0]
            # Suitability/use copy is only public when explicitly marked as such
            # in an approved version. We never infer it from internal notes.
            if artwork.public_suitability is None:
                suitability = (version.metadata or {}).get("public_suitability")
                if isinstance(suitability, str) and suitability.strip():
                    artwork.public_suitability = suitability.strip()
                elif isinstance(suitability, list):
                    clean = [str(item).strip() for item in suitability if str(item).strip()]
                    if clean:
                        artwork.public_suitability = " · ".join(clean[:3])
            if artwork.public_preview is not None and artwork.public_suitability is not None:
                break

    public_capabilities = ManufacturerCapability.objects.filter(is_active=True).order_by(
        "capability_type", "name"
    )
    manufacturers = (
        ManufacturerListing.objects.filter(
            status=ManufacturerListing.Status.PUBLISHED,
            organization__verification_status=Organization.VerificationStatus.ACTIVE,
        )
        .select_related("organization")
        .prefetch_related(
            Prefetch("capabilities", queryset=public_capabilities, to_attr="public_capabilities")
        )
        .order_by("organization__display_name")[:4]
    )
    return {
        "featured_products": products,
        "featured_stores": stores,
        "featured_artworks": artworks,
        "featured_manufacturers": manufacturers,
    }


def home(request):
    return render(request, "home.html", _public_home_data())


def placeholder_surface(request, surface):
    return render(request, "surface_placeholder.html", {"surface": surface})


def robots_txt(request):
    lines = [
        "User-agent: *",
        "Allow: /",
        "Disallow: /app/",
        "Disallow: /cart/",
        "Disallow: /checkout/",
        "Disallow: /purchases/",
        "Disallow: /orders/",
        "Disallow: /studio/",
        "Disallow: /media/private/",
        "Disallow: /notifications/",
        "Disallow: /designer/",
        "Disallow: /manufacturer/",
        "Disallow: /finance/",
        "Disallow: /onboarding/",
        "Disallow: /Maneg/",
        "Disallow: /api/",
        "Disallow: /healthz/",
        "Disallow: /readyz/",
        f"Sitemap: {absolute_url('/sitemap.xml')}",
    ]
    response = HttpResponse("\n".join(lines) + "\n", content_type="text/plain; charset=utf-8")
    response["Cache-Control"] = "public, max-age=3600"
    return response


def _sitemap_url(urlset, path, lastmod=None):
    ns = "http://www.w3.org/1999/xhtml"
    node = ET.SubElement(urlset, "url")
    ET.SubElement(node, "loc").text = absolute_url(path)
    if lastmod:
        ET.SubElement(node, "lastmod").text = lastmod.date().isoformat() if hasattr(lastmod, "date") else str(lastmod)
    ET.SubElement(node, f"{{{ns}}}link", {"rel": "alternate", "hreflang": "en", "href": localized_public_url(path, "en")})
    ET.SubElement(node, f"{{{ns}}}link", {"rel": "alternate", "hreflang": "ar", "href": localized_public_url(path, "ar")})
    ET.SubElement(node, f"{{{ns}}}link", {"rel": "alternate", "hreflang": "x-default", "href": absolute_url(path)})


def sitemap_xml(request):
    ET.register_namespace("xhtml", "http://www.w3.org/1999/xhtml")
    urlset = ET.Element("urlset", {"xmlns": "http://www.sitemaps.org/schemas/sitemap/0.9"})
    for name in (
        "home",
        "store-marketplace",
        "artwork",
        "manufacturer-marketplace",
        "about",
        "terms",
        "privacy",
        "returns",
        "shipping",
        "support",
    ):
        _sitemap_url(urlset, reverse(name))

    stores = Storefront.objects.filter(status=Storefront.Status.PUBLISHED).only("slug", "updated_at")
    for store in stores.iterator():
        _sitemap_url(urlset, reverse("public-storefront", args=[store.slug]), store.updated_at)

    products = StoreProduct.objects.filter(
        status=StoreProduct.Status.PUBLISHED,
        storefront__status=Storefront.Status.PUBLISHED,
    ).select_related("storefront").only("slug", "updated_at", "storefront__slug")
    for product in products.iterator():
        _sitemap_url(
            urlset,
            reverse("public-store-product", args=[product.storefront.slug, product.slug]),
            product.updated_at,
        )

    artworks = Artwork.objects.filter(
        status=Artwork.Status.APPROVED,
        versions__status=ArtworkVersion.Status.APPROVED,
    ).distinct().only("id", "updated_at")
    for artwork in artworks.iterator():
        _sitemap_url(urlset, reverse("artwork-detail", args=[artwork.pk]), artwork.updated_at)

    manufacturers = ManufacturerListing.objects.filter(
        status=ManufacturerListing.Status.PUBLISHED,
        organization__verification_status=Organization.VerificationStatus.ACTIVE,
    ).only("id", "updated_at")
    for listing in manufacturers.iterator():
        _sitemap_url(urlset, reverse("manufacturer-public-detail", args=[listing.pk]), listing.updated_at)

    xml = ET.tostring(urlset, encoding="utf-8", xml_declaration=True)
    response = HttpResponse(xml, content_type="application/xml; charset=utf-8")
    response["Cache-Control"] = "public, max-age=1800"
    return response


def site_manifest(request):
    manifest = {
        "name": "FABINZI",
        "short_name": "FABINZI",
        "description": "Designer fashion, distributed manufacturing and optional customer customization.",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#f7f7fb",
        "theme_color": "#6d4aff",
        "icons": [
            {"src": static("brand/fabinzi-icon.svg"), "sizes": "any", "type": "image/svg+xml"},
            {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png"},
        ],
    }
    response = JsonResponse(manifest, json_dumps_params={"ensure_ascii": False})
    response["Content-Type"] = "application/manifest+json"
    response["Cache-Control"] = "public, max-age=86400"
    return response


def _brand_binary(payload, content_type, max_age=604800):
    response = HttpResponse(payload, content_type=content_type)
    response["Cache-Control"] = f"public, max-age={max_age}, immutable"
    response["X-Content-Type-Options"] = "nosniff"
    return response


# Legacy raster compatibility endpoints only. They are not canonical V2 brand
# masters and are never used as master-equivalence evidence.
def favicon(request):
    return _brand_binary(favicon_ico(), "image/x-icon")


def apple_touch_icon(request):
    return _brand_binary(icon_png(180), "image/png")


def site_icon_192(request):
    return _brand_binary(icon_png(192), "image/png")


def site_icon_512(request):
    return _brand_binary(icon_png(512), "image/png")


def social_share_image(request):
    return _brand_binary(social_share_png(), "image/png", max_age=86400)


def handler403(request, exception=None):
    return render(request, "errors/403.html", status=403)


def handler404(request, exception=None):
    return render(request, "errors/404.html", status=404)


def handler500(request):
    return render(request, "errors/500.html", status=500)


def _deployment_identity():
    """Return only non-secret source identity supplied by the hosting runtime."""
    branch = os.environ.get("RENDER_GIT_BRANCH", "").strip()
    commit = os.environ.get("RENDER_GIT_COMMIT", "").strip()
    service = os.environ.get("RENDER_SERVICE_NAME", "").strip()
    if not any((branch, commit, service)):
        return None
    return {"branch": branch, "commit": commit, "service": service}


def healthz(request):
    payload = {"status": "ok", "service": "fabinzi", "version": APP_VERSION}
    deployment = _deployment_identity()
    if deployment is not None:
        payload["deployment"] = deployment
    return JsonResponse(payload)


def readyz(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        return JsonResponse({"status": "ready", "database": "ok"})
    except ImproperlyConfigured:
        diagnostic = "database_configuration"
    except OperationalError:
        diagnostic = "database_unavailable"
    except DatabaseError:
        diagnostic = "database_error"
    except Exception:
        diagnostic = "readiness_check_error"
    return JsonResponse(
        {"status": "not_ready", "database": "error", "diagnostic": diagnostic},
        status=503,
    )
