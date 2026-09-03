from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_audit_event
from apps.integrations.services import test_connection
from apps.organizations.models import Organization


def _require_staff(actor):
    if not getattr(actor, "is_staff", False):
        raise PermissionDenied("Staff access required.")


@transaction.atomic
def suspend_user(*, target, actor, request=None):
    _require_staff(actor)
    if target.pk == actor.pk:
        raise ValidationError("You cannot suspend your own administrator account.")
    if target.is_superuser and not actor.is_superuser:
        raise PermissionDenied("Only a superuser can suspend another superuser.")
    if not target.is_active:
        return target
    target.is_active = False
    target.save(update_fields=["is_active"])
    record_audit_event(
        actor=actor,
        action="control_center.user.suspended",
        instance=target,
        metadata={"target_user_id": target.pk, "was_staff": target.is_staff, "was_superuser": target.is_superuser},
        request=request,
    )
    return target


@transaction.atomic
def suspend_organization(*, organization, actor, request=None):
    _require_staff(actor)
    if organization.verification_status == Organization.VerificationStatus.SUSPENDED:
        return organization
    previous = organization.verification_status
    organization.verification_status = Organization.VerificationStatus.SUSPENDED
    organization.save(update_fields=["verification_status", "updated_at"])
    record_audit_event(
        actor=actor,
        action="control_center.organization.suspended",
        instance=organization,
        metadata={"organization_id": organization.pk, "previous_status": previous},
        request=request,
    )
    return organization


@transaction.atomic
def reactivate_organization(*, organization, actor, request=None):
    _require_staff(actor)
    if organization.verification_status != Organization.VerificationStatus.SUSPENDED:
        raise ValidationError("Only a suspended organization can be reactivated.")
    application = getattr(organization, "onboarding_application", None)
    if application is None or application.status != application.Status.APPROVED:
        raise ValidationError("Only a previously approved professional organization can be reactivated.")
    previous = organization.verification_status
    organization.verification_status = Organization.VerificationStatus.ACTIVE
    organization.save(update_fields=["verification_status", "updated_at"])

    # Reactivation is an explicit professional activation boundary. The
    # subscription service is idempotent, so an existing Manufacturer trial is
    # reused and an already-consumed trial is never restarted.
    from apps.subscriptions.services import ensure_subscription_for_organization
    from apps.subscriptions.team_services import reconcile_team_capacity_for_subscription

    subscription = ensure_subscription_for_organization(
        organization,
        actor=actor,
        request=request,
    )
    reconcile_team_capacity_for_subscription(
        organization=organization,
        actor=actor,
        request=request,
    )
    record_audit_event(
        actor=actor,
        action="control_center.organization.reactivated",
        instance=organization,
        metadata={
            "organization_id": organization.pk,
            "previous_status": previous,
            "subscription_id": subscription.pk,
        },
        request=request,
    )
    return organization


@transaction.atomic
def save_announcement(*, form, actor, request=None):
    _require_staff(actor)
    announcement = form.save(commit=False)
    if not announcement.created_by_id:
        announcement.created_by = actor
    announcement.full_clean()
    announcement.save()
    record_audit_event(
        actor=actor,
        action="platform_ops.platformannouncement.updated",
        instance=announcement,
        metadata={"enabled": announcement.enabled, "severity": announcement.severity, "audience": announcement.audience},
        request=request,
    )
    return announcement


@transaction.atomic
def save_maintenance(*, form, actor, request=None):
    _require_staff(actor)
    window = form.save(commit=False)
    if not window.created_by_id:
        window.created_by = actor
    window.full_clean()
    window.save()
    record_audit_event(
        actor=actor,
        action="platform_ops.maintenancewindow.updated",
        instance=window,
        metadata={"enabled": window.enabled, "mode": window.mode},
        request=request,
    )
    return window


@transaction.atomic
def save_integration_config(*, config, form, actor, request=None):
    _require_staff(actor)
    obj = form.save(commit=False)
    obj.updated_by = actor
    secret_payload = form.cleaned_data.get("secret_payload")
    if secret_payload is not None:
        obj.set_secrets(secret_payload)
    obj.full_clean()
    obj.save()
    record_audit_event(
        actor=actor,
        action="integration.config.updated",
        instance=obj,
        metadata={"provider": obj.provider, "enabled": obj.enabled, "secrets_replaced": secret_payload is not None},
        request=request,
    )
    return obj


@transaction.atomic
def run_integration_test(*, config, actor, request=None):
    _require_staff(actor)
    if config.provider == config.Provider.SENTRY:
        raise ValidationError("Sentry runtime delivery cannot be verified by this connection test; configuration presence is shown separately.")
    result = test_connection(config)
    config.last_test_status = config.TestStatus.SUCCESS if result.ok else config.TestStatus.FAILURE
    config.last_tested_at = timezone.now()
    config.last_test_message = result.message[:500]
    config.updated_by = actor
    config.save(update_fields=["last_test_status", "last_tested_at", "last_test_message", "updated_by", "updated_at"])
    record_audit_event(
        actor=actor,
        action="integration.connection.tested",
        instance=config,
        metadata={"provider": config.provider, "ok": result.ok},
        request=request,
    )
    return result
