import uuid
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from apps.audit.services import record_audit_event
from apps.checkout.models import PaymentAttempt
from apps.integrations.crypto import decrypt_text, encrypt_text
from apps.operations.models import FulfillmentRecord, ProductionSpecification
from apps.organizations.models import Membership
from apps.organizations.services import require_org_access
from .models import FinanceAccount, FinanceAdjustment, FinancePolicy, FinanceRecognitionPending, LedgerEntry, OrderFinance, OrderFinanceComponent, PayoutProfile, SettlementRequest
from .snapshots import build_finance_source_snapshot, validate_finance_source_snapshot

FINANCE_ROLES = [Membership.Role.OWNER, Membership.Role.MANAGER, Membership.Role.ACCOUNTANT]
PAYOUT_MUTATION_ROLES = [Membership.Role.OWNER]
OPEN_SETTLEMENT = {SettlementRequest.Status.REQUESTED, SettlementRequest.Status.UNDER_REVIEW, SettlementRequest.Status.APPROVED, SettlementRequest.Status.PROCESSING}


class FinancePolicyUnavailable(ValidationError):
    pass


def _money(value):
    return Decimal(value or 0).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _actor(actor):
    return actor if getattr(actor, "is_authenticated", False) else None


def organization_account(organization, currency):
    account, _ = FinanceAccount.objects.get_or_create(account_type=FinanceAccount.AccountType.ORGANIZATION, organization=organization, currency=currency.upper())
    return account


def platform_account(currency):
    account = FinanceAccount.objects.filter(account_type=FinanceAccount.AccountType.PLATFORM, organization__isnull=True, currency=currency.upper()).first()
    if account:
        return account
    account = FinanceAccount(account_type=FinanceAccount.AccountType.PLATFORM, currency=currency.upper())
    account.full_clean(); account.save(); return account


def require_finance_access(actor, organization):
    if getattr(actor, "is_staff", False): return
    require_org_access(actor, organization, roles=FINANCE_ROLES)


def require_payout_mutation_access(actor, organization):
    if getattr(actor, "is_staff", False): return
    require_org_access(actor, organization, roles=PAYOUT_MUTATION_ROLES)


def account_balance(account, at=None):
    now = at or timezone.now()
    total = account.ledger_entries.aggregate(v=Sum("amount"))["v"] or Decimal("0.00")
    available = account.ledger_entries.filter(available_at__lte=now).aggregate(v=Sum("amount"))["v"] or Decimal("0.00")
    pending = total - available
    reserved = account.settlement_requests.filter(status__in=OPEN_SETTLEMENT).aggregate(v=Sum("amount"))["v"] or Decimal("0.00")
    return {"currency": account.currency, "total": _money(total), "available": _money(available), "pending": _money(pending), "reserved": _money(reserved), "withdrawable": _money(max(Decimal("0.00"), available - reserved))}


def validate_finance_policy(policy):
    policy.full_clean()
    if not policy.is_v2_complete: raise ValidationError("Finance Policy is incomplete.")
    return policy


def active_policy(currency):
    policies = list(FinancePolicy.objects.filter(lifecycle_status=FinancePolicy.LifecycleStatus.ACTIVE, currency=currency.upper()).order_by("id")[:2])
    if len(policies) != 1: raise FinancePolicyUnavailable(f"Exactly one complete ACTIVE V2 Finance Policy is required for {currency.upper()}.")
    policy = validate_finance_policy(policies[0])
    if not policy.validated_at or not policy.activated_at: raise FinancePolicyUnavailable("ACTIVE V2 Finance Policy is not validated and activated.")
    return policy


