from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal

import pytest
from dateutil.relativedelta import relativedelta
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections
from django.utils import timezone

from apps.artwork.models import Artwork, ArtworkVersion, DesignedProduct
from apps.audit.models import AuditEvent
from apps.checkout.models import CustomerOrder, OrderItem
from apps.design.models import GarmentDesign, GarmentDesignVersion
from apps.manufacturer_marketplace.models import ManufacturerQuote, RFQ, RFQInvitation
from apps.operations.models import ProductionJob
from apps.organizations.models import Membership, OnboardingApplication, Organization
from apps.organizations.services import review_application
from apps.storefront.models import ProductVariant, StoreProduct, Storefront
from apps.subscriptions.models import (
    DesignPlanEntitlementState,
    ManufacturerOfferUsage,
    MembershipPlanSuspension,
    OrganizationSubscription,
    SubscriptionPlanPolicy,
    SubscriptionReminderEvent,
    TeamInvitation,
)
from apps.subscriptions.services import (
    DESIGNER_PRO,
    DESIGNER_STARTER,
    MANUFACTURER_STARTER,
    accept_team_invitation,
    activate_paid_pro,
    confirm_subscription_billing,
    create_team_invitation,
    downgrade_to_starter,
    entitlement_summary,
    generate_due_reminders,
    grant_manufacturer_trial_exception,
    process_subscription,
    revoke_team_invitation,
)

User = get_user_model()


def user(name, *, staff=False, superuser=False):
    return User.objects.create_user(
        username=name,
        email=f"{name}@example.test",
        password="password12345",
        is_staff=staff or superuser,
        is_superuser=superuser,
    )


def active_org(owner, kind, name):
    org = Organization.objects.create(
        kind=kind,
        display_name=name,
        email=f"{name.lower().replace(' ', '-')}@example.test",
        created_by=owner,
        verification_status=Organization.VerificationStatus.ACTIVE,
    )
    Membership.objects.create(organization=org, user=owner, role=Membership.Role.OWNER)
    return org


def approved_designer_assets(owner, org, suffix="a"):
    design = GarmentDesign.objects.create(
        organization=org,
        title=f"Design {suffix}",
        status=GarmentDesign.Status.APPROVED,
        created_by=owner,
    )
    gv = GarmentDesignVersion.objects.create(
        design=design,
        version_number=1,
        status=GarmentDesignVersion.Status.APPROVED,
        created_by=owner,
    )
    artwork = Artwork.objects.create(
        organization=org,
        title=f"Artwork {suffix}",
        status=Artwork.Status.APPROVED,
        created_by=owner,
    )
    av = ArtworkVersion.objects.create(
        artwork=artwork,
        version_number=1,
        status=ArtworkVersion.Status.APPROVED,
        created_by=owner,
    )
    product = DesignedProduct.objects.create(
        organization=org,
        garment_version=gv,
        artwork_version=av,
        title=f"Product {suffix}",
        status=DesignedProduct.Status.PUBLISHED,
        created_by=owner,
    )
    return design, gv, artwork, av, product


def quote_for(manufacturer, *, suffix):
    d_owner = user(f"designer-{suffix}")
    designer = active_org(d_owner, Organization.Kind.DESIGNER, f"Designer {suffix}")
    _, _, _, _, product = approved_designer_assets(d_owner, designer, suffix)
    rfq = RFQ.objects.create(
        designer_organization=designer,
        designed_product=product,
        title=f"RFQ {suffix}",
        quantity=100,
        status=RFQ.Status.OPEN,
        created_by=d_owner,
    )
    invitation = RFQInvitation.objects.create(rfq=rfq, manufacturer=manufacturer)
    return ManufacturerQuote.objects.create(
        invitation=invitation,
        status=ManufacturerQuote.Status.DRAFT,
        unit_price=Decimal("10.00"),
        production_lead_days=10,
        created_by=manufacturer.created_by,
    )


