import json
import threading
from datetime import date, datetime, timezone as datetime_timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied
from django.db import close_old_connections
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.finance.models import FinancePolicy, FinanceRecognitionPending, LedgerEntry, OrderFinance
from apps.finance.services import activate_policy, reconcile_finance_pending, validate_policy_draft
from apps.finance.snapshots import (
    FINANCE_SOURCE_SNAPSHOT_SCHEMA,
    FINANCE_SOURCE_SNAPSHOT_VERSION,
    FinanceSnapshotValidationError,
    build_finance_source_snapshot,
    canonicalize_finance_value,
)
from apps.operations.models import FulfillmentRecord
from apps.operations.services import deliver_order
from tests.v2_7_helpers import order_line, user

pytestmark = pytest.mark.django_db


def _grant(target, *codenames): target.user_permissions.add(*Permission.objects.filter(codename__in=codenames))


def _complete_draft(code, *, created_by=None, currency="EGP", garment="10.00", artwork="5.00", fabinzi="7.50"):
    return FinancePolicy.objects.create(name=f"SYNTHETIC QA {code}", code=code, lifecycle_status=FinancePolicy.LifecycleStatus.DRAFT, currency=currency, fabinzi_rule_type=FinancePolicy.RuleType.PERCENTAGE, fabinzi_rule_value=Decimal(fabinzi), garment_royalty_rule_type=FinancePolicy.RuleType.PERCENTAGE, garment_royalty_rule_value=Decimal(garment), artwork_royalty_rule_type=FinancePolicy.RuleType.PERCENTAGE, artwork_royalty_rule_value=Decimal(artwork), manufacturer_include_unit_price=True, manufacturer_include_setup_fee=False, manufacturer_include_sample_fee=False, manufacturer_include_shipping_estimate=False, settlement_trigger=FinancePolicy.SettlementTrigger.DELIVERY, settlement_hold_days=0, v2_minimum_payout=Decimal("1.00"), created_by=created_by, is_active=False)


def _activate_synthetic(code, staff, **kwargs):
    policy = _complete_draft(code, created_by=staff, **kwargs); validate_policy_draft(policy=policy, actor=staff); return activate_policy(policy=policy, actor=staff, confirmed=True)


def _delivered_without_policy(prefix):
    line = order_line(prefix, purchase_kind="ready_designed"); designed = line["product"].designed_product; designed.garment_creator_organization = line["designer_org"]; designed.artwork_creator_organization = line["designer_org"]; designed.economic_attribution = {"garment_creator_organization_id": line["designer_org"].pk, "artwork_creator_organization_id": line["designer_org"].pk}; designed.save(update_fields=["garment_creator_organization", "artwork_creator_organization", "economic_attribution", "updated_at"])
    fulfillment = line["fulfillment"]; fulfillment.status = FulfillmentRecord.Status.SHIPPED; fulfillment.shipped_at = timezone.now(); fulfillment.carrier = "SYNTHETIC-QA"; fulfillment.tracking_number = f"QA-{prefix}"; fulfillment.save(); delivered = deliver_order(fulfillment=fulfillment, actor=line["designer"]); return line, delivered


def _finance_staff(prefix):
    staff = user(f"{prefix}-finance-staff", staff=True); _grant(staff, "view_finance_policy_governance", "manage_finance_policy_governance", "activate_finance_policy_governance", "reconcile_finance_recognition"); return staff


def _raw_snapshot_payload():
    nested_uuid = uuid4()
    return {
        "purchase_id": 101,
        "order_id": 202,
        "order_number": uuid4(),
        "order_item_id": 303,
        "currency": "EGP",
        "gross_amount": Decimal("123.4500"),
        "quantity": 2,
        "pricing_snapshot": {"line_subtotal": Decimal("123.4500"), "nested": {"captured_on": date(2026, 9, 3)}},
        "production_snapshot": {"garment_version_id": nested_uuid, "captured_at": datetime(2026, 9, 3, 9, 30, 15, 123456, tzinfo=datetime_timezone.utc), "status": FinancePolicy.LifecycleStatus.DRAFT},
        "customization_snapshot": {"enabled": True, "elements": [{"artwork_version_id": nested_uuid, "transform": {"x": 0.125, "y": 0.25, "width": 0.5, "height": 0.5}}]},
        "garment_creator_organization_id": 404,
        "artwork_creator_organization_id": 505,
        "manufacturer_quote": {"quote_id": 606, "manufacturer_id": 707, "currency": "EGP", "unit_price": Decimal("10.00"), "setup_fee": Decimal("2.50"), "sample_fee": Decimal("0.00"), "shipping_estimate": Decimal("1.25")},
        "production_specification": {"id": 808, "snapshot_sha256": "a" * 64, "snapshot": {"source_uuid": nested_uuid}},
    }


