from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from dateutil.relativedelta import relativedelta
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from apps.accounts.forms import AccountPreferencesForm
from apps.artwork.models import Artwork, ArtworkVersion, DesignedProduct
from apps.checkout.models import Cart, CartItem, CheckoutSession, CustomerPurchase
from apps.design.models import GarmentDesign, GarmentDesignVersion
from apps.notifications.models import Notification
from apps.organizations.forms import DesignerOnboardingForm
from apps.organizations.models import DesignerProfile, Membership, OnboardingApplication, Organization
from apps.organizations.services import (
    create_designer_onboarding,
    create_reapplication_from_rejected,
    review_application,
    submit_application,
)
from apps.storefront.models import ProductVariant, StoreProduct, Storefront, StudioProject
from apps.subscriptions.models import (
    OnboardingPlanSelection,
    OrganizationSubscription,
    SubscriptionBillingConfirmation,
    SubscriptionPlanPolicy,
)
from apps.subscriptions.services import (
    _create_period,
    _period_end,
    activate_paid_pro,
    cancel_subscription,
    confirm_subscription_billing,
    downgrade_to_starter,
    ensure_subscription_for_organization,
    get_effective_plan,
    grant_manufacturer_trial_exception,
    onboarding_commercial_summary,
    plan_snapshot,
    price_snapshot,
    renew_paid_subscription,
    set_onboarding_plan_selection,
)
from apps.subscriptions.views import _commercial_context
from .v2_3_support import v2_3_reference_rows

User = get_user_model()
ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.usefixtures("v2_3_reference_rows")


def _user(name, *, staff=False, superuser=False):
    return User.objects.create_user(
        username=name,
        email=f"{name}@example.test",
        password="password12345",
        is_staff=staff or superuser,
        is_superuser=superuser,
    )


def _application(name, kind=Organization.Kind.DESIGNER):
    owner = _user(f"{name}-owner")
    org = Organization.objects.create(
        kind=kind,
        display_name=f"{name} business",
        email=f"{name}@business.test",
        created_by=owner,
        verification_status=Organization.VerificationStatus.DRAFT,
    )
    Membership.objects.create(organization=org, user=owner, role=Membership.Role.OWNER)
    app = OnboardingApplication.objects.create(organization=org)
    return owner, org, app


def _mark_submitted(app):
    app.status = OnboardingApplication.Status.SUBMITTED
    app.submitted_at = timezone.now()
    app.save(update_fields=["status", "submitted_at", "updated_at"])
    app.organization.verification_status = Organization.VerificationStatus.PENDING
    app.organization.save(update_fields=["verification_status", "updated_at"])
    return app


def _select(app, owner, code):
    policy = get_effective_plan(code)
    return set_onboarding_plan_selection(
        application=app,
        actor=owner,
        selected_plan_policy=policy,
    )


def _approve_selected(name, kind, code):
    owner, org, app = _application(name, kind)
    selection = _select(app, owner, code)
    _mark_submitted(app)
    reviewer = _user(f"{name}-reviewer", staff=True)
    review_application(
        application=app,
        reviewer=reviewer,
        decision=OnboardingApplication.Status.APPROVED,
    )
    app.refresh_from_db()
    org.refresh_from_db()
    selection.refresh_from_db()
    return owner, reviewer, org, app, selection, OrganizationSubscription.objects.get(organization=org)


def _new_designer_pro(*, version, price, effective_from):
    return SubscriptionPlanPolicy.objects.create(
        code="designer_pro",
        version=version,
        public_name_ar=f"المصمم — Pro v{version}",
        public_name_en=f"Designer Pro v{version}",
        audience=SubscriptionPlanPolicy.Audience.DESIGNER,
        monthly_price=Decimal(str(price)),
        currency="EGP",
        tax_inclusive=True,
        trial_months=0,
        designer_active_design_limit=12,
        designer_active_artwork_limit=6,
        manufacturer_monthly_offer_limit=None,
        team_subaccount_limit=4,
        active=True,
        effective_from=effective_from,
    )


