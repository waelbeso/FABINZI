from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class ProfessionalPublicState(models.Model):
    """V2-5 publication control plus public-only profile attributes.

    Existing Organization, DesignerProfile and ManufacturerListing records
    remain canonical for fields they already own.  PublicProfileRevision remains
    the only proposed-revision truth.  This model does not create a second
    mutable professional profile.
    """

    class Visibility(models.TextChoices):
        HIDDEN = "hidden", "Hidden"
        PENDING_APPROVAL = "pending_approval", "Pending FABINZI approval"
        VISIBLE = "visible", "Visible"

    organization = models.OneToOneField(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="public_state",
    )
    slug = models.SlugField(max_length=220, unique=True)
    visibility = models.CharField(
        max_length=24,
        choices=Visibility.choices,
        default=Visibility.HIDDEN,
        db_index=True,
    )
    public_name_en = models.CharField(max_length=180, blank=True)
    public_name_ar = models.CharField(max_length=180, blank=True)
    bio_en = models.TextField(blank=True)
    bio_ar = models.TextField(blank=True)
    specializations = models.JSONField(default=list, blank=True)
    profile_image = models.ForeignKey(
        "media.MediaAsset",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="public_profile_primary_uses",
    )
    cover_image = models.ForeignKey(
        "media.MediaAsset",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="public_profile_cover_uses",
    )
    public_google_maps_url = models.URLField(max_length=500, blank=True)
    public_categories = models.JSONField(default=list, blank=True)
    public_certifications = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["visibility", "organization"],
                name="pubprof_visibility_org_idx",
            ),
        ]

    def clean(self):
        super().clean()
        from apps.media.models import MediaAsset
        from apps.organizations.models import Organization

        if self.organization_id and self.organization.kind not in {
            Organization.Kind.DESIGNER,
            Organization.Kind.MANUFACTURER,
        }:
            raise ValidationError(
                "Public professional state requires a Designer or Manufacturer organization."
            )
        for field_name in ("profile_image", "cover_image"):
            asset = getattr(self, field_name, None)
            if asset and (
                asset.access != MediaAsset.Access.PUBLIC
                or not str(asset.mime_type or "").startswith("image/")
            ):
                raise ValidationError(
                    {field_name: "Public profile imagery must be an explicitly PUBLIC image MediaAsset."}
                )

    def __str__(self):
        return f"{self.organization} · {self.visibility}"


class ManufacturerCapabilityVerification(models.Model):
    """Explicit FABINZI mapping of a legacy capability to canonical V2 semantics.

    No legacy value, including PRINT, is inferred as DTF, DTG, or both.
    """

    class CanonicalCode(models.TextChoices):
        GARMENT_MANUFACTURING = "garment_manufacturing", "Garment Manufacturing"
        DTF = "dtf", "DTF"
        DTG = "dtg", "DTG"
        EMBROIDERY = "embroidery", "Embroidery"

    class Status(models.TextChoices):
        VERIFIED = "verified", "Verified"
        REVOKED = "revoked", "Revoked"

    capability = models.OneToOneField(
        "manufacturer_marketplace.ManufacturerCapability",
        on_delete=models.CASCADE,
        related_name="public_verification",
    )
    canonical_code = models.CharField(max_length=32, choices=CanonicalCode.choices)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.VERIFIED,
        db_index=True,
    )
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="verified_public_manufacturer_capabilities",
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.capability} · {self.canonical_code}"


class ManufacturerPublicProductApproval(models.Model):
    """Explicit FABINZI approval that a Manufacturer can produce a StoreProduct.

    The relationship is never inferred from RFQ, ManufacturerQuote,
    ProductionJob, order history, or transaction history.  It grants no retail
    ownership, pricing authority, Artwork ownership, or customer ownership.
    """

    class Status(models.TextChoices):
        APPROVED = "approved", "Approved"
        REVOKED = "revoked", "Revoked"

    manufacturer = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="public_product_approvals",
    )
    store_product = models.ForeignKey(
        "storefront.StoreProduct",
        on_delete=models.CASCADE,
        related_name="manufacturer_public_approvals",
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.APPROVED,
        db_index=True,
    )
    is_visible = models.BooleanField(default=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_manufacturer_public_products",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["manufacturer", "store_product"],
                name="uniq_public_manufacturer_store_product",
            )
        ]
        indexes = [
            models.Index(
                fields=["manufacturer", "status", "is_visible"],
                name="pubprod_mfr_status_idx",
            )
        ]

    def clean(self):
        super().clean()
        from apps.organizations.models import Organization

        if self.manufacturer_id and self.manufacturer.kind != Organization.Kind.MANUFACTURER:
            raise ValidationError(
                {"manufacturer": "Public product approval requires a Manufacturer organization."}
            )

    def __str__(self):
        return f"{self.manufacturer} · {self.store_product}"
