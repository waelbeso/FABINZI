from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from apps.organizations.models import Membership


class SubscriptionPlanPolicy(models.Model):
    class Audience(models.TextChoices):
        DESIGNER = "designer", "Designer"
        MANUFACTURER = "manufacturer", "Manufacturer"

    code = models.CharField(max_length=64, db_index=True)
    version = models.PositiveIntegerField(default=1)
    public_name_ar = models.CharField(max_length=180)
    public_name_en = models.CharField(max_length=180)
    audience = models.CharField(max_length=20, choices=Audience.choices, db_index=True)
    monthly_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, default="EGP")
    tax_inclusive = models.BooleanField(default=True)
    trial_months = models.PositiveSmallIntegerField(default=0)
    designer_active_design_limit = models.PositiveIntegerField(null=True, blank=True)
    designer_active_artwork_limit = models.PositiveIntegerField(null=True, blank=True)
    manufacturer_monthly_offer_limit = models.PositiveIntegerField(null=True, blank=True)
    team_subaccount_limit = models.PositiveIntegerField(default=1)
    active = models.BooleanField(default=True, db_index=True)
    effective_from = models.DateField(db_index=True)
    effective_to = models.DateField(null=True, blank=True, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_subscription_plan_policies",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("code", "-effective_from", "-version")
        constraints = [
            models.UniqueConstraint(fields=["code", "version"], name="unique_subscription_plan_version"),
            models.UniqueConstraint(fields=["code", "effective_from"], name="unique_subscription_plan_effective_date"),
        ]

    def clean(self):
        if self.currency and len(self.currency) != 3:
            raise ValidationError({"currency": "Currency must be a 3-letter code."})
        if self.monthly_price is not None and self.monthly_price < 0:
            raise ValidationError({"monthly_price": "Monthly price cannot be negative."})
        if self.effective_to and self.effective_to <= self.effective_from:
            raise ValidationError({"effective_to": "Effective-to must be later than effective-from."})
        if self.audience == self.Audience.DESIGNER:
            if self.designer_active_design_limit is None or self.designer_active_artwork_limit is None:
                raise ValidationError("Designer plans require Design and Artwork limits.")
            if self.manufacturer_monthly_offer_limit is not None:
                raise ValidationError({"manufacturer_monthly_offer_limit": "Designer plans cannot define Manufacturer offer limits."})
        elif self.audience == self.Audience.MANUFACTURER:
            if self.manufacturer_monthly_offer_limit is None:
                raise ValidationError("Manufacturer plans require a monthly Manufacturing Offer limit.")
            if self.designer_active_design_limit is not None or self.designer_active_artwork_limit is not None:
                raise ValidationError("Manufacturer plans cannot define Designer content limits.")

    def __str__(self):
        return f"{self.code} v{self.version} · {self.public_name_en}"


class OrganizationSubscription(models.Model):
    class Status(models.TextChoices):
        TRIALING = "trialing", "Trialing"
        ACTIVE = "active", "Active"
        PAST_DUE = "past_due", "Past due"
        GRACE_PERIOD = "grace_period", "Grace period"
        CANCELLED = "cancelled", "Cancelled"
        EXPIRED = "expired", "Expired"
        DOWNGRADED = "downgraded", "Downgraded"

    organization = models.OneToOneField(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="professional_subscription",
    )
    current_plan = models.ForeignKey(
        SubscriptionPlanPolicy,
        on_delete=models.PROTECT,
        related_name="current_subscriptions",
    )
    status = models.CharField(max_length=24, choices=Status.choices, db_index=True)
    started_at = models.DateTimeField()
    trial_started_at = models.DateTimeField(null=True, blank=True)
    trial_ends_at = models.DateTimeField(null=True, blank=True)
    trial_consumed = models.BooleanField(default=False)
    current_period_start = models.DateTimeField()
    current_period_end = models.DateTimeField()
    next_billing_at = models.DateTimeField(null=True, blank=True)
    grace_started_on = models.DateField(null=True, blank=True)
    grace_ends_on = models.DateField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    downgraded_at = models.DateTimeField(null=True, blank=True)
    policy_snapshot = models.JSONField(default=dict)
    price_snapshot = models.JSONField(default=dict)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        permissions = [
            ("manage_professional_subscription", "Can manage professional subscription lifecycle"),
        ]
        indexes = [models.Index(fields=["status", "current_period_end"], name="prosub_status_period_idx")]

    def __str__(self):
        return f"{self.organization} · {self.current_plan.code} · {self.get_status_display()}"


class SubscriptionPeriod(models.Model):
    subscription = models.ForeignKey(OrganizationSubscription, on_delete=models.PROTECT, related_name="periods")
    sequence = models.PositiveIntegerField()
    plan_code = models.CharField(max_length=64)
    status_snapshot = models.CharField(max_length=24)
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    policy_snapshot = models.JSONField(default=dict)
    price_snapshot = models.JSONField(default=dict)
    billing_reference = models.CharField(max_length=180, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-sequence",)
        constraints = [models.UniqueConstraint(fields=["subscription", "sequence"], name="unique_subscription_period_sequence")]


class SubscriptionBillingConfirmation(models.Model):
    class Status(models.TextChoices):
        CONFIRMED = "confirmed", "Confirmed"
        REVOKED = "revoked", "Revoked"

    organization = models.ForeignKey("organizations.Organization", on_delete=models.PROTECT, related_name="subscription_billing_confirmations")
    plan_policy = models.ForeignKey(
        SubscriptionPlanPolicy,
        on_delete=models.PROTECT,
        related_name="billing_confirmations",
        editable=False,
    )
    plan_code = models.CharField(max_length=64)
    plan_version = models.PositiveIntegerField(editable=False)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="EGP")
    tax_inclusive = models.BooleanField(default=True, editable=False)
    policy_snapshot = models.JSONField(default=dict, editable=False)
    price_snapshot = models.JSONField(default=dict, editable=False)
    provider = models.CharField(max_length=40)
    provider_reference = models.CharField(max_length=180, unique=True)
    idempotency_key = models.CharField(max_length=120, unique=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.CONFIRMED)
    confirmed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="confirmed_professional_subscription_billing")
    confirmed_at = models.DateTimeField(auto_now_add=True)
    consumed_period = models.OneToOneField(
        SubscriptionPeriod,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="billing_confirmation",
        editable=False,
    )
    consumed_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ("-confirmed_at",)


