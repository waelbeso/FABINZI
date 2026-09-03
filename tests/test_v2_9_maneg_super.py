import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.audit.models import AuditEvent
from apps.integrations.models import IntegrationConfig
from apps.platform_ops.models import ApplicationReviewConfiguration
from apps.platform_ops.staff_roles import (
    ROLE_AUDITOR,
    ROLE_CONTENT_MARKETPLACE,
    ROLE_CREATIVE_IP,
    ROLE_CUSTOMER_SUPPORT,
    ROLE_FINANCE,
    ROLE_MANUFACTURING_OPERATIONS,
    ROLE_PARTNER_ONBOARDING,
    ROLE_PLATFORM_OPERATIONS,
    ROLE_NAMES,
)
from apps.subscriptions.models import TeamInvitationConfiguration

User = get_user_model()


def staff(username):
    return User.objects.create_user(
        username=username,
        email=f"{username}@example.test",
        password="strong-pass-123",
        is_staff=True,
    )


def grant(user, *natural_permissions):
    for natural in natural_permissions:
        app_label, codename = natural.split(".", 1)
        permission = Permission.objects.get(content_type__app_label=app_label, codename=codename)
        user.user_permissions.add(permission)


def verify_otp(client, user, *, name="v2-9"):
    device = TOTPDevice.objects.create(user=user, name=name, confirmed=True)
    client.force_login(user)
    session = client.session
    session["otp_device_id"] = device.persistent_id
    session.save()
    return device


@pytest.mark.django_db
def test_maneg_authentication_and_existing_mfa_without_unconfigured_deadlock(client):
    assert client.get("/Maneg/").status_code == 302

    customer = User.objects.create_user(username="v29-customer", password="strong-pass-123")
    client.force_login(customer)
    assert client.get("/Maneg/").status_code == 403

    operator = staff("v29-no-device")
    client.force_login(operator)
    response = client.get("/Maneg/")
    assert response.status_code == 200
    assert b"MFA not configured" in response.content

    configured = staff("v29-configured")
    TOTPDevice.objects.create(user=configured, name="configured", confirmed=True)
    client.force_login(configured)
    assert client.get("/Maneg/").status_code == 302

    client.logout()
    verify_otp(client, configured, name="verified")
    assert client.get("/Maneg/").status_code == 200


@pytest.mark.django_db
def test_staff_role_bootstrap_is_idempotent_non_assigning_and_never_grants_integrations():
    call_command("bootstrap_staff_roles")
    assert set(Group.objects.filter(name__in=ROLE_NAMES).values_list("name", flat=True)) == set(ROLE_NAMES)
    assert not User.objects.filter(groups__name__in=ROLE_NAMES).exists()
    first = {name: Group.objects.get(name=name).permissions.count() for name in ROLE_NAMES}

    for name in ROLE_NAMES:
        assert not Group.objects.get(name=name).permissions.filter(content_type__app_label="integrations").exists()

    call_command("bootstrap_staff_roles")
    second = {name: Group.objects.get(name=name).permissions.count() for name in ROLE_NAMES}
    assert first == second
    assert not User.objects.filter(groups__name__in=ROLE_NAMES).exists()


@pytest.mark.django_db
def test_representative_staff_role_matrix_is_server_side_not_navigation_only(client):
    call_command("bootstrap_staff_roles")
    matrix = (
        (ROLE_PLATFORM_OPERATIONS, "/Maneg/orders/", "/Maneg/finance/"),
        (ROLE_PARTNER_ONBOARDING, "/Maneg/verification/", "/Maneg/production-routing/"),
        (ROLE_CREATIVE_IP, "/Maneg/design-review/", "/Maneg/finance/"),
        (ROLE_MANUFACTURING_OPERATIONS, "/Maneg/production-routing/", "/Maneg/finance/"),
        (ROLE_FINANCE, "/Maneg/finance/", "/Maneg/integrations/"),
        (ROLE_CUSTOMER_SUPPORT, "/Maneg/orders/", "/Maneg/finance/"),
        (ROLE_CONTENT_MARKETPLACE, "/Maneg/catalog/", "/Maneg/orders/"),
        (ROLE_AUDITOR, "/Maneg/audit/", "/Maneg/integrations/"),
    )
    for index, (role, allowed, forbidden) in enumerate(matrix):
        user = staff(f"role-{index}")
        user.groups.add(Group.objects.get(name=role))
        client.force_login(user)
        assert client.get(allowed).status_code == 200, role
        assert client.get(forbidden).status_code == 403, role
        client.logout()

    auditor = staff("role-auditor-mutation")
    auditor.groups.add(Group.objects.get(name=ROLE_AUDITOR))
    target = User.objects.create_user(username="audited-target", password="strong-pass-123")
    client.force_login(auditor)
    assert client.post("/Maneg/users/", {"action": "suspend", "user_id": target.pk}).status_code == 403
    target.refresh_from_db()
    assert target.is_active is True


