from datetime import timedelta
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit.services import record_audit_event
from apps.organizations.models import Membership, OnboardingApplication, Organization
from .models import (
    OnboardingPlanSelection,
    OrganizationSubscription,
    SubscriptionBillingConfirmation,
    SubscriptionPlanPolicy,
    SubscriptionTrialException,
)

ONBOARDING_PAYMENT_WINDOW_DAYS = 27
DESIGNER_STARTER = "designer_starter"
DESIGNER_PRO = "designer_pro"
MANUFACTURER_STARTER = "manufacturer_starter"
MANUFACTURER_PRO = "manufacturer_pro"


def _core():
    # Lazy import avoids a module-import cycle while services.py re-exports these
    # commercial/onboarding lifecycle authorities.
    from . import services

    return services


def _now(value=None):
    return value or timezone.now()


def _codes_for_kind(kind):
    if kind == Organization.Kind.DESIGNER:
        return DESIGNER_STARTER, DESIGNER_PRO
    if kind == Organization.Kind.MANUFACTURER:
        return MANUFACTURER_STARTER, MANUFACTURER_PRO
    raise ValidationError("Onboarding plan selection requires a Designer or Manufacturer Organization.")


def onboarding_plan_options(kind, *, at=None):
    starter_code, pro_code = _codes_for_kind(kind)
    core = _core()
    return (
        core.get_effective_plan(starter_code, at=at),
        core.get_effective_plan(pro_code, at=at),
    )


def _selection_actor_allowed(actor, organization):
    if not actor or not actor.is_authenticated:
        return False
    if actor.is_superuser:
        return True
    return Membership.objects.filter(
        organization=organization,
        user=actor,
        role__in=[Membership.Role.OWNER, Membership.Role.MANAGER],
        is_active=True,
    ).exists()


def _selection_identity_is_valid(selection):
    policy = selection.selected_plan_policy
    organization = selection.application.organization
    return bool(
        policy.audience == organization.kind
        and selection.plan_code == policy.code
        and selection.plan_version == policy.version
        and policy.code in set(_codes_for_kind(organization.kind))
    )


def _assert_selection_identity(selection):
    if not _selection_identity_is_valid(selection):
        raise ValidationError("Stored onboarding plan identity no longer matches its selected policy/version.")
    return selection


def _selection_is_paid(selection):
    return selection.plan_code == _codes_for_kind(selection.application.organization.kind)[1]


@transaction.atomic
def set_onboarding_plan_selection(*, application, actor, selected_plan_policy, request=None, now=None):
    now = _now(now)
    application = (
        OnboardingApplication.objects.select_for_update()
        .select_related("organization")
        .get(pk=application.pk)
    )
    if application.status not in {
        OnboardingApplication.Status.DRAFT,
        OnboardingApplication.Status.REVISION_REQUIRED,
    }:
        raise ValidationError("Submitted or decided onboarding plan selections are frozen.")
    if not _selection_actor_allowed(actor, application.organization):
        raise PermissionDenied("Organization Owner or Manager authority is required to select an onboarding plan.")

    policy = SubscriptionPlanPolicy.objects.get(pk=selected_plan_policy.pk)
    starter, pro = onboarding_plan_options(application.organization.kind, at=now)
    valid_ids = {starter.pk, pro.pk}
    if policy.pk not in valid_ids or policy.audience != application.organization.kind:
        raise ValidationError("Choose a currently available Starter or Pro policy for this Organization type.")

    core = _core()
    values = {
        "selected_plan_policy": policy,
        "plan_code": policy.code,
        "plan_version": policy.version,
        "policy_snapshot": core.plan_snapshot(policy),
        "price_snapshot": core.price_snapshot(policy),
        "selected_by": actor,
        "selected_at": now,
        "payment_due_at": None,
    }
    selection, created = OnboardingPlanSelection.objects.select_for_update().get_or_create(
        application=application,
        defaults=values,
    )
    if not created:
        for field, value in values.items():
            setattr(selection, field, value)
        selection.full_clean()
        selection.save()
    else:
        selection.full_clean()

    record_audit_event(
        actor=actor,
        action="onboarding.plan_selected",
        instance=selection,
        metadata={
            "application_id": application.pk,
            "organization_id": application.organization_id,
            "plan_policy_id": policy.pk,
            "plan_code": policy.code,
            "plan_version": policy.version,
        },
        request=request,
    )
    return selection