def policy_snapshot(policy):
    return {"code": policy.code, "policy_id": policy.pk, "currency": policy.currency, "fabinzi": {"type": policy.fabinzi_rule_type, "value": str(policy.fabinzi_rule_value)}, "garment_royalty": {"type": policy.garment_royalty_rule_type, "value": str(policy.garment_royalty_rule_value)}, "artwork_royalty": {"type": policy.artwork_royalty_rule_type, "value": str(policy.artwork_royalty_rule_value)}, "manufacturer": {"unit_price": policy.manufacturer_include_unit_price, "setup_fee": policy.manufacturer_include_setup_fee, "sample_fee": policy.manufacturer_include_sample_fee, "shipping_estimate": policy.manufacturer_include_shipping_estimate}, "settlement_trigger": policy.settlement_trigger, "settlement_hold_days": policy.settlement_hold_days, "minimum_payout": str(policy.v2_minimum_payout)}


@transaction.atomic
def validate_policy_draft(*, policy, actor, request=None):
    if not getattr(actor, "is_staff", False) or not actor.has_perm("finance.manage_finance_policy_governance"): raise PermissionDenied("V2 Finance Policy draft management permission required.")
    policy = FinancePolicy.objects.select_for_update().get(pk=policy.pk)
    if policy.lifecycle_status != FinancePolicy.LifecycleStatus.DRAFT: raise ValidationError("Only DRAFT Finance Policy versions may be validated.")
    validate_finance_policy(policy); policy.validated_at = timezone.now(); policy.save(update_fields=["validated_at", "updated_at"])
    record_audit_event(actor=actor, action="finance.policy.validated", instance=policy, metadata={"code": policy.code}, request=request); return policy


@transaction.atomic
def activate_policy(*, policy, actor, confirmed=False, request=None):
    if not getattr(actor, "is_staff", False) or not actor.has_perm("finance.activate_finance_policy_governance"): raise PermissionDenied("V2 Finance Policy activation permission required.")
    if not confirmed: raise ValidationError("Explicit Finance Policy activation confirmation is required.")
    policy = FinancePolicy.objects.select_for_update().get(pk=policy.pk)
    if policy.lifecycle_status != FinancePolicy.LifecycleStatus.DRAFT: raise ValidationError("Only a DRAFT Finance Policy may be activated.")
    validate_finance_policy(policy)
    if not policy.validated_at: raise ValidationError("Validate the Finance Policy before activation.")
    now = timezone.now()
    for previous in FinancePolicy.objects.select_for_update().filter(lifecycle_status=FinancePolicy.LifecycleStatus.ACTIVE, currency=policy.currency):
        previous.lifecycle_status = FinancePolicy.LifecycleStatus.RETIRED; previous.retired_at = now; previous.retired_by = actor; previous.is_active = False
        previous.save(update_fields=["lifecycle_status", "retired_at", "retired_by", "is_active", "updated_at"])
        record_audit_event(actor=actor, action="finance.policy.retired", instance=previous, metadata={"superseded_by": policy.code}, request=request)
    policy.lifecycle_status = FinancePolicy.LifecycleStatus.ACTIVE; policy.activated_at = now; policy.activated_by = actor; policy.is_active = False
    policy.save(update_fields=["lifecycle_status", "activated_at", "activated_by", "is_active", "updated_at"])
    record_audit_event(actor=actor, action="finance.policy.activated", instance=policy, metadata={"code": policy.code, "currency": policy.currency}, request=request)
    return policy


@transaction.atomic
def retire_policy(*, policy, actor, confirmed=False, request=None):
    if not getattr(actor, "is_staff", False) or not actor.has_perm("finance.activate_finance_policy_governance"): raise PermissionDenied("V2 Finance Policy activation permission required.")
    if not confirmed: raise ValidationError("Explicit Finance Policy retirement confirmation is required.")
    policy = FinancePolicy.objects.select_for_update().get(pk=policy.pk)
    if policy.lifecycle_status != FinancePolicy.LifecycleStatus.ACTIVE: raise ValidationError("Only an ACTIVE Finance Policy may be retired.")
    policy.lifecycle_status = FinancePolicy.LifecycleStatus.RETIRED; policy.retired_at = timezone.now(); policy.retired_by = actor; policy.is_active = False
    policy.save(update_fields=["lifecycle_status", "retired_at", "retired_by", "is_active", "updated_at"])
    record_audit_event(actor=actor, action="finance.policy.retired", instance=policy, metadata={"code": policy.code}, request=request); return policy


