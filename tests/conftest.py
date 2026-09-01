import io
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from PIL import Image


def _png_bytes():
    buffer = io.BytesIO()
    Image.new("RGBA", (4, 4), (36, 44, 55, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


VALID_PNG = _png_bytes()


@pytest.fixture(autouse=True)
def _valid_png_upload_bytes(monkeypatch):
    """Keep image-upload fixtures genuinely decodable by the installed Pillow.

    The security/browser modules expose a PNG_1X1 constant only as a compact
    source for real multipart upload tests. Replace those bytes at runtime with
    a PNG produced by the same Pillow installation used by the application.
    """
    for module in list(sys.modules.values()):
        if module is not None and hasattr(module, "PNG_1X1"):
            monkeypatch.setattr(module, "PNG_1X1", VALID_PNG)


_V2_3_REFERENCE_REQUIRED_FILES = {
    "test_v2_subscriptions_entitlements_team.py",
    "test_v2_3_full_suite_integration.py",
    "test_v2_applications_organizations.py",
    "test_demo_seed.py",
    "test_artwork_studio_browser.py",
    "test_artwork_studio_productization.py",
    "test_designer_portal_acceptance_core.py",
    "test_designer_portal_browser.py",
    "test_manufacturer_portal_acceptance.py",
    "test_manufacturer_portal_browser.py",
}


@pytest.fixture(autouse=True)
def _v2_3_reference_rows(request, django_db_blocker):
    """Provision V2-3 policy/config prerequisites only for integration surfaces.

    Real pytest-django transaction/browser tests flush migration-seeded data.
    Recreate the canonical V2-3 reference rows only for tests that exercise
    V2-3 subscription/entitlement activation or transitions. This keeps real
    PostgreSQL transaction tests intact and avoids any global marker mutation.
    """
    filename = Path(str(getattr(request.node, "fspath", ""))).name
    if filename not in _V2_3_REFERENCE_REQUIRED_FILES:
        yield
        return

    from apps.subscriptions.models import (
        SubscriptionPlanPolicy,
        SubscriptionReminderMilestone,
        TeamInvitationConfiguration,
    )

    effective = date(2026, 9, 1)
    plans = [
        {
            "code": "manufacturer_starter",
            "version": 1,
            "public_name_ar": "المصنّع — Starter",
            "public_name_en": "Manufacturer Starter",
            "audience": "manufacturer",
            "monthly_price": Decimal("0.00"),
            "currency": "EGP",
            "tax_inclusive": True,
            "trial_months": 0,
            "designer_active_design_limit": None,
            "designer_active_artwork_limit": None,
            "manufacturer_monthly_offer_limit": 2,
            "team_subaccount_limit": 1,
            "active": True,
            "effective_from": effective,
            "effective_to": None,
        },
        {
            "code": "manufacturer_pro",
            "version": 1,
            "public_name_ar": "المصنّع — Pro",
            "public_name_en": "Manufacturer Pro",
            "audience": "manufacturer",
            "monthly_price": Decimal("1500.00"),
            "currency": "EGP",
            "tax_inclusive": True,
            "trial_months": 6,
            "designer_active_design_limit": None,
            "designer_active_artwork_limit": None,
            "manufacturer_monthly_offer_limit": 15,
            "team_subaccount_limit": 4,
            "active": True,
            "effective_from": effective,
            "effective_to": None,
        },
        {
            "code": "designer_starter",
            "version": 1,
            "public_name_ar": "المصمم — Starter",
            "public_name_en": "Designer Starter",
            "audience": "designer",
            "monthly_price": Decimal("0.00"),
            "currency": "EGP",
            "tax_inclusive": True,
            "trial_months": 0,
            "designer_active_design_limit": 2,
            "designer_active_artwork_limit": 2,
            "manufacturer_monthly_offer_limit": None,
            "team_subaccount_limit": 1,
            "active": True,
            "effective_from": effective,
            "effective_to": None,
        },
        {
            "code": "designer_pro",
            "version": 1,
            "public_name_ar": "المصمم — Pro",
            "public_name_en": "Designer Pro",
            "audience": "designer",
            "monthly_price": Decimal("350.00"),
            "currency": "EGP",
            "tax_inclusive": True,
            "trial_months": 0,
            "designer_active_design_limit": 10,
            "designer_active_artwork_limit": 5,
            "manufacturer_monthly_offer_limit": None,
            "team_subaccount_limit": 4,
            "active": True,
            "effective_from": effective,
            "effective_to": None,
        },
    ]
    reminders = [
        ("renewal_7_days", "7 days before renewal", "قبل التجديد بـ 7 أيام", -7),
        ("renewal_3_days", "3 days before renewal", "قبل التجديد بـ 3 أيام", -3),
        ("renewal_1_day", "1 day before renewal", "قبل التجديد بيوم", -1),
        ("renewal_due", "Renewal due date", "موعد التجديد", 0),
        ("grace_day_1", "Grace day 1", "اليوم الأول من المهلة", 1),
        ("grace_day_2", "Grace day 2", "اليوم الثاني من المهلة", 2),
        ("grace_day_3", "Final grace day 3", "اليوم الثالث والأخير من المهلة", 3),
    ]
    with django_db_blocker.unblock():
        for row in plans:
            SubscriptionPlanPolicy.objects.update_or_create(
                code=row["code"], version=row["version"], defaults=row
            )
        for code, en, ar, offset in reminders:
            SubscriptionReminderMilestone.objects.update_or_create(
                code=code,
                defaults={"label_en": en, "label_ar": ar, "offset_days": offset, "active": True},
            )
        TeamInvitationConfiguration.objects.update_or_create(
            singleton_key=1,
            defaults={"invitation_expiry_days": 7},
        )
    yield
