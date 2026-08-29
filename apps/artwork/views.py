from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render

from apps.organizations.models import Membership, Organization
from apps.platform_ops.seo import absolute_url, media_url, page_seo
from .forms import ArtworkForm, ArtworkVersionForm, DesignedProductForm
from .models import Artwork, ArtworkVersion, DesignedProduct
from .public import (
    decorate_public_artwork,
    decorate_public_artworks,
    eligible_products_for_version,
    public_artwork_queryset,
)
from .services import create_artwork, create_designed_product, require_artwork_access


def _localized(request, en, ar):
    return ar if getattr(request, "LANGUAGE_CODE", "en") == "ar" else en


def _asset_url(asset_row):
    if not asset_row:
        return None
    media = asset_row.media_asset
    metadata = media.metadata or {}
    return metadata.get("public_url") or metadata.get("static_url") or media.provider_asset_id


def artwork_marketplace(request):
    qs = public_artwork_queryset().filter(versions__status=ArtworkVersion.Status.APPROVED).distinct()
    q = request.GET.get("q", "").strip()
    tag = request.GET.get("tag", "").strip()
    designer = request.GET.get("designer", "").strip()
    method = request.GET.get("method", "").strip().lower()
    product_type = request.GET.get("product_type", "").strip()
    sort = request.GET.get("sort", "newest")

    if q:
        qs = qs.filter(
            Q(title__icontains=q)
            | Q(description__icontains=q)
            | Q(organization__display_name__icontains=q)
        )
    if tag:
        qs = qs.filter(tags__contains=[tag])
    if designer.isdigit():
        qs = qs.filter(organization_id=int(designer))
    else:
        designer = ""
    if method in {"print", "embroidery"}:
        suitability_key = f"versions__metadata__suitable_for_{method}"
        qs = qs.filter(
            Q(**{suitability_key: True})
            | Q(versions__metadata__public_production_methods__contains=[method])
        ).filter(versions__status=ArtworkVersion.Status.APPROVED).distinct()
    else:
        method = ""
    if product_type:
        qs = qs.filter(
            versions__status=ArtworkVersion.Status.APPROVED,
            versions__metadata__public_product_types__contains=[product_type],
        ).distinct()

    if sort == "alphabetical":
        qs = qs.order_by("title", "id")
    else:
        sort = "newest"
        qs = qs.order_by("-updated_at", "-id")

    page_obj = Paginator(qs, 12).get_page(request.GET.get("page"))
    artworks = decorate_public_artworks(list(page_obj.object_list))
    page_obj.object_list = artworks

    all_public = list(public_artwork_queryset().filter(versions__status=ArtworkVersion.Status.APPROVED).distinct())
    all_public = decorate_public_artworks(all_public)
    tags = sorted({str(value).strip() for art in all_public for value in (art.tags or []) if str(value).strip()})[:30]
    product_types = sorted({value for art in all_public for value in art.public_product_types})[:30]
    designers = (
        Organization.objects.filter(
            kind=Organization.Kind.DESIGNER,
            artworks__status=Artwork.Status.APPROVED,
            artworks__versions__status=ArtworkVersion.Status.APPROVED,
        )
        .distinct()
        .order_by("display_name")
    )

    return render(
        request,
        "artwork/marketplace.html",
        {
            "page_obj": page_obj,
            "artworks": artworks,
            "search_query": q,
            "selected_tag": tag,
            "selected_designer": designer,
            "selected_method": method,
            "selected_product_type": product_type,
            "sort": sort,
            "filter_tags": tags,
            "filter_product_types": product_types,
            "filter_designers": designers,
            "page_seo": page_seo(
                title=_localized(request, "Artwork Marketplace | FABINZI", "سوق الأعمال الفنية | FABINZI"),
                description=_localized(
                    request,
                    "Discover approved Designer Artwork that can be used on eligible FABINZI products.",
                    "اكتشف أعمال المصممين الفنية المعتمدة التي يمكن استخدامها على منتجات FABINZI المؤهلة.",
                ),
            ),
        },
    )


