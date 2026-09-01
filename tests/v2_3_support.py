from datetime import date
from decimal import Decimal

import pytest


def ensure_v2_3_reference_rows():
    """Create canonical V2-3 test reference rows explicitly and idempotently."""
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

    for row in plans:
        SubscriptionPlanPolicy.objects.update_or_create(
            code=row["code"],
            version=row["version"],
            defaults=row,
        )
    for code, en, ar, offset in reminders:
        SubscriptionReminderMilestone.objects.update_or_create(
            code=code,
            defaults={
                "label_en": en,
                "label_ar": ar,
                "offset_days": offset,
                "active": True,
            },
        )
    TeamInvitationConfiguration.objects.update_or_create(
        singleton_key=1,
        defaults={"invitation_expiry_days": 7},
    )


@pytest.fixture
def v2_3_reference_rows(django_db_setup, django_db_blocker):
    """Explicit opt-in fixture; safe after TransactionTestCase database flushes."""
    with django_db_blocker.unblock():
        ensure_v2_3_reference_rows()