def _store_fixture(customer):
    owner = _user(f"store-owner-{customer.pk}")
    org = Organization.objects.create(
        kind=Organization.Kind.DESIGNER,
        display_name=f"Store {customer.pk}",
        email=f"store-{customer.pk}@example.test",
        created_by=owner,
        verification_status=Organization.VerificationStatus.ACTIVE,
    )
    design = GarmentDesign.objects.create(
        organization=org,
        title="Dashboard design",
        status=GarmentDesign.Status.APPROVED,
        created_by=owner,
    )
    garment_version = GarmentDesignVersion.objects.create(
        design=design,
        version_number=1,
        status=GarmentDesignVersion.Status.APPROVED,
        created_by=owner,
    )
    artwork = Artwork.objects.create(
        organization=org,
        title="Dashboard artwork",
        status=Artwork.Status.APPROVED,
        created_by=owner,
    )
    artwork_version = ArtworkVersion.objects.create(
        artwork=artwork,
        version_number=1,
        status=ArtworkVersion.Status.APPROVED,
        created_by=owner,
    )
    designed = DesignedProduct.objects.create(
        organization=org,
        garment_version=garment_version,
        artwork_version=artwork_version,
        title="Dashboard designed product",
        status=DesignedProduct.Status.PUBLISHED,
        created_by=owner,
    )
    storefront = Storefront.objects.create(
        organization=org,
        slug=f"dashboard-{customer.pk}",
        status=Storefront.Status.PUBLISHED,
        name_en="Dashboard Store",
    )
    product = StoreProduct.objects.create(
        storefront=storefront,
        designed_product=designed,
        slug="dashboard-product",
        status=StoreProduct.Status.PUBLISHED,
        title_en="Dashboard Product",
        base_price=Decimal("100.00"),
        currency="EGP",
        customization_enabled=True,
    )
    variant = ProductVariant.objects.create(product=product, sku=f"DASH-{customer.pk}")
    return product, variant


@pytest.mark.django_db
def test_customer_hub_has_required_actions_and_unsliced_metrics_over_four(client):
    customer = _user("consolidated-dashboard")
    product, variant = _store_fixture(customer)
    cart = Cart.objects.create(customer=customer, status=Cart.Status.ACTIVE)
    for _ in range(5):
        CartItem.objects.create(
            cart=cart,
            kind=CartItem.Kind.PLAIN,
            store_product=product,
            variant=variant,
        )
        StudioProject.objects.create(customer=customer, product=product)
    for index in range(5):
        purchase_cart = Cart.objects.create(customer=customer, status=Cart.Status.CONVERTED)
        checkout = CheckoutSession.objects.create(
            customer=customer,
            cart=purchase_cart,
            status=CheckoutSession.Status.PLACED,
            total=Decimal("100.00"),
            subtotal=Decimal("100.00"),
            currency="EGP",
        )
        CustomerPurchase.objects.create(
            checkout=checkout,
            customer=customer,
            payment_method=CustomerPurchase.PaymentMethod.COD,
            subtotal=Decimal("100.00"),
            total=Decimal("100.00"),
            currency="EGP",
        )
        Notification.objects.create(
            recipient=customer,
            type=f"dashboard-{index}",
            title_en="Unread",
            title_ar="غير مقروء",
        )
    client.force_login(customer)
    response = client.get("/app/?lang=en")
    assert response.status_code == 200
    assert response.context["cart_item_count"] == 5
    assert response.context["active_studio_project_count"] == 5
    assert response.context["purchase_count"] == 5
    assert response.context["unread_notifications"] == 5
    assert len(response.context["studio_projects"]) == 4
    assert len(response.context["recent_purchases"]) == 4
    body = response.content.decode()
    for label in ("Shop now", "Open Studio", "My orders", "Explore artwork", "Notifications", "Account preferences", "Start your Business"):
        assert label in body
    assert "Recent purchases" in body
    assert "Customization projects" in body
    assert ">DISCOVER<" not in body
    assert ">ORIGINAL WORK<" not in body


