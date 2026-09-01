from django.shortcuts import render

from apps.platform_ops.seo import page_seo
from apps.storefront.models import Storefront
from .models import Organization


def designer_directory(request):
    stores = (
        Storefront.objects.filter(
            status=Storefront.Status.PUBLISHED,
            organization__kind=Organization.Kind.DESIGNER,
            organization__verification_status=Organization.VerificationStatus.ACTIVE,
        )
        .select_related("organization", "logo")
        .order_by("name_en", "organization__display_name")
    )
    language = getattr(request, "LANGUAGE_CODE", "en")
    return render(
        request,
        "organizations/designer_directory.html",
        {
            "designer_stores": stores,
            "page_seo": page_seo(
                title="المصممون | FABINZI" if language == "ar" else "Designers | FABINZI",
                description=(
                    "استكشف هويات المصممين الموثقة التي لديها واجهات منشورة على FABINZI."
                    if language == "ar"
                    else "Discover verified Designer organizations with published public storefronts on FABINZI."
                ),
            ),
        },
    )
