from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render

from apps.checkout.models import CartItem
from apps.checkout.services import add_cart_item
from apps.organizations.models import Membership, Organization
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


def store_marketplace(request):
    stores = (
        Storefront.objects.filter(status=Storefront.Status.PUBLISHED)
        .select_related("organization", "logo")
        .prefetch_related("products__images__media_asset", "products__variants")
    )
    return render(request, "storefront/store_marketplace.html", {"stores": stores})


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
    return render(request, "storefront/storefront_detail.html", {"store": store, "products": products})


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
    variants = product.variants.filter(is_active=True)
    is_ready_designed = product.designed_product.placements.exists()
    return render(
        request,
        "storefront/product_detail.html",
        {
            "product": product,
            "variants": variants,
            "is_ready_designed": is_ready_designed,
            "primary_image": product.images.first(),
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
