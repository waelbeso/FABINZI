import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.urls import reverse
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


def role_user(role, username):
    user = staff(username)
    user.groups.add(Group.objects.get(name=role))
    return user


@pytest.mark.django_db
def test_maneg_authentication_and_existing_mfa_without_unconfigured_deadlock(client):
    assert client.get("/Maneg/").status_code == 302

    customer = User.objects.create_user(username="v29-customer", password="strong-pass-123")
    client.force_login(customer)
    assert client.get("/Maneg/").status_code == 302

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
def test_platform_operations_role_direct_scope(client):
    call_command("bootstrap_staff_roles")
    user = role_user(ROLE_PLATFORM_OPERATIONS, "role-platform-ops")
    client.force_login(user)
    assert client.get("/Maneg/orders/").status_code == 200
    assert client.get("/Maneg/production/").status_code == 200
    assert client.get("/Maneg/finance-policies/").status_code == 403
    assert client.get("/Maneg/integrations/").status_code == 403


@pytest.mark.django_db
def test_partner_onboarding_role_direct_scope(client):
    call_command("bootstrap_staff_roles")
    user = role_user(ROLE_PARTNER_ONBOARDING, "role-partner")
    client.force_login(user)
    assert client.get("/Maneg/verification/").status_code == 200
    assert client.get("/Maneg/public-profiles/").status_code == 200
    assert client.get("/Maneg/finance/").status_code == 403
    assert client.get("/Maneg/integrations/").status_code == 403


@pytest.mark.django_db
def test_creative_ip_role_direct_scope(client):
    call_command("bootstrap_staff_roles")
    user = role_user(ROLE_CREATIVE_IP, "role-creative")
    client.force_login(user)
    assert client.get("/Maneg/design-review/").status_code == 200
    assert client.get("/Maneg/artwork-ip/").status_code == 200
    assert client.get("/Maneg/finance/").status_code == 403
    assert client.get("/Maneg/integrations/").status_code == 403


@pytest.mark.django_db
def test_manufacturing_operations_role_direct_scope(client):
    call_command("bootstrap_staff_roles")
    user = role_user(ROLE_MANUFACTURING_OPERATIONS, "role-manufacturing")
    client.force_login(user)
    assert client.get("/Maneg/production/").status_code == 200
    assert client.get("/Maneg/production-routing/").status_code == 200
    assert client.get("/Maneg/finance-policies/").status_code == 403
    assert client.get("/Maneg/integrations/").status_code == 403


@pytest.mark.django_db
def test_finance_role_direct_scope_without_platform_owner_access(client):
    call_command("bootstrap_staff_roles")
    user = role_user(ROLE_FINANCE, "role-finance")
    client.force_login(user)
    assert client.get("/Maneg/finance/").status_code == 200
    assert client.get("/Maneg/finance-policies/").status_code == 200
    assert client.get("/Maneg/subscriptions/").status_code == 200
    assert client.get("/Maneg/integrations/").status_code == 403
    assert client.get("/Maneg/system/").status_code == 403
    assert client.get("/super/").status_code == 403


@pytest.mark.django_db
def test_customer_support_role_visibility_without_bank_or_payout_mutation(client):
    call_command("bootstrap_staff_roles")
    user = role_user(ROLE_CUSTOMER_SUPPORT, "role-support")
    client.force_login(user)
    assert client.get("/Maneg/orders/").status_code == 200
    assert client.get("/Maneg/public-inquiries/").status_code == 200
    assert client.post("/Maneg/finance-payouts/", {"action": "verify_profile", "profile_id": "1"}).status_code == 403
    assert client.get("/Maneg/integrations/").status_code == 403


@pytest.mark.django_db
def test_content_marketplace_role_direct_scope(client):
    call_command("bootstrap_staff_roles")
    user = role_user(ROLE_CONTENT_MARKETPLACE, "role-content")
    client.force_login(user)
    assert client.get("/Maneg/catalog/").status_code == 200
    assert client.get("/Maneg/public-profiles/").status_code == 200
    assert client.get("/Maneg/finance/").status_code == 403
    assert client.get("/Maneg/integrations/").status_code == 403


@pytest.mark.django_db
def test_auditor_is_read_only_on_representative_direct_routes(client):
    call_command("bootstrap_staff_roles")
    auditor = role_user(ROLE_AUDITOR, "role-auditor")
    target = User.objects.create_user(username="audited-target", password="strong-pass-123")
    config, _ = ApplicationReviewConfiguration.objects.get_or_create(singleton_key=1)
    original_hours = config.application_initial_review_target_hours
    client.force_login(auditor)

    assert client.get("/Maneg/orders/").status_code == 200
    assert client.get("/Maneg/finance/").status_code == 200
    assert client.get("/Maneg/audit/").status_code == 200
    assert client.post("/Maneg/users/", {"action": "suspend", "user_id": target.pk}).status_code == 403
    target.refresh_from_db()
    assert target.is_active is True
    assert client.post(
        reverse("fabinzi_admin:platform_ops_applicationreviewconfiguration_change", args=[config.pk]),
        {"application_initial_review_target_hours": "72", "_save": "Save"},
    ).status_code == 403
    config.refresh_from_db()
    assert config.application_initial_review_target_hours == original_hours
    assert client.get("/Maneg/integrations/").status_code == 403


