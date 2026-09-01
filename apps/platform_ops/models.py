from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class Audience(models.TextChoices):
    ALL = "all", "All"
    CUSTOMERS = "customers", "Customers"
    DESIGNERS = "designers", "Designers"
    MANUFACTURERS = "manufacturers", "Manufacturers"
    STAFF = "staff", "Staff"


class PlatformAnnouncement(models.Model):
    class Severity(models.TextChoices):
        INFO = "info", "Information"
        SUCCESS = "success", "Success"
        WARNING = "warning", "Warning"
        MAINTENANCE = "maintenance", "Maintenance"
        CRITICAL = "critical", "Critical"

    enabled = models.BooleanField(default=False)
    title_ar = models.CharField(max_length=220)
    title_en = models.CharField(max_length=220)
    message_ar = models.TextField()
    message_en = models.TextField()
    severity = models.CharField(max_length=20, choices=Severity.choices, default=Severity.INFO)
    audience = models.CharField(max_length=20, choices=Audience.choices, default=Audience.ALL)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField(null=True, blank=True)
    dismissible = models.BooleanField(default=True)
    cta_label_ar = models.CharField(max_length=120, blank=True)
    cta_label_en = models.CharField(max_length=120, blank=True)
    cta_url = models.CharField(max_length=500, blank=True)
    priority = models.PositiveSmallIntegerField(default=100)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="announcements_created")
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def active(cls):
        now = timezone.now()
        return cls.objects.filter(enabled=True, starts_at__lte=now).filter(models.Q(ends_at__isnull=True) | models.Q(ends_at__gt=now)).order_by("priority", "-starts_at")


class MaintenanceWindow(models.Model):
    class Mode(models.TextChoices):
        BANNER_ONLY = "banner", "Warning banner only"
        RESTRICT = "restrict", "Restrict customer/business surfaces"

    enabled = models.BooleanField(default=False)
    mode = models.CharField(max_length=16, choices=Mode.choices, default=Mode.RESTRICT)
    message_ar = models.TextField()
    message_en = models.TextField()
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def current(cls):
        now = timezone.now()
        return cls.objects.filter(enabled=True, starts_at__lte=now).filter(models.Q(ends_at__isnull=True) | models.Q(ends_at__gt=now)).order_by("-starts_at").first()


class ApplicationReviewConfiguration(models.Model):
    DEFAULT_INITIAL_REVIEW_TARGET_HOURS = 27

    singleton_key = models.PositiveSmallIntegerField(default=1, unique=True, editable=False)
    application_initial_review_target_hours = models.PositiveSmallIntegerField(
        default=DEFAULT_INITIAL_REVIEW_TARGET_HOURS,
        validators=[MinValueValidator(1), MaxValueValidator(720)],
        help_text="Initial application review target in hours. This never performs automatic approval.",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="application_review_configuration_updates",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Application review configuration"
        verbose_name_plural = "Application review configuration"

    @classmethod
    def current_initial_review_target_hours(cls):
        value = cls.objects.filter(singleton_key=1).values_list(
            "application_initial_review_target_hours", flat=True
        ).first()
        return value or cls.DEFAULT_INITIAL_REVIEW_TARGET_HOURS

    def __str__(self):
        return f"Application review target · {self.application_initial_review_target_hours}h"