@pytest.mark.django_db
def test_four_canonical_plan_defaults_are_reproducible_and_correct():
    rows = {p.code: p for p in SubscriptionPlanPolicy.objects.filter(version=1)}
    assert set(rows) >= {"designer_starter", "designer_pro", "manufacturer_starter", "manufacturer_pro"}
    assert rows["designer_starter"].audience == "designer"
    assert rows["designer_starter"].monthly_price == Decimal("0.00")
    assert rows["designer_starter"].designer_active_design_limit == 2
    assert rows["designer_starter"].designer_active_artwork_limit == 2
    assert rows["designer_starter"].team_subaccount_limit == 1
    assert rows["designer_pro"].monthly_price == Decimal("350.00")
    assert rows["designer_pro"].designer_active_design_limit == 10
    assert rows["designer_pro"].designer_active_artwork_limit == 5
    assert rows["designer_pro"].team_subaccount_limit == 4
    assert rows["manufacturer_starter"].manufacturer_monthly_offer_limit == 2
    assert rows["manufacturer_starter"].team_subaccount_limit == 1
    assert rows["manufacturer_pro"].monthly_price == Decimal("1500.00")
    assert rows["manufacturer_pro"].trial_months == 6
    assert rows["manufacturer_pro"].manufacturer_monthly_offer_limit == 15
    assert rows["manufacturer_pro"].team_subaccount_limit == 4
    assert all(p.currency == "EGP" and p.tax_inclusive for p in rows.values())


@pytest.mark.django_db
def test_plan_change_does_not_rewrite_subscription_or_period_snapshot():
    owner = user("snapshot-owner")
    org = active_org(owner, Organization.Kind.DESIGNER, "Snapshot Studio")
    sub = org.professional_subscription
    old_price = dict(sub.price_snapshot)
    old_period = dict(sub.periods.first().price_snapshot)
    policy = SubscriptionPlanPolicy.objects.get(code=DESIGNER_STARTER, version=1)
    policy.monthly_price = Decimal("25.00")
    policy.save(update_fields=["monthly_price"])
    sub.refresh_from_db()
    assert sub.price_snapshot == old_price
    assert sub.periods.first().price_snapshot == old_period


@pytest.mark.django_db
def test_designer_approval_defaults_to_starter_not_pro():
    owner = user("designer-starter-owner")
    org = active_org(owner, Organization.Kind.DESIGNER, "Starter Studio")
    sub = org.professional_subscription
    assert sub.current_plan.code == DESIGNER_STARTER
    assert sub.status == OrganizationSubscription.Status.ACTIVE
    assert sub.price_snapshot["monthly_price"] == "0.00"


@pytest.mark.django_db
def test_manufacturer_trial_starts_from_organization_approval_and_is_six_calendar_months():
    owner = user("trial-owner")
    staff = user("trial-reviewer", staff=True)
    org = Organization.objects.create(
        kind=Organization.Kind.MANUFACTURER,
        display_name="Trial Factory",
        email="trial-factory@example.test",
        created_by=owner,
        verification_status=Organization.VerificationStatus.PENDING,
    )
    Membership.objects.create(organization=org, user=owner, role=Membership.Role.OWNER)
    app = OnboardingApplication.objects.create(organization=org, status=OnboardingApplication.Status.SUBMITTED, submitted_at=timezone.now())
    review_application(application=app, reviewer=staff, decision=OnboardingApplication.Status.APPROVED)
    app.refresh_from_db(); org.refresh_from_db()
    sub = org.professional_subscription
    assert sub.status == OrganizationSubscription.Status.TRIALING
    assert sub.current_plan.code == "manufacturer_pro"
    assert sub.trial_consumed is True
    assert abs((sub.trial_started_at - app.reviewed_at).total_seconds()) < 1
    assert sub.trial_ends_at == sub.trial_started_at + relativedelta(months=6)


@pytest.mark.django_db
def test_manufacturer_suspension_reactivation_does_not_restart_trial():
    owner = user("reactivate-owner")
    org = active_org(owner, Organization.Kind.MANUFACTURER, "Reactivate Factory")
    sub = org.professional_subscription
    original = (sub.trial_started_at, sub.trial_ends_at)
    org.verification_status = Organization.VerificationStatus.SUSPENDED; org.save(update_fields=["verification_status", "updated_at"])
    org.verification_status = Organization.VerificationStatus.ACTIVE; org.save(update_fields=["verification_status", "updated_at"])
    sub.refresh_from_db()
    assert (sub.trial_started_at, sub.trial_ends_at) == original


@pytest.mark.django_db
def test_trial_exception_superuser_only_and_audited():
    owner = user("exception-owner")
    normal_staff = user("normal-staff", staff=True)
    superuser = user("super-admin", superuser=True)
    org = active_org(owner, Organization.Kind.MANUFACTURER, "Exception Factory")
    sub = org.professional_subscription
    with pytest.raises(PermissionDenied):
        grant_manufacturer_trial_exception(subscription=sub, actor=normal_staff, reason="support")
    old_end = sub.trial_ends_at
    grant_manufacturer_trial_exception(subscription=sub, actor=superuser, reason="Owner-approved launch exception")
    sub.refresh_from_db()
    assert sub.trial_ends_at > old_end
    assert AuditEvent.objects.filter(action="subscription.trial_exception_granted", object_id=str(sub.trial_exceptions.first().pk)).exists()


