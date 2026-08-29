from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Exists, OuterRef, Q
from django.shortcuts import get_object_or_404, redirect, render

from apps.artwork.models import ArtworkPlacement
from apps.checkout.models import CartItem
from apps.checkout.services import add_cart_item
from apps.organizations.models import Membership, Organization
from apps.platform_ops.seo import absolute_url, media_url, page_seo
from .models import CustomizationElement, ProductVariant, StoreProduct, Storefront, StudioProject
from .services import (
    add_customization_element,
    create_storefront,
    create_studio_project,
    enable_customization,
    mark_project_ready,
    require_project_owner,
    update_studio_project,
)


def _localized(request, en, ar):
    return ar if getattr(request, "LANGUAGE_CODE", "en") == "ar" else en


def _positive_int(value, default=1):
    try:
        value = int(value)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _asset_url(asset):
    if not asset:
        return None
    metadata = asset.metadata or {}
    return metadata.get("public_url") or asset.provider_asset_id


def store_marketplace(request):
    ready_placements = ArtworkPlacement.objects.filter(product_id=OuterRef("designed_product_id"))
    products = (
        StoreProduct.objects.filter(
            status=StoreProduct.Status.PUBLISHED,
            storefront__status=Storefront.Status.PUBLISHED,
        )
        .select_related("storefront", "storefront__organization", "designed_product")
        .prefetch_related("images__media_asset", "variants", "designed_product__placements")
        .annotate(is_ready_designed=Exists(ready_placements))
    )

    q = request.GET.get("q", "").strip()
    collection = request.GET.get("collection", "all")
    fulfillment = request.GET.get("fulfillment", "all")
    sort = request.GET.get("sort", "featured")
    if q:
        products = products.filter(
            Q(title_en__icontains=q)
            | Q(title_ar__icontains=q)
            | Q(description_en__icontains=q)
            | Q(description_ar__icontains=q)
            | Q(storefront__name_en__icontains=q)
            | Q(storefront__name_ar__icontains=q)
        )
    if collection == "customizable":
        products = products.filter(customization_enabled=True)
    elif collection == "ready":
        products = products.filter(is_ready_designed=True)
    elif collection == "plain":
        products = products.filter(customization_enabled=False, is_ready_designed=False)
    else:
        collection = "all"
    if fulfillment in StoreProduct.FulfillmentMode.values:
        products = products.filter(fulfillment_mode=fulfillment)
    else:
        fulfillment = "all"

    orderings = {
        "featured": ("-featured", "-published_at", "-updated_at"),
        "newest": ("-published_at", "-updated_at"),
        "price_asc": ("base_price", "title_en"),
        "price_desc": ("-base_price", "title_en"),
        "title": ("title_en",),
    }
    if sort not in orderings:
        sort = "featured"
    products = products.order_by(*orderings[sort])
    page_obj = Paginator(products, 12).get_page(request.GET.get("page"))
    stores = (
        Storefront.objects.filter(status=Storefront.Status.PUBLISHED)
        .select_related("organization", "logo")
        .order_by("-published_at", "name_en")[:6]
    )
    title = _localized(request, "تسوّق منتجات المصممين | FABINZI", "تسوّق منتجات المصممين | FABINZI") if False else _localized(request, "Shop designer products | FABINZI", "تسوّق منتجات المصممين | FABINZI")
    description = _localized(
        request,
        "Browse published FABINZI products using real product, variant, price and fulfillment data.",
        "تصفح منتجات FABINZI المنشورة باستخدام بيانات المنتج والمتغير والسعر والتنفيذ الفعلية.",
    )
    return render(
        request,
        "storefront/store_marketplace.html",
        {
            "stores": stores,
            "page_obj": page_obj,
            "products": page_obj.object_list,
            "search_query": q,
            "collection": collection,
            "fulfillment": fulfillment,
            "sort": sort,
            "page_seo": page_seo(title=title, description=description),
        },
    )