def test_finance_snapshot_canonicalizer_is_explicit_exact_and_json_safe():
    raw = _raw_snapshot_payload(); expected_order_number = str(raw["order_number"]); expected_nested_uuid = str(raw["production_snapshot"]["garment_version_id"])
    snapshot = build_finance_source_snapshot(raw)
    assert snapshot["schema"] == FINANCE_SOURCE_SNAPSHOT_SCHEMA
    assert snapshot["schema_version"] == FINANCE_SOURCE_SNAPSHOT_VERSION
    assert snapshot["order_number"] == expected_order_number
    assert snapshot["gross_amount"] == "123.4500"
    assert snapshot["pricing_snapshot"]["line_subtotal"] == "123.4500"
    assert snapshot["production_snapshot"]["garment_version_id"] == expected_nested_uuid
    assert snapshot["production_snapshot"]["captured_at"] == "2026-09-03T09:30:15.123456+00:00"
    assert snapshot["production_snapshot"]["status"] == FinancePolicy.LifecycleStatus.DRAFT.value
    assert snapshot["customization_snapshot"]["elements"][0]["artwork_version_id"] == expected_nested_uuid
    assert snapshot["manufacturer_quote"]["unit_price"] == "10.00"
    assert json.loads(json.dumps(snapshot, sort_keys=True, separators=(",", ":"))) == snapshot
    assert build_finance_source_snapshot(raw) == snapshot


def test_finance_snapshot_rejects_models_querysets_unknown_objects_and_binary():
    line = order_line("v28-snapshot-reject")
    with pytest.raises(FinanceSnapshotValidationError): canonicalize_finance_value(line["order"])
    with pytest.raises(FinanceSnapshotValidationError): canonicalize_finance_value(OrderFinance.objects.all())
    with pytest.raises(FinanceSnapshotValidationError): canonicalize_finance_value(object())
    with pytest.raises(FinanceSnapshotValidationError): canonicalize_finance_value(b"bank-proof-bytes")


@pytest.mark.parametrize("protected_key", ["iban", "full_iban", "iban_encrypted", "bank_proof", "payment_secret", "client_secret", "card_number", "cvv"])
def test_finance_snapshot_rejects_protected_financial_credentials(protected_key):
    raw = _raw_snapshot_payload(); raw["customization_snapshot"] = {"nested": {protected_key: "PROHIBITED-QA-VALUE"}}
    with pytest.raises(FinanceSnapshotValidationError): build_finance_source_snapshot(raw)


def test_no_active_policy_delivery_remains_legitimate_and_durable_pending_exists():
    FinancePolicy.objects.create(name="LEGACY QA SENTINEL 10-7-100", platform_fee_bps=1000, settlement_delay_days=7, minimum_payout=Decimal("100.00"), is_active=True)
    line, delivered = _delivered_without_policy("v28-blocked"); delivered.refresh_from_db(); assert delivered.status == FulfillmentRecord.Status.DELIVERED; assert not OrderFinance.objects.filter(order=line["order"]).exists(); assert not LedgerEntry.objects.filter(order_finance__order=line["order"]).exists()
    pending = FinanceRecognitionPending.objects.get(order=line["order"]); assert pending.status == FinanceRecognitionPending.Status.BLOCKED; assert pending.currency == "EGP"; assert pending.purchase_id == line["purchase"].pk; assert pending.order_item_id == line["item"].pk; assert pending.source_snapshot["order_id"] == line["order"].pk; assert pending.source_snapshot["order_number"] == str(line["order"].number); assert pending.source_snapshot["schema"] == FINANCE_SOURCE_SNAPSHOT_SCHEMA; assert pending.source_snapshot["schema_version"] == FINANCE_SOURCE_SNAPSHOT_VERSION; assert pending.source_snapshot["gross_amount"] == "500.00"; assert "ACTIVE V2 Finance Policy" in pending.block_reason
    serialized = json.dumps(pending.source_snapshot, sort_keys=True); lowered = serialized.lower(); assert "iban" not in lowered; assert "bank_proof" not in lowered; assert "payment_secret" not in lowered


def test_explicit_reconciliation_binds_exact_policy_and_retry_is_idempotent():
    line, _ = _delivered_without_policy("v28-reconcile"); pending = FinanceRecognitionPending.objects.get(order=line["order"]); staff = _finance_staff("v28-reconcile"); policy = _activate_synthetic("FIN-POL-QA-V1", staff); pending.refresh_from_db(); assert pending.status == FinanceRecognitionPending.Status.BLOCKED; assert not OrderFinance.objects.filter(order=line["order"]).exists()
    first = reconcile_finance_pending(pending=pending, actor=staff); again = reconcile_finance_pending(pending=pending, actor=staff); assert again.pk == first.pk; assert first.finance_policy_id == policy.pk; assert first.policy_snapshot["code"] == "FIN-POL-QA-V1"; assert first.garment_designer_royalty == Decimal("50.00"); assert first.artwork_designer_royalty == Decimal("25.00"); assert first.fabinzi_component == Decimal("37.50"); assert OrderFinance.objects.filter(order=line["order"]).count() == 1; assert first.components.count() == 3; assert first.ledger_entries.count() == 3; assert first.ledger_entries.values("event_key").distinct().count() == 3
    expected = (first.garment_designer_royalty, first.artwork_designer_royalty, first.fabinzi_component, first.manufacturer_payable, first.policy_snapshot, first.source_snapshot)
    reloaded_pending = FinanceRecognitionPending.objects.get(pk=pending.pk); reloaded = reconcile_finance_pending(pending=reloaded_pending, actor=staff); reloaded.refresh_from_db(); assert (reloaded.garment_designer_royalty, reloaded.artwork_designer_royalty, reloaded.fabinzi_component, reloaded.manufacturer_payable, reloaded.policy_snapshot, reloaded.source_snapshot) == expected


