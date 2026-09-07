import json
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.finance.models import PayoutProfile
from apps.finance.services import payout_iban, review_payout_profile, update_payout_profile
from apps.notifications.models import Notification, NotificationPreference
from apps.organizations.designer_context import DESIGNER_ROUTE_SECTIONS
from apps.organizations.models import DesignerProfile, Membership, OnboardingApplication, Organization
from apps.storefront.models import Storefront
from apps.subscriptions.models import OnboardingPlanSelection, OrganizationSubscription
from apps.subscriptions.services import DESIGNER_PRO, entitlement_summary, get_effective_plan, plan_snapshot, price_snapshot

User = get_user_model()


def _designer(owner, name="Round 3 Studio", role=Membership.Role.OWNER):
    org = Organization.objects.create(
        kind=Organization.Kind.DESIGNER,
        display_name=name,
        email=f"{owner.username}@round3.test",
        verification_status=Organization.VerificationStatus.ACTIVE,
        created_by=owner,
    )
    Membership.objects.create(organization=org, user=owner, role=role)
    DesignerProfile.objects.create(organization=org, studio_name=name, terms_accepted=True)
    app = OnboardingApplication.objects.create(
        organization=org,
        status=OnboardingApplication.Status.APPROVED,
        reviewed_at=timezone.now(),
    )
    return org, app


def _bank_profile(org, owner, iban="EG00ROUNDTHREE00001234", *, submit=False):
    return update_payout_profile(
        organization=org,
        actor=owner,
        method=PayoutProfile.Method.BANK,
        account_holder="Round Three Owner",
        bank_name="Round Three Bank",
        iban=iban,
        country="EG",
        currency="EGP",
        submit=submit,
    )


def _verify_profile(profile):
    reviewer = User.objects.create_user(username=f"reviewer-{profile.pk}", password="password123", is_staff=True)
    reviewer.user_permissions.add(Permission.objects.get(codename="change_payoutprofile"))
    return review_payout_profile(
        profile=profile,
        reviewer=reviewer,
        decision=PayoutProfile.Status.VERIFIED,
        notes="Round 3 verified fixture",
    )


@pytest.mark.django_db
def test_bank_profile_blank_iban_keeps_ciphertext_and_can_submit_existing_secret():
    owner = User.objects.create_user(username="round3-bank-owner", password="password123")
    org, _ = _designer(owner)
    plaintext = "EG00ROUNDTHREE00001234"
    profile = _bank_profile(org, owner, plaintext, submit=False)
    original_ciphertext = profile.iban_encrypted
    original_last4 = profile.iban_last4
    original_mask = profile.destination_hint

    profile = update_payout_profile(
        organization=org,
        actor=owner,
        method=PayoutProfile.Method.BANK,
        account_holder="Round Three Owner",
        bank_name="Round Three Bank Updated",
        iban="",
        country="EG",
        currency="EGP",
        submit=False,
    )
    assert profile.iban_encrypted == original_ciphertext
    assert profile.iban_last4 == original_last4
    assert profile.destination_hint == original_mask
    assert payout_iban(profile) == plaintext

    profile = update_payout_profile(
        organization=org,
        actor=owner,
        method=PayoutProfile.Method.BANK,
        account_holder="Round Three Owner",
        bank_name="Round Three Bank Updated",
        iban="",
        country="EG",
        currency="EGP",
        submit=True,
    )
    assert profile.status == PayoutProfile.Status.PENDING
    assert profile.iban_encrypted == original_ciphertext
    assert profile.iban_last4 == original_last4
    assert profile.destination_hint == original_mask
    serialized_audit = json.dumps(
        list(AuditEvent.objects.filter(object_id=str(profile.pk)).values_list("metadata", flat=True)),
        sort_keys=True,
    )
    assert plaintext not in serialized_audit


