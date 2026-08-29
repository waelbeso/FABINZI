from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.organizations.models import Organization


class ManufacturerListing(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"
        PAUSED = "paused", "Paused"

    organization = models.OneToOneField(Organization, on_delete=models.CASCADE, related_name="marketplace_listing")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True)
    headline_en = models.CharField(max_length=220, blank=True)
    headline_ar = models.CharField(max_length=220, blank=True)
    overview_en = models.TextField(blank=True)
    overview_ar = models.TextField(blank=True)
    public_email = models.EmailField(blank=True)
    public_phone = models.CharField(max_length=50, blank=True)
    accepts_rfq = models.BooleanField(default=True)
    sample_orders = models.BooleanField(default=False)
    min_order_quantity = models.PositiveIntegerField(null=True, blank=True)
    lead_time_min_days = models.PositiveIntegerField(null=True, blank=True)
    lead_time_max_days = models.PositiveIntegerField(null=True, blank=True)
    available_monthly_capacity = models.PositiveIntegerField(null=True, blank=True)
    materials = models.JSONField(default=list, blank=True)
    production_methods = models.JSONField(default=list, blank=True)
    markets = models.JSONField(default=list, blank=True)
    certifications = models.JSONField(default=list, blank=True)
    last_capacity_update = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("organization__display_name",)
        indexes = [models.Index(fields=["status", "accepts_rfq"], name="mkt_listing_status_idx")]

    def clean(self):
        if self.organization_id and self.organization.kind != Organization.Kind.MANUFACTURER:
            raise ValidationError({"organization": "Marketplace listings require a Manufacturer organization."})
        if self.lead_time_min_days is not None and self.lead_time_max_days is not None and self.lead_time_min_days > self.lead_time_max_days:
            raise ValidationError({"lead_time_max_days": "Maximum lead time must be greater than or equal to minimum lead time."})

    def __str__(self):
        return f"{self.organization} marketplace listing"


class ManufacturerCapability(models.Model):
    class CapabilityType(models.TextChoices):
        CUT_SEW = "cut_sew", "Cut & sew"
        PRINT = "print", "Printing"
        EMBROIDERY = "embroidery", "Embroidery"
        SAMPLING = "sampling", "Sampling"
        PATTERN = "pattern", "Pattern making"
        FINISHING = "finishing", "Finishing"
        PACKAGING = "packaging", "Packaging"
        OTHER = "other", "Other"

    listing = models.ForeignKey(ManufacturerListing, on_delete=models.CASCADE, related_name="capabilities")
    capability_type = models.CharField(max_length=24, choices=CapabilityType.choices)
    name = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    methods = models.JSONField(default=list, blank=True)
    min_quantity = models.PositiveIntegerField(null=True, blank=True)
    max_quantity = models.PositiveIntegerField(null=True, blank=True)
    lead_time_days = models.PositiveIntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("capability_type", "name")
        constraints = [models.UniqueConstraint(fields=["listing", "capability_type", "name"], name="unique_listing_capability")]

    def clean(self):
        if self.min_quantity is not None and self.max_quantity is not None and self.min_quantity > self.max_quantity:
            raise ValidationError({"max_quantity": "Maximum quantity must be greater than or equal to minimum quantity."})