@pytest.mark.django_db
def test_paid_pro_requires_confirmed_billing_and_cannot_activate_suspended_org():
    owner = user("paid-owner")
    ops = user("paid-ops", superuser=True)
    org = active_org(owner, Organization.Kind.DESIGNER, "Paid Studio")
    with pytest.raises(Exception):
        activate_paid_pro(organization=org, actor=owner, billing_confirmation=None)
    confirmation = confirm_subscription_billing(
        organization=org,
        actor=ops,
        plan_code=DESIGNER_PRO,
        amount="350.00",
        currency="EGP",
        provider="manual_verified_reference",
        provider_reference="BILL-001",
        idempotency_key="bill-001",
    )
    org.verification_status = Organization.VerificationStatus.SUSPENDED
    org.save(update_fields=["verification_status", "updated_at"])
    activate_paid_pro(organization=org, actor=owner, billing_confirmation=confirmation)
    org.refresh_from_db()
    assert org.verification_status == Organization.VerificationStatus.SUSPENDED
    assert org.professional_subscription.current_plan.code == DESIGNER_PRO


@pytest.mark.django_db
def test_three_calendar_day_grace_preserves_pro_then_downgrades_after_final_day():
    owner = user("grace-owner")
    ops = user("grace-ops", superuser=True)
    org = active_org(owner, Organization.Kind.DESIGNER, "Grace Studio")
    confirmation = confirm_subscription_billing(organization=org, actor=ops, plan_code=DESIGNER_PRO, amount="350.00", currency="EGP", provider="verified", provider_reference="G-1", idempotency_key="g-1")
    sub = activate_paid_pro(organization=org, actor=owner, billing_confirmation=confirmation)
    due = sub.current_period_end
    process_subscription(subscription=sub, now=due + timedelta(hours=1))
    sub.refresh_from_db()
    assert sub.status == OrganizationSubscription.Status.GRACE_PERIOD
    assert sub.current_plan.code == DESIGNER_PRO
    process_subscription(subscription=sub, now=due + timedelta(days=3, hours=1))
    sub.refresh_from_db()
    assert sub.status == OrganizationSubscription.Status.GRACE_PERIOD
    process_subscription(subscription=sub, now=due + timedelta(days=4, hours=1))
    sub.refresh_from_db()
    assert sub.status == OrganizationSubscription.Status.DOWNGRADED
    assert sub.current_plan.code == DESIGNER_STARTER


@pytest.mark.django_db
def test_reminder_defaults_and_idempotent_in_platform_evidence():
    owner = user("reminder-owner")
    ops = user("reminder-ops", superuser=True)
    org = active_org(owner, Organization.Kind.DESIGNER, "Reminder Studio")
    c = confirm_subscription_billing(organization=org, actor=ops, plan_code=DESIGNER_PRO, amount="350.00", currency="EGP", provider="verified", provider_reference="R-1", idempotency_key="r-1")
    sub = activate_paid_pro(organization=org, actor=owner, billing_confirmation=c)
    due = timezone.localtime(sub.current_period_end).date()
    when = timezone.make_aware(timezone.datetime.combine(due - timedelta(days=7), timezone.datetime.min.time()), timezone.get_current_timezone())
    generate_due_reminders(subscription=sub, now=when)
    generate_due_reminders(subscription=sub, now=when)
    assert SubscriptionReminderEvent.objects.filter(subscription=sub, due_date=due).count() == 1
    event = SubscriptionReminderEvent.objects.get(subscription=sub, due_date=due)
    assert event.notification_id is not None