def test_customer_hub_source_has_no_product_or_artwork_discovery_queries():
    source = (ROOT / "apps/accounts/views.py").read_text(encoding="utf-8")
    template = (ROOT / "templates/accounts/app_home.html").read_text(encoding="utf-8")
    assert "StoreProduct" not in source
    assert "Artwork" not in source
    assert "featured_products" not in source
    assert "featured_artworks" not in source
    assert "active_studio_qs.count()" in source
    assert "purchases_qs.count()" in source
    assert "active_cart.items.count()" in source
    assert "[:4]" in source
    assert "DISCOVER" not in template
    assert "ORIGINAL WORK" not in template


@pytest.mark.django_db
def test_account_preferences_names_email_security_language_direction_and_theme(client):
    user = _user("prefs-owner")
    duplicate = _user("prefs-duplicate")
    duplicate.email = "taken@example.test"
    duplicate.save(update_fields=["email"])

    form = AccountPreferencesForm(
        {
            "first_name": "  Wael  ",
            "last_name": "  Owner  ",
            "email": user.email.upper(),
            "language": "en",
            "theme": "light",
            "current_password": "",
        },
        user=user,
    )
    assert form.is_valid(), form.errors
    form.save()
    user.refresh_from_db()
    assert user.first_name == "Wael"
    assert user.last_name == "Owner"
    assert user.email == user.email.lower()

    duplicate_form = AccountPreferencesForm(
        {"email": "TAKEN@EXAMPLE.TEST", "language": "en", "theme": "light"},
        user=user,
    )
    assert not duplicate_form.is_valid()
    assert "email" in duplicate_form.errors

    missing_password = AccountPreferencesForm(
        {"email": "new@example.test", "language": "en", "theme": "light"},
        user=user,
    )
    assert not missing_password.is_valid()
    assert "current_password" in missing_password.errors
    wrong_password = AccountPreferencesForm(
        {"email": "new@example.test", "language": "en", "theme": "light", "current_password": "wrong"},
        user=user,
    )
    assert not wrong_password.is_valid()

    client.force_login(user)
    changed = client.post(
        "/app/settings/preferences/",
        {
            "first_name": "Wael",
            "last_name": "Owner",
            "email": "new@example.test",
            "language": "ar",
            "theme": "dark",
            "current_password": "password12345",
        },
        follow=True,
    )
    assert changed.status_code == 200
    user.refresh_from_db()
    assert user.email == "new@example.test"
    assert user.language_preference == "ar"
    assert user.theme_preference == "dark"
    assert 'lang="ar" dir="rtl"' in changed.content.decode()

    english = client.post(
        "/app/settings/preferences/",
        {
            "first_name": "Wael",
            "last_name": "Owner",
            "email": "new@example.test",
            "language": "en",
            "theme": "system",
            "current_password": "",
        },
        follow=True,
    )
    user.refresh_from_db()
    assert user.theme_preference == "system"
    assert 'lang="en" dir="ltr"' in english.content.decode()
    assert User._meta.get_field("email").unique is False
    urls = (ROOT / "config/urls.py").read_text(encoding="utf-8")
    assert "auth_views.PasswordChangeView.as_view" in urls


