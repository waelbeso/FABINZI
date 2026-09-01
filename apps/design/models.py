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
    symbolic_ref = models.CharField(max_length=80, null=True, blank=True, unique=True)
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

    class ProductClass(models.TextChoices):
        APPAREL = "apparel", "Apparel"
        ACCESSORY = "accessory", "Accessory"
        HEADWEAR = "headwear", "Headwear"

    class SizeSystem(models.TextChoices):
        MULTI_SIZE = "multi_size", "Multi size"
        ONE_SIZE = "one_size", "One size"
        ONE_SIZE_ACCESSORY = "one_size_accessory", "One size accessory"

    class DecorationApplicability(models.TextChoices):
        UNDECLARED = "undeclared", "Undeclared"
        CONFIGURED = "configured", "Decoration configured"
        NOT_APPLICABLE = "not_applicable", "Decoration not applicable"

    design = models.ForeignKey(GarmentDesign, on_delete=models.CASCADE, related_name="versions")
    symbolic_ref = models.CharField(max_length=100, null=True, blank=True, unique=True)
    version_number = models.PositiveIntegerField()
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.DRAFT)
    summary = models.CharField(max_length=255, blank=True)
    base_material = models.CharField(max_length=255, blank=True)
    construction_notes = models.TextField(blank=True)
    technical_specs = models.JSONField(default=dict, blank=True)
    technical_schema_version = models.CharField(max_length=24, default="2.4")
    product_class = models.CharField(max_length=24, choices=ProductClass.choices, default=ProductClass.APPAREL)
    size_system = models.CharField(max_length=32, choices=SizeSystem.choices, default=SizeSystem.MULTI_SIZE)
    decoration_applicability = models.CharField(max_length=24, choices=DecorationApplicability.choices, default=DecorationApplicability.UNDECLARED)
    requires_3d_source = models.BooleanField(default=True)
    technical_policy = models.JSONField(default=dict, blank=True)
    qc_requirements = models.JSONField(default=dict, blank=True)
    production_engineering_validated = models.BooleanField(default=False)
    production_engineering_notes = models.TextField(blank=True)
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


class DesignPointOfMeasure(models.Model):
    class Unit(models.TextChoices):
        MM = "mm", "Millimetres"
        CM = "cm", "Centimetres"
        IN = "in", "Inches"

    version = models.ForeignKey(GarmentDesignVersion, on_delete=models.CASCADE, related_name="points_of_measure")
    symbolic_ref = models.CharField(max_length=100)
    name = models.CharField(max_length=180)
    unit = models.CharField(max_length=8, choices=Unit.choices, default=Unit.CM)
    tolerance_plus = models.DecimalField(max_digits=9, decimal_places=3, null=True, blank=True)
    tolerance_minus = models.DecimalField(max_digits=9, decimal_places=3, null=True, blank=True)
    required = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("sort_order", "id")
        constraints = [models.UniqueConstraint(fields=["version", "symbolic_ref"], name="unique_version_pom_ref")]


class DesignPOMValue(models.Model):
    point = models.ForeignKey(DesignPointOfMeasure, on_delete=models.CASCADE, related_name="values")
    size = models.ForeignKey(SizeChartRow, on_delete=models.CASCADE, related_name="pom_values")
    value = models.DecimalField(max_digits=10, decimal_places=3)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["point", "size"], name="unique_pom_size_value")]

    def clean(self):
        if self.point_id and self.size_id and self.point.version_id != self.size.version_id:
            raise ValidationError({"size": "POM value size must belong to the same Garment Design Version."})


