from django.shortcuts import render

from .seo import absolute_url, page_seo
from .views import _public_home_data


def _localized(request, en, ar):
    return ar if getattr(request, "LANGUAGE_CODE", "en") == "ar" else en


def discover(request):
    context = _public_home_data()
    context["page_seo"] = page_seo(
        title=_localized(request, "Discover FABINZI | Fashion creation to commerce", "اكتشف FABINZI | من ابتكار الأزياء إلى التجارة"),
        description=_localized(
            request,
            "Discover how FABINZI connects Customers, Designers and qualified Manufacturers while keeping design, artwork, customization and production responsibilities distinct.",
            "اكتشف كيف تربط FABINZI العملاء والمصممين والمصنعين المؤهلين مع الحفاظ على الفصل بين تصميم القطعة والعمل الفني والتخصيص والإنتاج.",
        ),
        json_ld={
            "@context": "https://schema.org",
            "@type": "AboutPage",
            "name": _localized(request, "Discover FABINZI", "اكتشف FABINZI"),
            "url": absolute_url(request.path),
            "isPartOf": {"@type": "WebSite", "name": "FABINZI", "url": absolute_url("/")},
        },
    )
    return render(request, "home.html", context)


def how_it_works(request):
    return render(
        request,
        "how_it_works.html",
        {
            "page_seo": page_seo(
                title=_localized(request, "How FABINZI works | Customers, Designers & Manufacturers", "كيف تعمل FABINZI | العملاء والمصممون والمصنعون"),
                description=_localized(
                    request,
                    "Understand the distinct Customer, Designer, Manufacturer and FABINZI Platform roles from fashion creation through customization, production and fulfillment.",
                    "تعرّف على الأدوار المنفصلة للعميل والمصمم والمصنع ومنصة FABINZI من ابتكار الأزياء والتخصيص حتى الإنتاج والتنفيذ.",
                ),
                json_ld={
                    "@context": "https://schema.org",
                    "@type": "WebPage",
                    "name": _localized(request, "How FABINZI works", "كيف تعمل FABINZI"),
                    "url": absolute_url(request.path),
                    "about": [
                        {"@type": "Thing", "name": "Fashion design"},
                        {"@type": "Thing", "name": "Customer customization"},
                        {"@type": "Thing", "name": "Garment manufacturing"},
                    ],
                },
            )
        },
    )
