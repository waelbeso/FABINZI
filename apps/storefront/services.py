from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.artwork.models import DesignedProduct
from apps.audit.services import record_audit_event
from apps.organizations.models import Membership, Organization
from apps.organizations.services import require_org_access
from .models import CustomerCustomization, CustomizationElement, ProductVariant, StoreProduct, StoreProductImage, Storefront, StudioProject

STORE_EDIT_ROLES = [Membership.Role.OWNER, Membership.Role.MANAGER, Membership.Role.DESIGN_MANAGER]


def _require_active_designer(organization):
    if organization.kind != Organization.Kind.DESIGNER or organization.verification_status != Organization.VerificationStatus.ACTIVE:
        raise ValidationError("An approved active Designer business is required.")


def require_store_access(actor, storefront):
    return require_org_access(actor, storefront.organization, roles=STORE_EDIT_ROLES)


@transaction.atomic
def create_storefront(*, organization, actor, slug, name_en, name_ar="", about_en="", about_ar="", request=None):
    _require_active_designer(organization)
    require_org_access(actor, organization, roles=STORE_EDIT_ROLES)
    store = Storefront(organization=organization, slug=slug, name_en=name_en, name_ar=name_ar, about_en=about_en, about_ar=about_ar)
    store.full_clean(); store.save()
    record_audit_event(actor=actor, action="storefront.created", instance=store, metadata={"organization_id": organization.pk}, request=request)
    return store


@transaction.atomic
def publish_storefront(*, storefront, actor, request=None):
    require_store_access(actor, storefront)
    if not storefront.name_en or not storefront.slug:
        raise ValidationError("Storefront name and slug are required.")
    storefront.status = Storefront.Status.PUBLISHED
    storefront.published_at = storefront.published_at or timezone.now()
    storefront.save(update_fields=["status", "published_at", "updated_at"])
    record_audit_event(actor=actor, action="storefront.published", instance=storefront, request=request)
    return storefront


@transaction.atomic
def create_store_product(*, storefront, actor, designed_product, slug, title_en, base_price, currency="EGP", title_ar="", description_en="", description_ar="", customization_enabled=False, fulfillment_mode=StoreProduct.FulfillmentMode.MADE_TO_ORDER, lead_time_days=None, request=None):
    require_store_access(actor, storefront)
    if designed_product.organization_id != storefront.organization_id:
        raise ValidationError("Designed Product must belong to the Storefront Designer business.")
    if designed_product.status != DesignedProduct.Status.PUBLISHED:
        raise ValidationError("Only published Designed Products may be listed in the Store.")
    if customization_enabled and not designed_product.garment_version.decoration_zones.exists():
        raise ValidationError("Customization requires at least one garment decoration zone.")
    product = StoreProduct(storefront=storefront, designed_product=designed_product, slug=slug, title_en=title_en, title_ar=title_ar, description_en=description_en, description_ar=description_ar, base_price=base_price, currency=currency.upper(), customization_enabled=customization_enabled, fulfillment_mode=fulfillment_mode, lead_time_days=lead_time_days)
    product.full_clean(); product.save()
    record_audit_event(actor=actor, action="store.product.created", instance=product, metadata={"designed_product_id": designed_product.pk}, request=request)
    return product


@transaction.atomic
def add_variant(*, product, actor, sku, size="", color_name="", color_hex="", price_adjustment=0, stock_quantity=None, request=None):
    require_store_access(actor, product.storefront)
    if product.status not in {StoreProduct.Status.DRAFT, StoreProduct.Status.HIDDEN}:
        raise ValidationError("Published products must be hidden before editing variants.")
    variant = ProductVariant(product=product, sku=sku, size=size, color_name=color_name, color_hex=color_hex, price_adjustment=price_adjustment, stock_quantity=stock_quantity)
    variant.full_clean(); variant.save()
    record_audit_event(actor=actor, action="store.variant.created", instance=variant, metadata={"product_id": product.pk}, request=request)
    return variant


@transaction.atomic
def add_product_image(*, product, actor, media_asset, alt_en="", alt_ar="", sort_order=0, request=None):
    require_store_access(actor, product.storefront)
    image = StoreProductImage(product=product, media_asset=media_asset, alt_en=alt_en, alt_ar=alt_ar, sort_order=sort_order)
    image.full_clean(); image.save()
    record_audit_event(actor=actor, action="store.product.image.added", instance=image, metadata={"product_id": product.pk}, request=request)
    return image