@pytest.mark.django_db
def test_bank_profile_replacement_no_stored_iban_failure_and_manual_semantics():
    owner = User.objects.create_user(username="round3-bank-replace", password="password123")
    org, _ = _designer(owner)
    first = "EG00ROUNDTHREE00001234"
    second = "EG00ROUNDTHREE99995678"
    profile = _bank_profile(org, owner, first, submit=False)
    old_ciphertext = profile.iban_encrypted

    profile = update_payout_profile(
        organization=org,
        actor=owner,
        method=PayoutProfile.Method.BANK,
        account_holder="Round Three Owner",
        bank_name="Replacement Bank",
        iban=second,
        country="EG",
        currency="EGP",
        submit=False,
    )
    assert profile.iban_encrypted != old_ciphertext
    assert profile.iban_last4 == "5678"
    assert profile.destination_hint == "IBAN •••• 5678"
    assert second not in json.dumps(AuditEvent.objects.filter(object_id=str(profile.pk)).values_list("metadata", flat=True), default=str)

    other = User.objects.create_user(username="round3-bank-empty", password="password123")
    other_org, _ = _designer(other, "Round 3 Empty")
    with pytest.raises(ValidationError):
        update_payout_profile(
            organization=other_org,
            actor=other,
            method=PayoutProfile.Method.BANK,
            account_holder="No IBAN",
            bank_name="Bank",
            iban="",
            country="EG",
            currency="EGP",
            destination_hint="IBAN •••• 9999",
            submit=True,
        )
    assert not PayoutProfile.objects.filter(organization=other_org).exists()

    manual = update_payout_profile(
        organization=other_org,
        actor=other,
        method=PayoutProfile.Method.MANUAL,
        account_holder="Manual Owner",
        destination_hint="MANUAL-REFERENCE",
        submit=False,
    )
    assert manual.method == PayoutProfile.Method.MANUAL
    assert manual.destination_hint == "MANUAL-REFERENCE"
    assert manual.iban_encrypted == ""


@pytest.mark.django_db
def test_verified_profile_fails_closed_before_any_owner_mutation_or_success_audit():
    owner = User.objects.create_user(username="round3-verified-owner", password="password123")
    org, _ = _designer(owner)
    profile = _verify_profile(_bank_profile(org, owner, submit=True))
    profile.refresh_from_db()
    material_fields = (
        "method", "account_holder", "destination_hint", "bank_name", "iban_encrypted", "iban_last4",
        "country", "currency", "bank_proof_id", "status", "verification_notes", "verified_by_id", "verified_at",
    )
    before = {field: getattr(profile, field) for field in material_fields}
    success_actions = ["finance.payout_profile.updated", "finance.payout_profile.submitted"]
    audit_before = AuditEvent.objects.filter(object_id=str(profile.pk), action__in=success_actions).count()

    for submit in (False, True):
        with pytest.raises(ValidationError, match="Verified payout profiles are read-only"):
            update_payout_profile(
                organization=org,
                actor=owner,
                method=PayoutProfile.Method.BANK,
                account_holder="MUTATED",
                bank_name="MUTATED",
                iban="EG00ROUNDTHREE99995678",
                country="US",
                currency="USD",
                submit=submit,
            )
        profile.refresh_from_db()
        assert {field: getattr(profile, field) for field in material_fields} == before
    assert AuditEvent.objects.filter(object_id=str(profile.pk), action__in=success_actions).count() == audit_before


@pytest.mark.django_db
def test_finance_api_verified_mutation_returns_controlled_validation_and_cannot_mutate(client):
    owner = User.objects.create_user(username="round3-api-owner", password="password123")
    org, _ = _designer(owner)
    profile = _verify_profile(_bank_profile(org, owner, submit=True))
    before = (profile.status, profile.account_holder, profile.iban_encrypted, profile.verified_at, profile.verified_by_id)
    client.force_login(owner)
    response = client.post(
        f"/api/v1/finance/{org.pk}/payout-profile/",
        data=json.dumps({"method": "bank", "account_holder": "API MUTATION", "destination_hint": "fake", "submit": False}),
        content_type="application/json",
    )
    assert response.status_code == 400
    profile.refresh_from_db()
    assert (profile.status, profile.account_holder, profile.iban_encrypted, profile.verified_at, profile.verified_by_id) == before