def public_storefront(request, slug):
    store = get_object_or_404(
        Storefront.objects.select_related("organization", "logo"),
        slug=slug,
        status=Storefront.Status.PUBLISHED,
    )
    products = (
        store.products.filter(status=StoreProduct.Status.PUBLISHED)
        .select_related("designed_product")
        .prefetch_related("images__media_asset", "variants", "designed_product__placements")
    )
    name = _localized(request, store.name_en, store.name_ar or store.name_en)
    about = _localized(request, store.about_en, store.about_ar or store.about_en)
    logo = _asset_url(store.logo)
    schema = {
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": name,
        "description": about or f"{name} on FABINZI",
        "url": absolute_url(request.path),
        "isPartOf": {"@type": "WebSite", "name": "FABINZI", "url": absolute_url("/")},
    }
    return render(
        request,
        "storefront/storefront_detail.html",
        {
            "store": store,
            "products": products,
            "page_seo": page_seo(
                title=f"{name} | FABINZI",
                description=about or _localized(request, "Published designer storefront on FABINZI.", "متجر مصمم منشور على FABINZI."),
                image=logo,
                json_ld=schema,
            ),
        },
    )


def public_product(request, store_slug, product_slug):
    product = get_object_or_404(
        StoreProduct.objects.select_related(
            "storefront",
            "storefront__organization",
            "designed_product",
            "designed_product__garment_version",
            "designed_product__artwork_version__artwork",
        ).prefetch_related("variants", "images__media_asset", "designed_product__placements"),
        storefront__slug=store_slug,
        storefront__status=Storefront.Status.PUBLISHED,
        slug=product_slug,
        status=StoreProduct.Status.PUBLISHED,
    )
    variants = list(product.variants.filter(is_active=True))
    is_ready_designed = product.designed_product.placements.exists()
    primary_image = product.images.first()
    image_url = _asset_url(primary_image.media_asset) if primary_image else None
    name = _localized(request, product.title_en, product.title_ar or product.title_en)
    description = _localized(request, product.description_en, product.description_ar or product.description_en)
    prices = [variant.price for variant in variants] or [product.base_price]
    available = any(variant.stock_quantity is None or variant.stock_quantity > 0 for variant in variants)
    schema = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": name,
        "description": description or name,
        "url": absolute_url(request.path),
        "sku": variants[0].sku if len(variants) == 1 else None,
        "image": [media_url(image_url)] if image_url else [media_url(None)],
        "brand": {"@type": "Brand", "name": product.storefront.organization.display_name},
        "offers": {
            "@type": "AggregateOffer" if len(prices) > 1 else "Offer",
            "priceCurrency": product.currency,
            "lowPrice": str(min(prices)),
            "highPrice": str(max(prices)),
            "price": str(prices[0]),
            "offerCount": len(variants),
            "availability": "https://schema.org/InStock" if available else "https://schema.org/OutOfStock",
            "url": absolute_url(request.path),
        },
    }
    schema["offers"] = {key: value for key, value in schema["offers"].items() if value is not None}
    schema = {key: value for key, value in schema.items() if value is not None}
    return render(
        request,
        "storefront/product_detail.html",
        {
            "product": product,
            "variants": variants,
            "is_ready_designed": is_ready_designed,
            "primary_image": primary_image,
            "page_seo": page_seo(
                title=f"{name} | FABINZI",
                description=description or _localized(request, "Published designer product on FABINZI.", "منتج مصمم منشور على FABINZI."),
                image=image_url,
                page_type="product",
                json_ld=schema,
            ),
        },
    )


@login_required
def designer_store_dashboard(request):
    membership = (
        Membership.objects.filter(
            user=request.user,
            is_active=True,
            organization__kind=Organization.Kind.DESIGNER,
        )
        .select_related("organization")
        .first()
    )
    org = membership.organization if membership else None
    store = Storefront.objects.filter(organization=org).first() if org else None
    if request.method == "POST" and org and not store:
        create_storefront(
            organization=org,
            actor=request.user,
            slug=request.POST.get("slug", ""),
            name_en=request.POST.get("name_en", ""),
            name_ar=request.POST.get("name_ar", ""),
            request=request,
        )
        return redirect("designer-store")
    return render(request, "storefront/designer_store.html", {"organization": org, "store": store})


