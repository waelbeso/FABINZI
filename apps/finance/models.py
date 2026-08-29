from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class FinancePolicy(models.Model):
    name = models.CharField(max_length=80, unique=True, default="default")
    platform_fee_bps = models.PositiveIntegerField(default=1000, help_text="Platform fee in basis points; 1000 = 10%.")
    settlement_delay_days = models.PositiveIntegerField(default=7)
    minimum_payout = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("100.00"))
    is_active = models.BooleanField(default=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        if self.platform_fee_bps > 10000:
            raise ValidationError({"platform_fee_bps": "Platform fee cannot exceed 100%."})
        if self.minimum_payout < 0:
            raise ValidationError({"minimum_payout": "Minimum payout cannot be negative."})


class PayoutProfile(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PENDING = "pending", "Pending verification"
        VERIFIED = "verified", "Verified"
        REJECTED = "rejected", "Rejected"

    class Method(models.TextChoices):
        BANK = "bank", "Bank transfer"
        MANUAL = "manual", "Manual settlement"

    organization = models.OneToOneField("organizations.Organization", on_delete=models.CASCADE, related_name="finance_payout_profile")
    method = models.CharField(max_length=20, choices=Method.choices, default=Method.BANK)
    account_holder = models.CharField(max_length=180)
    destination_hint = models.CharField(max_length=120, help_text="Masked/non-sensitive payout destination only.")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True)
    verification_notes = models.TextField(blank=True)
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="verified_payout_profiles")
    verified_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class FinanceAccount(models.Model):
    class AccountType(models.TextChoices):
        ORGANIZATION = "organization", "Organization"
        PLATFORM = "platform", "Platform"

    account_type = models.CharField(max_length=20, choices=AccountType.choices)
    organization = models.ForeignKey("organizations.Organization", null=True, blank=True, on_delete=models.PROTECT, related_name="finance_accounts")
    currency = models.CharField(max_length=3, default="EGP")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["organization", "currency"], name="unique_org_finance_currency")]
        indexes = [models.Index(fields=["account_type", "currency"], name="finance_acct_type_idx")]

    def clean(self):
        if self.account_type == self.AccountType.ORGANIZATION and not self.organization_id:
            raise ValidationError({"organization": "Organization finance accounts require an organization."})
        if self.account_type == self.AccountType.PLATFORM and self.organization_id:
            raise ValidationError({"organization": "Platform finance accounts cannot belong to an organization."})
        if self.currency and len(self.currency) != 3:
            raise ValidationError({"currency": "Currency must be a 3-letter code."})


class OrderFinance(models.Model):
    class Status(models.TextChoices):
        RECOGNIZED = "recognized", "Recognized"
        REVERSED = "reversed", "Reversed"

    order = models.OneToOneField("checkout.CustomerOrder", on_delete=models.PROTECT, related_name="finance_record")
    designer_account = models.ForeignKey(FinanceAccount, on_delete=models.PROTECT, related_name="designer_order_finance")
    manufacturer_account = models.ForeignKey(FinanceAccount, null=True, blank=True, on_delete=models.PROTECT, related_name="manufacturer_order_finance")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.RECOGNIZED, db_index=True)
    gross_amount = models.DecimalField(max_digits=12, decimal_places=2)
    platform_fee = models.DecimalField(max_digits=12, decimal_places=2)
    manufacturer_payable = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    designer_earnings = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3)
    policy_snapshot = models.JSONField(default=dict)
    recognized_at = models.DateTimeField()
    available_at = models.DateTimeField(db_index=True)

    class Meta:
        ordering = ("-recognized_at",)


class SettlementRequest(models.Model):
    class Status(models.TextChoices):
        REQUESTED = "requested", "Requested"
        APPROVED = "approved", "Approved"
        PAID = "paid", "Paid"
        REJECTED = "rejected", "Rejected"
        CANCELLED = "cancelled", "Cancelled"

    organization = models.ForeignKey("organizations.Organization", on_delete=models.PROTECT, related_name="settlement_requests")
    account = models.ForeignKey(FinanceAccount, on_delete=models.PROTECT, related_name="settlement_requests")
    payout_profile = models.ForeignKey(PayoutProfile, on_delete=models.PROTECT, related_name="settlement_requests")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.REQUESTED, db_index=True)
    payout_snapshot = models.JSONField(default=dict)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="requested_settlements")
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="reviewed_settlements")
    paid_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="paid_settlements")
    review_notes = models.TextField(blank=True)
    external_reference = models.CharField(max_length=180, blank=True)
    requested_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-requested_at",)
        indexes = [models.Index(fields=["organization", "status"], name="settle_org_status_idx")]

    def clean(self):
        if self.account_id and self.account.organization_id != self.organization_id:
            raise ValidationError({"account": "Settlement account must belong to the organization."})
        if self.payout_profile_id and self.payout_profile.organization_id != self.organization_id:
            raise ValidationError({"payout_profile": "Payout profile must belong to the organization."})
        if self.amount <= 0:
            raise ValidationError({"amount": "Settlement amount must be positive."})


class LedgerEntry(models.Model):
    class EntryType(models.TextChoices):
        DESIGNER_EARNING = "designer_earning", "Designer earning"
        MANUFACTURER_EARNING = "manufacturer_earning", "Manufacturer earning"
        PLATFORM_FEE = "platform_fee", "Platform fee"
        SETTLEMENT = "settlement", "Settlement"
        ADJUSTMENT = "adjustment", "Adjustment"
        REVERSAL = "reversal", "Reversal"

    account = models.ForeignKey(FinanceAccount, on_delete=models.PROTECT, related_name="ledger_entries")
    order_finance = models.ForeignKey(OrderFinance, null=True, blank=True, on_delete=models.PROTECT, related_name="ledger_entries")
    settlement = models.OneToOneField(SettlementRequest, null=True, blank=True, on_delete=models.PROTECT, related_name="ledger_entry")
    entry_type = models.CharField(max_length=32, choices=EntryType.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2, help_text="Signed amount; credits positive, debits negative.")
    currency = models.CharField(max_length=3)
    available_at = models.DateTimeField(db_index=True)
    memo = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="finance_ledger_entries")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at", "id")
        indexes = [models.Index(fields=["account", "available_at"], name="ledger_acct_avail_idx")]


class FinanceAdjustment(models.Model):
    order_finance = models.ForeignKey(OrderFinance, on_delete=models.PROTECT, related_name="adjustments")
    account = models.ForeignKey(FinanceAccount, on_delete=models.PROTECT, related_name="adjustments")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.CharField(max_length=255)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="finance_adjustments")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def clean(self):
        if self.amount == 0:
            raise ValidationError({"amount": "Adjustment amount cannot be zero."})