@pytest.mark.django_db
def test_designer_finance_real_bank_fields_blank_secret_and_role_aware_controls(client):
    owner = User.objects.create_user(username="round3-web-owner", password="password123")
    org, _ = _designer(owner)
    plaintext = "EG00ROUNDTHREE00001234"
    profile = _bank_profile(org, owner, plaintext, submit=False)
    original_ciphertext = profile.iban_encrypted
    client.force_login(owner)

    response = client.get(reverse("designer-finance") + f"?org={org.pk}")
    body = response.content.decode()
    assert response.status_code == 200
    for field in ("account_holder", "bank_name", "iban", "country", "payout_currency"):
        assert f'name="{field}"' in body
    assert plaintext not in body
    assert "IBAN •••• 1234" in body
    assert 'name="iban" value=""' in body
    assert "Masked payout destination" not in body

    saved = client.post(
        reverse("designer-finance") + f"?org={org.pk}",
        {
            "action": "payout_profile", "method": "bank", "account_holder": "Round Three Owner",
            "bank_name": "Round Three Web Bank", "iban": "", "country": "EG", "payout_currency": "EGP",
        },
        follow=True,
    )
    assert saved.status_code == 200
    profile.refresh_from_db()
    assert profile.iban_encrypted == original_ciphertext
    assert plaintext not in saved.content.decode()

    profile.status = PayoutProfile.Status.PENDING
    profile.save(update_fields=["status"])
    profile = _verify_profile(profile)
    verified = client.get(reverse("designer-finance") + f"?org={org.pk}")
    verified_body = verified.content.decode()
    assert "read-only" in verified_body
    assert 'name="iban"' not in verified_body

    accountant = User.objects.create_user(username="round3-accountant", password="password123")
    Membership.objects.create(organization=org, user=accountant, role=Membership.Role.ACCOUNTANT)
    client.force_login(accountant)
    read_only = client.get(reverse("designer-finance") + f"?org={org.pk}")
    assert read_only.status_code == 200
    assert 'name="action" value="payout_profile"' not in read_only.content.decode()
    before_holder = profile.account_holder
    crafted = client.post(reverse("designer-finance") + f"?org={org.pk}", {"action": "payout_profile", "method": "manual", "account_holder": "NO"}, follow=True)
    assert crafted.status_code == 200
    profile.refresh_from_db()
    assert profile.account_holder == before_holder


@pytest.mark.django_db
def test_designer_notifications_reuse_canonical_records_and_preserve_org(client):
    owner = User.objects.create_user(username="round3-notify-owner", password="password123", email="notify@round3.test")
    org, _ = _designer(owner)
    notification = Notification.objects.create(
        recipient=owner,
        type="round3",
        title_en="Round 3 canonical notification",
        title_ar="إشعار الجولة الثالثة",
        body_en="Canonical notification data",
        body_ar="بيانات الإشعار الأصلية",
        destination="/designer/",
    )
    client.force_login(owner)
    generic = client.get(reverse("notifications"))
    designer = client.get(reverse("designer-notifications") + f"?org={org.pk}")
    assert generic.status_code == designer.status_code == 200
    assert "Round 3 canonical notification" in generic.content.decode()
    designer_body = designer.content.decode()
    assert "Round 3 canonical notification" in designer_body
    assert "designer-workspace" in designer_body
    assert designer_body.count('aria-current="page"') == 1

    marked = client.post(reverse("designer-notifications") + f"?org={org.pk}", {"action": "mark_all_read"}, follow=True)
    assert marked.status_code == 200
    notification.refresh_from_db()
    assert notification.is_read is True
    assert client.session["designer_organization_id"] == org.pk

    prefs = client.post(
        reverse("designer-notifications") + f"?org={org.pk}",
        {"action": "preferences", "email_enabled": "on", "phone_e164": ""},
        follow=True,
    )
    assert prefs.status_code == 200
    assert NotificationPreference.objects.get(user=owner).email_enabled is True


