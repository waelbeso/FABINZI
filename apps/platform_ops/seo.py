import json
from urllib.parse import urlencode

from django.conf import settings

INDEXABLE_URL_NAMES = {
    "home",
    "discover",
    "how-it-works",
    "designer-directory",
    "designer-public-detail",
    "public-storefront",
    "public-store-product",
    "artwork",
    "artwork-detail",
    "manufacturer-marketplace",
    "manufacturer-public-detail",
    "about",
    "terms",
    "privacy",
    "returns",
    "shipping",
    "support",
}

DEFAULT_DESCRIPTIONS = {
    "en": "Discover fashion, approved Artwork, optional customer customization and qualified production on FABINZI, where Customers, Designers and Manufacturers keep distinct roles.",
    "ar": "اكتشف الأزياء والأعمال الفنية المعتمدة والتخصيص الاختياري والإنتاج المؤهل على FABINZI، مع الحفاظ على الأدوار المنفصلة للعملاء والمصممين والمصنعين.",
}

PUBLIC_PAGE_SEO = {
    "home": {"en": ("FABINZI Store | Fashion, ready designs & customization", "Shop the FABINZI catalog, including published fashion products, ready-designed products and optional customization where the product is eligible."), "ar": ("متجر FABINZI | أزياء وتصميمات جاهزة وتخصيص", "تسوّق كتالوج FABINZI من منتجات الأزياء المنشورة والتصميمات الجاهزة والتخصيص الاختياري عندما يكون المنتج مؤهلًا.")},
    "discover": {"en": ("Discover FABINZI | Fashion creation to commerce", "Discover the FABINZI ecosystem for Customers, Designers and qualified Manufacturers."), "ar": ("اكتشف FABINZI | من ابتكار الأزياء إلى التجارة", "اكتشف منظومة FABINZI للعملاء والمصممين والمصنعين المؤهلين.")},
    "how-it-works": {"en": ("How FABINZI works | Customers, Designers & Manufacturers", "See how FABINZI keeps garment design, Artwork, customer customization and manufacturing responsibilities distinct."), "ar": ("كيف تعمل FABINZI | العملاء والمصممون والمصنعون", "تعرّف على فصل تصميم الملابس والعمل الفني وتخصيص العميل ومسؤوليات التصنيع داخل FABINZI.")},
    "designer-directory": {"en": ("Designers | FABINZI", "Discover active FABINZI-approved public Designer profiles; Storefront publication is not a prerequisite."), "ar": ("المصممون | FABINZI", "اكتشف ملفات المصممين العامة النشطة والمعتمدة من FABINZI دون اشتراط وجود متجر منشور.")},
    "artwork": {"en": ("Artwork Marketplace | FABINZI", "Discover approved Designer Artwork that can be used on eligible FABINZI products."), "ar": ("سوق الأعمال الفنية | FABINZI", "اكتشف أعمال المصممين الفنية المعتمدة التي يمكن استخدامها على منتجات FABINZI المؤهلة.")},
    "manufacturer-marketplace": {"en": ("Manufacturers | FABINZI", "Discover FABINZI-approved public production partners and explicitly verified canonical capabilities."), "ar": ("المصنّعون | FABINZI", "استكشف شركاء الإنتاج ذوي الملفات العامة المعتمدة والقدرات القياسية الموثقة صراحةً على FABINZI.")},
}


def absolute_url(path="/"):
    if path.startswith("http://") or path.startswith("https://"):
        return path
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{settings.FABINZI_PUBLIC_BASE_URL.rstrip('/')}{path}"


def localized_public_url(path, language):
    return f"{absolute_url(path)}?{urlencode({'lang': language})}"


def media_url(value):
    if not value:
        return absolute_url("/share/fabinzi-1200x630.png")
    return absolute_url(value)


def safe_json_ld(payload):
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def page_seo(*, title, description, image=None, page_type="website", json_ld=None):
    uses_default_social_image = not image
    return {"title": title, "description": description, "image": media_url(image), "image_width": 1200 if uses_default_social_image else None, "image_height": 630 if uses_default_social_image else None, "type": page_type, "json_ld": safe_json_ld(json_ld) if json_ld else ""}


def request_is_indexable(request):
    match = getattr(request, "resolver_match", None)
    return bool(match and match.url_name in INDEXABLE_URL_NAMES)


def seo_context(request):
    language = getattr(request, "LANGUAGE_CODE", settings.LANGUAGE_CODE)
    if language not in {"en", "ar"}:
        language = "en"
    path = request.path or "/"
    match = getattr(request, "resolver_match", None)
    url_name = match.url_name if match else None
    indexable = request_is_indexable(request)
    has_filter_query = any(key != "lang" for key in request.GET.keys())
    if indexable and not has_filter_query:
        robots = "index,follow,max-image-preview:large,max-snippet:-1,max-video-preview:-1"
    elif indexable:
        robots = "noindex,follow"
    else:
        robots = "noindex,nofollow,noarchive"
    canonical = localized_public_url(path, language) if indexable else absolute_url(path)
    hreflang = {"en": localized_public_url(path, "en"), "ar": localized_public_url(path, "ar"), "x_default": absolute_url(path)} if indexable else None
    social_image = absolute_url("/share/fabinzi-1200x630.png")
    organization_schema = {"@context": "https://schema.org", "@type": "Organization", "name": "FABINZI", "url": absolute_url("/"), "logo": absolute_url("/static/brand/fabinzi-logo.svg")}
    website_schema = {"@context": "https://schema.org", "@type": "WebSite", "name": "FABINZI", "url": absolute_url("/"), "inLanguage": ["en", "ar"], "potentialAction": {"@type": "SearchAction", "target": f"{absolute_url('/')}?q={{search_term_string}}&lang={language}", "query-input": "required name=search_term_string"}}
    default_page_seo = None
    if url_name in PUBLIC_PAGE_SEO:
        title, description = PUBLIC_PAGE_SEO[url_name][language]
        default_page_seo = page_seo(title=title, description=description)
    return {"seo_default_description": DEFAULT_DESCRIPTIONS[language], "seo_robots": robots, "seo_canonical": canonical, "seo_hreflang": hreflang, "seo_default_image": social_image, "seo_default_image_width": 1200, "seo_default_image_height": 630, "seo_public_base_url": settings.FABINZI_PUBLIC_BASE_URL, "seo_base_json_ld": safe_json_ld([organization_schema, website_schema]), "seo_is_indexable": indexable, "page_seo": default_page_seo}