@transaction.atomic
def publish_store_product(*, product, actor, request=None):
    require_store_access(actor, product.storefront)
    if product.storefront.status != Storefront.Status.PUBLISHED:
        raise ValidationError("Publish the Storefront first.")
    if product.designed_product.status != DesignedProduct.Status.PUBLISHED:
        raise ValidationError("The underlying Designed Product is not published.")
    if not product.variants.filter(is_active=True).exists():
        raise ValidationError("At least one active product variant is required.")
    if not product.images.exists():
        raise ValidationError("At least one public product image is required.")
    product.status = StoreProduct.Status.PUBLISHED
    product.published_at = product.published_at or timezone.now()
    product.save(update_fields=["status", "published_at", "updated_at"])
    record_audit_event(actor=actor, action="store.product.published", instance=product, request=request)
    return product


def _validate_available_product(product, variant=None, quantity=1):
    if product.status != StoreProduct.Status.PUBLISHED or product.storefront.status != Storefront.Status.PUBLISHED:
        raise ValidationError("This product is not currently available.")
    if product.designed_product.status != DesignedProduct.Status.PUBLISHED:
        raise ValidationError("This product is no longer available.")
    if variant:
        if variant.product_id != product.pk or not variant.is_active:
            raise ValidationError("Selected variant is not available for this product.")
        if product.fulfillment_mode == StoreProduct.FulfillmentMode.STOCK and variant.stock_quantity is not None and quantity > variant.stock_quantity:
            raise ValidationError("Requested quantity exceeds available stock.")


@transaction.atomic
def create_studio_project(*, customer, product, variant=None, quantity=1, customer_notes="", request=None):
    if not getattr(customer, "is_authenticated", False):
        raise PermissionDenied("Authentication required to save a Studio project.")
    _validate_available_product(product, variant, quantity)
    project = StudioProject(customer=customer, product=product, variant=variant, quantity=quantity, customer_notes=customer_notes)
    project.full_clean(); project.save()
    record_audit_event(actor=customer, action="studio.project.created", instance=project, metadata={"product_id": product.pk}, request=request)
    return project


def require_project_owner(actor, project):
    if not getattr(actor, "is_authenticated", False) or (project.customer_id != actor.pk and not actor.is_staff):
        raise PermissionDenied("Studio project access denied.")
    return True


def require_project_draft(actor, project):
    require_project_owner(actor, project)
    if project.status != StudioProject.Status.DRAFT:
        raise ValidationError("Ready or archived Studio projects are immutable.")


@transaction.atomic
def update_studio_project(*, project, actor, variant=None, quantity=None, customer_notes=None, request=None):
    require_project_draft(actor, project)
    if variant is not None:
        project.variant = variant
    if quantity is not None:
        project.quantity = quantity
    if customer_notes is not None:
        project.customer_notes = customer_notes
    _validate_available_product(project.product, project.variant, project.quantity)
    project.full_clean(); project.save()
    record_audit_event(actor=actor, action="studio.project.updated", instance=project, request=request)
    return project


@transaction.atomic
def enable_customization(*, project, actor, request=None):
    require_project_draft(actor, project)
    if not project.product.customization_enabled:
        raise ValidationError("Customization is not enabled for this product.")
    customization, _ = CustomerCustomization.objects.get_or_create(project=project, defaults={"enabled": True})
    if not customization.enabled:
        customization.enabled = True; customization.full_clean(); customization.save(update_fields=["enabled", "updated_at"])
    record_audit_event(actor=actor, action="studio.customization.enabled", instance=customization, metadata={"project_id": project.pk}, request=request)
    return customization


@transaction.atomic
def add_customization_element(*, customization, actor, decoration_zone, kind, text="", media_asset=None, transform=None, style=None, sort_order=0, request=None):
    project = customization.project
    require_project_draft(actor, project)
    if not customization.enabled:
        raise ValidationError("Customization is disabled.")
    element = CustomizationElement(customization=customization, decoration_zone=decoration_zone, kind=kind, text=text, media_asset=media_asset, transform=transform or {}, style=style or {}, sort_order=sort_order)
    element.full_clean(); element.save()
    record_audit_event(actor=actor, action="studio.element.created", instance=element, metadata={"project_id": project.pk, "kind": kind}, request=request)
    return element


@transaction.atomic
def mark_project_ready(*, project, actor, request=None):
    require_project_draft(actor, project)
    _validate_available_product(project.product, project.variant, project.quantity)
    if project.variant_id is None:
        raise ValidationError("Select a product variant before continuing.")
    if hasattr(project, "customization") and project.customization.enabled:
        for element in project.customization.elements.select_related("decoration_zone", "media_asset"):
            element.full_clean()
    project.status = StudioProject.Status.READY
    project.ready_at = timezone.now()
    project.save(update_fields=["status", "ready_at", "updated_at"])
    record_audit_event(actor=actor, action="studio.project.ready", instance=project, metadata={"checkout_created": False}, request=request)
    return project
