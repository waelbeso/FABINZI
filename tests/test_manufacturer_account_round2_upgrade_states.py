from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.urls import reverse
from django.utils import timezone

from apps.subscriptions.models import (
    ManufacturerSubscriptionUpgradeRequest,
    OnboardingPlanSelection,
    OrganizationSubscription,
)
from apps.subscriptions.services import (
    MANUFACTURER_PRO,
    confirm_subscription_billing,
    entitlement_summary,
    get_effective_plan,
    plan_snapshot,
    price_snapshot,
)

from .test_manufacturer_portal_acceptance import manufacturer

User = get_user_model()


def _url(org):
    return f"{reverse('manufacturer-subscription')}?org={org.pk}"


def _selection(app, owner, *, due_at):
    pro = get_effective_plan(MANUFACTURER_PRO)
    app.reviewed_at = timezone.now()
    app.save(update_fields=["reviewed_at", "updated_at"])
    return OnboardingPlanSelection.objects.create(
        application=app,
        selected_plan_policy=pro,
        plan_code=pro.code,
        plan_version=pro.version,
        policy_snapshot=plan_snapshot(pro),
        price_snapshot=price_snapshot(pro),
        selected_by=owner,
        payment_due_at=due_at,
    )


def _operator(name):
    user = User.objects.create_user(
        username=name,
        email=f"{name}@example.test",
        password="password123",
        is_staff=True,
    )
    user.user_permissions.add(
        Permission.objects.get(
            content_type__app_label="subscriptions",
            codename="manage_professional_subscription",
        )
    )
    return user


@pytest.mark.django_db
def test_active_onboarding_pro_payment_window_blocks_duplicate_upgrade_intent(client, v2_3_reference_rows):
    owner, org, _profile, app = manufacturer("round2-window-active")
    _selection(app, owner, due_at=timezone.now() + timedelta(days=10))
    client.force_login(owner)
    page = client.get(_url(org))
    assert page.status_code == 200
    assert b"approved Pro onboarding payment path" in page.content
    assert b"Request Pro upgrade" not in page.content
    post = client.post(_url(org), {"action": "upgrade"})
    assert post.status_code == 200
    assert ManufacturerSubscriptionUpgradeRequest.objects.filter(organization=org).count() == 0


@pytest.mark.django_db
def test_paid_pending_activation_window_blocks_duplicate_upgrade_intent(client, v2_3_reference_rows):
    owner, org, _profile, app = manufacturer("round2-window-paid")
    selection = _selection(app, owner, due_at=timezone.now() + timedelta(days=10))
    operator = _operator("round2-window-paid-operator")
    confirmation = confirm_subscription_billing(
        organization=org,
        actor=operator,
        plan_code=selection.plan_code,
        amount=selection.selected_plan_policy.monthly_price,
        currency=selection.selected_plan_policy.currency,
        provider="round2-state-test",
        provider_reference="round2-paid-pending",
        idempotency_key="round2-paid-pending-idempotency",
    )
    assert confirmation.consumed_period_id is None
    client.force_login(owner)
    page = client.get(_url(org))
    assert b"Payment confirmed; activation pending" in page.content
    assert b"Request Pro upgrade" not in page.content
    post = client.post(_url(org), {"action": "upgrade"})
    assert post.status_code == 200
    assert ManufacturerSubscriptionUpgradeRequest.objects.filter(organization=org).count() == 0
    confirmation.refresh_from_db()
    assert confirmation.consumed_period_id is None


@pytest.mark.django_db
def test_expired_onboarding_window_allows_new_current_policy_upgrade_intent(client, v2_3_reference_rows):
    owner, org, _profile, app = manufacturer("round2-window-expired")
    selection = _selection(app, owner, due_at=timezone.now() - timedelta(days=1))
    client.force_login(owner)
    page = client.get(_url(org))
    assert page.status_code == 200
    assert b"Payment window expired" in page.content
    assert b"Request Pro upgrade" in page.content
    post = client.post(_url(org), {"action": "upgrade"})
    assert post.status_code == 302
    upgrade = ManufacturerSubscriptionUpgradeRequest.objects.get(organization=org)
    assert upgrade.status == ManufacturerSubscriptionUpgradeRequest.Status.REQUESTED
    current = get_effective_plan(MANUFACTURER_PRO)
    assert upgrade.target_plan_policy_id == current.pk
    assert upgrade.plan_code == current.code
    assert upgrade.plan_version == current.version
    assert upgrade.policy_snapshot == plan_snapshot(current)
    assert upgrade.price_snapshot == price_snapshot(current)
    assert upgrade.plan_version == selection.plan_version


@pytest.mark.django_db
def test_active_pro_entitlement_has_no_upgrade_action_or_request(client, v2_3_reference_rows):
    owner, org, _profile, _app = manufacturer("round2-active-pro")
    subscription = entitlement_summary(org)["subscription"]
    pro = get_effective_plan(MANUFACTURER_PRO)
    subscription.current_plan = pro
    subscription.status = OrganizationSubscription.Status.ACTIVE
    subscription.policy_snapshot = plan_snapshot(pro)
    subscription.price_snapshot = price_snapshot(pro)
    subscription.save(update_fields=["current_plan", "status", "policy_snapshot", "price_snapshot", "updated_at"])
    client.force_login(owner)
    page = client.get(_url(org))
    assert page.status_code == 200
    assert b"Request Pro upgrade" not in page.content
    post = client.post(_url(org), {"action": "upgrade"})
    assert post.status_code == 200
    assert ManufacturerSubscriptionUpgradeRequest.objects.filter(organization=org).count() == 0