def _rule_amount(rule_type, value, *, gross, quantity):
    value = Decimal(value)
    if rule_type == FinancePolicy.RuleType.PERCENTAGE: return _money(gross * value / Decimal("100"))
    if rule_type == FinancePolicy.RuleType.FIXED: return _money(value)
    if rule_type == FinancePolicy.RuleType.PER_UNIT: return _money(value * Decimal(quantity))
    raise ValidationError("Unsupported Finance Policy rule type.")


def _payment_succeeded(order):
    if order.purchase_id: return PaymentAttempt.objects.filter(purchase_id=order.purchase_id, status=PaymentAttempt.Status.SUCCEEDED).exists()
    return PaymentAttempt.objects.filter(order=order, status=PaymentAttempt.Status.SUCCEEDED).exists()


def _immutable_source(order):
    item = getattr(order, "item", None); job = getattr(order, "production_job", None); specification = None; quote = None
    if job:
        try: specification = job.production_specification
        except ProductionSpecification.DoesNotExist: pass
        if getattr(job, "selection_id", None): quote = job.selection.quote
    quote_data = None
    if quote:
        quote_data = {"quote_id": quote.pk, "manufacturer_id": job.manufacturer_id, "currency": quote.currency.upper(), "unit_price": str(_money(quote.unit_price)), "setup_fee": str(_money(quote.setup_fee or 0)), "sample_fee": str(_money(quote.sample_fee or 0)), "shipping_estimate": str(_money(quote.shipping_estimate or 0))}
    designed = item.store_product.designed_product if item and item.store_product_id else None
    garment_org_id = getattr(designed, "garment_creator_organization_id", None) if designed else None
    artwork_org_id = getattr(designed, "artwork_creator_organization_id", None) if designed else None
    customization = dict(getattr(item, "customization_snapshot", None) or {})
    studio_versions = [e.get("artwork_version_id") for e in customization.get("elements", []) if e.get("kind") == "artwork" and e.get("artwork_version_id")]
    if studio_versions and not artwork_org_id:
        from apps.artwork.models import ArtworkVersion
        orgs = list(ArtworkVersion.objects.filter(pk__in=studio_versions).values_list("artwork__organization_id", flat=True).distinct())
        if len(orgs) == 1: artwork_org_id = orgs[0]
    source = {"purchase_id": order.purchase_id, "order_id": order.pk, "order_number": order.number, "order_item_id": item.pk if item else None, "currency": order.currency.upper(), "gross_amount": str(_money(order.total)), "quantity": int(item.quantity if item else 1), "pricing_snapshot": dict(getattr(item, "pricing_snapshot", None) or {}), "production_snapshot": dict(getattr(item, "production_snapshot", None) or {}), "customization_snapshot": customization, "garment_creator_organization_id": garment_org_id, "artwork_creator_organization_id": artwork_org_id, "manufacturer_quote": quote_data, "production_specification": {"id": specification.pk, "snapshot_sha256": specification.snapshot_sha256, "snapshot": specification.snapshot} if specification else None}
    return item, specification, quote, build_finance_source_snapshot(source)


