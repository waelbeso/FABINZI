from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.organizations.models import Organization


class Artwork(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        IN_REVIEW = "in_review", "In review"
        REVISION_REQUIRED = "revision_required", "Revision required"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        SUSPENDED = "suspended", "Suspended"
        ARCHIVED = "archived", "Archived"

    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="artworks")
    title = models.CharField(max_length=220)
    description = models.TextField(blank=True)
    tags = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.DRAFT, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_artworks")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at",)
        indexes = [models.Index(fields=["organization", "status"], name="artwork_org_status_idx")]

    def clean(self):
        if self.organization_id and self.organization.kind != Organization.Kind.DESIGNER:
            raise ValidationError({"organization": "Artwork requires a Designer organization."})

    def __str__(self):
        return self.title


class ArtworkVersion(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted"
        REVISION_REQUIRED = "revision_required", "Revision required"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    artwork = models.ForeignKey(Artwork, on_delete=models.CASCADE, related_name="versions")
    version_number = models.PositiveIntegerField()
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.DRAFT, db_index=True)
    color_profile = models.CharField(max_length=80, blank=True)
    production_notes = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_artwork_versions")
    created_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="reviewed_artwork_versions")
    review_notes = models.TextField(blank=True)

    class Meta:
        ordering = ("-version_number",)
        constraints = [models.UniqueConstraint(fields=["artwork", "version_number"], name="unique_artwork_version_number")]

    def __str__(self):
        return f"{self.artwork} v{self.version_number}"


class ArtworkAsset(models.Model):
    class Kind(models.TextChoices):
        PREVIEW = "preview", "Preview image"
        SOURCE = "source", "Production source"
        RIGHTS_EVIDENCE = "rights_evidence", "Rights evidence"

    version = models.ForeignKey(ArtworkVersion, on_delete=models.CASCADE, related_name="assets")
    kind = models.CharField(max_length=24, choices=Kind.choices)
    media_asset = models.ForeignKey("media.MediaAsset", on_delete=models.PROTECT, related_name="artwork_assets")
    label = models.CharField(max_length=180, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        if not self.media_asset_id:
            return
        media = self.media_asset
        if self.kind == self.Kind.PREVIEW:
            if not media.mime_type.startswith("image/"):
                raise ValidationError({"media_asset": "Artwork previews must be images."})
        elif media.access != media.Access.PRIVATE:
            raise ValidationError({"media_asset": "Artwork source and rights evidence must be private."})


class IPDeclaration(models.Model):
    class RightsBasis(models.TextChoices):
        ORIGINAL = "original", "Original work owned by creator"
        EXCLUSIVE_LICENSE = "exclusive_license", "Exclusive license"
        NONEXCLUSIVE_LICENSE = "nonexclusive_license", "Non-exclusive license"
        PUBLIC_DOMAIN = "public_domain", "Public domain"
        OTHER = "other", "Other documented rights"

    version = models.OneToOneField(ArtworkVersion, on_delete=models.CASCADE, related_name="ip_declaration")
    rights_basis = models.CharField(max_length=32, choices=RightsBasis.choices)
    rights_holder_name = models.CharField(max_length=220)
    third_party_content = models.BooleanField(default=False)
    details = models.TextField(blank=True)
    accepts_ip_policy = models.BooleanField(default=False)
    declared_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="ip_declarations")
    declared_at = models.DateTimeField(auto_now_add=True)


class ArtworkReview(models.Model):
    class Decision(models.TextChoices):
        APPROVED = "approved", "Approved"
        REVISION_REQUIRED = "revision_required", "Revision required"
        REJECTED = "rejected", "Rejected"

    version = models.ForeignKey(ArtworkVersion, on_delete=models.CASCADE, related_name="reviews")
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="artwork_reviews")
    decision = models.CharField(max_length=24, choices=Decision.choices)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)


