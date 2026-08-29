import pytest
from django.contrib.auth import get_user_model
from django.test import Client, override_settings
from apps.integrations.models import IntegrationConfig
from apps.notifications.models import Notification, NotificationDelivery, NotificationPreference

@pytest.mark.django_db
def test_notification_center_is_owner_scoped():
    U=get_user_model(); a=U.objects.create_user(username="a",password="strong-pass-123"); b=U.objects.create_user(username="b",password="strong-pass-123")
    own=Notification.objects.create(recipient=a,type="x",title_en="Own",title_ar="Own"); Notification.objects.create(recipient=b,type="x",title_en="Other",title_ar="Other")
    c=Client(); c.force_login(a); r=c.get("/api/v1/notifications/"); assert r.status_code==200; assert [x["id"] for x in r.json()]==[own.id]

@pytest.mark.django_db
def test_external_delivery_requires_opt_in():
    U=get_user_model(); u=U.objects.create_user(username="u",password="strong-pass-123",email="u@example.com")
    Notification.objects.create(recipient=u,type="x",title_en="A",title_ar="A"); assert NotificationDelivery.objects.count()==0
    p=NotificationPreference.objects.get(user=u); p.email_enabled=True; p.save(); n=Notification.objects.create(recipient=u,type="x",title_en="B",title_ar="B")
    d=NotificationDelivery.objects.get(notification=n); assert d.channel=="email" and d.provider=="mailgun"

@pytest.mark.django_db
def test_sms_preference_requires_e164():
    U=get_user_model(); u=U.objects.create_user(username="u2",password="strong-pass-123"); c=Client(); c.force_login(u)
    r=c.patch("/api/v1/notifications/preferences/",data='{"sms_enabled":true,"phone_e164":"0100"}',content_type="application/json"); assert r.status_code==400

@pytest.mark.django_db
def test_read_endpoint_cannot_read_other_users_notification():
    U=get_user_model(); a=U.objects.create_user(username="a2",password="strong-pass-123"); b=U.objects.create_user(username="b2",password="strong-pass-123"); n=Notification.objects.create(recipient=b,type="x",title_en="X",title_ar="X"); c=Client(); c.force_login(a)
    assert c.post(f"/api/v1/notifications/{n.id}/read/").status_code==404

@pytest.mark.django_db
def test_readiness_endpoint_checks_database():
    r=Client().get("/readyz/"); assert r.status_code==200 and r.json()["status"]=="ready"

@pytest.mark.django_db
def test_security_headers_present():
    r=Client().get("/healthz/"); assert r["Permissions-Policy"]=="camera=(), microphone=(), geolocation=()"; assert r["X-Permitted-Cross-Domain-Policies"]=="none"

def test_production_requires_explicit_integration_key():
    from pathlib import Path
    text=(Path(__file__).resolve().parents[1]/"config"/"settings.py").read_text(); assert 'default=""' in text and 'if DEBUG and not INTEGRATION_ENCRYPTION_KEY' in text
