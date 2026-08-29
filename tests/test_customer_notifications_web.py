import pytest
from django.contrib.auth import get_user_model

from apps.notifications.models import Notification, NotificationPreference

User = get_user_model()


@pytest.mark.django_db
def test_notification_center_is_bilingual_private_and_supports_read_state(client):
    customer = User.objects.create_user(username="notify-customer", password="password12345", email="notify@example.test")
    notification = Notification.objects.create(
        recipient=customer,
        type="purchase_update",
        title_en="Your order is confirmed",
        title_ar="تم تأكيد طلبك",
        body_en="Your FABINZI purchase is moving to processing.",
        body_ar="انتقل طلبك على FABINZI إلى مرحلة التجهيز.",
        destination="/purchases/",
    )
    client.force_login(customer)

    response = client.get("/notifications/?lang=ar")
    assert response.status_code == 200
    body = response.content.decode()
    assert '<html lang="ar" dir="rtl"' in body
    assert "تم تأكيد طلبك" in body
    assert "جديد" in body
    assert '<meta name="robots" content="noindex,nofollow,noarchive">' in body

    marked = client.post("/notifications/?lang=ar", {"action": "mark_all_read"}, follow=True)
    assert marked.status_code == 200
    notification.refresh_from_db()
    assert notification.is_read is True
    assert notification.read_at is not None


@pytest.mark.django_db
def test_notification_preferences_are_server_validated_and_persisted(client):
    customer = User.objects.create_user(username="notify-pref-customer", password="password12345", email="customer@example.test")
    client.force_login(customer)

    invalid = client.post(
        "/notifications/",
        {"action": "preferences", "email_enabled": "on", "sms_enabled": "on", "phone_e164": "0100"},
        follow=True,
    )
    assert invalid.status_code == 200
    pref = NotificationPreference.objects.get(user=customer)
    assert pref.email_enabled is False
    assert pref.sms_enabled is False

    saved = client.post(
        "/notifications/",
        {"action": "preferences", "email_enabled": "on", "sms_enabled": "on", "phone_e164": "+201000000000"},
        follow=True,
    )
    assert saved.status_code == 200
    pref.refresh_from_db()
    assert pref.email_enabled is True
    assert pref.sms_enabled is True
    assert pref.phone_e164 == "+201000000000"
    assert "Notification preferences saved" in saved.content.decode()