@transaction.atomic
def ensure_onboarding_plan_selection(*, application, actor, request=None, now=None):
    existing = (
        OnboardingPlanSelection.objects.select_for_update()
        .select_related("selected_plan_policy", "application__organization")
        .filter(application=application)
        .first()
    )
    if existing:
        return existing
    if application.status not in {
        OnboardingApplication.Status.DRAFT,
        OnboardingApplication.Status.REVISION_REQUIRED,
    }:
        # Legacy Submitted applications intentionally remain historically unselected.
        return None
    starter, _ = onboarding_plan_options(application.organization.kind, at=now)
    return set_onboarding_plan_selection(
        application=application,
        actor=actor,
        selected_plan_policy=starter,
        request=request,
        now=now,
    )


@transaction.atomic
def apply_approved_onboarding_plan_selection(*, application, actor=None, request=None):
    application = (
        OnboardingApplication.objects.select_for_update()
        .select_related("organization")
        .get(pk=application.pk)
    )
    if application.status != OnboardingApplication.Status.APPROVED or not application.reviewed_at:
        raise ValidationError("Payment window can only be established at an approved onboarding decision.")
    selection = (
        OnboardingPlanSelection.objects.select_for_update()
        .select_related("selected_plan_policy", "application__organization")
        .filter(application=application)
        .first()
    )
    if selection is None:
        return None
    _assert_selection_identity(selection)
    due = application.reviewed_at + timedelta(days=ONBOARDING_PAYMENT_WINDOW_DAYS) if _selection_is_paid(selection) else None
    selection.payment_due_at = due
    selection.save(update_fields=["payment_due_at"])
    if due:
        record_audit_event(
            actor=actor,
            action="onboarding.payment_window_opened",
            instance=selection,
            metadata={
                "application_id": application.pk,
                "organization_id": application.organization_id,
                "plan_policy_id": selection.selected_plan_policy_id,
                "plan_code": selection.plan_code,
                "plan_version": selection.plan_version,
                "payment_due_at": due.isoformat(),
                "payment_window_days": ONBOARDING_PAYMENT_WINDOW_DAYS,
            },
            request=request,
        )
    return selection


def onboarding_commercial_summary(organization, *, now=None):
    now = _now(now)
    selection = (
        OnboardingPlanSelection.objects.select_related("selected_plan_policy", "application")
        .filter(
            application__organization=organization,
            application__status=OnboardingApplication.Status.APPROVED,
        )
        .first()
    )
    if not selection:
        return {"selection": None, "payment_window_state": "none", "payment_due_at": None}
    if not _selection_is_paid(selection):
        return {"selection": selection, "payment_window_state": "not_required", "payment_due_at": None}
    matching = [
        row
        for row in SubscriptionBillingConfirmation.objects.filter(
            organization=organization,
            plan_policy_id=selection.selected_plan_policy_id,
            plan_code=selection.plan_code,
            plan_version=selection.plan_version,
        ).order_by("confirmed_at", "pk")
        if _confirmation_matches_selection(row, selection)
    ]
    if any(row.consumed_period_id for row in matching):
        state = "consumed"
    elif any(
        row.status == SubscriptionBillingConfirmation.Status.CONFIRMED
        and selection.payment_due_at
        and row.confirmed_at <= selection.payment_due_at
        for row in matching
    ):
        state = "paid_pending_activation"
    elif selection.payment_due_at and now <= selection.payment_due_at:
        state = "active"
    else:
        state = "expired"
    return {"selection": selection, "payment_window_state": state, "payment_due_at": selection.payment_due_at}


@transaction.atomic
def ensure_subscription_for_organization(organization, *, activation_at=None, actor=None, request=None):
    """Provision Starter for every new professional Organization; never create a new Manufacturer trial."""
    core = _core()
    organization = Organization.objects.select_for_update().get(pk=organization.pk)
    existing = (
        OrganizationSubscription.objects.select_for_update()
        .select_related("current_plan")
        .filter(organization=organization)
        .first()
    )
    if existing:
        # Historical Manufacturer trials are deliberately returned untouched.
        return existing
    if organization.kind not in {Organization.Kind.DESIGNER, Organization.Kind.MANUFACTURER}:
        raise ValidationError("Professional subscriptions require a Designer or Manufacturer Organization.")
    if organization.verification_status != Organization.VerificationStatus.ACTIVE:
        raise ValidationError("A professional subscription cannot create or replace Organization approval.")

    started_at = activation_at or core._activation_at(organization)
    starter_code, _ = _codes_for_kind(organization.kind)
    plan = core.get_effective_plan(starter_code, at=started_at)
    subscription = OrganizationSubscription.objects.create(
        organization=organization,
        current_plan=plan,
        status=OrganizationSubscription.Status.ACTIVE,
        started_at=started_at,
        current_period_start=started_at,
        current_period_end=core._period_end(started_at),
        next_billing_at=None,
        policy_snapshot=core.plan_snapshot(plan),
        price_snapshot=core.price_snapshot(plan),
    )
    core._create_period(subscription)
    record_audit_event(
        actor=actor,
        action="subscription.created",
        instance=subscription,
        metadata={"organization_id": organization.pk, "plan_code": plan.code},
        request=request,
    )
    return subscription


