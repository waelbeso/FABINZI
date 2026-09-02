import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class PublicInquiry(models.Model):
    """Public visitor/customer inquiry, deliberately separate from Manufacturing RFQ."""

    class TargetKind(models.TextChoices):
        DESIGNER = "designer", "Designer"
        MANUFACTURER = "manufacturer", "Manufacturer"

    class DesignerWorkKind(models.TextChoices):
        GARMENT_DESIGN = "garment_design", "Garment Design"
        ARTWORK = "artwork", "Artwork"
        READY_PRODUCT = "ready_product", "Ready Designed Product"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted"
        HANDLING = "handling", "Handling"
        RESPONDED = "responded", "Responded"
        CLOSED = "closed", "Closed"
        SPAM = "spam", "Spam / abuse"

    reference = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    target_kind = models.CharField(max_length=16, choices=TargetKind.choices)
    target_organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="public_inquiries_received",
    )
    sender_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="public_inquiries_sent",
    )
    sender_email = models.EmailField(blank=True)
    sender_email_verified = models.BooleanField(default=False)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT, db_index=True)
    designer_work_kind = models.CharField(max_length=24, choices=DesignerWorkKind.choices, blank=True)
    garment_design = models.ForeignKey("design.GarmentDesign", null=True, blank=True, on_delete=models.PROTECT, related_name="public_inquiries")
    artwork = models.ForeignKey("artwork.Artwork", null=True, blank=True, on_delete=models.PROTECT, related_name="public_inquiries")
    ready_product = models.ForeignKey("artwork.DesignedProduct", null=True, blank=True, on_delete=models.PROTECT, related_name="public_inquiries")
    manufacturer_product_approval = models.ForeignKey(
        "public_profiles.ManufacturerPublicProductApproval",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="public_inquiries",
    )
    quantity = models.PositiveIntegerField(default=1)
    size_requirements = models.JSONField(default=dict, blank=True)
    color_requirements = models.JSONField(default=list, blank=True)
    customization_description = models.TextField(blank=True)
    delivery_city = models.CharField(max_length=120, blank=True)
    delivery_country = models.CharField(max_length=2, blank=True)
    desired_date = models.DateField(null=True, blank=True)
    requirements = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    staff_notes = models.TextField(blank=True)
    handled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="public_inquiries_handled",
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["target_organization", "status", "created_at"], name="pubinq_target_status_idx"),
            models.Index(fields=["sender_user", "created_at"], name="pubinq_sender_created_idx"),
        ]

    def clean(self):
        super().clean()
        from apps.organizations.models import Organization

        if self.quantity < 1:
            raise ValidationError({"quantity": "Quantity must be at least one."})
        if self.target_organization_id:
            expected = Organization.Kind.DESIGNER if self.target_kind == self.TargetKind.DESIGNER else Organization.Kind.MANUFACTURER
            if self.target_organization.kind != expected:
                raise ValidationError({"target_organization": "Inquiry target kind does not match the professional organization."})
        selected = [self.garment_design_id, self.artwork_id, self.ready_product_id]
        if self.target_kind == self.TargetKind.DESIGNER:
            if self.manufacturer_product_approval_id:
                raise ValidationError("Designer inquiries cannot reference a Manufacturer public-product approval.")
            if sum(bool(value) for value in selected) != 1:
                raise ValidationError("A Designer inquiry must reference exactly one approved public work.")
            expected_map = {
                self.DesignerWorkKind.GARMENT_DESIGN: self.garment_design_id,
                self.DesignerWorkKind.ARTWORK: self.artwork_id,
                self.DesignerWorkKind.READY_PRODUCT: self.ready_product_id,
            }
            if not self.designer_work_kind or not expected_map.get(self.designer_work_kind):
                raise ValidationError("Designer inquiry work type must match its selected public work.")
        elif self.target_kind == self.TargetKind.MANUFACTURER:
            if any(selected) or self.designer_work_kind:
                raise ValidationError("Manufacturer inquiries cannot reference Designer work fields.")
            if not self.manufacturer_product_approval_id:
                raise ValidationError("Manufacturer inquiries require an explicitly approved public product relationship.")
            if self.manufacturer_product_approval.manufacturer_id != self.target_organization_id:
                raise ValidationError("The selected public product is not approved for this Manufacturer.")

    def __str__(self):
        return f"{self.reference} · {self.target_kind} · {self.status}"


class PublicInquiryMessage(models.Model):
    class SenderRole(models.TextChoices):
        VISITOR = "visitor", "Visitor / customer"
        PROFESSIONAL = "professional", "Professional"
        STAFF = "staff", "FABINZI staff"

    inquiry = models.ForeignKey(PublicInquiry, on_delete=models.CASCADE, related_name="messages")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="public_inquiry_messages")
    sender_role = models.CharField(max_length=16, choices=SenderRole.choices)
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]


class PublicInquiryAttachment(models.Model):
    inquiry = models.ForeignKey(PublicInquiry, on_delete=models.CASCADE, related_name="attachments")
    media_asset = models.ForeignKey("media.MediaAsset", on_delete=models.PROTECT, related_name="public_inquiry_attachments")
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="public_inquiry_attachments")
    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        super().clean()
        from apps.media.models import MediaAsset
        if self.media_asset_id and self.media_asset.access != MediaAsset.Access.PRIVATE:
            raise ValidationError({"media_asset": "Public inquiry attachments must remain PRIVATE MediaAssets."})


class PublicInquiryEmailChallenge(models.Model):
    reference = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    email = models.EmailField(db_index=True)
    session_key_hash = models.CharField(max_length=64)
    otp_hash = models.CharField(max_length=256)
    expires_at = models.DateTimeField()
    verified_at = models.DateTimeField(null=True, blank=True)
    consumed_at = models.DateTimeField(null=True, blank=True)
    attempt_count = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["email", "created_at"], name="pubinq_email_created_idx")]

    @property
    def is_verified(self):
        return bool(self.verified_at and not self.consumed_at)