@transaction.atomic
def capture_finance_recognition(*, order, actor=None, request=None, trigger_event=FinanceRecognitionPending.TriggerEvent.FULFILLMENT_DELIVERED):
    fulfillment = FulfillmentRecord.objects.select_for_update().filter(order=order).first()
    if not fulfillment or fulfillment.status != FulfillmentRecord.Status.DELIVERED or not fulfillment.delivered_at: raise ValidationError("Finance recognition requires delivered fulfillment.")
    existing = OrderFinance.objects.filter(order=order).first()
    if existing: return existing
    item, specification, quote, source = _immutable_source(order)
    pending, created = FinanceRecognitionPending.objects.get_or_create(order=order, defaults={"purchase_id": order.purchase_id, "order_item": item, "manufacturer_quote": quote, "production_specification": specification, "currency": order.currency.upper(), "trigger_event": trigger_event, "block_reason": "Awaiting eligible ACTIVE Finance Policy.", "source_snapshot": source})
    if created: record_audit_event(actor=actor, action="finance.recognition.pending_created", instance=pending, metadata={"order_id": order.pk, "trigger_event": trigger_event, "reason": pending.block_reason}, request=request)
    try:
        with transaction.atomic(): return reconcile_finance_pending(pending=pending, actor=actor, request=request, require_permission=False)
    except FinancePolicyUnavailable as exc:
        pending.refresh_from_db(); pending.block_reason = "; ".join(exc.messages); pending.last_attempt_at = timezone.now(); pending.save(update_fields=["block_reason", "last_attempt_at", "updated_at"]); return pending


def _manufacturer_payable(policy, source):
    quote = source.get("manufacturer_quote")
    if not quote: return Decimal("0.00")
    if quote["currency"].upper() != source["currency"].upper(): raise ValidationError("Manufacturer quote currency differs from immutable order currency; FX policy is not configured.")
    total = Decimal("0"); quantity = Decimal(source.get("quantity") or 1)
    if policy.manufacturer_include_unit_price: total += Decimal(quote["unit_price"]) * quantity
    if policy.manufacturer_include_setup_fee: total += Decimal(quote["setup_fee"])
    if policy.manufacturer_include_sample_fee: total += Decimal(quote["sample_fee"])
    if policy.manufacturer_include_shipping_estimate: total += Decimal(quote["shipping_estimate"])
    return _money(total)


def _trigger_eligible(policy, pending):
    if not FulfillmentRecord.objects.filter(order=pending.order, status=FulfillmentRecord.Status.DELIVERED).exists(): return False
    if policy.settlement_trigger == FinancePolicy.SettlementTrigger.DELIVERY: return True
    if policy.settlement_trigger == FinancePolicy.SettlementTrigger.PAYMENT_AND_DELIVERY: return _payment_succeeded(pending.order)
    return False


