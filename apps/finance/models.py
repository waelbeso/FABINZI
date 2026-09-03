from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class FinancePolicy(models.Model):
    class LifecycleStatus(models.TextChoices):
        DRAFT = "draft", "Draft"
        ACTIVE = "active", "Active"
        RETIRED = "retired", "Retired"

    class RuleType(models.TextChoices):
        PERCENTAGE = "percentage", "Percentage of line gross"
        FIXED = "fixed", "Fixed amount per order line"
        PER_UNIT = "per_unit", "Amount per unit"

    class SettlementTrigger(models.TextChoices):
        DELIVERY = "delivery", "Fulfillment delivered"
        PAYMENT_AND_DELIVERY = "payment_and_delivery", "Payment succeeded and fulfillment delivered"

    # Stage-8 compatibility fields. V2 resolution deliberately ignores them.
    name = models.CharField(max_length=80, unique=True, default="default")
    platform_fee_bps = models.PositiveIntegerField(default=1000, help_text="LEGACY ONLY; not a V2 policy input.")
    settlement_delay_days = models.PositiveIntegerField(default=7, help_text="LEGACY ONLY; not a V2 policy input.")
    minimum_payout = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("100.00"), help_text="LEGACY ONLY; not a V2 policy input.")
    is_active = models.BooleanField(default=False, db_index=True, help_text="LEGACY ONLY; V2 uses lifecycle_status.")
    updated_at = models.DateTimeField(auto_now=True)

    code = models.CharField(max_length=40, unique=True, null=True, blank=True)
    lifecycle_status = models.CharField(max_length=16, choices=LifecycleStatus.choices, default=LifecycleStatus.DRAFT, db_index=True)
    currency = models.CharField(max_length=3, blank=True)
    fabinzi_rule_type = models.CharField(max_length=16, choices=RuleType.choices, blank=True)
    fabinzi_rule_value = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    garment_royalty_rule_type = models.CharField(max_length=16, choices=RuleType.choices, blank=True)
    garment_royalty_rule_value = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    artwork_royalty_rule_type = models.CharField(max_length=16, choices=RuleType.choices, blank=True)
    artwork_royalty_rule_value = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    manufacturer_include_unit_price = models.BooleanField(null=True, blank=True)
    manufacturer_include_setup_fee = models.BooleanField(null=True, blank=True)
    manufacturer_include_sample_fee = models.BooleanField(null=True, blank=True)
    manufacturer_include_shipping_estimate = models.BooleanField(null=True, blank=True)
    settlement_trigger = models.CharField(max_length=32, choices=SettlementTrigger.choices, blank=True)
    settlement_hold_days = models.PositiveIntegerField(null=True, blank=True)
    v2_minimum_payout = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    validated_at = models.DateTimeField(null=True, blank=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    retired_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="created_finance_policies")
    activated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="activated_finance_policies")
    retired_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="retired_finance_policies")

    class Meta:
        ordering = ("-created_at", "-id")
        constraints = [models.UniqueConstraint(fields=["currency"], condition=models.Q(lifecycle_status="active"), name="one_active_v2_finance_policy_per_currency")]
        permissions = [
            ("view_finance_policy_governance", "Can view V2 Finance Policy governance"),
            ("manage_finance_policy_governance", "Can create and edit V2 Finance Policy drafts"),
            ("activate_finance_policy_governance", "Can activate or retire V2 Finance Policy versions"),
            ("reconcile_finance_recognition", "Can reconcile blocked V2 finance recognition"),
            ("execute_finance_payout", "Can execute V2 payout lifecycle transitions"),
        ]

    @property
    def is_v2_complete(self):
        required = [self.code, self.currency, self.fabinzi_rule_type, self.fabinzi_rule_value, self.garment_royalty_rule_type, self.garment_royalty_rule_value, self.artwork_royalty_rule_type, self.artwork_royalty_rule_value, self.settlement_trigger, self.settlement_hold_days, self.v2_minimum_payout]
        manufacturer = [self.manufacturer_include_unit_price, self.manufacturer_include_setup_fee, self.manufacturer_include_sample_fee, self.manufacturer_include_shipping_estimate]
        return all(v not in (None, "") for v in required) and all(v is not None for v in manufacturer)

    def clean(self):
        errors = {}
        if self.currency:
            self.currency = self.currency.upper()
            if len(self.currency) != 3 or not self.currency.isalpha():
                errors["currency"] = "Currency must be a 3-letter alphabetic code."
        for type_field, value_field in (("fabinzi_rule_type", "fabinzi_rule_value"), ("garment_royalty_rule_type", "garment_royalty_rule_value"), ("artwork_royalty_rule_type", "artwork_royalty_rule_value")):
            rule_type = getattr(self, type_field)
            value = getattr(self, value_field)
            if rule_type or value is not None:
                if rule_type not in self.RuleType.values:
                    errors[type_field] = "Choose an explicit supported rule type."
                if value is None or value < 0:
                    errors[value_field] = "Rule value must be zero or positive."
                elif rule_type == self.RuleType.PERCENTAGE and value > 100:
                    errors[value_field] = "Percentage cannot exceed 100."
        if self.v2_minimum_payout is not None and self.v2_minimum_payout < 0:
            errors["v2_minimum_payout"] = "Minimum payout cannot be negative."
        if self.lifecycle_status in {self.LifecycleStatus.ACTIVE, self.LifecycleStatus.RETIRED} and not self.is_v2_complete:
            errors["lifecycle_status"] = "Only a complete validated V2 policy may be active or retired."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk:
            previous = type(self).objects.filter(pk=self.pk).values("lifecycle_status", "code", "currency", "fabinzi_rule_type", "fabinzi_rule_value", "garment_royalty_rule_type", "garment_royalty_rule_value", "artwork_royalty_rule_type", "artwork_royalty_rule_value", "manufacturer_include_unit_price", "manufacturer_include_setup_fee", "manufacturer_include_sample_fee", "manufacturer_include_shipping_estimate", "settlement_trigger", "settlement_hold_days", "v2_minimum_payout").first()
            if previous and previous["lifecycle_status"] != self.LifecycleStatus.DRAFT:
                immutable = {k: v for k, v in previous.items() if k != "lifecycle_status"}
                current = {k: getattr(self, k) for k in immutable}
                if immutable != current:
                    raise ValidationError("Historical Finance Policy commercial rules are immutable.")
        super().save(*args, **kwargs)


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
    bank_name = models.CharField(max_length=180, blank=True)
    iban_encrypted = models.TextField(blank=True)
    iban_last4 = models.CharField(max_length=4, blank=True)
    country = models.CharField(max_length=2, blank=True)
    currency = models.CharField(max_length=3, blank=True)
    bank_proof = models.ForeignKey("media.MediaAsset", null=True, blank=True, on_delete=models.PROTECT, related_name="finance_bank_proofs")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True)
    verification_notes = models.TextField(blank=True)
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="verified_payout_profiles")
    verified_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        if self.currency:
            self.currency = self.currency.upper()
            if len(self.currency) != 3:
                raise ValidationError({"currency": "Currency must be a 3-letter code."})
        if self.country:
            self.country = self.country.upper()
            if len(self.country) != 2:
                raise ValidationError({"country": "Country must be a 2-letter code."})
        if self.bank_proof_id and self.bank_proof.access != self.bank_proof.Access.PRIVATE:
            raise ValidationError({"bank_proof": "Bank proof must remain private media."})


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
        if self.account_type == self.AccountType.ORGANIZATION and not self.organization_id: raise ValidationError({"organization": "Organization finance accounts require an organization."})
        if self.account_type == self.AccountType.PLATFORM and self.organization_id: raise ValidationError({"organization": "Platform finance accounts cannot belong to an organization."})
        if self.currency and len(self.currency) != 3: raise ValidationError({"currency": "Currency must be a 3-letter code."})