@pytest.mark.django_db
def test_integrations_are_superuser_only_even_if_normal_staff_has_model_permissions(client):
    config = IntegrationConfig.objects.get(provider=IntegrationConfig.Provider.STRIPE)
    config.set_secrets({"secret_key": "sk_v29_never_render"})
    config.save(update_fields=["encrypted_secrets", "updated_at"])

    operator = staff("v29-integration-perms")
    grant(operator, "integrations.view_integrationconfig", "integrations.change_integrationconfig")
    client.force_login(operator)
    dashboard = client.get("/Maneg/")
    assert dashboard.status_code == 200
    assert dashboard.content.count(b'href="/Maneg/integrations/') == 0
    assert dashboard.content.count(b'href="/super/') == 0
    denied = client.get(f"/Maneg/integrations/{config.pk}/")
    assert denied.status_code == 403
    denied_post = client.post(
        f"/Maneg/integrations/{config.pk}/",
        {"provider": "stripe", "config": "{}", "enabled": "on", "secret_key": "attempted-overwrite"},
    )
    assert denied_post.status_code == 403
    config.refresh_from_db()
    assert config.get_secrets().get("secret_key") == "sk_v29_never_render"

    root = User.objects.create_superuser(username="v29-root-integrations", email="root@example.test", password="strong-pass-123")
    client.force_login(root)
    root_dashboard = client.get("/Maneg/")
    assert root_dashboard.status_code == 200
    assert root_dashboard.content.count(b'href="/Maneg/integrations/') == 1
    assert root_dashboard.content.count(b'href="/super/') == 1
    allowed = client.get(f"/Maneg/integrations/{config.pk}/")
    assert allowed.status_code == 200
    html = allowed.content.decode()
    assert "sk_v29_never_render" not in html
    assert config.encrypted_secrets not in html
    assert all("sk_v29_never_render" not in str(event.metadata) for event in AuditEvent.objects.all())


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
    assert "/Maneg/" not in html
    assert admin.site.is_registered(User)
    assert admin.site.is_registered(IntegrationConfig)

    user_list = client.get(reverse("admin:accounts_user_changelist"))
    user_change = client.get(reverse("admin:accounts_user_change", args=[root.pk]))
    integration_list = client.get(reverse("admin:integrations_integrationconfig_changelist"))
    integration = IntegrationConfig.objects.get(provider=IntegrationConfig.Provider.STRIPE)
    integration.set_secrets({"secret_key": "sk_super_stock_never_render"})
    integration.save(update_fields=["encrypted_secrets", "updated_at"])
    integration_change = client.get(reverse("admin:integrations_integrationconfig_change", args=[integration.pk]))
    for expert_response in (user_list, user_change, integration_list, integration_change):
        assert expert_response.status_code == 200
        expert_html = expert_response.content.decode()
        assert "maneg-layout" not in expert_html
        assert "FABINZI Control Center" not in expert_html
    assert b"sk_super_stock_never_render" not in integration_change.content
    assert integration.encrypted_secrets.encode() not in integration_change.content

    TOTPDevice.objects.create(user=root, name="super-mfa", confirmed=True)
    client.force_login(root)
    assert client.get("/super/").status_code == 302
    client.logout()
    verify_otp(client, root, name="super-mfa-verified")
    assert client.get("/super/").status_code == 200


@pytest.mark.django_db
def test_superuser_has_full_maneg_platform_owner_scope(client):
    root = User.objects.create_superuser(username="v29-owner", email="owner@example.test", password="strong-pass-123")
    client.force_login(root)
    for route in (
        "/Maneg/",
        "/Maneg/verification/",
        "/Maneg/design-review/",
        "/Maneg/artwork-ip/",
        "/Maneg/catalog/",
        "/Maneg/orders/",
        "/Maneg/production-routing/",
        "/Maneg/subscriptions/",
        "/Maneg/finance/",
        "/Maneg/finance-policies/",
        "/Maneg/integrations/",
        "/Maneg/system/",
        "/super/",
    ):
        assert client.get(route).status_code == 200, route


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

    config = ApplicationReviewConfiguration.objects.get(singleton_key=1)
    compatibility = client.post(
        reverse("fabinzi_admin:platform_ops_applicationreviewconfiguration_change", args=[config.pk]),
        {"application_initial_review_target_hours": "32", "_save": "Save"},
    )
    assert compatibility.status_code == 302
    config.refresh_from_db()
    assert config.application_initial_review_target_hours == 32

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
    assert maneg["Referrer-Policy"] == "same-origin"

    root = User.objects.create_superuser(username="v29-index-root", email="idx@example.test", password="strong-pass-123")
    client.force_login(root)
    super_response = client.get("/super/")
    assert super_response["X-Robots-Tag"] == "noindex, nofollow, noarchive"
    assert "private" in super_response["Cache-Control"] and "no-store" in super_response["Cache-Control"]
    assert super_response["Referrer-Policy"] == "same-origin"

    sitemap = client.get("/sitemap.xml").content.decode()
    assert "/Maneg/" not in sitemap
    assert "/super/" not in sitemap
