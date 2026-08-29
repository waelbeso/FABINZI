import pytest
from django.urls import reverse
from apps.accounts.models import User
from apps.audit.models import AuditEvent
from apps.integrations.models import IntegrationConfig
from apps.platform_ops.models import MaintenanceWindow, PlatformAnnouncement
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
