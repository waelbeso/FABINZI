"""Canonical, JSON-safe immutable snapshots for V2 finance recognition.

This module is intentionally strict. Finance evidence must never depend on a
catch-all serializer that silently stringifies unknown Python objects. Values
that are not part of the supported historical-evidence vocabulary fail closed.
"""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from io import IOBase
import math
from uuid import UUID

from django.core.files.base import File
from django.db.models import Model, QuerySet


FINANCE_SOURCE_SNAPSHOT_SCHEMA = "fabinzi.finance-recognition-source"
FINANCE_SOURCE_SNAPSHOT_VERSION = 1

_SOURCE_FIELDS = {
    "purchase_id",
    "order_id",
    "order_number",
    "order_item_id",
    "currency",
    "gross_amount",
    "quantity",
    "pricing_snapshot",
    "production_snapshot",
    "customization_snapshot",
    "garment_creator_organization_id",
    "artwork_creator_organization_id",
    "manufacturer_quote",
    "production_specification",
}
_REQUIRED_SOURCE_FIELDS = {
    "purchase_id",
    "order_id",
    "order_number",
    "order_item_id",
    "currency",
    "gross_amount",
    "quantity",
    "pricing_snapshot",
    "production_snapshot",
    "customization_snapshot",
    "garment_creator_organization_id",
    "artwork_creator_organization_id",
    "manufacturer_quote",
    "production_specification",
}

_EXACT_PROTECTED_KEYS = {
    "iban",
    "iban_encrypted",
    "full_iban",
    "bank_proof",
    "bank_proof_bytes",
    "bank_credentials",
    "bank_account_credentials",
    "payment_secret",
    "client_secret",
    "secret_key",
    "api_secret",
    "private_key",
    "password",
    "card_number",
    "cvv",
    "cvc",
    "access_token",
    "refresh_token",
}


class FinanceSnapshotValidationError(ValueError):
    """Raised when finance evidence cannot be represented unambiguously/safely."""


def _normalized_key(key):
    return key.strip().lower().replace("-", "_").replace(" ", "_")


def _is_protected_key(key):
    normalized = _normalized_key(key)
    return (
        normalized in _EXACT_PROTECTED_KEYS
        or "iban" in normalized
        or "bank_proof" in normalized
        or normalized.endswith("_secret")
        or normalized.startswith("payment_secret_")
    )


def _path(parent, key):
    return f"{parent}.{key}" if parent else str(key)


def canonicalize_finance_value(value, *, path="$"):
    """Return a deterministic JSON-safe representation of a finance value.

    Decimal values are exact decimal strings; UUIDs are canonical strings;
    date/datetime values use ISO-8601; TextChoices/Enum values are normalized
    through their primitive ``value``. Technical finite floats are retained as
    JSON numbers (e.g. normalized Studio transform coordinates), while all
    financial amounts created by V2 finance itself use Decimal/string sources.
    """

    if isinstance(value, (Model, QuerySet)):
        raise FinanceSnapshotValidationError(f"Django model/queryset is prohibited at {path}.")
    if isinstance(value, (File, IOBase, bytes, bytearray, memoryview)):
        raise FinanceSnapshotValidationError(f"File/binary value is prohibited at {path}.")
    if isinstance(value, Enum):
        return canonicalize_finance_value(value.value, path=path)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise FinanceSnapshotValidationError(f"Non-finite Decimal is prohibited at {path}.")
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise FinanceSnapshotValidationError(f"Non-finite float is prohibited at {path}.")
        return value
    if isinstance(value, dict):
        normalized = {}
        for key, child in value.items():
            if not isinstance(key, str):
                raise FinanceSnapshotValidationError(f"Finance snapshot keys must be strings at {path}.")
            if _is_protected_key(key):
                raise FinanceSnapshotValidationError(f"Protected financial credential/evidence key is prohibited at {_path(path, key)}.")
            normalized[key] = canonicalize_finance_value(child, path=_path(path, key))
        return normalized
    if isinstance(value, (list, tuple)):
        return [canonicalize_finance_value(child, path=f"{path}[{index}]") for index, child in enumerate(value)]
    raise FinanceSnapshotValidationError(f"Unsupported finance snapshot type {type(value).__name__} at {path}.")


def build_finance_source_snapshot(payload):
    """Build the only supported V2 finance-recognition source snapshot schema."""

    if not isinstance(payload, dict):
        raise FinanceSnapshotValidationError("Finance source snapshot payload must be a dict.")
    unknown = set(payload) - _SOURCE_FIELDS
    missing = _REQUIRED_SOURCE_FIELDS - set(payload)
    if unknown:
        raise FinanceSnapshotValidationError(f"Unknown finance source snapshot fields: {sorted(unknown)}")
    if missing:
        raise FinanceSnapshotValidationError(f"Missing finance source snapshot fields: {sorted(missing)}")
    snapshot = {
        "schema": FINANCE_SOURCE_SNAPSHOT_SCHEMA,
        "schema_version": FINANCE_SOURCE_SNAPSHOT_VERSION,
        **payload,
    }
    return canonicalize_finance_value(snapshot)


def validate_finance_source_snapshot(snapshot):
    """Validate a persisted snapshot before it drives historical finance."""

    if not isinstance(snapshot, dict):
        raise FinanceSnapshotValidationError("Persisted finance source snapshot must be a dict.")
    if snapshot.get("schema") != FINANCE_SOURCE_SNAPSHOT_SCHEMA:
        raise FinanceSnapshotValidationError("Unsupported finance source snapshot schema.")
    if snapshot.get("schema_version") != FINANCE_SOURCE_SNAPSHOT_VERSION:
        raise FinanceSnapshotValidationError("Unsupported finance source snapshot version.")
    payload = {key: value for key, value in snapshot.items() if key not in {"schema", "schema_version"}}
    canonical = build_finance_source_snapshot(payload)
    if canonical != snapshot:
        raise FinanceSnapshotValidationError("Persisted finance source snapshot is not canonical.")
    return canonical