class ManufacturerPortfolioAsset(models.Model):
    listing = models.ForeignKey(ManufacturerListing, on_delete=models.CASCADE, related_name="portfolio_assets")
    media_asset = models.ForeignKey("media.MediaAsset", on_delete=models.PROTECT, related_name="manufacturer_portfolio_assets")
    caption = models.CharField(max_length=220, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("sort_order", "id")

    def clean(self):
        if self.media_asset_id:
            if not self.media_asset.mime_type.startswith("image/"):
                raise ValidationError({"media_asset": "Manufacturer portfolio assets must be images."})
            if self.media_asset.access != self.media_asset.Access.PUBLIC:
                raise ValidationError({"media_asset": "Manufacturer portfolio images must be public."})


class RFQ(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        OPEN = "open", "Open"
        QUOTED = "quoted", "Quotes received"
        SELECTED = "selected", "Manufacturer selected"
        CLOSED = "closed", "Closed"
        CANCELLED = "cancelled", "Cancelled"

    designer_organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="manufacturer_rfqs")
    designed_product = models.ForeignKey("artwork.DesignedProduct", on_delete=models.PROTECT, related_name="manufacturer_rfqs")
    title = models.CharField(max_length=220)
    quantity = models.PositiveIntegerField()
    size_breakdown = models.JSONField(default=dict, blank=True)
    color_requirements = models.JSONField(default=list, blank=True)
    requested_methods = models.JSONField(default=list, blank=True)
    target_unit_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=3, default="EGP")
    desired_delivery_date = models.DateField(null=True, blank=True)
    delivery_country = models.CharField(max_length=2, default="EG")
    delivery_city = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_manufacturer_rfqs")
    created_at = models.DateTimeField(auto_now_add=True)
    opened_at = models.DateTimeField(null=True, blank=True)
    selected_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at",)
        indexes = [models.Index(fields=["designer_organization", "status"], name="rfq_designer_status_idx")]

    def clean(self):
        if self.designer_organization_id and self.designer_organization.kind != Organization.Kind.DESIGNER:
            raise ValidationError({"designer_organization": "RFQs require a Designer organization."})
        if self.designed_product_id and self.designed_product.organization_id != self.designer_organization_id:
            raise ValidationError({"designed_product": "Designed Product must belong to the RFQ Designer business."})
        if self.quantity < 1:
            raise ValidationError({"quantity": "Quantity must be at least 1."})
        if self.currency and len(self.currency) != 3:
            raise ValidationError({"currency": "Currency must be a 3-letter code."})

    def __str__(self):
        return self.title


class RFQInvitation(models.Model):
    class Status(models.TextChoices):
        INVITED = "invited", "Invited"
        VIEWED = "viewed", "Viewed"
        DECLINED = "declined", "Declined"
        QUOTED = "quoted", "Quoted"

    rfq = models.ForeignKey(RFQ, on_delete=models.CASCADE, related_name="invitations")
    manufacturer = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="rfq_invitations")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.INVITED, db_index=True)
    sent_at = models.DateTimeField(auto_now_add=True)
    viewed_at = models.DateTimeField(null=True, blank=True)
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-sent_at",)
        constraints = [models.UniqueConstraint(fields=["rfq", "manufacturer"], name="unique_rfq_manufacturer_invite")]

    def clean(self):
        if self.manufacturer_id and self.manufacturer.kind != Organization.Kind.MANUFACTURER:
            raise ValidationError({"manufacturer": "RFQ invitations require a Manufacturer organization."})


class ManufacturerQuote(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted"
        WITHDRAWN = "withdrawn", "Withdrawn"
        ACCEPTED = "accepted", "Accepted"
        DECLINED = "declined", "Declined"
        EXPIRED = "expired", "Expired"

    invitation = models.OneToOneField(RFQInvitation, on_delete=models.CASCADE, related_name="quote")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    setup_fee = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    sample_fee = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    shipping_estimate = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, default="EGP")
    minimum_order_quantity = models.PositiveIntegerField(default=1)
    production_lead_days = models.PositiveIntegerField()
    sample_lead_days = models.PositiveIntegerField(null=True, blank=True)
    valid_until = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="manufacturer_quotes")
    created_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at",)

    def clean(self):
        if self.invitation_id and self.minimum_order_quantity > self.invitation.rfq.quantity:
            raise ValidationError({"minimum_order_quantity": "Quote MOQ cannot exceed the requested RFQ quantity."})
        if self.currency and len(self.currency) != 3:
            raise ValidationError({"currency": "Currency must be a 3-letter code."})

    @property
    def estimated_total(self):
        return self.unit_price * self.invitation.rfq.quantity + self.setup_fee + self.sample_fee + self.shipping_estimate


class ManufacturerSelection(models.Model):
    rfq = models.OneToOneField(RFQ, on_delete=models.PROTECT, related_name="selection")
    quote = models.OneToOneField(ManufacturerQuote, on_delete=models.PROTECT, related_name="selection")
    manufacturer = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="marketplace_selections")
    selected_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="manufacturer_selections")
    selected_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        if self.quote_id and self.rfq_id and self.quote.invitation.rfq_id != self.rfq_id:
            raise ValidationError({"quote": "Selected quote must belong to the selected RFQ."})
        if self.quote_id and self.manufacturer_id and self.quote.invitation.manufacturer_id != self.manufacturer_id:
            raise ValidationError({"manufacturer": "Selected Manufacturer must match the quote."})