@transaction.atomic
def reconcile_finance_pending(*, pending, actor, request=None, require_permission=True):
    if require_permission and (not getattr(actor, "is_staff", False) or not actor.has_perm("finance.reconcile_finance_recognition")): raise PermissionDenied("Finance reconciliation permission required.")
    pending = FinanceRecognitionPending.objects.select_for_update().select_related("order").get(pk=pending.pk)
    if pending.reconciled_finance_id: return pending.reconciled_finance
    existing = OrderFinance.objects.select_for_update().filter(order=pending.order).first()
    if existing:
        pending.status = FinanceRecognitionPending.Status.RECONCILED; pending.reconciled_finance = existing; pending.reconciled_at = pending.reconciled_at or timezone.now(); pending.last_attempt_at = timezone.now(); pending.save(update_fields=["status", "reconciled_finance", "reconciled_at", "last_attempt_at", "updated_at"]); return existing
    policy = active_policy(pending.currency)
    if not _trigger_eligible(policy, pending): raise FinancePolicyUnavailable("The ACTIVE Finance Policy settlement eligibility trigger is not yet satisfied.")
    source = validate_finance_source_snapshot(pending.source_snapshot or {}); gross = _money(source["gross_amount"]); quantity = int(source.get("quantity") or 1)
    manufacturer_payable = _manufacturer_payable(policy, source)
    garment_amount = _rule_amount(policy.garment_royalty_rule_type, policy.garment_royalty_rule_value, gross=gross, quantity=quantity) if source.get("garment_creator_organization_id") else Decimal("0.00")
    artwork_amount = _rule_amount(policy.artwork_royalty_rule_type, policy.artwork_royalty_rule_value, gross=gross, quantity=quantity) if source.get("artwork_creator_organization_id") else Decimal("0.00")
    fabinzi_amount = _rule_amount(policy.fabinzi_rule_type, policy.fabinzi_rule_value, gross=gross, quantity=quantity)
    recognized_at = timezone.now(); available_at = recognized_at + timedelta(days=int(policy.settlement_hold_days))
    from apps.organizations.models import Organization
    garment_org = Organization.objects.filter(pk=source.get("garment_creator_organization_id")).first(); artwork_org = Organization.objects.filter(pk=source.get("artwork_creator_organization_id")).first(); manufacturer_org = Organization.objects.filter(pk=(source.get("manufacturer_quote") or {}).get("manufacturer_id")).first()
    fallback_designer = garment_org or pending.order.designer_organization
    garment_account = organization_account(garment_org, pending.currency) if garment_org else None; artwork_account = organization_account(artwork_org, pending.currency) if artwork_org else None; manufacturer_account = organization_account(manufacturer_org, pending.currency) if manufacturer_org else None; p_account = platform_account(pending.currency); compat_account = garment_account or organization_account(fallback_designer, pending.currency)
    try:
        finance = OrderFinance.objects.create(order=pending.order, order_item_id=source.get("order_item_id"), finance_policy=policy, designer_account=compat_account, manufacturer_account=manufacturer_account, garment_designer_account=garment_account, artwork_designer_account=artwork_account, platform_account=p_account, gross_amount=gross, platform_fee=fabinzi_amount, fabinzi_component=fabinzi_amount, manufacturer_payable=manufacturer_payable, designer_earnings=_money(garment_amount + artwork_amount), garment_designer_royalty=garment_amount, artwork_designer_royalty=artwork_amount, currency=pending.currency, policy_snapshot=policy_snapshot(policy), source_snapshot=source, pricing_snapshot=dict(source.get("pricing_snapshot") or {}), recognized_at=recognized_at, available_at=available_at)
    except IntegrityError: finance = OrderFinance.objects.select_for_update().get(order=pending.order)
    specs = [(OrderFinanceComponent.ComponentType.MANUFACTURER_PAYABLE, manufacturer_org, manufacturer_account, manufacturer_payable, LedgerEntry.EntryType.MANUFACTURER_PAYABLE), (OrderFinanceComponent.ComponentType.GARMENT_ROYALTY, garment_org, garment_account, garment_amount, LedgerEntry.EntryType.GARMENT_DESIGNER_ROYALTY), (OrderFinanceComponent.ComponentType.ARTWORK_ROYALTY, artwork_org, artwork_account, artwork_amount, LedgerEntry.EntryType.ARTWORK_DESIGNER_ROYALTY), (OrderFinanceComponent.ComponentType.FABINZI_COMPONENT, None, p_account, fabinzi_amount, LedgerEntry.EntryType.FABINZI_COMPONENT)]
    for component_type, beneficiary, account, amount, entry_type in specs:
        if account is None: continue
        OrderFinanceComponent.objects.get_or_create(order_finance=finance, component_type=component_type, defaults={"beneficiary_organization": beneficiary, "account": account, "amount": amount, "currency": pending.currency, "available_at": available_at})
        LedgerEntry.objects.get_or_create(event_key=f"order-finance:{finance.pk}:{component_type}", defaults={"account": account, "order_finance": finance, "entry_type": entry_type, "amount": amount, "currency": pending.currency, "available_at": available_at, "memo": f"Order {pending.order.number} · {policy.code}", "created_by": _actor(actor)})
    pending.status = FinanceRecognitionPending.Status.RECONCILED; pending.reconciled_finance = finance; pending.reconciled_at = timezone.now(); pending.last_attempt_at = pending.reconciled_at; pending.block_reason = ""; pending.save(update_fields=["status", "reconciled_finance", "reconciled_at", "last_attempt_at", "block_reason", "updated_at"])
    record_audit_event(actor=actor, action="finance.recognition.reconciled", instance=pending, metadata={"order_finance_id": finance.pk, "policy_code": policy.code, "order_id": pending.order_id}, request=request); return finance