@pytest.mark.django_db
def test_designer_starter_active_slot_mapping_blocks_third_design_and_artwork():
    owner = user("slot-owner")
    org = active_org(owner, Organization.Kind.DESIGNER, "Slot Studio")
    designs = [GarmentDesign.objects.create(organization=org, title=f"D{i}", created_by=owner) for i in range(3)]
    for design in designs[:2]:
        design.status = GarmentDesign.Status.IN_REVIEW; design.save(update_fields=["status", "updated_at"])
    designs[2].status = GarmentDesign.Status.IN_REVIEW
    with pytest.raises(ValidationError):
        designs[2].save(update_fields=["status", "updated_at"])
    designs[0].status = GarmentDesign.Status.ARCHIVED; designs[0].save(update_fields=["status", "updated_at"])
    designs[2].save(update_fields=["status", "updated_at"])

    artworks = [Artwork.objects.create(organization=org, title=f"A{i}", created_by=owner) for i in range(3)]
    for artwork in artworks[:2]:
        artwork.status = Artwork.Status.IN_REVIEW; artwork.save(update_fields=["status", "updated_at"])
    artworks[2].status = Artwork.Status.IN_REVIEW
    with pytest.raises(ValidationError):
        artworks[2].save(update_fields=["status", "updated_at"])
    artworks[0].status = Artwork.Status.REJECTED; artworks[0].save(update_fields=["status", "updated_at"])
    artworks[2].save(update_fields=["status", "updated_at"])


@pytest.mark.django_db
def test_manufacturer_starter_offer_quota_first_submit_only_and_withdrawal_does_not_restore():
    owner = user("quota-owner")
    org = active_org(owner, Organization.Kind.MANUFACTURER, "Quota Factory")
    downgrade_to_starter(subscription=org.professional_subscription, actor=owner)
    q1, q2, q3 = [quote_for(org, suffix=f"quota-{i}") for i in range(3)]
    for quote in (q1, q2):
        quote.status = ManufacturerQuote.Status.SUBMITTED; quote.save(update_fields=["status", "updated_at"])
    assert ManufacturerOfferUsage.objects.filter(organization=org).count() == 2
    q1.notes = "edited"; q1.save(update_fields=["notes", "updated_at"])
    assert ManufacturerOfferUsage.objects.filter(organization=org).count() == 2
    q1.status = ManufacturerQuote.Status.WITHDRAWN; q1.save(update_fields=["status", "updated_at"])
    q1.status = ManufacturerQuote.Status.SUBMITTED; q1.save(update_fields=["status", "updated_at"])
    assert ManufacturerOfferUsage.objects.filter(organization=org).count() == 2
    q3.status = ManufacturerQuote.Status.SUBMITTED
    with pytest.raises(ValidationError):
        q3.save(update_fields=["status", "updated_at"])


@pytest.mark.django_db(transaction=True)
def test_concurrent_manufacturer_starter_submissions_cannot_exceed_quota():
    owner = user("concurrent-quota-owner")
    org = active_org(owner, Organization.Kind.MANUFACTURER, "Concurrent Quota Factory")
    downgrade_to_starter(subscription=org.professional_subscription, actor=owner)
    quotes = [quote_for(org, suffix=f"cq-{i}") for i in range(3)]

    def submit(pk):
        close_old_connections()
        try:
            quote = ManufacturerQuote.objects.get(pk=pk)
            quote.status = ManufacturerQuote.Status.SUBMITTED
            quote.save(update_fields=["status", "updated_at"])
            return "ok"
        except ValidationError:
            return "denied"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(submit, [q.pk for q in quotes]))
    assert results.count("ok") == 2
    assert results.count("denied") == 1
    assert ManufacturerOfferUsage.objects.filter(organization=org).count() == 2


@pytest.mark.django_db
def test_offer_quota_is_independent_in_next_monthly_usage_period():
    owner = user("next-period-owner")
    org = active_org(owner, Organization.Kind.MANUFACTURER, "Next Period Factory")
    sub = downgrade_to_starter(subscription=org.professional_subscription, actor=owner)
    q1, q2 = quote_for(org, suffix="np-1"), quote_for(org, suffix="np-2")
    for q in (q1, q2):
        q.status = ManufacturerQuote.Status.SUBMITTED; q.save(update_fields=["status", "updated_at"])
    old_start = timezone.localtime(sub.current_period_start).date()
    sub.current_period_start = sub.current_period_end
    sub.current_period_end = sub.current_period_end + relativedelta(months=1)
    sub.save(update_fields=["current_period_start", "current_period_end", "updated_at"])
    q3 = quote_for(org, suffix="np-3")
    q3.status = ManufacturerQuote.Status.SUBMITTED; q3.save(update_fields=["status", "updated_at"])
    usage = ManufacturerOfferUsage.objects.get(quote=q3)
    assert usage.period_start != old_start