@pytest.mark.django_db
@pytest.mark.parametrize(
    "status,verification,label",
    [
        (OnboardingApplication.Status.DRAFT, Organization.VerificationStatus.DRAFT, "Continue your Business"),
        (OnboardingApplication.Status.SUBMITTED, Organization.VerificationStatus.PENDING, "Business under review"),
        (OnboardingApplication.Status.REVISION_REQUIRED, Organization.VerificationStatus.DRAFT, "Update your Business application"),
        (OnboardingApplication.Status.APPROVED, Organization.VerificationStatus.ACTIVE, "Manage your Business"),
        (OnboardingApplication.Status.REJECTED, Organization.VerificationStatus.REJECTED, "Reapply for Business"),
    ],
)
def test_customer_business_cta_is_state_aware(client, status, verification, label):
    owner, org, app = _application(f"cta-{status}")
    app.status = status
    app.save(update_fields=["status", "updated_at"])
    org.verification_status = verification
    org.save(update_fields=["verification_status", "updated_at"])
    client.force_login(owner)
    body = client.get("/app/?lang=en").content.decode()
    assert label in body
    if status == OnboardingApplication.Status.APPROVED:
        assert "Start your Business" not in body


@pytest.mark.django_db
def test_business_start_role_cards_show_exact_application_lifecycle_actions(client):
    cases = [
        (OnboardingApplication.Status.DRAFT, "Continue Designer application"),
        (OnboardingApplication.Status.SUBMITTED, "Designer application under review"),
        (OnboardingApplication.Status.REVISION_REQUIRED, "Update Designer application"),
        (OnboardingApplication.Status.APPROVED, "Open Designer workspace"),
        (OnboardingApplication.Status.REJECTED, "Reapply as Designer"),
    ]
    for index, (status, expected) in enumerate(cases):
        owner, org, app = _application(f"business-card-{index}")
        app.status = status
        app.save(update_fields=["status", "updated_at"])
        client.force_login(owner)
        response = client.get("/app/business/start/?lang=en")
        assert response.status_code == 200
        assert expected in response.content.decode()
        client.logout()


@pytest.mark.django_db
def test_plan_selection_restricts_audience_stale_and_arbitrary_ids_and_uses_current_policy():
    owner, org, app = _application("plan-security")
    designer_starter = get_effective_plan("designer_starter")
    designer_pro_v1 = get_effective_plan("designer_pro")
    manufacturer_pro = get_effective_plan("manufacturer_pro")
    with pytest.raises(ValidationError):
        set_onboarding_plan_selection(application=app, actor=owner, selected_plan_policy=manufacturer_pro)

    stale = _new_designer_pro(
        version=99,
        price="999.00",
        effective_from=timezone.localdate() + timedelta(days=30),
    )
    stale.active = False
    stale.save(update_fields=["active"])
    with pytest.raises(ValidationError):
        set_onboarding_plan_selection(application=app, actor=owner, selected_plan_policy=stale)

    current = _new_designer_pro(
        version=2,
        price="375.00",
        effective_from=timezone.localdate(),
    )
    form = DesignerOnboardingForm()
    choice_ids = {value for value, _ in form.fields["plan_policy_id"].choices}
    assert str(designer_starter.pk) in choice_ids
    assert str(current.pk) in choice_ids
    assert str(designer_pro_v1.pk) not in choice_ids
    invalid_form = DesignerOnboardingForm({"accept_terms": "on", "plan_policy_id": "999999"})
    assert not invalid_form.is_valid()
    assert "plan_policy_id" in invalid_form.errors


@pytest.mark.django_db
def test_onboarding_selection_is_durable_editable_before_submission_and_frozen_after():
    owner, org, app = _application("selection-persistence")
    starter = _select(app, owner, "designer_starter")
    saved_id = starter.pk
    starter.refresh_from_db()
    assert starter.pk == saved_id
    assert starter.selected_plan_policy_id == get_effective_plan("designer_starter").pk
    assert starter.plan_code == "designer_starter"
    assert starter.plan_version == starter.selected_plan_policy.version
    assert starter.policy_snapshot["plan_policy_id"] == starter.selected_plan_policy_id
    assert starter.price_snapshot["monthly_price"] == "0.00"

    pro = _select(app, owner, "designer_pro")
    assert pro.pk == saved_id
    assert pro.plan_code == "designer_pro"
    app.status = OnboardingApplication.Status.REVISION_REQUIRED
    app.save(update_fields=["status", "updated_at"])
    changed = _select(app, owner, "designer_starter")
    assert changed.pk == saved_id and changed.plan_code == "designer_starter"
    _mark_submitted(app)
    with pytest.raises(ValidationError):
        _select(app, owner, "designer_pro")
    frozen = OnboardingPlanSelection.objects.get(pk=saved_id)
    assert frozen.plan_code == "designer_starter"


