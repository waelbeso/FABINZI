import json
from pathlib import Path
from xml.etree import ElementTree as ET

from django.conf import settings
from django.db import connection
from django.db.models import Prefetch
from django.http import FileResponse, HttpResponse, JsonResponse
from django.shortcuts import render
from django.urls import reverse

from apps.artwork.models import Artwork, ArtworkAsset, ArtworkVersion
from apps.manufacturer_marketplace.models import ManufacturerListing
from apps.organizations.models import Organization
from apps.storefront.models import StoreProduct, Storefront
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
        for version in getattr(artwork, "approved_versions", []):
            previews = getattr(version, "public_previews", [])
            if previews:
                artwork.public_preview = previews[0]
                break

    manufacturers = (
        ManufacturerListing.objects.filter(
            status=ManufacturerListing.Status.PUBLISHED,
            organization__verification_status=Organization.VerificationStatus.ACTIVE,
        )
        .select_related("organization")
        .prefetch_related("capabilities")
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
    for name in ("home", "store-marketplace", "artwork", "manufacturer-marketplace"):
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
        "description": "Designer fashion, distributed manufacturing and customer customization.",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#f7f7fb",
        "theme_color": "#6d4aff",
        "icons": [
            {"src": "/static/brand/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/static/brand/icon-512.png", "sizes": "512x512", "type": "image/png"},
        ],
    }
    response = JsonResponse(manifest, json_dumps_params={"ensure_ascii": False})
    response["Content-Type"] = "application/manifest+json"
    response["Cache-Control"] = "public, max-age=86400"
    return response


def favicon(request):
    path = Path(settings.BASE_DIR) / "static" / "brand" / "favicon.ico"
    response = FileResponse(path.open("rb"), content_type="image/x-icon")
    response["Cache-Control"] = "public, max-age=604800, immutable"
    return response


def healthz(request):
    return JsonResponse({"status": "ok", "service": "fabinzi"})


def readyz(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        return JsonResponse({"status": "ready", "database": "ok"})
    except Exception:
        return JsonResponse({"status": "not_ready", "database": "error"}, status=503)