def _selection_confirmations_locked(selection):
    return list(
        SubscriptionBillingConfirmation.objects.select_for_update()
        .filter(
            organization=selection.application.organization,
            plan_policy_id=selection.selected_plan_policy_id,
            plan_code=selection.plan_code,
            plan_version=selection.plan_version,
        )
        .order_by("confirmed_at", "pk")
    )


def _confirmation_matches_selection(confirmation, selection):
    price = dict(selection.price_snapshot or {})
    try:
        expected_amount = Decimal(str(price["monthly_price"]))
    except (KeyError, TypeError, ValueError):
        return False
    return bool(
        confirmation.organization_id == selection.application.organization_id
        and confirmation.plan_policy_id == selection.selected_plan_policy_id
        and confirmation.plan_code == selection.plan_code
        and confirmation.plan_version == selection.plan_version
        and Decimal(confirmation.amount) == expected_amount
        and confirmation.currency == price.get("currency")
        and confirmation.tax_inclusive == price.get("tax_inclusive")
        and dict(confirmation.policy_snapshot or {}) == dict(selection.policy_snapshot or {})
        and dict(confirmation.price_snapshot or {}) == price
    )


def _selection_has_been_consumed(selection):
    return any(
        row.consumed_period_id or row.consumed_at
        for row in _selection_confirmations_locked(selection)
        if _confirmation_matches_selection(row, selection)
    )


def _active_onboarding_selection_locked(organization, *, now):
    selection = (
        OnboardingPlanSelection.objects.select_for_update()
        .select_related("selected_plan_policy", "application__organization")
        .filter(
            application__organization=organization,
            application__status=OnboardingApplication.Status.APPROVED,
            payment_due_at__isnull=False,
        )
        .first()
    )
    if not selection or not _selection_is_paid(selection):
        return None
    _assert_selection_identity(selection)
    if _selection_has_been_consumed(selection):
        return None
    if now > selection.payment_due_at:
        return None
    return selection


def _timely_selection_for_confirmation_locked(organization, confirmation):
    selection = (
        OnboardingPlanSelection.objects.select_for_update()
        .select_related("selected_plan_policy", "application__organization")
        .filter(
            application__organization=organization,
            application__status=OnboardingApplication.Status.APPROVED,
            payment_due_at__isnull=False,
        )
        .first()
    )
    if not selection or not _selection_is_paid(selection):
        return None
    _assert_selection_identity(selection)
    if not _confirmation_matches_selection(confirmation, selection):
        return None
    if confirmation.confirmed_at > selection.payment_due_at:
        return None
    for other in _selection_confirmations_locked(selection):
        if other.pk != confirmation.pk and _confirmation_matches_selection(other, selection) and (other.consumed_period_id or other.consumed_at):
            raise ValidationError("The approved onboarding paid agreement has already been consumed.")
    return selection


def _retry_matches_inputs(confirmation, *, organization, plan_code, amount, currency, provider, provider_reference, idempotency_key):
    return bool(
        confirmation.organization_id == organization.pk
        and confirmation.plan_code == plan_code
        and Decimal(confirmation.amount) == Decimal(str(amount))
        and confirmation.currency == str(currency).upper()
        and confirmation.provider == provider
        and confirmation.provider_reference == provider_reference
        and confirmation.idempotency_key == idempotency_key
    )