@pytest.mark.django_db
def test_rejected_reapplication_preserves_old_selection_and_creates_new_history():
    owner = _user("reapply-selection-owner")
    pro = get_effective_plan("designer_pro")
    application = create_designer_onboarding(
        user=owner,
        organization_data={"display_name": "Old Studio", "email": "old-studio@example.test"},
        profile_data={"studio_name": "Old Studio", "terms_accepted": True, "plan_policy_id": str(pro.pk)},
    )
    old_selection = application.plan_selection
    submit_application(application=application, actor=owner)
    reviewer = _user("reapply-selection-reviewer", staff=True)
    review_application(
        application=application,
        reviewer=reviewer,
        decision=OnboardingApplication.Status.REJECTED,
    )
    new_application = create_reapplication_from_rejected(application=application, actor=owner)
    old_selection.refresh_from_db()
    application.refresh_from_db()
    assert application.status == OnboardingApplication.Status.REJECTED
    assert old_selection.plan_code == "designer_pro"
    assert old_selection.selected_plan_policy_id == pro.pk
    assert new_application.pk != application.pk
    assert new_application.organization_id != application.organization_id
    assert new_application.status == OnboardingApplication.Status.DRAFT
    assert not OnboardingPlanSelection.objects.filter(application=new_application).exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "kind,starter_code",
    [
        (Organization.Kind.DESIGNER, "designer_starter"),
        (Organization.Kind.MANUFACTURER, "manufacturer_starter"),
    ],
)
def test_free_approval_activates_starter_without_payment_deadline_or_new_trial(kind, starter_code):
    owner, reviewer, org, app, selection, sub = _approve_selected(f"free-{kind}", kind, starter_code)
    assert org.verification_status == Organization.VerificationStatus.ACTIVE
    assert sub.current_plan.code == starter_code
    assert sub.status == OrganizationSubscription.Status.ACTIVE
    assert selection.payment_due_at is None
    assert sub.trial_started_at is None
    assert sub.trial_ends_at is None
    assert sub.trial_consumed is False


@pytest.mark.django_db
@pytest.mark.parametrize(
    "kind,pro_code,starter_code",
    [
        (Organization.Kind.DESIGNER, "designer_pro", "designer_starter"),
        (Organization.Kind.MANUFACTURER, "manufacturer_pro", "manufacturer_starter"),
    ],
)
def test_paid_approval_keeps_starter_and_opens_exact_27_day_payment_window(kind, pro_code, starter_code):
    owner, reviewer, org, app, selection, sub = _approve_selected(f"paid-{kind}", kind, pro_code)
    assert org.verification_status == Organization.VerificationStatus.ACTIVE
    assert sub.current_plan.code == starter_code
    assert sub.status == OrganizationSubscription.Status.ACTIVE
    assert sub.trial_started_at is None
    assert sub.trial_ends_at is None
    assert selection.plan_code == pro_code
    assert selection.payment_due_at == app.reviewed_at + timedelta(days=27)
    assert onboarding_commercial_summary(org)["payment_window_state"] == "active"