def recognize_order_finance(*, order, actor=None, request=None):
    # Return durable pending state instead of raising so delivery is never rolled back for missing policy.
    return capture_finance_recognition(order=order, actor=actor, request=request)


def preview_policy(policy, *, gross="1000.00", quantity=1):
    validate_finance_policy(policy); source = {"currency": policy.currency, "gross_amount": str(_money(gross)), "quantity": int(quantity), "manufacturer_quote": {"currency": policy.currency, "unit_price": "400.00", "setup_fee": "50.00", "sample_fee": "20.00", "shipping_estimate": "30.00", "manufacturer_id": None}}
    return {"synthetic": True, "gross": _money(gross), "manufacturer_payable": _manufacturer_payable(policy, source), "garment_designer_royalty": _rule_amount(policy.garment_royalty_rule_type, policy.garment_royalty_rule_value, gross=_money(gross), quantity=quantity), "artwork_designer_royalty": _rule_amount(policy.artwork_royalty_rule_type, policy.artwork_royalty_rule_value, gross=_money(gross), quantity=quantity), "fabinzi_component": _rule_amount(policy.fabinzi_rule_type, policy.fabinzi_rule_value, gross=_money(gross), quantity=quantity), "currency": policy.currency}


def _normalize_iban(iban):
    value = "".join(str(iban or "").upper().split())
    if value and (len(value) < 15 or len(value) > 34 or not value.isalnum()): raise ValidationError("IBAN must contain 15-34 letters/numbers.")
    return value


def payout_iban(profile): return decrypt_text(profile.iban_encrypted) if profile.iban_encrypted else ""


@transaction.atomic
def update_payout_profile(*, organization, actor, method, account_holder, destination_hint="", bank_name="", iban="", country="", currency="", bank_proof=None, submit=False, request=None):
    require_payout_mutation_access(actor, organization); profile = PayoutProfile.objects.select_for_update().filter(organization=organization).first() or PayoutProfile(organization=organization); normalized = _normalize_iban(iban) if method == PayoutProfile.Method.BANK else ""
    if method == PayoutProfile.Method.BANK and submit and not (bank_name.strip() and normalized and country.strip() and currency.strip()): raise ValidationError("Bank name, IBAN, country and currency are required before verification.")
    profile.method = method; profile.account_holder = account_holder.strip(); profile.bank_name = bank_name.strip(); profile.country = country.strip().upper(); profile.currency = currency.strip().upper()
    if normalized: profile.iban_encrypted = encrypt_text(normalized); profile.iban_last4 = normalized[-4:]; profile.destination_hint = f"IBAN •••• {profile.iban_last4}"
    elif destination_hint.strip(): profile.destination_hint = destination_hint.strip()
    else: profile.destination_hint = "Not configured"
    if bank_proof is not None: profile.bank_proof = bank_proof
    profile.status = PayoutProfile.Status.PENDING if submit else PayoutProfile.Status.DRAFT; profile.verification_notes = ""; profile.verified_by = None; profile.verified_at = None; profile.full_clean(); profile.save()
    record_audit_event(actor=actor, action="finance.payout_profile.submitted" if submit else "finance.payout_profile.updated", instance=profile, metadata={"method": profile.method, "bank_name": profile.bank_name, "country": profile.country, "currency": profile.currency, "iban_last4": profile.iban_last4}, request=request); return profile


