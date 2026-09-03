from decimal import Decimal

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
    symbolic_ref = models.CharField(max_length=100, null=True, blank=True, unique=True)
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

    class TechnicalCheckStatus(models.TextChoices):
        NOT_CHECKED = "not_checked", "Not checked"
        PASS = "pass", "Pass"
        FAIL = "fail", "Fail"
        NEEDS_EVIDENCE = "needs_evidence", "Needs evidence"

    artwork = models.ForeignKey(Artwork, on_delete=models.CASCADE, related_name="versions")
    symbolic_ref = models.CharField(max_length=120, null=True, blank=True, unique=True)
    version_number = models.PositiveIntegerField()
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.DRAFT, db_index=True)
    color_profile = models.CharField(max_length=80, blank=True)
    production_notes = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    intended_methods = models.JSONField(default=list, blank=True)
    technical_check_status = models.CharField(max_length=24, choices=TechnicalCheckStatus.choices, default=TechnicalCheckStatus.NOT_CHECKED, db_index=True)
    technical_check_result = models.JSONField(default=dict, blank=True)
    resolution_evidence = models.JSONField(default=dict, blank=True, help_text="Measured source-resolution/DPI evidence where genuinely available.")
    embroidery_suitability_evidence = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_artwork_versions")
    created_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="reviewed_artwork_versions")
    review_notes = models.TextField(blank=True)

    class Meta:
        ordering = ("-version_number",)
        constraints = [models.UniqueConstraint(fields=["artwork", "version_number"], name="unique_artwork_version_number")]

    def clean(self):
        valid_methods = {"dtf", "dtg", "embroidery"}
        if set(self.intended_methods or []) - valid_methods:
            raise ValidationError({"intended_methods": "Artwork production methods must be DTF, DTG and/or Embroidery."})

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
    technical_role = models.CharField(max_length=80, blank=True)
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


class ArtworkRegistrationSource(models.Model):
    """Versioned external procedure/source snapshot; no legal applicability is inferred."""

    source_name = models.CharField(max_length=220)
    source_kind = models.CharField(max_length=80, default="external_procedure_source")
    source_filename = models.CharField(max_length=255, blank=True)
    source_sha256 = models.CharField(max_length=64, blank=True)
    source_version = models.CharField(max_length=80, blank=True)
    source_date = models.DateField(null=True, blank=True)
    scope_description = models.TextField(blank=True)
    visual_graphic_applicability_confirmed = models.BooleanField(default=False)
    field_schema = models.JSONField(default=dict, blank=True)
    procedure_facts = models.JSONField(default=dict, blank=True)
    source_limitations = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["source_name", "source_sha256", "source_version"], name="unique_artwork_registration_source_snapshot")]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            old = type(self).objects.get(pk=self.pk)
            frozen = ("source_name", "source_kind", "source_filename", "source_sha256", "source_version", "source_date", "scope_description", "visual_graphic_applicability_confirmed", "field_schema", "procedure_facts", "source_limitations")
            if any(getattr(old, field) != getattr(self, field) for field in frozen):
                raise ValidationError("Registration source snapshots are immutable; create a new versioned source snapshot.")
        return super().save(*args, **kwargs)


class ArtworkRegistrationCase(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        EVIDENCE_REQUIRED = "evidence_required", "Evidence required"
        STAFF_REVIEW = "staff_review", "Staff review"
        READY_FOR_EXTERNAL_SUBMISSION = "ready_external", "Ready for external submission"
        SUBMITTED_EXTERNALLY = "submitted_external", "Submitted externally"
        COMPLETED = "completed", "Completed"
        REJECTED = "rejected", "Rejected"
        CANCELLED = "cancelled", "Cancelled"

    artwork_version = models.ForeignKey(ArtworkVersion, on_delete=models.PROTECT, related_name="registration_cases")
    applicant = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="artwork_registration_cases")
    source_snapshot = models.ForeignKey(ArtworkRegistrationSource, null=True, blank=True, on_delete=models.PROTECT, related_name="registration_cases")
    procedure_template_key = models.CharField(max_length=100, blank=True)
    captured_data = models.JSONField(default=dict, blank=True)
    representation_state = models.JSONField(default=dict, blank=True)
    service_price_egp = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("400.00"))
    official_fee_information = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.DRAFT, db_index=True)
    source_applicability_confirmed_for_case = models.BooleanField(default=False)
    external_reference = models.CharField(max_length=180, blank=True)
    external_submitted_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    staff_notes = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="reviewed_artwork_registration_cases")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at",)

    def clean(self):
        if self.service_price_egp != Decimal("400.00") and self.pk is None:
            # V2-4 policy snapshot is exactly the current FABINZI service price; future price policy may version this.
            raise ValidationError({"service_price_egp": "Current Artwork Registration Service price snapshot is EGP 400."})
        if self.source_applicability_confirmed_for_case and (not self.source_snapshot_id or not self.source_snapshot.visual_graphic_applicability_confirmed):
            raise ValidationError({"source_applicability_confirmed_for_case": "Case applicability cannot be represented as confirmed unless the selected versioned source explicitly supports it."})