@pytest.mark.django_db
def test_selected_v1_price_remains_payable_during_window_then_renewal_uses_current_policy():
    owner, reviewer, org, app, selection, sub = _approve_selected(
        "version-drift",
        Organization.Kind.DESIGNER,
        "designer_pro",
    )
    selected_policy = selection.selected_plan_policy
    selected_price = Decimal(selection.price_snapshot["monthly_price"])
    newer = _new_designer_pro(
        version=2,
        price="375.00",
        effective_from=timezone.localdate() + timedelta(days=1),
    )
    ops = _user("version-drift-ops", superuser=True)
    within_window = app.reviewed_at + timedelta(days=2)
    confirmation = confirm_subscription_billing(
        organization=org,
        actor=ops,
        plan_code="designer_pro",
        amount=selected_price,
        currency="EGP",
        provider="verified_test_provider",
        provider_reference="ONBOARD-V1",
        idempotency_key="onboard-v1",
        now=within_window,
    )
    assert confirmation.plan_policy_id == selected_policy.pk
    assert confirmation.plan_version == selection.plan_version
    activated = activate_paid_pro(
        organization=org,
        actor=owner,
        billing_confirmation=confirmation,
        now=within_window,
    )
    assert activated.current_plan_id == selected_policy.pk
    assert activated.price_snapshot == selection.price_snapshot

    after_window = selection.payment_due_at + timedelta(days=1)
    with pytest.raises(ValidationError):
        confirm_subscription_billing(
            organization=org,
            actor=ops,
            plan_code="designer_pro",
            amount=selected_price,
            currency="EGP",
            provider="verified_test_provider",
            provider_reference="EXPIRED-OLD-PRICE",
            idempotency_key="expired-old-price",
            now=after_window,
        )

    renewal_at = activated.current_period_end
    renewal_confirmation = confirm_subscription_billing(
        organization=org,
        actor=ops,
        plan_code="designer_pro",
        amount=Decimal("375.00"),
        currency="EGP",
        provider="verified_test_provider",
        provider_reference="RENEW-V2",
        idempotency_key="renew-v2",
        now=renewal_at,
    )
    renewed = renew_paid_subscription(
        subscription=activated,
        actor=ops,
        billing_confirmation=renewal_confirmation,
        now=renewal_at,
    )
    assert renewed.current_plan_id == newer.pk
    assert renewed.price_snapshot["monthly_price"] == "375.00"


@pytest.mark.django_db
def test_onboarding_paid_agreement_is_one_time_idempotent_and_revocation_replacement_safe():
    owner, reviewer, org, app, selection, sub = _approve_selected(
        "one-time",
        Organization.Kind.DESIGNER,
        "designer_pro",
    )
    ops = _user("one-time-ops", superuser=True)
    amount = Decimal(selection.price_snapshot["monthly_price"])
    when = app.reviewed_at + timedelta(days=1)
    first = confirm_subscription_billing(
        organization=org,
        actor=ops,
        plan_code=selection.plan_code,
        amount=amount,
        currency="EGP",
        provider="verified_test_provider",
        provider_reference="ONBOARD-FIRST",
        idempotency_key="onboard-first",
        now=when,
    )
    retry = confirm_subscription_billing(
        organization=org,
        actor=ops,
        plan_code=selection.plan_code,
        amount=amount,
        currency="EGP",
        provider="verified_test_provider",
        provider_reference="ONBOARD-FIRST",
        idempotency_key="onboard-first",
        now=when,
    )
    assert retry.pk == first.pk
    with pytest.raises(ValidationError):
        confirm_subscription_billing(
            organization=org,
            actor=ops,
            plan_code=selection.plan_code,
            amount=amount,
            currency="EGP",
            provider="verified_test_provider",
            provider_reference="ONBOARD-SECOND",
            idempotency_key="onboard-second",
            now=when,
        )

    first.status = SubscriptionBillingConfirmation.Status.REVOKED
    first.save(update_fields=["status"])
    with pytest.raises(ValidationError):
        activate_paid_pro(organization=org, actor=owner, billing_confirmation=first, now=when)
    replacement = confirm_subscription_billing(
        organization=org,
        actor=ops,
        plan_code=selection.plan_code,
        amount=amount,
        currency="EGP",
        provider="verified_test_provider",
        provider_reference="ONBOARD-REPLACEMENT",
        idempotency_key="onboard-replacement",
        now=when + timedelta(hours=1),
    )
    activated = activate_paid_pro(
        organization=org,
        actor=owner,
        billing_confirmation=replacement,
        now=when + timedelta(hours=1),
    )
    replacement.refresh_from_db()
    assert replacement.consumed_period_id is not None

    with pytest.raises(ValidationError):
        confirm_subscription_billing(
            organization=org,
            actor=ops,
            plan_code=selection.plan_code,
            amount=amount,
            currency="EGP",
            provider="verified_test_provider",
            provider_reference="ONBOARD-THIRD",
            idempotency_key="onboard-third",
            now=when + timedelta(days=2),
        )

    downgraded = downgrade_to_starter(subscription=activated, actor=owner, now=when + timedelta(days=2))
    replay = activate_paid_pro(
        organization=org,
        actor=owner,
        billing_confirmation=replacement,
        now=when + timedelta(days=3),
    )
    replay.refresh_from_db()
    assert replay.current_plan.code == "designer_starter"
    assert replay.status == OrganizationSubscription.Status.DOWNGRADED
    cancelled = cancel_subscription(subscription=downgraded, actor=owner)
    replay_after_cancel = activate_paid_pro(
        organization=org,
        actor=owner,
        billing_confirmation=replacement,
        now=when + timedelta(days=4),
    )
    replay_after_cancel.refresh_from_db()
    assert replay_after_cancel.current_plan.code == "designer_starter"
    assert replay_after_cancel.status == OrganizationSubscription.Status.CANCELLED
    with pytest.raises(ValidationError):
        confirm_subscription_billing(
            organization=org,
            actor=ops,
            plan_code=selection.plan_code,
            amount=amount,
            currency="EGP",
            provider="verified_test_provider",
            provider_reference="AFTER-CANCEL",
            idempotency_key="after-cancel",
            now=when + timedelta(days=4),
        )