@transaction.atomic
def confirm_subscription_billing(
    *,
    organization,
    actor,
    plan_code,
    amount,
    currency,
    provider,
    provider_reference,
    idempotency_key,
    request=None,
    now=None,
):
    core = _core()
    core.require_subscription_operator(actor)
    now = _now(now)
    provider_value = str(provider or "").strip()
    provider_reference_value = str(provider_reference or "").strip()
    idempotency_value = str(idempotency_key or "").strip()
    currency_value = str(currency or "").strip().upper()
    if not provider_value or not provider_reference_value or not idempotency_value:
        raise ValidationError("Provider, provider reference, and idempotency key are required.")

    existing = SubscriptionBillingConfirmation.objects.select_for_update().filter(idempotency_key=idempotency_value).first()
    if existing is not None:
        if _retry_matches_inputs(
            existing,
            organization=organization,
            plan_code=plan_code,
            amount=amount,
            currency=currency_value,
            provider=provider_value,
            provider_reference=provider_reference_value,
            idempotency_key=idempotency_value,
        ):
            return existing
        raise ValidationError("Billing idempotency key is already bound to different immutable subscription evidence.")

    selection = _active_onboarding_selection_locked(organization, now=now)
    if selection:
        price = dict(selection.price_snapshot or {})
        expected_amount = Decimal(str(price.get("monthly_price")))
        expected_currency = str(price.get("currency") or "").upper()
        if plan_code != selection.plan_code or Decimal(str(amount)) != expected_amount or currency_value != expected_currency:
            raise ValidationError("Billing confirmation must match the exact approved onboarding policy/version and price snapshot.")
        live = [
            row
            for row in _selection_confirmations_locked(selection)
            if _confirmation_matches_selection(row, selection)
            and row.status == SubscriptionBillingConfirmation.Status.CONFIRMED
            and not row.consumed_period_id
        ]
        if live:
            raise ValidationError("This onboarding paid agreement already has live confirmed billing evidence.")
        plan = selection.selected_plan_policy
        expected_policy_snapshot = dict(selection.policy_snapshot or {})
        expected_price_snapshot = price
        expected_tax = bool(price.get("tax_inclusive"))
        expected_version = selection.plan_version
    else:
        plan = core.get_effective_plan(plan_code, at=now)
        if plan.audience != organization.kind:
            raise ValidationError("Billing confirmation plan audience does not match the Organization.")
        if Decimal(str(amount)) != plan.monthly_price or currency_value != plan.currency:
            raise ValidationError("Billing confirmation amount/currency must match the exact effective plan policy.")
        expected_policy_snapshot = core.plan_snapshot(plan)
        expected_price_snapshot = core.price_snapshot(plan)
        expected_tax = plan.tax_inclusive
        expected_version = plan.version

    defaults = {
        "organization": organization,
        "plan_policy": plan,
        "plan_code": plan_code,
        "plan_version": expected_version,
        "amount": Decimal(str(amount)),
        "currency": currency_value,
        "tax_inclusive": expected_tax,
        "policy_snapshot": expected_policy_snapshot,
        "price_snapshot": expected_price_snapshot,
        "provider": provider_value,
        "provider_reference": provider_reference_value,
        "confirmed_by": actor,
    }
    created = False
    try:
        with transaction.atomic():
            confirmation = SubscriptionBillingConfirmation.objects.create(
                idempotency_key=idempotency_value,
                **defaults,
            )
            created = True
    except IntegrityError:
        confirmation = SubscriptionBillingConfirmation.objects.select_for_update().filter(
            provider_reference=provider_reference_value
        ).first()
        if confirmation is None or not _retry_matches_inputs(
            confirmation,
            organization=organization,
            plan_code=plan_code,
            amount=amount,
            currency=currency_value,
            provider=provider_value,
            provider_reference=provider_reference_value,
            idempotency_key=idempotency_value,
        ):
            raise ValidationError("Billing evidence conflicts with an existing unique reference.")

    if created:
        record_audit_event(
            actor=actor,
            action="subscription.billing_confirmed",
            instance=confirmation,
            metadata={
                "organization_id": organization.pk,
                "plan_code": confirmation.plan_code,
                "plan_policy_id": confirmation.plan_policy_id,
                "plan_version": confirmation.plan_version,
                "provider": confirmation.provider,
                "tax_inclusive": confirmation.tax_inclusive,
                "onboarding_plan_selection_id": selection.pk if selection else None,
            },
            request=request,
        )
    return confirmation