class OrderFinance(models.Model):
    class Status(models.TextChoices):
        RECOGNIZED = "recognized", "Recognized"
        REVERSED = "reversed", "Reversed"
    order = models.OneToOneField("checkout.CustomerOrder", on_delete=models.PROTECT, related_name="finance_record")
    order_item = models.ForeignKey("checkout.OrderItem", null=True, blank=True, on_delete=models.PROTECT, related_name="finance_records")
    finance_policy = models.ForeignKey(FinancePolicy, null=True, blank=True, on_delete=models.PROTECT, related_name="order_finances")
    designer_account = models.ForeignKey(FinanceAccount, on_delete=models.PROTECT, related_name="designer_order_finance")
    manufacturer_account = models.ForeignKey(FinanceAccount, null=True, blank=True, on_delete=models.PROTECT, related_name="manufacturer_order_finance")
    garment_designer_account = models.ForeignKey(FinanceAccount, null=True, blank=True, on_delete=models.PROTECT, related_name="garment_royalty_finance")
    artwork_designer_account = models.ForeignKey(FinanceAccount, null=True, blank=True, on_delete=models.PROTECT, related_name="artwork_royalty_finance")
    platform_account = models.ForeignKey(FinanceAccount, null=True, blank=True, on_delete=models.PROTECT, related_name="platform_order_finance")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.RECOGNIZED, db_index=True)
    gross_amount = models.DecimalField(max_digits=12, decimal_places=2)
    platform_fee = models.DecimalField(max_digits=12, decimal_places=2)
    fabinzi_component = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    manufacturer_payable = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    designer_earnings = models.DecimalField(max_digits=12, decimal_places=2)
    garment_designer_royalty = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    artwork_designer_royalty = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=3)
    policy_snapshot = models.JSONField(default=dict)
    source_snapshot = models.JSONField(default=dict)
    pricing_snapshot = models.JSONField(default=dict)
    recognized_at = models.DateTimeField()
    available_at = models.DateTimeField(db_index=True)
    class Meta: ordering = ("-recognized_at",)


