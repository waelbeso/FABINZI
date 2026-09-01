from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Organization(models.Model):
    class Kind(models.TextChoices):
        DESIGNER = "designer", "Designer"
        MANUFACTURER = "manufacturer", "Manufacturer"

    class VerificationStatus(models.TextChoices):
        DRAFT = "draft", "Draft"
        PENDING = "pending", "Pending verification"
        ACTIVE = "active", "Active"
        REJECTED = "rejected", "Rejected"
        SUSPENDED = "suspended", "Suspended"

    kind = models.CharField(max_length=20, choices=Kind.choices, db_index=True)
    display_name = models.CharField(max_length=180)
    legal_name = models.CharField(max_length=220, blank=True)
    email = models.EmailField()
    phone = models.CharField(max_length=50, blank=True)
    website = models.URLField(blank=True)
    address_line1 = models.CharField(max_length=255, blank=True)
    address_line2 = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=120, blank=True)
    region = models.CharField(max_length=120, blank=True)
    country = models.CharField(max_length=2, default="EG")
    verification_status = models.CharField(max_length=20, choices=VerificationStatus.choices, default=VerificationStatus.DRAFT, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_organizations")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("display_name",)
        indexes = [models.Index(fields=["kind", "verification_status"])]

    def __str__(self):
        return self.display_name


class Membership(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        MANAGER = "manager", "Manager"
        DESIGNER = "designer", "Designer"
        DESIGN_MANAGER = "design_manager", "Design Manager"
        ACCOUNTANT = "accountant", "Accountant"
        PRODUCTION_MANAGER = "production_manager", "Production Manager"
        OPERATOR = "operator", "Operator"
        QC = "qc", "QC"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="business_memberships")
    role = models.CharField(max_length=32, choices=Role.choices)
    is_active = models.BooleanField(default=True)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["organization", "user"], name="unique_org_user_membership")]
        indexes = [models.Index(fields=["user", "is_active"]), models.Index(fields=["organization", "role"])]

    def clean(self):
        if not self.organization_id:
            return
        designer_roles = {self.Role.OWNER, self.Role.MANAGER, self.Role.DESIGNER, self.Role.DESIGN_MANAGER, self.Role.ACCOUNTANT}
        manufacturer_roles = {self.Role.OWNER, self.Role.MANAGER, self.Role.PRODUCTION_MANAGER, self.Role.OPERATOR, self.Role.QC, self.Role.ACCOUNTANT}
        allowed = designer_roles if self.organization.kind == Organization.Kind.DESIGNER else manufacturer_roles
        if self.role not in allowed:
            raise ValidationError({"role": "This role is not valid for this organization type."})

    def __str__(self):
        return f"{self.user} · {self.organization} · {self.get_role_display()}"


class DesignerProfile(models.Model):
    organization = models.OneToOneField(Organization, on_delete=models.CASCADE, related_name="designer_profile")
    studio_name = models.CharField(max_length=180, blank=True)
    portfolio_url = models.URLField(blank=True)
    social_links = models.JSONField(default=dict, blank=True)
    legal_registration_number = models.CharField(max_length=120, blank=True)
    tax_number = models.CharField(max_length=120, blank=True)
    payout_information = models.TextField(blank=True, help_text="Stage 1 onboarding information only; payout execution is implemented in the finance stage.")
    terms_accepted = models.BooleanField(default=False)
    terms_accepted_at = models.DateTimeField(null=True, blank=True)

    def clean(self):
        if self.organization_id and self.organization.kind != Organization.Kind.DESIGNER:
            raise ValidationError("DesignerProfile requires a designer organization.")

    def __str__(self):
        return self.studio_name or (self.organization.display_name if self.organization_id else "Designer")