class ArtworkRegistrationDocument(models.Model):
    case = models.ForeignKey(ArtworkRegistrationCase, on_delete=models.CASCADE, related_name="documents")
    kind = models.CharField(max_length=100)
    media_asset = models.ForeignKey("media.MediaAsset", on_delete=models.PROTECT, related_name="artwork_registration_documents")
    description = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="artwork_registration_documents")
    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        if self.media_asset_id and self.media_asset.access != self.media_asset.Access.PRIVATE:
            raise ValidationError({"media_asset": "Artwork registration documents must be private."})


class DesignedProduct(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"
        SUSPENDED = "suspended", "Suspended"
        ARCHIVED = "archived", "Archived"

    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="designed_products")
    symbolic_ref = models.CharField(max_length=120, null=True, blank=True, unique=True)
    garment_version = models.ForeignKey("design.GarmentDesignVersion", on_delete=models.PROTECT, related_name="designed_products")
    artwork_version = models.ForeignKey(ArtworkVersion, on_delete=models.PROTECT, related_name="designed_products")
    garment_creator_organization = models.ForeignKey(Organization, null=True, blank=True, on_delete=models.PROTECT, related_name="garment_attributed_designed_products")
    artwork_creator_organization = models.ForeignKey(Organization, null=True, blank=True, on_delete=models.PROTECT, related_name="artwork_attributed_designed_products")
    economic_attribution = models.JSONField(default=dict, blank=True)
    reference_only = models.BooleanField(default=False)
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
        if self.garment_creator_organization_id and self.garment_version_id and self.garment_creator_organization_id != self.garment_version.design.organization_id:
            raise ValidationError({"garment_creator_organization": "Garment creator attribution must match the canonical Garment Design creator."})
        if self.artwork_creator_organization_id and self.artwork_version_id and self.artwork_creator_organization_id != self.artwork_version.artwork.organization_id:
            raise ValidationError({"artwork_creator_organization": "Artwork creator attribution must match the canonical Artwork creator."})

    def __str__(self):
        return self.title


class ArtworkPlacement(models.Model):
    class ProductionMethod(models.TextChoices):
        PRINT_LEGACY = "print", "Print (legacy)"
        DTF = "dtf", "DTF"
        DTG = "dtg", "DTG"
        EMBROIDERY = "embroidery", "Embroidery"

    product = models.ForeignKey(DesignedProduct, on_delete=models.CASCADE, related_name="placements")
    decoration_zone = models.ForeignKey("design.DecorationZone", on_delete=models.PROTECT, related_name="artwork_placements")
    transform = models.JSONField(default=dict, help_text="Normalized x/y/width/height/rotation composition transform.")
    production_method = models.CharField(max_length=20, choices=ProductionMethod.choices)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["product", "decoration_zone"], name="unique_product_decoration_zone")]

    def clean(self):
        if self.product_id and self.decoration_zone_id and self.decoration_zone.version_id != self.product.garment_version_id:
            raise ValidationError({"decoration_zone": "Decoration zone must belong to the product garment version."})
        if self.decoration_zone_id:
            allowed = set(self.decoration_zone.effective_methods())
            method = self.production_method
            if method == self.ProductionMethod.PRINT_LEGACY:
                legacy_allowed = bool(allowed & {"dtf", "dtg"})
                if not legacy_allowed:
                    raise ValidationError({"production_method": "Legacy print is not supported by this Decoration Zone."})
            elif method not in allowed:
                raise ValidationError({"production_method": "Production method is not supported by this Decoration Zone."})
        transform = self.transform or {}
        required = {"x", "y", "width", "height"}
        if not required.issubset(transform):
            raise ValidationError({"transform": "Ready Designed Product placement requires normalized x, y, width and height."})
        try:
            x, y, width, height = [float(transform[key]) for key in ("x", "y", "width", "height")]
            float(transform.get("rotation", 0))
        except (TypeError, ValueError):
            raise ValidationError({"transform": "Placement transform values must be numeric."})
        if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > 1 or y + height > 1:
            raise ValidationError({"transform": "Placement transform must remain within normalized 0..1 bounds."})
        zone = self.decoration_zone.placement if self.decoration_zone_id else {}
        if all(key in zone for key in required):
            zx, zy, zw, zh = [float(zone[key]) for key in ("x", "y", "width", "height")]
            if x < zx or y < zy or x + width > zx + zw or y + height > zy + zh:
                raise ValidationError({"transform": "Artwork placement must remain inside the canonical Decoration Zone."})


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
