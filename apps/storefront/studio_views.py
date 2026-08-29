from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render

from apps.artwork.models import ArtworkVersion
from apps.artwork.public import decorate_public_artworks, public_artwork_queryset, version_eligible_for_zone
from apps.checkout.models import CartItem
from apps.checkout.services import add_cart_item
from apps.design.models import DecorationZone
from apps.media.models import MediaAsset
from apps.media.services import create_private_studio_image
from .models import CustomizationElement, ProductVariant, StoreProduct, Storefront, StudioProject
from .services import (
    add_customization_element,
    allowed_methods_for_zone,
    create_studio_project,
    delete_customization_element,
    element_source_url,
    enable_customization,
    mark_project_ready,
    normalize_transform,
    require_project_owner,
    update_studio_project,
    validate_studio_project,
)


def _localized(request, en, ar):
    return ar if getattr(request, "LANGUAGE_CODE", "en") == "ar" else en


def _positive_int(value, default=1):
    try:
        value = int(value)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _customer_error(request, exc=None):
    if getattr(request, "LANGUAGE_CODE", "en") == "ar":
        return "تعذر حفظ هذا التغيير. راجع المنتج والمنطقة وطريقة الإنتاج وموضع العنصر ثم حاول مرة أخرى."
    if isinstance(exc, ValidationError) and exc.messages:
        return " ".join(exc.messages)
    return "We could not save this change. Review the product, zone, production method and placement, then try again."


def _project_queryset():
    return StudioProject.objects.select_related(
        "customer",
        "product",
        "product__storefront",
        "product__designed_product",
        "product__designed_product__garment_version",
        "variant",
    ).prefetch_related(
        "product__variants",
        "product__images__media_asset",
        "product__designed_product__garment_version__decoration_zones",
        "customization__elements__decoration_zone",
        "customization__elements__media_asset",
        "customization__elements__artwork_version__artwork__organization",
        "customization__elements__artwork_version__assets__media_asset",
    )


def _marketplace_for_product(product, search=""):
    zones = list(product.designed_product.garment_version.decoration_zones.all())
    qs = public_artwork_queryset().filter(versions__status=ArtworkVersion.Status.APPROVED).distinct().order_by("-updated_at")
    if search:
        from django.db.models import Q
        qs = qs.filter(Q(title__icontains=search) | Q(description__icontains=search) | Q(organization__display_name__icontains=search))
    rows = decorate_public_artworks(list(qs[:60]))
    eligible = []
    for artwork in rows:
        if artwork.public_version and any(version_eligible_for_zone(artwork.public_version, zone) for zone in zones):
            eligible.append(artwork)
        if len(eligible) >= 24:
            break
    return eligible


def _validation_context(project, request):
    try:
        result = validate_studio_project(project)
        return {"valid": True, "issues": [], "unit_price": result["unit_price"], "currency": result["currency"]}
    except ValidationError as exc:
        if getattr(request, "LANGUAGE_CODE", "en") == "ar":
            if project.variant_id is None:
                issues = ["اختر المقاس/اللون المتاح أولاً."]
            elif not hasattr(project, "customization") or not project.customization.elements.exists():
                issues = ["أضف عملاً فنياً أو صورة خاصة أو نصاً إلى منطقة زخرفة."]
            else:
                issues = ["يوجد عنصر يحتاج مراجعة في الموضع أو طريقة الإنتاج أو أهلية المصدر."]
        else:
            issues = exc.messages
        return {"valid": False, "issues": issues, "unit_price": project.variant.price if project.variant_id else project.product.base_price, "currency": project.product.currency}


@login_required
def studio(request):
    projects = _project_queryset().filter(customer=request.user)
    product = None
    preferred_artwork = None
    preferred_variant = request.GET.get("variant", "")
    preferred_quantity = _positive_int(request.GET.get("quantity"), 1)

    if request.GET.get("product"):
        product = get_object_or_404(
            StoreProduct.objects.select_related("storefront", "designed_product").prefetch_related("variants", "images__media_asset"),
            pk=request.GET["product"],
            status=StoreProduct.Status.PUBLISHED,
            storefront__status=Storefront.Status.PUBLISHED,
        )
        if not product.customization_enabled:
            messages.error(request, _localized(request, "This product is not customizable. You can still buy it directly.", "هذا المنتج غير قابل للتخصيص، ويمكنك شراؤه مباشرة."))
            return redirect("public-store-product", store_slug=product.storefront.slug, product_slug=product.slug)
        if request.GET.get("artwork"):
            preferred_artwork = get_object_or_404(ArtworkVersion, pk=request.GET["artwork"], status=ArtworkVersion.Status.APPROVED, artwork__status="approved")

    if request.method == "POST":
        product = get_object_or_404(
            StoreProduct,
            pk=request.POST.get("product"),
            status=StoreProduct.Status.PUBLISHED,
            storefront__status=Storefront.Status.PUBLISHED,
            customization_enabled=True,
        )
        variant = get_object_or_404(ProductVariant, pk=request.POST.get("variant"), product=product, is_active=True)
        try:
            project = create_studio_project(customer=request.user, product=product, variant=variant, quantity=_positive_int(request.POST.get("quantity")), request=request)
            enable_customization(project=project, actor=request.user, request=request)
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, _customer_error(request, exc))
            return redirect(f"/studio/?product={product.pk}")
        target = f"/studio/{project.pk}/"
        if request.POST.get("artwork"):
            target += f"?artwork={request.POST['artwork']}"
        messages.success(request, _localized(request, "Studio project created. Your work will be saved to this project.", "تم إنشاء مشروع Studio وسيتم حفظ عملك داخل هذا المشروع."))
        return redirect(target)

    return render(
        request,
        "storefront/studio.html",
        {
            "projects": projects,
            "product": product,
            "preferred_artwork": preferred_artwork,
            "preferred_variant": preferred_variant,
            "preferred_quantity": preferred_quantity,
        },
    )