@pytest.mark.django_db
def test_integrations_are_superuser_only_even_if_normal_staff_has_model_permissions(client):
    config = IntegrationConfig.objects.get(provider=IntegrationConfig.Provider.STRIPE)
    config.set_secrets({"secret_key": "sk_v29_never_render"})
    config.save(update_fields=["encrypted_secrets", "updated_at"])

    operator = staff("v29-integration-perms")
    grant(operator, "integrations.view_integrationconfig", "integrations.change_integrationconfig")
    client.force_login(operator)
    denied = client.get(f"/Maneg/integrations/{config.pk}/")
    assert denied.status_code == 403
    dashboard = client.get("/Maneg/")
    assert b"Integrations" not in dashboard.content
    assert b"sk_v29_never_render" not in dashboard.content

    root = User.objects.create_superuser(username="v29-root-integrations", email="root@example.test", password="strong-pass-123")
    client.force_login(root)
    allowed = client.get(f"/Maneg/integrations/{config.pk}/")
    assert allowed.status_code == 200
    html = allowed.content.decode()
    assert "sk_v29_never_render" not in html
    assert config.encrypted_secrets not in html


@pytest.mark.django_db
def test_super_is_stock_default_admin_superuser_only_and_keeps_expert_registrations(client):
    normal = staff("v29-super-denied")
    client.force_login(normal)
    assert client.get("/super/").status_code == 403

    root = User.objects.create_superuser(username="v29-super-root", email="super@example.test", password="strong-pass-123")
    client.force_login(root)
    response = client.get("/super/")
    assert response.status_code == 200
    html = response.content.decode()
    assert "Django administration" in html
    assert "FABINZI Control Center" not in html
    assert "maneg-layout" not in html
    assert "maneg-control-center.css" not in html
    assert admin.site.is_registered(User)
    assert admin.site.is_registered(IntegrationConfig)

    TOTPDevice.objects.create(user=root, name="super-mfa", confirmed=True)
    client.force_login(root)
    assert client.get("/super/").status_code == 302
    client.logout()
    verify_otp(client, root, name="super-mfa-verified")
    assert client.get("/super/").status_code == 200


@pytest.mark.django_db
def test_productized_subscription_and_commercial_settings_use_authoritative_models_and_audit(client):
    operator = staff("v29-commercial")
    grant(
        operator,
        "subscriptions.view_organizationsubscription",
        "subscriptions.view_subscriptionplanpolicy",
        "subscriptions.view_subscriptionbillingconfirmation",
        "subscriptions.view_teaminvitationconfiguration",
        "subscriptions.change_teaminvitationconfiguration",
        "platform_ops.view_applicationreviewconfiguration",
        "platform_ops.change_applicationreviewconfiguration",
        "finance.view_finance_policy_governance",
    )
    client.force_login(operator)

    subscriptions = client.get("/Maneg/subscriptions/?lang=en")
    assert subscriptions.status_code == 200
    assert b"Authoritative plan policies" in subscriptions.content
    assert b"Django administration" not in subscriptions.content

    settings_page = client.get("/Maneg/commercial-settings/?lang=en")
    assert settings_page.status_code == 200
    assert b"Application initial-review target" in settings_page.content
    assert b"V2 Finance Policy" in settings_page.content

    response = client.post("/Maneg/commercial-settings/", {"action": "application_review_target", "hours": "31"})
    assert response.status_code == 302
    assert ApplicationReviewConfiguration.current_initial_review_target_hours() == 31
    assert AuditEvent.objects.filter(action="control_center.application_review_configuration.updated").exists()

    response = client.post("/Maneg/commercial-settings/", {"action": "team_invitation_expiry", "days": "9"})
    assert response.status_code == 302
    assert TeamInvitationConfiguration.current_expiry_days() == 9
    assert AuditEvent.objects.filter(action="subscription.team_invitation_configuration_changed").exists()


@pytest.mark.django_db
def test_maneg_and_super_are_nonindexable_private_and_absent_from_sitemap(client):
    operator = staff("v29-index")
    client.force_login(operator)
    maneg = client.get("/Maneg/")
    assert maneg["X-Robots-Tag"] == "noindex, nofollow, noarchive"
    assert "private" in maneg["Cache-Control"] and "no-store" in maneg["Cache-Control"]

    root = User.objects.create_superuser(username="v29-index-root", email="idx@example.test", password="strong-pass-123")
    client.force_login(root)
    super_response = client.get("/super/")
    assert super_response["X-Robots-Tag"] == "noindex, nofollow, noarchive"
    assert "private" in super_response["Cache-Control"] and "no-store" in super_response["Cache-Control"]

    sitemap = client.get("/sitemap.xml").content.decode()
    assert "/Maneg/" not in sitemap
    assert "/super/" not in sitemap
