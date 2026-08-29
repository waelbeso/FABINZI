from django.core.exceptions import ValidationError
from django.db import transaction

from apps.audit.services import record_audit_event
from .models import ProductVariant, StoreProduct, Storefront
from .services import require_store_access


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


@transaction.atomic
def update_store_product(*, product, actor, data, request=None):
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