@login_required
def studio_project(request, pk):
    project = get_object_or_404(_project_queryset(), pk=pk)
    try:
        require_project_owner(request.user, project)
    except PermissionDenied:
        return render(request, "checkout/error.html", {"error": _localized(request, "Studio access denied.", "غير مسموح بالوصول إلى هذا المشروع.")}, status=403)

    zones = list(project.product.designed_product.garment_version.decoration_zones.all())
    preferred_artwork_id = request.GET.get("artwork", "")

    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "update_project":
                variant = get_object_or_404(ProductVariant, pk=request.POST.get("variant"), product=project.product, is_active=True)
                update_studio_project(project=project, actor=request.user, variant=variant, quantity=_positive_int(request.POST.get("quantity")), customer_notes=request.POST.get("customer_notes", ""), request=request)
                messages.success(request, _localized(request, "Product choices saved.", "تم حفظ اختيارات المنتج."))
            elif action in {"add_artwork", "add_text", "upload_image"}:
                customization = enable_customization(project=project, actor=request.user, request=request)
                zone = get_object_or_404(DecorationZone, pk=request.POST.get("decoration_zone"), version=project.product.designed_product.garment_version)
                production_method = request.POST.get("production_method", "")
                if action == "add_artwork":
                    artwork_version = get_object_or_404(ArtworkVersion, pk=request.POST.get("artwork_version"), status=ArtworkVersion.Status.APPROVED, artwork__status="approved")
                    add_customization_element(customization=customization, actor=request.user, decoration_zone=zone, kind=CustomizationElement.Kind.ARTWORK, artwork_version=artwork_version, production_method=production_method, transform={"x": .5, "y": .5, "scale": .35, "rotation": 0}, request=request)
                    messages.success(request, _localized(request, "Artwork added. Move, resize or rotate it in the zone workspace.", "تمت إضافة العمل الفني. حرّكه أو غيّر حجمه أو دوّره داخل مساحة المنطقة."))
                elif action == "add_text":
                    add_customization_element(customization=customization, actor=request.user, decoration_zone=zone, kind=CustomizationElement.Kind.TEXT, text=request.POST.get("text", ""), production_method=production_method, transform={"x": .5, "y": .5, "scale": .3, "rotation": 0}, request=request)
                    messages.success(request, _localized(request, "Text added to the active zone.", "تمت إضافة النص إلى منطقة الزخرفة."))
                else:
                    if request.POST.get("rights_confirmed") != "on":
                        raise ValidationError("Confirm that you have the right to use this content.")
                    asset = create_private_studio_image(upload=request.FILES.get("file"), owner=request.user)
                    add_customization_element(customization=customization, actor=request.user, decoration_zone=zone, kind=CustomizationElement.Kind.IMAGE, media_asset=asset, production_method=production_method, rights_confirmed=True, transform={"x": .5, "y": .5, "scale": .35, "rotation": 0}, request=request)
                    messages.success(request, _localized(request, "Private image uploaded and added to Studio.", "تم رفع الصورة الخاصة وإضافتها إلى Studio."))
            elif action == "delete_element":
                element = get_object_or_404(CustomizationElement, pk=request.POST.get("element"), customization__project=project)
                delete_customization_element(element=element, actor=request.user, request=request)
                messages.success(request, _localized(request, "Customization element removed.", "تم حذف عنصر التخصيص."))
            elif action == "ready":
                mark_project_ready(project=project, actor=request.user, request=request)
                messages.success(request, _localized(request, "Customization is Ready for Cart.", "التخصيص جاهز للإضافة إلى السلة."))
            elif action == "add_cart":
                if project.status != StudioProject.Status.READY:
                    raise ValidationError("Mark the Studio project Ready first.")
                validate_studio_project(project)
                add_cart_item(customer=request.user, product=project.product, variant=project.variant, quantity=project.quantity, kind=CartItem.Kind.STUDIO, studio_project=project, request=request)
                messages.success(request, _localized(request, "Customized product added to Cart.", "تمت إضافة المنتج المخصص إلى السلة."))
                return redirect("cart")
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, _customer_error(request, exc))
        return redirect("studio-project", pk=project.pk)

    elements = []
    if hasattr(project, "customization"):
        for element in project.customization.elements.select_related("decoration_zone", "media_asset", "artwork_version__artwork__organization"):
            element.visual_transform = normalize_transform(element.transform)
            element.visual_source_url = element_source_url(element)
            elements.append(element)
    for zone in zones:
        placement = zone.placement or {}
        try:
            zone.anchor_x = max(0.0, min(1.0, float(placement.get("x", .5))))
            zone.anchor_y = max(0.0, min(1.0, float(placement.get("y", .5))))
        except (TypeError, ValueError):
            zone.anchor_x, zone.anchor_y = .5, .5
        zone.allowed_methods = allowed_methods_for_zone(zone)
        if zone.max_width_mm and zone.max_height_mm:
            zone.workspace_ratio = float(zone.max_width_mm) / float(zone.max_height_mm)
        else:
            zone.workspace_ratio = 1.0

    marketplace = _marketplace_for_product(project.product, request.GET.get("art_q", "").strip())
    validation = _validation_context(project, request)
    return render(
        request,
        "storefront/studio_project.html",
        {
            "project": project,
            "zones": zones,
            "elements": elements,
            "marketplace_artworks": marketplace,
            "preferred_artwork_id": preferred_artwork_id,
            "validation": validation,
        },
    )