class DesignedProduct(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"
        SUSPENDED = "suspended", "Suspended"
        ARCHIVED = "archived", "Archived"

    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="designed_products")
    garment_version = models.ForeignKey("design.GarmentDesignVersion", on_delete=models.PROTECT, related_name="designed_products")
    artwork_version = models.ForeignKey(ArtworkVersion, on_delete=models.PROTECT, related_name="designed_products")
    title = models.CharField(max_length=220)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_designed_products")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at",)
        indexes = [models.Index(fields=["organization", "status"], name="dproduct_org_status_idx")]

    def clean(self):
        if not self.organization_id:
            return
        if self.organization.kind != Organization.Kind.DESIGNER:
            raise ValidationError({"organization": "Designed Products require a Designer organization."})
        if self.garment_version_id and self.garment_version.design.organization_id != self.organization_id:
            raise ValidationError({"garment_version": "Garment Design must belong to the same Designer business."})
        if self.artwork_version_id and self.artwork_version.artwork.organization_id != self.organization_id:
            raise ValidationError({"artwork_version": "Artwork must belong to the same Designer business."})

    def __str__(self):
        return self.title


class ArtworkPlacement(models.Model):
    product = models.ForeignKey(DesignedProduct, on_delete=models.CASCADE, related_name="placements")
    decoration_zone = models.ForeignKey("design.DecorationZone", on_delete=models.PROTECT, related_name="artwork_placements")
    transform = models.JSONField(default=dict, help_text="Normalized x/y/scale/rotation transform.")
    production_method = models.CharField(max_length=20, choices=[("print", "Print"), ("embroidery", "Embroidery")])

    class Meta:
        constraints = [models.UniqueConstraint(fields=["product", "decoration_zone"], name="unique_product_decoration_zone")]

    def clean(self):
        if self.product_id and self.decoration_zone_id and self.decoration_zone.version_id != self.product.garment_version_id:
            raise ValidationError({"decoration_zone": "Decoration zone must belong to the product garment version."})
        if self.decoration_zone_id and self.decoration_zone.method != "both" and self.production_method != self.decoration_zone.method:
            raise ValidationError({"production_method": "Production method is not supported by this decoration zone."})


class IPCase(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        UNDER_REVIEW = "under_review", "Under review"
        ACTION_REQUIRED = "action_required", "Action required"
        RESOLVED = "resolved", "Resolved"
        DISMISSED = "dismissed", "Dismissed"

    class Resolution(models.TextChoices):
        NONE = "none", "No resolution yet"
        TAKEDOWN = "takedown", "Takedown"
        RESTORED = "restored", "Restored"
        CLAIM_REJECTED = "claim_rejected", "Claim rejected"

    artwork = models.ForeignKey(Artwork, null=True, blank=True, on_delete=models.PROTECT, related_name="ip_cases")
    designed_product = models.ForeignKey(DesignedProduct, null=True, blank=True, on_delete=models.PROTECT, related_name="ip_cases")
    reporter_name = models.CharField(max_length=220)
    reporter_email = models.EmailField()
    claimant_rights = models.TextField()
    allegation = models.TextField()
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.OPEN, db_index=True)
    resolution = models.CharField(max_length=24, choices=Resolution.choices, default=Resolution.NONE)
    staff_notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="reported_ip_cases")
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="assigned_ip_cases")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)

    def clean(self):
        if bool(self.artwork_id) == bool(self.designed_product_id):
            raise ValidationError("An IP case must target exactly one Artwork or Designed Product.")


class IPCaseEvidence(models.Model):
    case = models.ForeignKey(IPCase, on_delete=models.CASCADE, related_name="evidence")
    media_asset = models.ForeignKey("media.MediaAsset", on_delete=models.PROTECT, related_name="ip_case_evidence")
    description = models.CharField(max_length=255, blank=True)
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        if self.media_asset_id and self.media_asset.access != self.media_asset.Access.PRIVATE:
            raise ValidationError({"media_asset": "IP case evidence must be private."})