@transaction.atomic
def review_payout_profile(*, profile, reviewer, decision, notes="", request=None):
    if not getattr(reviewer, "is_staff", False) or not reviewer.has_perm("finance.change_payoutprofile"): raise PermissionDenied("Staff payout-profile review permission required.")
    profile = PayoutProfile.objects.select_for_update().get(pk=profile.pk)
    if decision not in {PayoutProfile.Status.VERIFIED, PayoutProfile.Status.REJECTED}: raise ValidationError("Unsupported payout profile decision.")
    if profile.status != PayoutProfile.Status.PENDING: raise ValidationError("Only pending payout profiles can be reviewed.")
    profile.status = decision; profile.verification_notes = notes; profile.verified_by = reviewer; profile.verified_at = timezone.now() if decision == PayoutProfile.Status.VERIFIED else None; profile.save(); record_audit_event(actor=reviewer, action=f"finance.payout_profile.{decision}", instance=profile, request=request); return profile


@transaction.atomic
def request_settlement(*, organization, actor, amount, currency, idempotency_key=None, request=None):
    require_payout_mutation_access(actor, organization); currency = currency.upper()
    if idempotency_key:
        existing = SettlementRequest.objects.filter(idempotency_key=idempotency_key).first()
        if existing:
            if existing.organization_id != organization.pk: raise PermissionDenied("Settlement idempotency key belongs to another organization.")
            return existing
    account = FinanceAccount.objects.select_for_update().filter(account_type=FinanceAccount.AccountType.ORGANIZATION, organization=organization, currency=currency).first()
    if not account: raise ValidationError("No finance account exists for this currency.")
    profile = PayoutProfile.objects.select_for_update().filter(organization=organization, status=PayoutProfile.Status.VERIFIED).first()
    if not profile: raise ValidationError("A verified payout profile is required.")
    policy = active_policy(currency); amount = _money(amount)
    if amount < policy.v2_minimum_payout: raise ValidationError(f"Minimum settlement is {policy.v2_minimum_payout} {currency}.")
    if amount > account_balance(account)["withdrawable"]: raise ValidationError("Settlement amount exceeds withdrawable balance.")
    settlement = SettlementRequest(organization=organization, account=account, payout_profile=profile, amount=amount, currency=currency, idempotency_key=idempotency_key or f"portal-{organization.pk}-{uuid.uuid4().hex}", payout_snapshot={"method": profile.method, "account_holder": profile.account_holder, "destination_hint": profile.destination_hint, "bank_name": profile.bank_name, "country": profile.country, "currency": profile.currency, "iban_last4": profile.iban_last4}, requested_by=actor, reserved_at=timezone.now()); settlement.full_clean(); settlement.save(); record_audit_event(actor=actor, action="finance.settlement.requested", instance=settlement, metadata={"amount": str(amount), "currency": currency}, request=request); return settlement


@transaction.atomic
def review_settlement(*, settlement, reviewer, decision, notes="", request=None):
    if not getattr(reviewer, "is_staff", False) or not reviewer.has_perm("finance.change_settlementrequest"): raise PermissionDenied("Staff settlement review permission required.")
    settlement = SettlementRequest.objects.select_for_update().get(pk=settlement.pk)
    if decision == SettlementRequest.Status.UNDER_REVIEW and settlement.status != SettlementRequest.Status.REQUESTED: raise ValidationError("Only requested payouts can enter review.")
    if decision in {SettlementRequest.Status.APPROVED, SettlementRequest.Status.REJECTED} and settlement.status not in {SettlementRequest.Status.REQUESTED, SettlementRequest.Status.UNDER_REVIEW}: raise ValidationError("Only requested/under-review payouts can be decided.")
    if decision not in {SettlementRequest.Status.UNDER_REVIEW, SettlementRequest.Status.APPROVED, SettlementRequest.Status.REJECTED}: raise ValidationError("Unsupported settlement decision.")
    settlement.status = decision; settlement.reviewed_by = reviewer; settlement.reviewed_at = timezone.now(); settlement.review_notes = notes; settlement.save(); record_audit_event(actor=reviewer, action=f"finance.settlement.{decision}", instance=settlement, request=request); return settlement