@transaction.atomic
def activate_paid_pro(*, organization, actor, billing_confirmation, request=None, now=None):
    core = _core()
    core._require_owner_or_operator(actor, organization)
    if billing_confirmation is None:
        raise ValidationError("Confirmed billing evidence is required.")
    now = _now(now)
    confirmation = core._lock_confirmation(billing_confirmation.pk)
    subscription = core._subscription_locked_for_org(organization, now=now)
    if core._existing_consumed_period(confirmation, subscription):
        # Exact replay is idempotent and can never reactivate after a later downgrade.
        return subscription
    if confirmation.status != SubscriptionBillingConfirmation.Status.CONFIRMED:
        raise ValidationError("Confirmed billing evidence is required.")

    selection = _timely_selection_for_confirmation_locked(organization, confirmation)
    if selection:
        plan = selection.selected_plan_policy
        if plan.audience != organization.kind or selection.plan_code != _codes_for_kind(organization.kind)[1]:
            raise ValidationError("Onboarding billing evidence is not a valid Pro agreement for this Organization.")
        subscription_policy_snapshot = dict(selection.policy_snapshot or {})
        subscription_price_snapshot = dict(selection.price_snapshot or {})
    else:
        plan = core.get_effective_plan(_codes_for_kind(organization.kind)[1], at=now)
        core._validate_confirmation_for_policy(confirmation=confirmation, organization=organization, plan=plan)
        subscription_policy_snapshot = core.plan_snapshot(plan)
        subscription_price_snapshot = core.price_snapshot(plan)

    old_plan = subscription.current_plan.code
    subscription.current_plan = plan
    subscription.status = OrganizationSubscription.Status.ACTIVE
    subscription.current_period_start = now
    subscription.current_period_end = core._period_end(now)
    subscription.next_billing_at = subscription.current_period_end
    subscription.grace_started_on = None
    subscription.grace_ends_on = None
    subscription.policy_snapshot = subscription_policy_snapshot
    subscription.price_snapshot = subscription_price_snapshot
    subscription.save()
    period = core._create_period(subscription, billing_reference=confirmation.provider_reference)
    core._consume_confirmation(confirmation=confirmation, period=period, now=now)
    core.restore_plan_limited_resources(organization=organization, actor=actor, request=request, now=now)
    record_audit_event(
        actor=actor,
        action="subscription.upgraded",
        instance=subscription,
        metadata={
            "organization_id": organization.pk,
            "old_plan": old_plan,
            "new_plan": plan.code,
            "plan_policy_id": plan.pk,
            "plan_version": selection.plan_version if selection else plan.version,
            "billing_confirmation_id": confirmation.pk,
            "subscription_period_id": period.pk,
            "onboarding_plan_selection_id": selection.pk if selection else None,
        },
        request=request,
    )
    core._notify_subscription_owners(
        subscription,
        "subscription_plan_changed",
        "Subscription plan changed",
        "تم تغيير خطة الاشتراك",
    )
    return subscription


@transaction.atomic
def grant_manufacturer_trial_exception(
    *,
    subscription,
    actor,
    reason,
    months=6,
    request=None,
    now=None,
):
    if not actor or not actor.is_superuser:
        raise PermissionDenied("Only a superuser may grant a Manufacturer trial exception.")
    now = _now(now)
    subscription = (
        OrganizationSubscription.objects.select_for_update()
        .select_related("organization", "current_plan")
        .get(pk=subscription.pk)
    )
    if subscription.organization.kind != Organization.Kind.MANUFACTURER:
        raise ValidationError("Trial exceptions apply only to Manufacturer Organizations.")
    if not (
        subscription.status == OrganizationSubscription.Status.TRIALING
        and subscription.current_plan.code == MANUFACTURER_PRO
        and subscription.trial_consumed
        and subscription.trial_started_at
        and subscription.trial_ends_at
    ):
        raise ValidationError("Trial exceptions are restricted to already-existing historical Manufacturer Pro trials.")
    reason = str(reason or "").strip()
    if not reason:
        raise ValidationError("A trial exception reason is required.")
    if int(months) <= 0:
        raise ValidationError("Trial exception duration must be positive.")

    old_state = {
        "trial_started_at": subscription.trial_started_at.isoformat(),
        "trial_ends_at": subscription.trial_ends_at.isoformat(),
        "trial_consumed": subscription.trial_consumed,
        "status": subscription.status,
        "plan_code": subscription.current_plan.code,
    }
    extension_base = max(subscription.trial_ends_at, now)
    subscription.trial_ends_at = extension_base + relativedelta(months=int(months))
    subscription.next_billing_at = subscription.trial_ends_at
    subscription.save(update_fields=["trial_ends_at", "next_billing_at", "updated_at"])
    new_state = {
        "trial_started_at": subscription.trial_started_at.isoformat(),
        "trial_ends_at": subscription.trial_ends_at.isoformat(),
        "trial_consumed": subscription.trial_consumed,
        "status": subscription.status,
        "plan_code": subscription.current_plan.code,
    }
    exception = SubscriptionTrialException.objects.create(
        subscription=subscription,
        actor=actor,
        reason=reason,
        old_trial_state=old_state,
        new_trial_state=new_state,
    )
    record_audit_event(
        actor=actor,
        action="subscription.trial_exception_granted",
        instance=exception,
        metadata={
            "organization_id": subscription.organization_id,
            "reason_present": True,
            "old_trial_state": old_state,
            "new_trial_state": new_state,
            "historical_trial_only": True,
        },
        request=request,
    )
    return subscription