class ManufacturerProfile(models.Model):
    organization = models.OneToOneField(Organization, on_delete=models.CASCADE, related_name="manufacturer_profile")
    commercial_registration = models.CharField(max_length=120, blank=True)
    tax_number = models.CharField(max_length=120, blank=True)
    google_maps_url = models.URLField(blank=True)
    primary_contact_person = models.CharField(max_length=180, blank=True)
    contact_job_title = models.CharField(max_length=120, blank=True)
    whatsapp = models.CharField(max_length=50, blank=True)
    manufacturing_categories = models.JSONField(default=list, blank=True)
    equipment = models.JSONField(default=list, blank=True)
    capability_summary = models.JSONField(default=dict, blank=True)
    daily_capacity = models.PositiveIntegerField(null=True, blank=True)
    monthly_capacity = models.PositiveIntegerField(null=True, blank=True)
    certifications = models.JSONField(default=list, blank=True)
    payout_information = models.TextField(blank=True, help_text="Stage 1 onboarding information only; payout execution is implemented in the finance stage.")
    terms_accepted = models.BooleanField(default=False)
    terms_accepted_at = models.DateTimeField(null=True, blank=True)

    def clean(self):
        if self.organization_id and self.organization.kind != Organization.Kind.MANUFACTURER:
            raise ValidationError("ManufacturerProfile requires a manufacturer organization.")

    def __str__(self):
        return self.organization.display_name if self.organization_id else "Manufacturer"


class OnboardingApplication(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted"
        REVISION_REQUIRED = "revision_required", "Revision required"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    organization = models.OneToOneField(Organization, on_delete=models.CASCADE, related_name="onboarding_application")
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.DRAFT, db_index=True)
    review_notes = models.TextField(blank=True)
    revision_count = models.PositiveIntegerField(default=0)
    submitted_at = models.DateTimeField(null=True, blank=True)
    initial_review_target_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="reviewed_onboarding_applications")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at",)
        indexes = [models.Index(fields=["status", "updated_at"])]

    @property
    def review_target_at(self):
        return self.initial_review_target_at

    def __str__(self):
        return f"{self.organization} · {self.get_status_display()}"


class PublicProfileRevision(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted"
        UNDER_REVIEW = "under_review", "Under review"
        CHANGES_REQUIRED = "changes_required", "Changes required"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    OPEN_STATUSES = (Status.DRAFT, Status.SUBMITTED, Status.UNDER_REVIEW, Status.CHANGES_REQUIRED)
    EDITABLE_STATUSES = (Status.DRAFT, Status.CHANGES_REQUIRED)

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="public_profile_revisions")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True)
    proposed_data = models.JSONField(default=dict)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_public_profile_revisions")
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="reviewed_public_profile_revisions")
    review_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at", "-id")
        indexes = [
            models.Index(fields=["status", "updated_at"], name="org_pubrev_status_updated_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["organization"],
                condition=models.Q(status__in=["draft", "submitted", "under_review", "changes_required"]),
                name="unique_open_public_profile_revision",
            )
        ]

    def __str__(self):
        return f"{self.organization} · public profile · {self.get_status_display()}"


class VerificationDocument(models.Model):
    class DocumentType(models.TextChoices):
        REGISTRATION = "registration", "Registration document"
        TAX = "tax", "Tax document"
        IDENTITY = "identity", "Identity / authorized representative"
        CERTIFICATION = "certification", "Certification"
        OTHER = "other", "Other"

    application = models.ForeignKey(OnboardingApplication, on_delete=models.CASCADE, related_name="verification_documents")
    document_type = models.CharField(max_length=32, choices=DocumentType.choices)
    media_asset = models.ForeignKey("media.MediaAsset", on_delete=models.PROTECT, related_name="verification_documents")
    description = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at",)

    def clean(self):
        if self.media_asset_id and self.media_asset.access != self.media_asset.Access.PRIVATE:
            raise ValidationError({"media_asset": "Verification documents must use private media assets."})

    def __str__(self):
        return f"{self.application.organization} · {self.get_document_type_display()}"