@transaction.atomic
def mark_settlement_processing(*, settlement, reviewer, execution_evidence, request=None):
    if not getattr(reviewer, "is_staff", False) or not reviewer.has_perm("finance.execute_finance_payout"): raise PermissionDenied("Payout execution permission required.")
    settlement = SettlementRequest.objects.select_for_update().get(pk=settlement.pk)
    if settlement.status != SettlementRequest.Status.APPROVED: raise ValidationError("Only approved payouts can enter processing.")
    if not execution_evidence.strip(): raise ValidationError("Processing evidence/reference is required.")
    settlement.status = SettlementRequest.Status.PROCESSING; settlement.processing_at = timezone.now(); settlement.execution_evidence = execution_evidence.strip(); settlement.save(); record_audit_event(actor=reviewer, action="finance.settlement.processing", instance=settlement, metadata={"evidence": settlement.execution_evidence}, request=request); return settlement


@transaction.atomic
def mark_settlement_paid(*, settlement, reviewer, external_reference, request=None):
    if not getattr(reviewer, "is_staff", False) or not reviewer.has_perm("finance.execute_finance_payout"): raise PermissionDenied("Payout execution permission required.")
    settlement = SettlementRequest.objects.select_for_update().get(pk=settlement.pk)
    if settlement.status != SettlementRequest.Status.PROCESSING: raise ValidationError("Only processing payouts can be marked paid.")
    if not external_reference.strip() or not settlement.execution_evidence.strip(): raise ValidationError("External payout reference and execution evidence are required.")
    settlement.status = SettlementRequest.Status.PAID; settlement.paid_by = reviewer; settlement.paid_at = timezone.now(); settlement.external_reference = external_reference.strip(); settlement.save(); LedgerEntry.objects.get_or_create(event_key=f"settlement:{settlement.pk}:paid", defaults={"account": settlement.account, "settlement": settlement, "entry_type": LedgerEntry.EntryType.SETTLEMENT, "amount": -settlement.amount, "currency": settlement.currency, "available_at": timezone.now(), "memo": f"Settlement {settlement.pk}", "created_by": reviewer}); record_audit_event(actor=reviewer, action="finance.settlement.paid", instance=settlement, metadata={"external_reference": settlement.external_reference}, request=request); return settlement


@transaction.atomic
def cancel_settlement(*, settlement, actor, request=None):
    require_payout_mutation_access(actor, settlement.organization); settlement = SettlementRequest.objects.select_for_update().get(pk=settlement.pk)
    if settlement.status not in {SettlementRequest.Status.REQUESTED, SettlementRequest.Status.UNDER_REVIEW}: raise ValidationError("Only requested/under-review payouts can be cancelled.")
    settlement.status = SettlementRequest.Status.CANCELLED; settlement.save(update_fields=["status"]); record_audit_event(actor=actor, action="finance.settlement.cancelled", instance=settlement, request=request); return settlement


@transaction.atomic
def create_adjustment(*, order_finance, account, amount, reason, actor, request=None):
    if not actor.is_staff: raise PermissionDenied("Staff access required.")
    adjustment = FinanceAdjustment(order_finance=order_finance, account=account, amount=_money(amount), reason=reason.strip(), created_by=actor); adjustment.full_clean(); adjustment.save(); LedgerEntry.objects.create(account=account, order_finance=order_finance, entry_type=LedgerEntry.EntryType.ADJUSTMENT, amount=adjustment.amount, currency=account.currency, available_at=timezone.now(), memo=reason.strip(), created_by=actor); record_audit_event(actor=actor, action="finance.adjustment.created", instance=adjustment, metadata={"amount": str(adjustment.amount)}, request=request); return adjustment
