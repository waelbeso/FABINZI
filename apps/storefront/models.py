from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.organizations.models import Organization


class Storefront(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"
        PAUSED = "paused", "Paused"

    organization = models.OneToOneField(Organization, on_delete=models.CASCADE, related_name="storefront")
    slug = models.SlugField(max_length=100, unique=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True)
    name_en = models.CharField(max_length=180)
    name_ar = models.CharField(max_length=180, blank=True)
    about_en = models.TextField(blank=True)
    about_ar = models.TextField(blank=True)
    logo = models.ForeignKey("media.MediaAsset", null=True, blank=True, on_delete=models.PROTECT, related_name="storefront_logos")
    published_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name_en",)

    def clean(self):
        if self.organization_id and self.organization.kind != Organization.Kind.DESIGNER:
            raise ValidationError({"organization": "Storefronts require a Designer organization."})
        if self.logo_id and (not self.logo.mime_type.startswith("image/") or self.logo.access != self.logo.Access.PUBLIC):
            raise ValidationError({"logo": "Storefront logo must be a public image."})

    def __str__(self):
        return self.name_en


class StoreProduct(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"
        HIDDEN = "hidden", "Hidden"
        ARCHIVED = "archived", "Archived"

    class FulfillmentMode(models.TextChoices):
        MADE_TO_ORDER = "made_to_order", "Made to order"
        STOCK = "stock", "Stock"

    storefront = models.ForeignKey(Storefront, on_delete=models.CASCADE, related_name="products")
    designed_product = models.ForeignKey("artwork.DesignedProduct", on_delete=models.PROTECT, related_name="store_products")
    slug = models.SlugField(max_length=120)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True)
    title_en = models.CharField(max_length=220)
    title_ar = models.CharField(max_length=220, blank=True)
    description_en = models.TextField(blank=True)
    description_ar = models.TextField(blank=True)
    base_price = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="EGP")
    fulfillment_mode = models.CharField(max_length=20, choices=FulfillmentMode.choices, default=FulfillmentMode.MADE_TO_ORDER)
    lead_time_days = models.PositiveIntegerField(null=True, blank=True)
    customization_enabled = models.BooleanField(default=False)
    featured = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-featured", "-updated_at")
        constraints = [models.UniqueConstraint(fields=["storefront", "slug"], name="unique_store_product_slug")]
        indexes = [models.Index(fields=["storefront", "status"], name="store_product_status_idx")]

    def clean(self):
        if self.storefront_id and self.designed_product_id and self.designed_product.organization_id != self.storefront.organization_id:
            raise ValidationError({"designed_product": "Designed Product must belong to the Storefront Designer business."})
        if self.currency and len(self.currency) != 3:
            raise ValidationError({"currency": "Currency must be a 3-letter code."})
        if self.base_price is not None and self.base_price < 0:
            raise ValidationError({"base_price": "Price cannot be negative."})


class ProductVariant(models.Model):
    product = models.ForeignKey(StoreProduct, on_delete=models.CASCADE, related_name="variants")
    sku = models.CharField(max_length=120, unique=True)
    size = models.CharField(max_length=40, blank=True)
    color_name = models.CharField(max_length=80, blank=True)
    color_hex = models.CharField(max_length=7, blank=True)
    price_adjustment = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    stock_quantity = models.PositiveIntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("size", "color_name", "sku")

    def clean(self):
        if self.color_hex and (len(self.color_hex) != 7 or not self.color_hex.startswith("#")):
            raise ValidationError({"color_hex": "Color must use #RRGGBB format."})

    @property
    def price(self):
        return self.product.base_price + self.price_adjustment


class StoreProductImage(models.Model):
    product = models.ForeignKey(StoreProduct, on_delete=models.CASCADE, related_name="images")
    media_asset = models.ForeignKey("media.MediaAsset", on_delete=models.PROTECT, related_name="store_product_images")
    alt_en = models.CharField(max_length=180, blank=True)
    alt_ar = models.CharField(max_length=180, blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("sort_order", "id")

    def clean(self):
        if self.media_asset_id and (not self.media_asset.mime_type.startswith("image/") or self.media_asset.access != self.media_asset.Access.PUBLIC):
            raise ValidationError({"media_asset": "Store product images must be public images."})


class StudioProject(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        READY = "ready", "Ready for checkout"
        ARCHIVED = "archived", "Archived"

    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="studio_projects")
    product = models.ForeignKey(StoreProduct, on_delete=models.PROTECT, related_name="studio_projects")
    variant = models.ForeignKey(ProductVariant, null=True, blank=True, on_delete=models.PROTECT, related_name="studio_projects")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True)
    quantity = models.PositiveIntegerField(default=1)
    customer_notes = models.TextField(blank=True)
    preview = models.ForeignKey("media.MediaAsset", null=True, blank=True, on_delete=models.PROTECT, related_name="studio_previews")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    ready_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-updated_at",)

    def clean(self):
        if self.variant_id and self.variant.product_id != self.product_id:
            raise ValidationError({"variant": "Variant must belong to the selected Store Product."})
        if self.quantity < 1:
            raise ValidationError({"quantity": "Quantity must be at least 1."})
        if self.preview_id and (not self.preview.mime_type.startswith("image/") or self.preview.uploaded_by_id not in {None, self.customer_id}):
            raise ValidationError({"preview": "Studio preview must be an image owned by the customer."})