@pytest.mark.django_db(transaction=True)
def test_concurrent_reconciliation_produces_exactly_one_financial_result():
    line, _ = _delivered_without_policy("v28-concurrent"); pending = FinanceRecognitionPending.objects.get(order=line["order"]); staff = _finance_staff("v28-concurrent"); _activate_synthetic("FIN-POL-QA-CONCURRENT", staff); barrier = threading.Barrier(2); results, errors = [], []
    def worker():
        close_old_connections()
        try:
            from django.contrib.auth import get_user_model
            local_staff = get_user_model().objects.get(pk=staff.pk); local_pending = FinanceRecognitionPending.objects.get(pk=pending.pk); barrier.wait(); results.append(reconcile_finance_pending(pending=local_pending, actor=local_staff).pk)
        except Exception as exc: errors.append(exc)
        finally: close_old_connections()
    threads = [threading.Thread(target=worker), threading.Thread(target=worker)]
    for thread in threads: thread.start()
    for thread in threads: thread.join()
    assert errors == []; assert len(set(results)) == 1; finance = OrderFinance.objects.get(order=line["order"]); assert finance.ledger_entries.count() == 3; assert finance.components.count() == 3


def test_policy_v2_activation_does_not_recalculate_historical_v1_finance_or_ledger():
    line, _ = _delivered_without_policy("v28-history"); staff = _finance_staff("v28-history"); p1 = _activate_synthetic("FIN-POL-QA-HIST-V1", staff, garment="10.00", artwork="5.00", fabinzi="7.50"); finance = reconcile_finance_pending(pending=FinanceRecognitionPending.objects.get(order=line["order"]), actor=staff); frozen = {"policy_id": finance.finance_policy_id, "policy_snapshot": finance.policy_snapshot, "garment": finance.garment_designer_royalty, "artwork": finance.artwork_designer_royalty, "fabinzi": finance.fabinzi_component, "ledger": list(finance.ledger_entries.order_by("event_key").values_list("event_key", "amount"))}
    p2 = _complete_draft("FIN-POL-QA-HIST-V2", created_by=staff, garment="20.00", artwork="1.00", fabinzi="3.00"); validate_policy_draft(policy=p2, actor=staff); activate_policy(policy=p2, actor=staff, confirmed=True); p1.refresh_from_db(); assert p1.lifecycle_status == FinancePolicy.LifecycleStatus.RETIRED; finance.refresh_from_db(); assert finance.finance_policy_id == frozen["policy_id"]; assert finance.policy_snapshot == frozen["policy_snapshot"]; assert finance.garment_designer_royalty == frozen["garment"]; assert finance.artwork_designer_royalty == frozen["artwork"]; assert finance.fabinzi_component == frozen["fabinzi"]; assert list(finance.ledger_entries.order_by("event_key").values_list("event_key", "amount")) == frozen["ledger"]


def test_policy_activation_alone_does_not_mutate_blocked_record():
    line, _ = _delivered_without_policy("v28-no-auto"); pending = FinanceRecognitionPending.objects.get(order=line["order"]); before_snapshot = pending.source_snapshot; staff = _finance_staff("v28-no-auto"); _activate_synthetic("FIN-POL-QA-NO-AUTO", staff); pending.refresh_from_db(); assert pending.status == FinanceRecognitionPending.Status.BLOCKED; assert pending.source_snapshot == before_snapshot; assert pending.reconciled_finance_id is None; assert not OrderFinance.objects.filter(order=line["order"]).exists()


def test_reconciliation_is_audited_with_policy_identity():
    line, _ = _delivered_without_policy("v28-audit"); staff = _finance_staff("v28-audit"); _activate_synthetic("FIN-POL-QA-AUDIT", staff); pending = FinanceRecognitionPending.objects.get(order=line["order"]); finance = reconcile_finance_pending(pending=pending, actor=staff); event = AuditEvent.objects.filter(action="finance.recognition.reconciled", object_id=str(pending.pk)).latest("created_at"); assert event.actor_id == staff.pk; assert event.metadata["policy_code"] == finance.finance_policy.code


def test_unauthorized_designer_cannot_activate_finance_policy():
    line = order_line("v28-policy-denied"); policy = _complete_draft("FIN-POL-QA-DENIED")
    with pytest.raises(PermissionDenied): validate_policy_draft(policy=policy, actor=line["designer"])
    with pytest.raises(PermissionDenied): activate_policy(policy=policy, actor=line["designer"], confirmed=True)