@pytest.mark.django_db
def test_team_owner_consumes_zero_pending_invite_consumes_seat_and_revoke_releases():
    owner = user("team-owner")
    org = active_org(owner, Organization.Kind.DESIGNER, "Team Studio")
    summary = entitlement_summary(org)
    assert summary["team_used"] == 0 and summary["team_limit"] == 1
    invite, _ = create_team_invitation(organization=org, actor=owner, email="invitee@example.test", role=Membership.Role.DESIGNER)
    assert entitlement_summary(org)["team_used"] == 1
    with pytest.raises(ValidationError):
        create_team_invitation(organization=org, actor=owner, email="second@example.test", role=Membership.Role.DESIGNER)
    revoke_team_invitation(invitation=invite, actor=owner)
    assert entitlement_summary(org)["team_used"] == 0


@pytest.mark.django_db
def test_team_invite_no_fake_user_acceptance_rechecks_email_and_seat():
    owner = user("invite-owner")
    invitee = user("invitee")
    org = active_org(owner, Organization.Kind.DESIGNER, "Invite Studio")
    before = User.objects.count()
    invite, token = create_team_invitation(organization=org, actor=owner, email=invitee.email, role=Membership.Role.DESIGNER)
    assert User.objects.count() == before
    wrong = user("wrong-invitee")
    with pytest.raises(PermissionDenied):
        accept_team_invitation(token=token, actor=wrong)
    membership = accept_team_invitation(token=token, actor=invitee)
    assert membership.role == Membership.Role.DESIGNER and membership.is_active
    invite.refresh_from_db(); assert invite.status == TeamInvitation.Status.ACCEPTED


@pytest.mark.django_db
def test_wrong_audience_role_and_owner_promotion_are_rejected():
    owner = user("roles-owner")
    manufacturer = active_org(owner, Organization.Kind.MANUFACTURER, "Roles Factory")
    with pytest.raises(ValidationError):
        create_team_invitation(organization=manufacturer, actor=owner, email="creative@example.test", role=Membership.Role.DESIGN_MANAGER)
    with pytest.raises(ValidationError):
        create_team_invitation(organization=manufacturer, actor=owner, email="owner2@example.test", role=Membership.Role.OWNER)


@pytest.mark.django_db
def test_manager_cannot_change_subscription_or_team_owner_authority():
    owner = user("auth-owner")
    manager = user("auth-manager")
    org = active_org(owner, Organization.Kind.DESIGNER, "Auth Studio")
    Membership.objects.create(organization=org, user=manager, role=Membership.Role.MANAGER)
    with pytest.raises(PermissionDenied):
        downgrade_to_starter(subscription=org.professional_subscription, actor=manager)
    with pytest.raises(PermissionDenied):
        create_team_invitation(organization=org, actor=manager, email="x@example.test", role=Membership.Role.DESIGNER)


@pytest.mark.django_db
def test_designer_downgrade_preserves_content_and_pauses_excess_deterministically():
    owner = user("down-owner")
    ops = user("down-ops", superuser=True)
    org = active_org(owner, Organization.Kind.DESIGNER, "Down Studio")
    c = confirm_subscription_billing(organization=org, actor=ops, plan_code=DESIGNER_PRO, amount="350.00", currency="EGP", provider="verified", provider_reference="D-1", idempotency_key="d-1")
    activate_paid_pro(organization=org, actor=owner, billing_confirmation=c)
    designs = []
    for i in range(3):
        d = GarmentDesign.objects.create(organization=org, title=f"Design {i}", created_by=owner)
        d.status = GarmentDesign.Status.APPROVED; d.save(update_fields=["status", "updated_at"]); designs.append(d)
    downgrade_to_starter(subscription=org.professional_subscription, actor=owner)
    assert GarmentDesign.objects.filter(organization=org).count() == 3
    states = {s.design_id: s for s in DesignPlanEntitlementState.objects.filter(design__organization=org)}
    assert states[designs[0].pk].plan_paused is False
    assert states[designs[1].pk].plan_paused is False
    assert states[designs[2].pk].plan_paused is True