class DesignMaterial(models.Model):
    version = models.ForeignKey(GarmentDesignVersion, on_delete=models.CASCADE, related_name="materials")
    symbolic_ref = models.CharField(max_length=100)
    role = models.CharField(max_length=120)
    name = models.CharField(max_length=220)
    composition = models.CharField(max_length=255, blank=True)
    gsm = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    specifications = models.JSONField(default=dict, blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("sort_order", "id")
        constraints = [models.UniqueConstraint(fields=["version", "symbolic_ref"], name="unique_version_material_ref")]


class DesignAsset(models.Model):
    class Kind(models.TextChoices):
        PRODUCT_IMAGE = "product_image", "Product image"
        PATTERN = "pattern", "Pattern"
        TECH_PACK = "tech_pack", "Tech pack"
        THREE_D = "3d", "3D asset"
        TECHNICAL = "technical", "Technical file"

    version = models.ForeignKey(GarmentDesignVersion, on_delete=models.CASCADE, related_name="assets")
    symbolic_ref = models.CharField(max_length=120, null=True, blank=True, unique=True)
    kind = models.CharField(max_length=24, choices=Kind.choices)
    media_asset = models.ForeignKey("media.MediaAsset", on_delete=models.PROTECT, related_name="design_assets")
    label = models.CharField(max_length=180, blank=True)
    technical_role = models.CharField(max_length=80, blank=True)
    size_label = models.CharField(max_length=40, blank=True)
    reference_only = models.BooleanField(default=False)
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


class DesignPatternRequirement(models.Model):
    version = models.ForeignKey(GarmentDesignVersion, on_delete=models.CASCADE, related_name="pattern_requirements")
    size = models.OneToOneField(SizeChartRow, on_delete=models.CASCADE, related_name="pattern_requirement")
    required = models.BooleanField(default=True)
    declared_scale_1_to_1 = models.BooleanField(default=False)
    pattern_asset = models.ForeignKey(DesignAsset, null=True, blank=True, on_delete=models.PROTECT, related_name="pattern_requirements")
    notes = models.TextField(blank=True)

    def clean(self):
        if self.size_id and self.version_id and self.size.version_id != self.version_id:
            raise ValidationError({"size": "Pattern size must belong to the same Garment Design Version."})
        if self.pattern_asset_id:
            if self.pattern_asset.version_id != self.version_id or self.pattern_asset.kind != DesignAsset.Kind.PATTERN:
                raise ValidationError({"pattern_asset": "Pattern asset must be a Pattern on the same Garment Design Version."})


class DesignColorway(models.Model):
    version = models.ForeignKey(GarmentDesignVersion, on_delete=models.CASCADE, related_name="colorways")
    symbolic_ref = models.CharField(max_length=100)
    name = models.CharField(max_length=160)
    hex_color = models.CharField(max_length=16, blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("sort_order", "id")
        constraints = [models.UniqueConstraint(fields=["version", "symbolic_ref"], name="unique_version_colorway_ref")]


class DesignColorwayImage(models.Model):
    class Role(models.TextChoices):
        THUMBNAIL = "thumbnail", "Thumbnail"
        PRODUCT_CARD_4_3 = "product_card_4_3", "Product card 4:3"
        PRODUCT_DETAIL = "product_detail", "Product detail"
        ZOOM_REFERENCE = "zoom_reference", "Zoom reference"
        TECHNICAL_REFERENCE = "technical_reference", "Technical reference"

    colorway = models.ForeignKey(DesignColorway, on_delete=models.CASCADE, related_name="images")
    asset = models.ForeignKey(DesignAsset, on_delete=models.PROTECT, related_name="colorway_roles")
    role = models.CharField(max_length=32, choices=Role.choices)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("sort_order", "id")
        constraints = [models.UniqueConstraint(fields=["colorway", "role", "asset"], name="unique_colorway_role_asset")]

    def clean(self):
        if self.colorway_id and self.asset_id:
            if self.asset.version_id != self.colorway.version_id or self.asset.kind != DesignAsset.Kind.PRODUCT_IMAGE:
                raise ValidationError({"asset": "Colorway image must be a product image on the same Garment Design Version."})


class DecorationZone(models.Model):
    class Method(models.TextChoices):
        PRINT = "print", "Print (legacy)"
        EMBROIDERY = "embroidery", "Embroidery"
        BOTH = "both", "Print or embroidery (legacy)"

    class ProductionMethod(models.TextChoices):
        DTF = "dtf", "DTF"
        DTG = "dtg", "DTG"
        EMBROIDERY = "embroidery", "Embroidery"

    version = models.ForeignKey(GarmentDesignVersion, on_delete=models.CASCADE, related_name="decoration_zones")
    symbolic_ref = models.CharField(max_length=120, null=True, blank=True, unique=True)
    name = models.CharField(max_length=120)
    surface = models.CharField(max_length=80, blank=True)
    method = models.CharField(max_length=20, choices=Method.choices, default=Method.BOTH)
    allowed_methods = models.JSONField(default=list, blank=True)
    placement = models.JSONField(default=dict, help_text="Normalized placement/geometry definition.")
    max_width_mm = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    max_height_mm = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    minimum_dpi = models.PositiveIntegerField(null=True, blank=True)
    embroidery_constraints = models.JSONField(default=dict, blank=True)
    reference_only = models.BooleanField(default=False)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ("id",)
        constraints = [models.UniqueConstraint(fields=["version", "name"], name="unique_version_decoration_zone")]

    def effective_methods(self):
        if self.allowed_methods:
            return list(self.allowed_methods)
        if self.method == self.Method.EMBROIDERY:
            return [self.ProductionMethod.EMBROIDERY]
        if self.method == self.Method.PRINT:
            return [self.ProductionMethod.DTF, self.ProductionMethod.DTG]
        return [self.ProductionMethod.DTF, self.ProductionMethod.DTG, self.ProductionMethod.EMBROIDERY]

    def clean(self):
        allowed = set(self.allowed_methods or [])
        valid = {choice for choice, _ in self.ProductionMethod.choices}
        if allowed - valid:
            raise ValidationError({"allowed_methods": "Unsupported production method in Decoration Zone."})
        geometry = self.placement or {}
        if all(key in geometry for key in ("x", "y", "width", "height")):
            try:
                x, y, width, height = [float(geometry[key]) for key in ("x", "y", "width", "height")]
            except (TypeError, ValueError):
                raise ValidationError({"placement": "Normalized geometry values must be numeric."})
            if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > 1 or y + height > 1:
                raise ValidationError({"placement": "Normalized Decoration Zone geometry must remain within 0..1 bounds."})


class TechnicalBlocker(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        RESOLVED = "resolved", "Resolved"

    version = models.ForeignKey(GarmentDesignVersion, on_delete=models.CASCADE, related_name="technical_blockers")
    code = models.CharField(max_length=100)
    description = models.TextField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN, db_index=True)
    reference_only = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="resolved_design_blockers")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["version", "code"], name="unique_version_blocker_code")]


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


