import pytest
from django.urls import reverse
from apps.accounts.models import User
from apps.audit.models import AuditEvent
from apps.integrations.models import IntegrationConfig
from apps.platform_ops.models import MaintenanceWindow, PlatformAnnouncement
from config.release import APP_VERSION
from django.utils import timezone

@pytest.mark.django_db
def test_optional_integrations_disabled_by_default():
    cfg = IntegrationConfig.objects.get(provider=IntegrationConfig.Provider.STRIPE)
    assert cfg.enabled is False
    assert cfg.last_test_status == IntegrationConfig.TestStatus.NEVER

@pytest.mark.django_db
def test_cod_seeded_enabled():
    assert IntegrationConfig.objects.get(provider=IntegrationConfig.Provider.COD).enabled is True

@pytest.mark.django_db
def test_theme_and_language_persist(client):
    user = User.objects.create_user(username="customer", password="strong-pass-123")
    client.force_login(user)
    response = client.post(reverse("profile-preferences"), {"theme": "dark", "language": "ar"})
    assert response.status_code == 302
    user.refresh_from_db()
    assert user.theme_preference == "dark"
    assert user.language_preference == "ar"

@pytest.mark.django_db
def test_audit_event_is_append_only():
    event = AuditEvent.objects.create(action="test")
    event.action = "tampered"
    with pytest.raises(ValueError):
        event.save()

@pytest.mark.django_db
def test_maintenance_keeps_health_available(client):
    MaintenanceWindow.objects.create(enabled=True, mode="restrict", message_ar="صيانة", message_en="Maintenance", starts_at=timezone.now())
    assert client.get("/healthz/").status_code == 200
    assert client.get("/").status_code == 503

@pytest.mark.django_db
def test_active_announcement_window():
    PlatformAnnouncement.objects.create(enabled=True, title_ar="تنبيه", title_en="Notice", message_ar="رسالة", message_en="Message", starts_at=timezone.now())
    assert PlatformAnnouncement.active().count() == 1


def test_health_exposes_only_non_secret_render_source_identity(client, monkeypatch):
    monkeypatch.setenv("RENDER_GIT_BRANCH", "work/global-live-e2e-qa")
    monkeypatch.setenv("RENDER_GIT_COMMIT", "0123456789abcdef0123456789abcdef01234567")
    monkeypatch.setenv("RENDER_SERVICE_NAME", "fabinzi-qa-web")
    monkeypatch.setenv("DJANGO_SECRET_KEY", "must-not-leak")
    monkeypatch.setenv("INTEGRATION_ENCRYPTION_KEY", "must-not-leak-either")

    response = client.get("/healthz/")
    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "status": "ok",
        "service": "fabinzi",
        "version": APP_VERSION,
        "deployment": {
            "branch": "work/global-live-e2e-qa",
            "commit": "0123456789abcdef0123456789abcdef01234567",
            "service": "fabinzi-qa-web",
        },
    }
    rendered = response.content.decode()
    assert "must-not-leak" not in rendered


def test_health_omits_deployment_identity_outside_supported_host_runtime(client, monkeypatch):
    for key in ("RENDER_GIT_BRANCH", "RENDER_GIT_COMMIT", "RENDER_SERVICE_NAME"):
        monkeypatch.delenv(key, raising=False)
    response = client.get("/healthz/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "fabinzi", "version": APP_VERSION}