class OrderFinanceComponent(models.Model):
    class ComponentType(models.TextChoices):
        MANUFACTURER_PAYABLE = "manufacturer_payable", "Manufacturer payable"
        GARMENT_ROYALTY = "garment_royalty", "Garment Designer royalty"
        ARTWORK_ROYALTY = "artwork_royalty", "Artwork Designer royalty"
        FABINZI_COMPONENT = "fabinzi_component", "FABINZI component"
    order_finance = models.ForeignKey(OrderFinance, on_delete=models.PROTECT, related_name="components")
    component_type = models.CharField(max_length=32, choices=ComponentType.choices)
    beneficiary_organization = models.ForeignKey("organizations.Organization", null=True, blank=True, on_delete=models.PROTECT, related_name="finance_components")
    account = models.ForeignKey(FinanceAccount, on_delete=models.PROTECT, related_name="finance_components")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3)
    available_at = models.DateTimeField()
    class Meta: constraints = [models.UniqueConstraint(fields=["order_finance", "component_type"], name="unique_v2_finance_component_type")]


class FinanceRecognitionPending(models.Model):
    class Status(models.TextChoices):
        BLOCKED = "blocked", "Blocked for finance policy"
        RECONCILED = "reconciled", "Reconciled"
    class TriggerEvent(models.TextChoices):
        FULFILLMENT_DELIVERED = "fulfillment.delivered", "Fulfillment delivered"
    order = models.OneToOneField("checkout.CustomerOrder", on_delete=models.PROTECT, related_name="pending_finance_recognition")
    purchase = models.ForeignKey("checkout.CustomerPurchase", null=True, blank=True, on_delete=models.PROTECT, related_name="pending_finance_recognitions")
    order_item = models.ForeignKey("checkout.OrderItem", null=True, blank=True, on_delete=models.PROTECT, related_name="pending_finance_recognitions")
    manufacturer_quote = models.ForeignKey("manufacturer_marketplace.ManufacturerQuote", null=True, blank=True, on_delete=models.PROTECT, related_name="pending_finance_recognitions")
    production_specification = models.ForeignKey("operations.ProductionSpecification", null=True, blank=True, on_delete=models.PROTECT, related_name="pending_finance_recognitions")
    reconciled_finance = models.OneToOneField(OrderFinance, null=True, blank=True, on_delete=models.PROTECT, related_name="recognition_source")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.BLOCKED, db_index=True)
    currency = models.CharField(max_length=3)
    trigger_event = models.CharField(max_length=40, choices=TriggerEvent.choices)
    block_reason = models.CharField(max_length=255)
    source_snapshot = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    reconciled_at = models.DateTimeField(null=True, blank=True)
    class Meta:
        ordering = ("created_at", "id")
        indexes = [models.Index(fields=["status", "created_at"], name="finance_pending_status_idx")]


