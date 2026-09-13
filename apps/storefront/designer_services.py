from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction

from apps.audit.services import record_audit_event
from .models import ProductVariant, StoreProduct, StoreProductImage, Storefront
from .services import require_store_access, require_store_product_image_access, store_product_image_eligible


def _localized(request, en, ar):
    return ar if request is not None and getattr(request, "LANGUAGE_CODE", "en") == "ar" else en


@transaction.atomic
def update_storefront_details(*, storefront, actor, data, request=None):
    require_store_access(actor, storefront)
    for field in ("name_en", "name_ar", "about_en", "about_ar"):
        if field in data:
            setattr(storefront, field, data[field])
    storefront.full_clean()
    storefront.save()
    record_audit_event(actor=actor, action="storefront.updated", instance=storefront, request=request)
    return storefront


@transaction.atomic
def pause_storefront(*, storefront, actor, request=None):
    require_store_access(actor, storefront)
    if storefront.status != Storefront.Status.PUBLISHED:
        raise ValidationError("Only a published Storefront can be paused.")
    storefront.status = Storefront.Status.PAUSED
    storefront.save(update_fields=["status", "updated_at"])
    record_audit_event(actor=actor, action="storefront.paused", instance=storefront, request=request)
    return storefront


def _renumber(rows):
    for index, row in enumerate(rows):
        if row.sort_order != index:
            row.sort_order = index
            row.save(update_fields=["sort_order"])


@transaction.atomic
def set_primary_product_image(*, product, actor, image_id, request=None):
    product = StoreProduct.objects.select_for_update().select_related("storefront__organization").get(pk=product.pk)
    organization = require_store_product_image_access(product=product, actor=actor)
    rows = list(
        StoreProductImage.objects.select_for_update()
        .filter(product=product)
        .select_related("media_asset")
        .order_by("sort_order", "id")
    )
    target = next((row for row in rows if str(row.pk) == str(image_id)), None)
    if target is None or not store_product_image_eligible(target.media_asset, organization):
        raise ValidationError("Choose a genuine image attached to this product. / اختر صورة منتج حقيقية مرفقة بهذا المنتج.")
    ordered = [target] + [row for row in rows if row.pk != target.pk]
    _renumber(ordered)
    record_audit_event(
        actor=actor,
        action="store.product.image.primary_set",
        instance=target,
        metadata={"product_id": product.pk, "media_asset_id": target.media_asset_id},
        request=request,
    )
    return target


@transaction.atomic
def detach_product_image(*, product, actor, image_id, request=None):
    product = StoreProduct.objects.select_for_update().select_related("storefront__organization").get(pk=product.pk)
    require_store_product_image_access(product=product, actor=actor)
    rows = list(
        StoreProductImage.objects.select_for_update()
        .filter(product=product)
        .select_related("media_asset")
        .order_by("sort_order", "id")
    )
    target = next((row for row in rows if str(row.pk) == str(image_id)), None)
    if target is None:
        raise ValidationError("Choose an image attached to this product. / اختر صورة مرفقة بهذا المنتج.")
    target_id = target.pk
    media_asset_id = target.media_asset_id
    target.delete()
    _renumber([row for row in rows if row.pk != target_id])
    record_audit_event(
        actor=actor,
        action="store.product.image.detached",
        instance=product,
        metadata={"store_product_image_id": target_id, "media_asset_id": media_asset_id},
        request=request,
    )
    return product


def _handle_media_action(*, product, actor, request):
    action = request.POST.get("media_action", "").strip()
    if action == "upload":
        from apps.media.designer_public_services import create_designer_store_product_image

        organization = product.storefront.organization
        create_designer_store_product_image(
            upload=request.FILES.get("product_image"),
            product=product,
            organization=organization,
            actor=actor,
            alt_en=request.POST.get("alt_en", "").strip(),
            alt_ar=request.POST.get("alt_ar", "").strip(),
            request=request,
        )
        messages.success(
            request,
            _localized(request, "Product image uploaded and attached.", "تم رفع صورة المنتج وإرفاقها."),
        )
        return product
    if action == "set_primary":
        set_primary_product_image(
            product=product,
            actor=actor,
            image_id=request.POST.get("image_id"),
            request=request,
        )
        messages.success(
            request,
            _localized(request, "Primary product image updated.", "تم تحديث صورة المنتج الأساسية."),
        )
        return product
    if action == "detach":
        detach_product_image(
            product=product,
            actor=actor,
            image_id=request.POST.get("image_id"),
            request=request,
        )
        messages.success(
            request,
            _localized(request, "Product image detached. The reusable media asset was retained.", "تم فصل صورة المنتج مع الاحتفاظ بملف الوسائط القابل لإعادة الاستخدام."),
        )
        return product
    raise ValidationError("Unsupported product-media action. / إجراء صور المنتج غير مدعوم.")


def update_store_product(*, product, actor, data, request=None):
    # The existing Designer product-detail route remains canonical. Media forms
    # submit through its existing update action using a bounded media_action.
    # Dispatch before the commercial-definition transaction so provider I/O is
    # never wrapped by an outer database transaction.
    if request is not None and request.POST.get("media_action"):
        require_store_access(actor, product.storefront)
        return _handle_media_action(product=product, actor=actor, request=request)
    return _update_store_product_definition(product=product, actor=actor, data=data, request=request)


@transaction.atomic
def _update_store_product_definition(*, product, actor, data, request=None):
    require_store_access(actor, product.storefront)
    if product.status not in {StoreProduct.Status.DRAFT, StoreProduct.Status.HIDDEN}:
        raise ValidationError("Hide a published product before changing its commercial definition.")
    editable = {
        "title_en", "title_ar", "description_en", "description_ar", "base_price",
        "currency", "fulfillment_mode", "lead_time_days", "customization_enabled",
    }
    for field, value in data.items():
        if field in editable:
            setattr(product, field, value)
    product.full_clean()
    product.save()
    record_audit_event(actor=actor, action="store.product.updated", instance=product, request=request)
    return product


@transaction.atomic
def hide_store_product(*, product, actor, request=None):
    require_store_access(actor, product.storefront)
    if product.status != StoreProduct.Status.PUBLISHED:
        raise ValidationError("Only a published product can be hidden.")
    product.status = StoreProduct.Status.HIDDEN
    product.save(update_fields=["status", "updated_at"])
    record_audit_event(actor=actor, action="store.product.hidden", instance=product, request=request)
    return product


@transaction.atomic
def update_variant(*, variant, actor, data, request=None):
    product = variant.product
    require_store_access(actor, product.storefront)
    if product.status not in {StoreProduct.Status.DRAFT, StoreProduct.Status.HIDDEN}:
        raise ValidationError("Hide a published product before changing variants.")
    for field in ("sku", "size", "color_name", "color_hex", "price_adjustment", "stock_quantity", "is_active"):
        if field in data:
            setattr(variant, field, data[field])
    variant.full_clean()
    variant.save()
    record_audit_event(
        actor=actor,
        action="store.variant.updated",
        instance=variant,
        metadata={"product_id": product.pk},
        request=request,
    )
    return variant
