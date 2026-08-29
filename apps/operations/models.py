from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class ProductionJob(models.Model):
    class Status(models.TextChoices):
        AWAITING_ASSIGNMENT = "awaiting_assignment", "Awaiting manufacturer"
        QUEUED = "queued", "Queued"
        IN_PRODUCTION = "in_production", "In production"
        QC_PENDING = "qc_pending", "QC pending"
        QC_FAILED = "qc_failed", "QC failed"
        READY = "ready_for_fulfillment", "Ready for fulfillment"
        CANCELLED = "cancelled", "Cancelled"

    order = models.OneToOneField("checkout.CustomerOrder", on_delete=models.PROTECT, related_name="production_job")
    manufacturer = models.ForeignKey("organizations.Organization", null=True, blank=True, on_delete=models.PROTECT, related_name="production_jobs")
    selection = models.ForeignKey("manufacturer_marketplace.ManufacturerSelection", null=True, blank=True, on_delete=models.PROTECT, related_name="production_jobs")
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.AWAITING_ASSIGNMENT, db_index=True)
    production_notes = models.TextField(blank=True)
    target_completion_date = models.DateField(null=True, blank=True)
    assigned_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    ready_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at",)
        indexes = [models.Index(fields=["manufacturer", "status"], name="prodjob_mfr_status_idx")]

    def clean(self):
        if self.manufacturer_id and self.manufacturer.kind != "manufacturer":
            raise ValidationError({"manufacturer": "Production jobs require a Manufacturer organization."})
        if self.selection_id:
            if self.manufacturer_id and self.selection.manufacturer_id != self.manufacturer_id:
                raise ValidationError({"selection": "Selection manufacturer must match the Production Job manufacturer."})
            if self.order_id and self.selection.rfq.designed_product_id != self.order.item.store_product.designed_product_id:
                raise ValidationError({"selection": "Manufacturer selection must belong to this order's Designed Product."})


class ProductionMilestone(models.Model):
    class Kind(models.TextChoices):
        MATERIALS = "materials", "Materials"
        CUTTING = "cutting", "Cutting"
        ASSEMBLY = "assembly", "Assembly / Sewing"
        DECORATION = "decoration", "Printing / Embroidery"
        FINISHING = "finishing", "Finishing"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        IN_PROGRESS = "in_progress", "In progress"
        COMPLETED = "completed", "Completed"
        BLOCKED = "blocked", "Blocked"

    job = models.ForeignKey(ProductionJob, on_delete=models.CASCADE, related_name="milestones")
    kind = models.CharField(max_length=24, choices=Kind.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)
    notes = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="updated_production_milestones")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("id",)
        constraints = [models.UniqueConstraint(fields=["job", "kind"], name="unique_job_milestone_kind")]


class ProductionAsset(models.Model):
    class Kind(models.TextChoices):
        WORK_INSTRUCTION = "work_instruction", "Work instruction"
        QC_EVIDENCE = "qc_evidence", "QC evidence"
        OTHER = "other", "Other"

    job = models.ForeignKey(ProductionJob, on_delete=models.CASCADE, related_name="assets")
    media_asset = models.ForeignKey("media.MediaAsset", on_delete=models.PROTECT, related_name="production_assets")
    kind = models.CharField(max_length=24, choices=Kind.choices)
    label = models.CharField(max_length=180, blank=True)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="production_assets")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at",)

    def clean(self):
        if self.media_asset_id and self.media_asset.access != self.media_asset.Access.PRIVATE:
            raise ValidationError({"media_asset": "Production assets must use private media."})


class QCInspection(models.Model):
    class Decision(models.TextChoices):
        PASSED = "passed", "Passed"
        FAILED = "failed", "Failed"
        REWORK = "rework", "Rework required"

    job = models.ForeignKey(ProductionJob, on_delete=models.PROTECT, related_name="qc_inspections")
    decision = models.CharField(max_length=16, choices=Decision.choices)
    checklist = models.JSONField(default=dict)
    notes = models.TextField(blank=True)
    inspected_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="qc_inspections")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)


class FulfillmentRecord(models.Model):
    class Status(models.TextChoices):
        WAITING_PRODUCTION = "waiting_production", "Waiting for production"
        READY_TO_PACK = "ready_to_pack", "Ready to pack"
        PACKED = "packed", "Packed"
        SHIPPED = "shipped", "Shipped"
        DELIVERED = "delivered", "Delivered"
        FAILED = "failed", "Delivery failed"
        RETURNED = "returned", "Returned"
        CANCELLED = "cancelled", "Cancelled"

    order = models.OneToOneField("checkout.CustomerOrder", on_delete=models.PROTECT, related_name="fulfillment")
    status = models.CharField(max_length=28, choices=Status.choices, db_index=True)
    carrier = models.CharField(max_length=120, blank=True)
    tracking_number = models.CharField(max_length=180, blank=True)
    tracking_url = models.URLField(blank=True)
    packed_at = models.DateTimeField(null=True, blank=True)
    shipped_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at",)
        indexes = [models.Index(fields=["status", "updated_at"], name="fulfill_status_time_idx")]


class FulfillmentEvent(models.Model):
    fulfillment = models.ForeignKey(FulfillmentRecord, on_delete=models.CASCADE, related_name="events")
    status = models.CharField(max_length=28, choices=FulfillmentRecord.Status.choices)
    note = models.CharField(max_length=255, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="fulfillment_events")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at",)
