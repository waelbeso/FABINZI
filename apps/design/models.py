from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.organizations.models import Organization


class GarmentDesign(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        IN_REVIEW = "in_review", "In technical review"
        REVISION_REQUIRED = "revision_required", "Revision required"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        ARCHIVED = "archived", "Archived"

    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="garment_designs")
    title = models.CharField(max_length=220)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.DRAFT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_garment_designs")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at",)

    def clean(self):
        if self.organization_id and self.organization.kind != Organization.Kind.DESIGNER:
            raise ValidationError({"organization": "Garment Designs require a Designer organization."})

    def __str__(self):
        return self.title


class GarmentDesignVersion(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted"
        REVISION_REQUIRED = "revision_required", "Revision required"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    design = models.ForeignKey(GarmentDesign, on_delete=models.CASCADE, related_name="versions")
    version_number = models.PositiveIntegerField()
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.DRAFT)
    summary = models.CharField(max_length=255, blank=True)
    base_material = models.CharField(max_length=255, blank=True)
    construction_notes = models.TextField(blank=True)
    technical_specs = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_design_versions")
    created_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="reviewed_design_versions")
    review_notes = models.TextField(blank=True)

    class Meta:
        ordering = ("-version_number",)
        constraints = [models.UniqueConstraint(fields=["design", "version_number"], name="unique_design_version_number")]

    def __str__(self):
        return f"{self.design} v{self.version_number}"


class SizeChartRow(models.Model):
    version = models.ForeignKey(GarmentDesignVersion, on_delete=models.CASCADE, related_name="size_rows")
    size_label = models.CharField(max_length=40)
    measurements = models.JSONField(default=dict)
    notes = models.CharField(max_length=255, blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("sort_order", "id")
        constraints = [models.UniqueConstraint(fields=["version", "size_label"], name="unique_version_size_label")]


class DecorationZone(models.Model):
    class Method(models.TextChoices):
        PRINT = "print", "Print"
        EMBROIDERY = "embroidery", "Embroidery"
        BOTH = "both", "Print or embroidery"

    version = models.ForeignKey(GarmentDesignVersion, on_delete=models.CASCADE, related_name="decoration_zones")
    name = models.CharField(max_length=120)
    method = models.CharField(max_length=20, choices=Method.choices, default=Method.BOTH)
    placement = models.JSONField(default=dict, help_text="Normalized placement/geometry definition.")
    max_width_mm = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    max_height_mm = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ("id",)
        constraints = [models.UniqueConstraint(fields=["version", "name"], name="unique_version_decoration_zone")]


class DesignAsset(models.Model):
    class Kind(models.TextChoices):
        PRODUCT_IMAGE = "product_image", "Product image"
        PATTERN = "pattern", "Pattern"
        TECH_PACK = "tech_pack", "Tech pack"
        THREE_D = "3d", "3D asset"
        TECHNICAL = "technical", "Technical file"

    version = models.ForeignKey(GarmentDesignVersion, on_delete=models.CASCADE, related_name="assets")
    kind = models.CharField(max_length=24, choices=Kind.choices)
    media_asset = models.ForeignKey("media.MediaAsset", on_delete=models.PROTECT, related_name="design_assets")
    label = models.CharField(max_length=180, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        if not self.media_asset_id:
            return
        media = self.media_asset
        if self.kind == self.Kind.PRODUCT_IMAGE:
            if not media.mime_type.startswith("image/"):
                raise ValidationError({"media_asset": "Product images must be image media."})
        else:
            if media.access != media.Access.PRIVATE:
                raise ValidationError({"media_asset": "Patterns, tech packs, 3D and technical assets must be private."})
            if media.provider == media.Provider.CLOUDFLARE_IMAGES:
                raise ValidationError({"media_asset": "Technical files cannot use Cloudflare Images."})


class TechnicalReview(models.Model):
    class Decision(models.TextChoices):
        APPROVED = "approved", "Approved"
        REVISION_REQUIRED = "revision_required", "Revision required"
        REJECTED = "rejected", "Rejected"

    version = models.ForeignKey(GarmentDesignVersion, on_delete=models.CASCADE, related_name="reviews")
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="garment_technical_reviews")
    decision = models.CharField(max_length=24, choices=Decision.choices)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