class ReferenceDataset(models.Model):
    dataset_name = models.CharField(max_length=180)
    dataset_version = models.CharField(max_length=40)
    machine_contract_identity = models.CharField(max_length=180)
    machine_contract_version = models.CharField(max_length=40)
    machine_contract_sha256 = models.CharField(max_length=64)
    image_role_contract_identity = models.CharField(max_length=180)
    image_role_contract_version = models.CharField(max_length=40)
    image_role_contract_sha256 = models.CharField(max_length=64)
    reference_notice = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["dataset_name", "dataset_version"], name="unique_reference_dataset_version")]


class ReferencePackage(models.Model):
    class Status(models.TextChoices):
        APPROVED_REFERENCE = "approved_reference", "Approved reference"

    dataset = models.ForeignKey(ReferenceDataset, on_delete=models.PROTECT, related_name="packages")
    product_ref = models.CharField(max_length=32)
    product_name = models.CharField(max_length=180)
    canonical_filename = models.CharField(max_length=255)
    package_sha256 = models.CharField(max_length=64)
    source_design_ref = models.CharField(max_length=100)
    source_gdv_ref = models.CharField(max_length=100)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.APPROVED_REFERENCE)
    golden_reference_complete = models.BooleanField(default=True)
    public_reference_allowed = models.BooleanField(default=True)
    production_engineering_validated = models.BooleanField(default=False)
    synthetic_reference = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["dataset", "product_ref"], name="unique_reference_product_ref"),
            models.UniqueConstraint(fields=["dataset", "canonical_filename"], name="unique_reference_filename"),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            old = type(self).objects.filter(pk=self.pk).values(
                "dataset_id", "product_ref", "canonical_filename", "package_sha256", "source_design_ref", "source_gdv_ref"
            ).first()
            if old:
                current = {
                    "dataset_id": self.dataset_id,
                    "product_ref": self.product_ref,
                    "canonical_filename": self.canonical_filename,
                    "package_sha256": self.package_sha256,
                    "source_design_ref": self.source_design_ref,
                    "source_gdv_ref": self.source_gdv_ref,
                }
                if old != current:
                    raise ValidationError("Frozen reference package identity/provenance cannot be modified in place.")
        return super().save(*args, **kwargs)


class DesignReferenceProvenance(models.Model):
    package = models.OneToOneField(ReferencePackage, on_delete=models.PROTECT, related_name="design_provenance")
    design = models.OneToOneField(GarmentDesign, on_delete=models.PROTECT, related_name="reference_provenance")
    version = models.OneToOneField(GarmentDesignVersion, on_delete=models.PROTECT, related_name="reference_provenance")
    source_symbolic_ids = models.JSONField(default=dict, blank=True)
    import_implementation_version = models.CharField(max_length=40)
    imported_at = models.DateTimeField(auto_now_add=True)
    imported_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="reference_imports")

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("Imported reference provenance is immutable; create a versioned reference artifact instead.")
        return super().save(*args, **kwargs)