def _historical_trial(name, *, expired=False, with_selection=False):
    owner, org, app = _application(name, Organization.Kind.MANUFACTURER)
    if with_selection:
        _select(app, owner, "manufacturer_pro")
    org.verification_status = Organization.VerificationStatus.ACTIVE
    org.save(update_fields=["verification_status", "updated_at"])
    now = timezone.now()
    started = now - (timedelta(days=220) if expired else timedelta(days=1))
    pro = get_effective_plan("manufacturer_pro", at=now)
    trial_end = started + relativedelta(months=6)
    sub = OrganizationSubscription.objects.create(
        organization=org,
        current_plan=pro,
        status=OrganizationSubscription.Status.TRIALING,
        started_at=started,
        trial_started_at=started,
        trial_ends_at=trial_end,
        trial_consumed=True,
        current_period_start=started,
        current_period_end=_period_end(started, hard_end=trial_end),
        next_billing_at=trial_end,
        policy_snapshot=plan_snapshot(pro),
        price_snapshot=price_snapshot(pro),
    )
    _create_period(sub)
    return owner, org, app, sub


@pytest.mark.django_db
def test_trial_exception_only_extends_active_historical_trial_and_never_starts_or_restarts_one():
    superuser = _user("trial-guard-super", superuser=True)
    owner, org, app, historical = _historical_trial("historical-trial")
    original_start = historical.trial_started_at
    original_plan = historical.current_plan_id
    original_end = historical.trial_ends_at
    extended = grant_manufacturer_trial_exception(
        subscription=historical,
        actor=superuser,
        reason="Historical support exception",
    )
    assert extended.status == OrganizationSubscription.Status.TRIALING
    assert extended.current_plan_id == original_plan
    assert extended.trial_started_at == original_start
    assert extended.trial_ends_at == original_end + relativedelta(months=6)

    starter_owner, starter_org, _ = _application("starter-trial-guard", Organization.Kind.MANUFACTURER)
    starter_org.verification_status = Organization.VerificationStatus.ACTIVE
    starter_org.save(update_fields=["verification_status", "updated_at"])
    starter = ensure_subscription_for_organization(starter_org)
    with pytest.raises(ValidationError):
        grant_manufacturer_trial_exception(subscription=starter, actor=superuser, reason="No backdoor")

    _, _, _, expired = _historical_trial("expired-trial", expired=True)
    with pytest.raises(ValidationError):
        grant_manufacturer_trial_exception(subscription=expired, actor=superuser, reason="No restart")

    _, _, _, post_change = _historical_trial("post-change-trial", with_selection=True)
    with pytest.raises(ValidationError):
        grant_manufacturer_trial_exception(subscription=post_change, actor=superuser, reason="No new onboarding trial")