class SettlementRequest(models.Model):
    class Status(models.TextChoices):
        REQUESTED = "requested", "Requested"
        UNDER_REVIEW = "under_review", "Under review"
        APPROVED = "approved", "Approved"
        PROCESSING = "processing", "Processing"
        PAID = "paid", "Paid"
        REJECTED = "rejected", "Rejected"
        CANCELLED = "cancelled", "Cancelled"
        FAILED = "failed", "Failed"
    organization = models.ForeignKey("organizations.Organization", on_delete=models.PROTECT, related_name="settlement_requests")
    account = models.ForeignKey(FinanceAccount, on_delete=models.PROTECT, related_name="settlement_requests")
    payout_profile = models.ForeignKey(PayoutProfile, on_delete=models.PROTECT, related_name="settlement_requests")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.REQUESTED, db_index=True)
    idempotency_key = models.CharField(max_length=80, unique=True, null=True, blank=True)
    payout_snapshot = models.JSONField(default=dict)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="requested_settlements")
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="reviewed_settlements")
    paid_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="paid_settlements")
    review_notes = models.TextField(blank=True)
    external_reference = models.CharField(max_length=180, blank=True)
    execution_evidence = models.CharField(max_length=255, blank=True)
    requested_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reserved_at = models.DateTimeField(null=True, blank=True)
    processing_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    class Meta:
        ordering = ("-requested_at",)
        indexes = [models.Index(fields=["organization", "status"], name="settle_org_status_idx")]
    def clean(self):
        if self.account_id and self.account.organization_id != self.organization_id: raise ValidationError({"account": "Settlement account must belong to the organization."})
        if self.payout_profile_id and self.payout_profile.organization_id != self.organization_id: raise ValidationError({"payout_profile": "Payout profile must belong to the organization."})
        if self.amount <= 0: raise ValidationError({"amount": "Settlement amount must be positive."})


class LedgerEntry(models.Model):
    class EntryType(models.TextChoices):
        DESIGNER_EARNING = "designer_earning", "Legacy Designer earning"
        MANUFACTURER_EARNING = "manufacturer_earning", "Legacy Manufacturer earning"
        PLATFORM_FEE = "platform_fee", "Legacy Platform fee"
        GARMENT_DESIGNER_ROYALTY = "garment_designer_royalty", "Garment Designer royalty"
        ARTWORK_DESIGNER_ROYALTY = "artwork_designer_royalty", "Artwork Designer royalty"
        MANUFACTURER_PAYABLE = "manufacturer_payable", "Manufacturer payable"
        FABINZI_COMPONENT = "fabinzi_component", "FABINZI component"
        SETTLEMENT = "settlement", "Settlement"
        ADJUSTMENT = "adjustment", "Adjustment"
        REVERSAL = "reversal", "Reversal"
    account = models.ForeignKey(FinanceAccount, on_delete=models.PROTECT, related_name="ledger_entries")
    order_finance = models.ForeignKey(OrderFinance, null=True, blank=True, on_delete=models.PROTECT, related_name="ledger_entries")
    settlement = models.OneToOneField(SettlementRequest, null=True, blank=True, on_delete=models.PROTECT, related_name="ledger_entry")
    entry_type = models.CharField(max_length=40, choices=EntryType.choices)
    event_key = models.CharField(max_length=120, unique=True, null=True, blank=True)
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
    class Meta: ordering = ("-created_at",)
    def clean(self):
        if self.amount == 0: raise ValidationError({"amount": "Adjustment amount cannot be zero."})