class CustomerCustomization(models.Model):
    project = models.OneToOneField(StudioProject, on_delete=models.CASCADE, related_name="customization")
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        if self.project_id and self.enabled and not self.project.product.customization_enabled:
            raise ValidationError("Customization is not enabled for this Store Product.")


class CustomizationElement(models.Model):
    class Kind(models.TextChoices):
        TEXT = "text", "Text"
        IMAGE = "image", "Customer image"
        ARTWORK = "artwork", "Marketplace artwork"

    customization = models.ForeignKey(CustomerCustomization, on_delete=models.CASCADE, related_name="elements")
    decoration_zone = models.ForeignKey("design.DecorationZone", on_delete=models.PROTECT, related_name="customer_customization_elements")
    kind = models.CharField(max_length=16, choices=Kind.choices)
    text = models.CharField(max_length=240, blank=True)
    media_asset = models.ForeignKey("media.MediaAsset", null=True, blank=True, on_delete=models.PROTECT, related_name="customization_elements")
    artwork_version = models.ForeignKey("artwork.ArtworkVersion", null=True, blank=True, on_delete=models.PROTECT, related_name="customer_customization_elements")
    production_method = models.CharField(max_length=20, choices=[("print", "Print"), ("embroidery", "Embroidery")], blank=True)
    rights_confirmed = models.BooleanField(default=False)
    transform = models.JSONField(default=dict)
    style = models.JSONField(default=dict, blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("sort_order", "id")

    def clean(self):
        project = self.customization.project if self.customization_id else None
        if project and self.decoration_zone_id and self.decoration_zone.version_id != project.product.designed_product.garment_version_id:
            raise ValidationError({"decoration_zone": "Customization zone must belong to the product Garment Design Version."})
        if self.production_method:
            if self.production_method not in {"print", "embroidery"}:
                raise ValidationError({"production_method": "Unsupported production method."})
            if self.decoration_zone_id and self.decoration_zone.method != "both" and self.production_method != self.decoration_zone.method:
                raise ValidationError({"production_method": "Production method is not supported by this decoration zone."})

        if self.kind == self.Kind.TEXT:
            if not self.text.strip():
                raise ValidationError({"text": "Text customization requires text."})
            if self.media_asset_id or self.artwork_version_id:
                raise ValidationError("Text customization cannot reference image or Artwork media.")
        elif self.kind == self.Kind.IMAGE:
            if not self.media_asset_id or not self.media_asset.mime_type.startswith("image/"):
                raise ValidationError({"media_asset": "Image customization requires image media."})
            if self.media_asset.access != self.media_asset.Access.PRIVATE:
                raise ValidationError({"media_asset": "Customer customization images must remain private."})
            if not (self.media_asset.metadata or {}).get("studio_private_upload"):
                raise ValidationError({"media_asset": "Studio image must come from the protected customer upload flow."})
            if project and self.media_asset.uploaded_by_id != project.customer_id:
                raise ValidationError({"media_asset": "Customer image must be owned by the Studio customer."})
            if not self.rights_confirmed:
                raise ValidationError({"rights_confirmed": "Confirm that you have the right to use this content."})
            if self.artwork_version_id:
                raise ValidationError({"artwork_version": "Customer image customization cannot reference Marketplace Artwork."})
        elif self.kind == self.Kind.ARTWORK:
            if not self.artwork_version_id:
                raise ValidationError({"artwork_version": "Marketplace Artwork is required."})
            if self.artwork_version.status != self.artwork_version.Status.APPROVED or self.artwork_version.artwork.status != self.artwork_version.artwork.Status.APPROVED:
                raise ValidationError({"artwork_version": "Marketplace Artwork is not currently approved for use."})
            if self.media_asset_id:
                raise ValidationError({"media_asset": "Marketplace Artwork uses its approved source, not a customer media upload."})
        else:
            raise ValidationError({"kind": "Unsupported customization element type."})