@pytest.mark.django_db
def test_designer_navigation_store_and_overview_round3_behavior(client, v2_3_reference_rows):
    owner = User.objects.create_user(username="round3-nav-owner", password="password123")
    org, _ = _designer(owner)
    Storefront.objects.create(
        organization=org,
        slug="round3-store",
        name_en="Round 3 Store",
        name_ar="متجر الجولة الثالثة",
        about_en="Read first",
        status=Storefront.Status.DRAFT,
    )
    client.force_login(owner)

    expected_sections = {
        "designer": "overview", "designer-profile": "profile", "designer-public-profile": "public-profile",
        "designer-public-inquiries": "public-inquiries", "designer-public-inquiry-detail": "public-inquiries",
        "designer-team": "team", "designer-design-list": "designs", "designer-design-detail": "designs",
        "designer-design-technical-v2-4": "designs", "designer-artworks": "artwork",
        "designer-artwork-detail": "artwork", "designer-artwork-technical-v2-4": "artwork",
        "designer-products": "products", "designer-product-detail": "products",
        "designer-ready-product-composer-v2-4": "products", "designer-ready-product-composer-detail-v2-4": "products",
        "designer-rfqs": "rfqs", "designer-rfq-detail": "rfqs", "designer-store": "store",
        "designer-store-product": "store", "designer-fulfillment": "fulfillment", "designer-finance": "finance",
        "designer-subscription": "subscription", "designer-notifications": "notifications",
    }
    assert DESIGNER_ROUTE_SECTIONS == expected_sections

    overview = client.get(reverse("designer") + f"?org={org.pk}")
    overview_body = overview.content.decode()
    assert overview_body.count('aria-current="page"') == 1
    assert ">New Garment Design</a>" not in overview_body
    assert ">New Artwork</a>" not in overview_body
    assert client.get(reverse("designer-design-list") + f"?org={org.pk}").status_code == 200
    assert client.get(reverse("designer-artworks") + f"?org={org.pk}").status_code == 200

    store = client.get(reverse("designer-store") + f"?org={org.pk}")
    store_body = store.content.decode()
    assert store_body.count('aria-current="page"') == 1
    assert '<details class="round3-store-edit">' in store_body
    assert '<details class="round3-store-edit" open' not in store_body
    assert "Round 3 Store" in store_body
    updated = client.post(
        reverse("designer-store") + f"?org={org.pk}",
        {"action": "update", "name_en": "Round 3 Store Updated", "name_ar": "", "about_en": "Updated", "about_ar": ""},
        follow=True,
    )
    assert updated.status_code == 200
    storefront = Storefront.objects.get(organization=org)
    assert storefront.name_en == "Round 3 Store Updated"
    assert storefront.status == Storefront.Status.DRAFT
    assert '<details class="round3-store-edit" open' not in updated.content.decode()

    for route in ("designer-finance", "designer-subscription", "designer-notifications"):
        response = client.get(reverse(route) + f"?org={org.pk}")
        assert response.status_code == 200
        assert response.content.decode().count('aria-current="page"') == 1


@pytest.mark.django_db
def test_subscription_usage_productization_preserves_starter_and_payment_window_authority(client, v2_3_reference_rows):
    owner = User.objects.create_user(username="round3-sub-owner", password="password123")
    org, application = _designer(owner)
    client.force_login(owner)
    summary = entitlement_summary(org)
    assert summary["plan_code"] == "designer_starter"
    assert summary["subscription"].next_billing_at is None

    starter_page = client.get(reverse("designer-subscription") + f"?org={org.pk}")
    starter_body = starter_page.content.decode()
    assert starter_page.status_code == 200
    assert "Actual entitlement" in starter_body
    assert "Designer Starter" in starter_body
    assert "Designer Pro" in starter_body
    assert "No paid renewal currently due" in starter_body

    before_plan = OrganizationSubscription.objects.get(organization=org).current_plan_id
    upgrade = client.post(reverse("designer-subscription") + f"?org={org.pk}", {"action": "upgrade"}, follow=True)
    assert upgrade.status_code == 200
    subscription = OrganizationSubscription.objects.get(organization=org)
    assert subscription.current_plan_id == before_plan
    assert subscription.current_plan.code == "designer_starter"
    assert "confirmed billing evidence" in upgrade.content.decode()

    pro = get_effective_plan(DESIGNER_PRO)
    OnboardingPlanSelection.objects.create(
        application=application,
        selected_plan_policy=pro,
        plan_code=pro.code,
        plan_version=pro.version,
        policy_snapshot=plan_snapshot(pro),
        price_snapshot=price_snapshot(pro),
        selected_by=owner,
        payment_due_at=timezone.now() + timedelta(days=27),
    )
    payment = client.get(reverse("designer-subscription") + f"?org={org.pk}")
    payment_body = payment.content.decode()
    assert "Requested plan" in payment_body
    assert "payment window, not a Pro trial" in payment_body
    assert "Actual entitlement" in payment_body
    subscription.refresh_from_db()
    assert subscription.current_plan.code == "designer_starter"