@login_required
def studio(request):
    projects = (
        StudioProject.objects.filter(customer=request.user)
        .select_related("product", "product__storefront", "variant")
        .prefetch_related("product__images__media_asset")
    )
    product = None
    if request.GET.get("product"):
        product = get_object_or_404(
            StoreProduct.objects.select_related("storefront", "designed_product").prefetch_related("variants", "images__media_asset"),
            pk=request.GET["product"],
            status=StoreProduct.Status.PUBLISHED,
            storefront__status=Storefront.Status.PUBLISHED,
        )
    if request.method == "POST":
        product = get_object_or_404(
            StoreProduct,
            pk=request.POST.get("product"),
            status=StoreProduct.Status.PUBLISHED,
            storefront__status=Storefront.Status.PUBLISHED,
        )
        variant = get_object_or_404(ProductVariant, pk=request.POST.get("variant"), product=product, is_active=True)
        if not product.customization_enabled:
            messages.error(
                request,
                _localized(request, "This product is not customizable. Add it directly to Cart instead.", "هذا المنتج غير قابل للتخصيص. أضفه مباشرة إلى السلة."),
            )
            return redirect("public-store-product", store_slug=product.storefront.slug, product_slug=product.slug)
        try:
            project = create_studio_project(
                customer=request.user,
                product=product,
                variant=variant,
                quantity=_positive_int(request.POST.get("quantity")),
                request=request,
            )
            enable_customization(project=project, actor=request.user, request=request)
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, str(exc))
            return redirect(f"/studio/?product={product.pk}")
        messages.success(request, _localized(request, "Studio project created.", "تم إنشاء مشروع الاستوديو."))
        return redirect("studio-project", pk=project.pk)
    return render(request, "storefront/studio.html", {"projects": projects, "product": product})


@login_required
def studio_project(request, pk):
    project = get_object_or_404(
        StudioProject.objects.select_related(
            "product",
            "product__storefront",
            "product__designed_product__garment_version",
            "variant",
        ).prefetch_related(
            "product__variants",
            "product__images__media_asset",
            "product__designed_product__garment_version__decoration_zones",
            "customization__elements__decoration_zone",
        ),
        pk=pk,
    )
    try:
        require_project_owner(request.user, project)
    except PermissionDenied:
        return render(request, "checkout/error.html", {"error": _localized(request, "Studio access denied.", "غير مسموح بالوصول إلى هذا المشروع.")}, status=403)

    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "update":
                variant = get_object_or_404(ProductVariant, pk=request.POST.get("variant"), product=project.product, is_active=True)
                update_studio_project(
                    project=project,
                    actor=request.user,
                    variant=variant,
                    quantity=_positive_int(request.POST.get("quantity")),
                    customer_notes=request.POST.get("customer_notes", ""),
                    request=request,
                )
                messages.success(request, _localized(request, "Studio choices updated.", "تم تحديث اختيارات الاستوديو."))
            elif action == "enable_customization":
                enable_customization(project=project, actor=request.user, request=request)
                messages.success(request, _localized(request, "Customization enabled.", "تم تفعيل التخصيص."))
            elif action == "add_text":
                customization = enable_customization(project=project, actor=request.user, request=request)
                zone = get_object_or_404(
                    project.product.designed_product.garment_version.decoration_zones,
                    pk=request.POST.get("decoration_zone"),
                )
                add_customization_element(
                    customization=customization,
                    actor=request.user,
                    decoration_zone=zone,
                    kind=CustomizationElement.Kind.TEXT,
                    text=request.POST.get("text", ""),
                    request=request,
                )
                messages.success(request, _localized(request, "Text added to your customization.", "تمت إضافة النص إلى التخصيص."))
            elif action == "ready":
                mark_project_ready(project=project, actor=request.user, request=request)
                messages.success(request, _localized(request, "Customization is ready for Cart.", "التخصيص جاهز للإضافة إلى السلة."))
            elif action == "add_cart":
                if project.status != StudioProject.Status.READY:
                    raise ValidationError(_localized(request, "Mark the Studio project Ready before adding it to Cart.", "اجعل مشروع الاستوديو جاهزًا قبل إضافته إلى السلة."))
                add_cart_item(
                    customer=request.user,
                    product=project.product,
                    variant=project.variant,
                    quantity=project.quantity,
                    kind=CartItem.Kind.STUDIO,
                    studio_project=project,
                    request=request,
                )
                messages.success(request, _localized(request, "Customized product added to Cart.", "تمت إضافة المنتج المخصص إلى السلة."))
                return redirect("cart")
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, str(exc))
        return redirect("studio-project", pk=project.pk)

    zones = project.product.designed_product.garment_version.decoration_zones.all()
    return render(request, "storefront/studio_project.html", {"project": project, "zones": zones})