@pytest.mark.django_db
def test_active_chain_protected_when_excess_content_is_plan_paused_and_new_store_use_hidden():
    owner = user("chain-owner")
    ops = user("chain-ops", superuser=True)
    customer = user("chain-customer")
    org = active_org(owner, Organization.Kind.DESIGNER, "Chain Studio")
    c = confirm_subscription_billing(organization=org, actor=ops, plan_code=DESIGNER_PRO, amount="350.00", currency="EGP", provider="verified", provider_reference="C-1", idempotency_key="c-1")
    activate_paid_pro(organization=org, actor=owner, billing_confirmation=c)
    base_artwork = Artwork.objects.create(organization=org, title="Chain artwork", status=Artwork.Status.APPROVED, created_by=owner)
    av = ArtworkVersion.objects.create(artwork=base_artwork, version_number=1, status=ArtworkVersion.Status.APPROVED, created_by=owner)
    designs = []
    for i in range(3):
        d = GarmentDesign.objects.create(organization=org, title=f"Chain D{i}", created_by=owner)
        d.status = GarmentDesign.Status.APPROVED; d.save(update_fields=["status", "updated_at"])
        gv = GarmentDesignVersion.objects.create(design=d, version_number=1, status=GarmentDesignVersion.Status.APPROVED, created_by=owner)
        designs.append((d, gv))
    excess_design, excess_gv = designs[2]
    dp = DesignedProduct.objects.create(organization=org, garment_version=excess_gv, artwork_version=av, title="Excess product", status=DesignedProduct.Status.PUBLISHED, created_by=owner)
    store = Storefront.objects.create(organization=org, slug="chain-store", status=Storefront.Status.PUBLISHED, name_en="Chain")
    product = StoreProduct.objects.create(storefront=store, designed_product=dp, slug="excess", status=StoreProduct.Status.PUBLISHED, title_en="Excess", base_price=Decimal("100.00"))
    variant = ProductVariant.objects.create(product=product, sku="CHAIN-1", is_active=True)
    order = CustomerOrder.objects.create(customer=customer, designer_organization=org, status=CustomerOrder.Status.CONFIRMED, payment_method=CustomerOrder.PaymentMethod.COD, subtotal=100, total=100, currency="EGP")
    OrderItem.objects.create(order=order, store_product=product, variant=variant, sku="CHAIN-1", title="Excess", unit_price=100, quantity=1, line_total=100)
    ProductionJob.objects.create(order=order, status=ProductionJob.Status.IN_PRODUCTION)
    downgrade_to_starter(subscription=org.professional_subscription, actor=owner)
    state = DesignPlanEntitlementState.objects.get(design=excess_design)
    product.refresh_from_db(); order.refresh_from_db()
    assert state.plan_paused and state.protected_active_chain
    assert product.status == StoreProduct.Status.HIDDEN
    assert order.status == CustomerOrder.Status.CONFIRMED
    assert order.production_job.status == ProductionJob.Status.IN_PRODUCTION


@pytest.mark.django_db
def test_manufacturer_downgrade_preserves_memberships_but_plan_suspends_excess_seats():
    owner = user("m-down-owner")
    org = active_org(owner, Organization.Kind.MANUFACTURER, "M Down Factory")
    members = []
    for i in range(3):
        u = user(f"m-down-{i}")
        members.append(Membership.objects.create(organization=org, user=u, role=Membership.Role.OPERATOR))
    downgrade_to_starter(subscription=org.professional_subscription, actor=owner)
    assert Membership.objects.filter(organization=org).exclude(role=Membership.Role.OWNER).count() == 3
    assert Membership.objects.filter(organization=org, is_active=True).exclude(role=Membership.Role.OWNER).count() == 1
    assert MembershipPlanSuspension.objects.filter(membership__organization=org, suspended_by_plan=True).count() == 2


@pytest.mark.django_db
def test_portal_subscription_and_team_surfaces_are_available(client):
    d_owner = user("portal-designer")
    d_org = active_org(d_owner, Organization.Kind.DESIGNER, "Portal Designer")
    client.force_login(d_owner)
    assert client.get(f"/designer/subscription/?org={d_org.pk}").status_code == 200
    assert client.get(f"/designer/team/?org={d_org.pk}").status_code == 200
    client.logout()
    m_owner = user("portal-manufacturer")
    m_org = active_org(m_owner, Organization.Kind.MANUFACTURER, "Portal Manufacturer")
    client.force_login(m_owner)
    assert client.get(f"/manufacturer/subscription/?org={m_org.pk}").status_code == 200
    assert client.get(f"/manufacturer/team/?org={m_org.pk}").status_code == 200


@pytest.mark.django_db
def test_subscription_sensitive_transitions_generate_audit_evidence():
    owner = user("audit-sub-owner")
    org = active_org(owner, Organization.Kind.MANUFACTURER, "Audit Sub Factory")
    downgrade_to_starter(subscription=org.professional_subscription, actor=owner)
    assert AuditEvent.objects.filter(action="subscription.downgraded", metadata__organization_id=org.pk).exists()