class ManufacturerOfferUsage(models.Model):
    subscription = models.ForeignKey(OrganizationSubscription, on_delete=models.PROTECT, related_name="manufacturer_offer_usage")
    organization = models.ForeignKey("organizations.Organization", on_delete=models.PROTECT, related_name="manufacturer_offer_usage")
    quote = models.OneToOneField("manufacturer_marketplace.ManufacturerQuote", on_delete=models.PROTECT, related_name="subscription_usage")
    plan_code = models.CharField(max_length=64)
    period_start = models.DateField()
    period_end = models.DateField()
    consumed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-consumed_at",)
        indexes = [models.Index(fields=["organization", "period_start"], name="mfr_usage_org_period_idx")]


class TeamInvitationConfiguration(models.Model):
    DEFAULT_EXPIRY_DAYS = 7

    singleton_key = models.PositiveSmallIntegerField(default=1, unique=True, editable=False)
    invitation_expiry_days = models.PositiveSmallIntegerField(
        default=DEFAULT_EXPIRY_DAYS,
        validators=[MinValueValidator(1), MaxValueValidator(90)],
    )
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="team_invitation_configuration_updates")
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def current_expiry_days(cls):
        return cls.objects.filter(singleton_key=1).values_list("invitation_expiry_days", flat=True).first() or cls.DEFAULT_EXPIRY_DAYS


class TeamInvitation(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        DECLINED = "declined", "Declined"
        EXPIRED = "expired", "Expired"
        REVOKED = "revoked", "Revoked"

    organization = models.ForeignKey("organizations.Organization", on_delete=models.PROTECT, related_name="team_invitations")
    email = models.EmailField()
    role = models.CharField(max_length=32, choices=Membership.Role.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True)
    token_hash = models.CharField(max_length=64, unique=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_team_invitations")
    accepted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="accepted_team_invitations")
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(db_index=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    declined_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "email"],
                condition=Q(status="pending"),
                name="unique_pending_team_invitation_email",
            )
        ]


class MembershipPlanSuspension(models.Model):
    membership = models.OneToOneField("organizations.Membership", on_delete=models.PROTECT, related_name="plan_suspension")
    suspended_by_plan = models.BooleanField(default=True)
    reason = models.CharField(max_length=180, blank=True)
    suspended_at = models.DateTimeField()
    restored_at = models.DateTimeField(null=True, blank=True)


class DesignPlanEntitlementState(models.Model):
    design = models.OneToOneField("design.GarmentDesign", on_delete=models.PROTECT, related_name="plan_entitlement_state")
    plan_paused = models.BooleanField(default=False, db_index=True)
    retained = models.BooleanField(default=False)
    protected_active_chain = models.BooleanField(default=False)
    pause_reason = models.CharField(max_length=180, blank=True)
    paused_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class ArtworkPlanEntitlementState(models.Model):
    artwork = models.OneToOneField("artwork.Artwork", on_delete=models.PROTECT, related_name="plan_entitlement_state")
    plan_paused = models.BooleanField(default=False, db_index=True)
    retained = models.BooleanField(default=False)
    protected_active_chain = models.BooleanField(default=False)
    pause_reason = models.CharField(max_length=180, blank=True)
    paused_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class StoreProductPlanPause(models.Model):
    store_product = models.OneToOneField("storefront.StoreProduct", on_delete=models.PROTECT, related_name="subscription_plan_pause")
    previous_status = models.CharField(max_length=20)
    active = models.BooleanField(default=True, db_index=True)
    paused_at = models.DateTimeField()
    restored_at = models.DateTimeField(null=True, blank=True)


class SubscriptionReminderMilestone(models.Model):
    code = models.CharField(max_length=40, unique=True)
    label_en = models.CharField(max_length=180)
    label_ar = models.CharField(max_length=180)
    offset_days = models.SmallIntegerField()
    active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("offset_days", "code")


class SubscriptionReminderEvent(models.Model):
    subscription = models.ForeignKey(OrganizationSubscription, on_delete=models.PROTECT, related_name="reminder_events")
    due_date = models.DateField()
    milestone = models.ForeignKey(SubscriptionReminderMilestone, on_delete=models.PROTECT, related_name="events")
    notification = models.ForeignKey("notifications.Notification", null=True, blank=True, on_delete=models.PROTECT, related_name="subscription_reminder_events")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["subscription", "due_date", "milestone"], name="unique_subscription_reminder_event")]


class SubscriptionTrialException(models.Model):
    subscription = models.ForeignKey(OrganizationSubscription, on_delete=models.PROTECT, related_name="trial_exceptions")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="subscription_trial_exceptions")
    reason = models.TextField()
    old_trial_state = models.JSONField(default=dict)
    new_trial_state = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