def artwork_detail(request, pk):
    artwork = get_object_or_404(public_artwork_queryset(), pk=pk, status=Artwork.Status.APPROVED)
    decorate_public_artwork(artwork)
    if not artwork.public_version:
        raise Http404
    version = artwork.public_version
    preview_url = _asset_url(artwork.public_preview)
    eligible_products = eligible_products_for_version(version)
    related = list(
        public_artwork_queryset()
        .filter(organization=artwork.organization, versions__status=ArtworkVersion.Status.APPROVED)
        .exclude(pk=artwork.pk)
        .distinct()
        .order_by("-updated_at")[:4]
    )
    related = decorate_public_artworks(related)

    can_customize = bool(artwork.public_methods and eligible_products)
    method_labels = [
        _localized(request, "Print", "طباعة") if method == "print" else _localized(request, "Embroidery", "تطريز")
        for method in artwork.public_methods
    ]
    description = artwork.description.strip() or _localized(
        request,
        f"Approved Artwork by {artwork.organization.display_name} on FABINZI.",
        f"عمل فني معتمد من {artwork.organization.display_name} على FABINZI.",
    )
    schema = [
        {
            "@context": "https://schema.org",
            "@type": "VisualArtwork",
            "name": artwork.title,
            "description": description,
            "url": absolute_url(request.path),
            "creator": {"@type": "Organization", "name": artwork.organization.display_name},
            "image": media_url(preview_url) if preview_url else media_url(None),
        },
        {
            "@context": "https://schema.org",
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "FABINZI", "item": absolute_url("/")},
                {"@type": "ListItem", "position": 2, "name": _localized(request, "Artwork", "الأعمال الفنية"), "item": absolute_url("/artwork/")},
                {"@type": "ListItem", "position": 3, "name": artwork.title, "item": absolute_url(request.path)},
            ],
        },
    ]
    return render(
        request,
        "artwork/detail.html",
        {
            "artwork": artwork,
            "version": version,
            "preview_url": preview_url,
            "eligible_products": eligible_products,
            "related_artworks": related,
            "can_customize": can_customize,
            "method_labels": method_labels,
            "page_seo": page_seo(
                title=f"{artwork.title} | FABINZI",
                description=description[:300],
                image=preview_url,
                page_type="article",
                json_ld=schema,
            ),
        },
    )


@login_required
def designer_artworks(request):
    memberships = Membership.objects.filter(user=request.user, is_active=True, organization__kind=Organization.Kind.DESIGNER).select_related("organization")
    artworks = Artwork.objects.filter(organization__memberships__user=request.user, organization__memberships__is_active=True).distinct()
    form = ArtworkForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        org = get_object_or_404(Organization, pk=request.POST.get("organization"))
        artwork = create_artwork(organization=org, actor=request.user, request=request, **form.cleaned_data)
        return redirect("designer-artwork-detail", pk=artwork.pk)
    return render(request, "artwork/designer_artworks.html", {"memberships": memberships, "artworks": artworks, "form": form})


@login_required
def designer_artwork_detail(request, pk):
    artwork = get_object_or_404(Artwork, pk=pk)
    require_artwork_access(request.user, artwork)
    version = artwork.versions.order_by("-version_number").first()
    form = ArtworkVersionForm(request.POST or None, instance=version)
    if request.method == "POST":
        require_artwork_access(request.user, artwork, edit=True)
        if version.status != version.Status.DRAFT:
            return render(request, "artwork/designer_artwork_detail.html", {"artwork": artwork, "version": version, "form": form, "locked": True}, status=409)
        if form.is_valid():
            form.save()
            return redirect("designer-artwork-detail", pk=artwork.pk)
    return render(request, "artwork/designer_artwork_detail.html", {"artwork": artwork, "version": version, "form": form})


@login_required
def designer_products(request):
    memberships = Membership.objects.filter(user=request.user, is_active=True, organization__kind=Organization.Kind.DESIGNER).select_related("organization")
    products = DesignedProduct.objects.filter(organization__memberships__user=request.user, organization__memberships__is_active=True).distinct()
    form = DesignedProductForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        org = get_object_or_404(Organization, pk=request.POST.get("organization"))
        product = create_designed_product(organization=org, actor=request.user, request=request, **form.cleaned_data)
        return redirect("designer-products")
    return render(request, "artwork/designer_products.html", {"memberships": memberships, "products": products, "form": form})
