from xml.etree import ElementTree as ET

from django.http import HttpResponse
from django.shortcuts import render
from django.urls import reverse

from apps.artwork.models import Artwork, ArtworkVersion
from apps.organizations.models import Organization
from apps.public_profiles.services import public_professional_queryset
from apps.storefront.models import StoreProduct, Storefront
from .seo import absolute_url, localized_public_url, page_seo
from .views import _public_home_data


def _localized(request, en, ar):
    return ar if getattr(request, "LANGUAGE_CODE", "en") == "ar" else en


def discover(request):
    context = _public_home_data()
    context["page_seo"] = page_seo(title=_localized(request, "Discover FABINZI | Fashion creation to commerce", "اكتشف FABINZI | من ابتكار الأزياء إلى التجارة"), description=_localized(request, "Discover how FABINZI connects Customers, Designers and qualified Manufacturers while keeping design, artwork, customization and production responsibilities distinct.", "اكتشف كيف تربط FABINZI العملاء والمصممين والمصنعين المؤهلين مع الحفاظ على الفصل بين تصميم القطعة والعمل الفني والتخصيص والإنتاج."), json_ld={"@context": "https://schema.org", "@type": "AboutPage", "name": _localized(request, "Discover FABINZI", "اكتشف FABINZI"), "url": absolute_url(request.path), "isPartOf": {"@type": "WebSite", "name": "FABINZI", "url": absolute_url("/")}})
    return render(request, "home.html", context)


def how_it_works(request):
    return render(request, "how_it_works.html", {"page_seo": page_seo(title=_localized(request, "How FABINZI works | Customers, Designers & Manufacturers", "كيف تعمل FABINZI | العملاء والمصممون والمصنعون"), description=_localized(request, "Understand the distinct Customer, Designer, Manufacturer and FABINZI Platform roles from fashion creation through customization, production and fulfillment.", "تعرّف على الأدوار المنفصلة للعميل والمصمم والمصنع ومنصة FABINZI من ابتكار الأزياء والتخصيص حتى الإنتاج والتنفيذ."), json_ld={"@context": "https://schema.org", "@type": "WebPage", "name": _localized(request, "How FABINZI works", "كيف تعمل FABINZI"), "url": absolute_url(request.path), "about": [{"@type": "Thing", "name": "Fashion design"}, {"@type": "Thing", "name": "Customer customization"}, {"@type": "Thing", "name": "Garment manufacturing"}]})})


def robots_txt(request):
    lines = ["User-agent: *", "Allow: /", "Disallow: /account/", "Disallow: /app/", "Disallow: /cart/", "Disallow: /checkout/", "Disallow: /purchases/", "Disallow: /orders/", "Disallow: /studio/", "Disallow: /media/private/", "Disallow: /inquiry/media/", "Disallow: /inquiry/status/", "Disallow: /notifications/", "Disallow: /designer/", "Disallow: /manufacturer/", "Disallow: /finance/", "Disallow: /onboarding/", "Disallow: /Maneg/", "Disallow: /api/", "Disallow: /healthz/", "Disallow: /readyz/", f"Sitemap: {absolute_url('/sitemap.xml')}"]
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
    for name in ("home", "discover", "how-it-works", "designer-directory", "artwork", "manufacturer-marketplace", "about", "terms", "privacy", "returns", "shipping", "support"):
        _sitemap_url(urlset, reverse(name))
    stores = Storefront.objects.filter(status=Storefront.Status.PUBLISHED, organization__kind=Organization.Kind.DESIGNER, organization__verification_status=Organization.VerificationStatus.ACTIVE).only("slug", "updated_at")
    for store in stores.iterator():
        _sitemap_url(urlset, reverse("public-storefront", args=[store.slug]), store.updated_at)
    products = StoreProduct.objects.filter(status=StoreProduct.Status.PUBLISHED, storefront__status=Storefront.Status.PUBLISHED, storefront__organization__verification_status=Organization.VerificationStatus.ACTIVE).select_related("storefront").only("slug", "updated_at", "storefront__slug")
    for product in products.iterator():
        _sitemap_url(urlset, reverse("public-store-product", args=[product.storefront.slug, product.slug]), product.updated_at)
    artworks = Artwork.objects.filter(status=Artwork.Status.APPROVED, versions__status=ArtworkVersion.Status.APPROVED, versions__assets__media_asset__access="public").distinct().only("id", "updated_at")
    for artwork in artworks.iterator():
        _sitemap_url(urlset, reverse("artwork-detail", args=[artwork.pk]), artwork.updated_at)
    for organization in public_professional_queryset(kind=Organization.Kind.DESIGNER).iterator():
        _sitemap_url(urlset, reverse("designer-public-detail", args=[organization.public_state.slug]), organization.public_state.updated_at)
    for organization in public_professional_queryset(kind=Organization.Kind.MANUFACTURER).iterator():
        _sitemap_url(urlset, reverse("manufacturer-public-detail", args=[organization.public_state.slug]), organization.public_state.updated_at)
    xml = ET.tostring(urlset, encoding="utf-8", xml_declaration=True)
    response = HttpResponse(xml, content_type="application/xml; charset=utf-8")
    response["Cache-Control"] = "public, max-age=1800"
    return response
