import json
from urllib.parse import urlencode

from django.conf import settings

INDEXABLE_URL_NAMES = {
    "home",
    "store-marketplace",
    "public-storefront",
    "public-store-product",
    "artwork",
    "manufacturer-marketplace",
    "manufacturer-public-detail",
}

DEFAULT_DESCRIPTIONS = {
    "en": "Discover designer fashion, ready-designed products and optional customization on FABINZI, where designers create, manufacturers produce and customers buy.",
    "ar": "اكتشف أزياء المصممين والمنتجات ذات التصميمات الجاهزة والتخصيص الاختياري على FABINZI، حيث يبدع المصمم وينتج المصنع ويشتري العميل.",
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
    return {
        "title": title,
        "description": description,
        "image": media_url(image),
        "type": page_type,
        "json_ld": safe_json_ld(json_ld) if json_ld else "",
    }


def request_is_indexable(request):
    match = getattr(request, "resolver_match", None)
    return bool(match and match.url_name in INDEXABLE_URL_NAMES)


def seo_context(request):
    language = getattr(request, "LANGUAGE_CODE", settings.LANGUAGE_CODE)
    if language not in {"en", "ar"}:
        language = "en"
    path = request.path or "/"
    indexable = request_is_indexable(request)
    has_filter_query = any(key != "lang" for key in request.GET.keys())

    if indexable and not has_filter_query:
        robots = "index,follow,max-image-preview:large,max-snippet:-1,max-video-preview:-1"
    elif indexable:
        robots = "noindex,follow"
    else:
        robots = "noindex,nofollow,noarchive"

    canonical = localized_public_url(path, language) if indexable else absolute_url(path)
    hreflang = (
        {
            "en": localized_public_url(path, "en"),
            "ar": localized_public_url(path, "ar"),
            "x_default": absolute_url(path),
        }
        if indexable
        else None
    )
    social_image = absolute_url("/share/fabinzi-1200x630.png")
    organization_schema = {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": "FABINZI",
        "url": absolute_url("/"),
        "logo": absolute_url("/static/brand/fabinzi-logo.svg"),
    }
    website_schema = {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "name": "FABINZI",
        "url": absolute_url("/"),
        "inLanguage": ["en", "ar"],
        "potentialAction": {
            "@type": "SearchAction",
            "target": f"{absolute_url('/store/')}?q={{search_term_string}}&lang={language}",
            "query-input": "required name=search_term_string",
        },
    }
    return {
        "seo_default_description": DEFAULT_DESCRIPTIONS[language],
        "seo_robots": robots,
        "seo_canonical": canonical,
        "seo_hreflang": hreflang,
        "seo_default_image": social_image,
        "seo_public_base_url": settings.FABINZI_PUBLIC_BASE_URL,
        "seo_base_json_ld": safe_json_ld([organization_schema, website_schema]),
        "seo_is_indexable": indexable,
    }