@pytest.mark.django_db
def test_subscription_history_context_is_safe_and_team_member_cannot_activate_paid_entitlement():
    owner, reviewer, org, app, selection, sub = _approve_selected(
        "history-security",
        Organization.Kind.DESIGNER,
        "designer_pro",
    )
    ops = _user("history-security-ops", superuser=True)
    evidence = confirm_subscription_billing(
        organization=org,
        actor=ops,
        plan_code=selection.plan_code,
        amount=Decimal(selection.price_snapshot["monthly_price"]),
        currency="EGP",
        provider="secret-provider",
        provider_reference="SECRET-REFERENCE",
        idempotency_key="SECRET-IDEMPOTENCY",
    )
    evidence.status = SubscriptionBillingConfirmation.Status.REVOKED
    evidence.save(update_fields=["status"])
    context = _commercial_context(org)
    row = context["billing_history"][0]
    assert row["status"] == SubscriptionBillingConfirmation.Status.REVOKED
    assert set(row) == {"confirmed_at", "plan_code", "plan_version", "amount", "currency", "status", "consumed"}
    serialized = repr(context)
    assert "SECRET-REFERENCE" not in serialized
    assert "SECRET-IDEMPOTENCY" not in serialized
    assert "secret-provider" not in serialized

    active = confirm_subscription_billing(
        organization=org,
        actor=ops,
        plan_code=selection.plan_code,
        amount=Decimal(selection.price_snapshot["monthly_price"]),
        currency="EGP",
        provider="verified_test_provider",
        provider_reference="SAFE-ACTIVE",
        idempotency_key="safe-active",
    )
    team_user = _user("history-security-team")
    Membership.objects.create(organization=org, user=team_user, role=Membership.Role.DESIGNER)
    with pytest.raises(PermissionDenied):
        activate_paid_pro(organization=org, actor=team_user, billing_confirmation=active)

    views_source = (ROOT / "apps/subscriptions/views.py").read_text(encoding="utf-8")
    assert 'if action == "upgrade":' in views_source
    assert "browser/client requests cannot activate paid entitlement" in views_source
    designer_template = (ROOT / "templates/designer/subscription.html").read_text(encoding="utf-8")
    manufacturer_template = (ROOT / "templates/manufacturer/subscription.html").read_text(encoding="utf-8")
    assert "Actual entitlement" in designer_template
    assert "Requested plan" in designer_template
    assert "Payment due" in designer_template
    assert "payment window, not a Pro trial" in designer_template
    assert "Historical trial started" in manufacturer_template
    assert "Historical trial ends" in manufacturer_template


def test_onboarding_migration_is_additive_and_has_no_historical_backfill():
    migration = (ROOT / "apps/subscriptions/migrations/0004_onboarding_plan_selection.py").read_text(encoding="utf-8")
    assert '("subscriptions", "0003_billing_evidence_corrections")' in migration
    assert "migrations.CreateModel" in migration
    assert 'name="OnboardingPlanSelection"' in migration
    assert "migrations.RunPython" not in migration
    assert "migrations.DeleteModel" not in migration
    assert "migrations.RemoveField" not in migration
    assert "migrations.AlterField" not in migration
