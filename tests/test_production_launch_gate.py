from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone

from apps.platform_ops.launch_views import bad_request, csrf_failure
from apps.platform_ops.models import MaintenanceWindow


TRUST_ROUTES = ("about", "terms", "privacy", "returns", "shipping", "support")


@pytest.mark.django_db
def test_public_trust_pages_are_bilingual_indexable_and_discoverable(client):
    for name in TRUST_ROUTES:
        en = client.get(reverse(name) + "?lang=en")
        assert en.status_code == 200
        body = en.content.decode()
        assert 'dir="ltr"' in body
        assert 'name="robots" content="index,follow' in body
        assert 'rel="canonical"' in body
        assert 'hreflang="en"' in body and 'hreflang="ar"' in body
        assert reverse("terms") in body and reverse("privacy") in body and reverse("support") in body

        ar = client.get(reverse(name) + "?lang=ar")
        assert ar.status_code == 200
        assert 'dir="rtl"' in ar.content.decode()

    terms = client.get(reverse("terms")).content.decode().lower()
    assert "not represented as reviewed or approved by legal counsel" in terms
    support = client.get(reverse("support")).content.decode().lower()
    assert "does not invent an email address or phone number" in support


@pytest.mark.django_db
def test_robots_and_sitemap_publish_only_public_launch_surfaces(client):
    robots = client.get(reverse("robots-txt"))
    assert robots.status_code == 200
    text = robots.content.decode()
    for path in ("/app/", "/studio/", "/designer/", "/manufacturer/", "/Maneg/", "/api/"):
        assert f"Disallow: {path}" in text

    sitemap = client.get(reverse("sitemap-xml"))
    assert sitemap.status_code == 200
    xml = sitemap.content.decode()
    for name in TRUST_ROUTES:
        assert reverse(name) in xml
    for private_path in ("/app/", "/studio/", "/designer/", "/manufacturer/", "/Maneg/", "/api/"):
        assert private_path not in xml


@pytest.mark.django_db
def test_private_surfaces_receive_noindex_header(client):
    response = client.get(reverse("app-home"))
    assert response.status_code in {302, 403}
    assert "noindex" in response.headers.get("X-Robots-Tag", "")
    assert "nofollow" in response.headers.get("X-Robots-Tag", "")


@pytest.mark.django_db
def test_branded_error_and_csrf_surfaces_do_not_expose_reason(client):
    factory = RequestFactory()
    request = factory.get("/bad-request/?lang=en")
    request.LANGUAGE_CODE = "en"
    request.user = AnonymousUser()
    response = bad_request(request)
    assert response.status_code == 400
    assert b"FABINZI" in response.content

    request = factory.post("/checkout/")
    request.LANGUAGE_CODE = "en"
    request.user = AnonymousUser()
    csrf = csrf_failure(request, reason="SECRET INTERNAL CSRF DIAGNOSTIC")
    assert csrf.status_code == 403
    assert b"FABINZI" in csrf.content
    assert b"SECRET INTERNAL CSRF DIAGNOSTIC" not in csrf.content

    enforced = client.__class__(enforce_csrf_checks=True)
    response = enforced.post("/")
    assert response.status_code == 403
    assert b"secure form session" in response.content


@pytest.mark.django_db
def test_maintenance_restriction_is_branded_bilingual_503(client):
    MaintenanceWindow.objects.create(
        enabled=True,
        mode=MaintenanceWindow.Mode.RESTRICT,
        message_en="Scheduled repository launch-gate maintenance.",
        message_ar="صيانة مجدولة لاختبار بوابة الإطلاق.",
        starts_at=timezone.now(),
    )
    en = client.get(reverse("terms") + "?lang=en")
    assert en.status_code == 503
    assert b"Maintenance in progress" in en.content
    ar = client.get(reverse("terms") + "?lang=ar")
    assert ar.status_code == 503
    assert "نجري أعمال صيانة" in ar.content.decode()


@pytest.mark.django_db
def test_brand_assets_and_health_payloads_are_safe(client, monkeypatch):
    assert client.get(reverse("favicon")).status_code == 200
    assert client.get(reverse("apple-touch-icon")).status_code == 200
    assert client.get(reverse("site-manifest")).status_code == 200

    monkeypatch.setenv("RENDER_GIT_BRANCH", "work/production-launch-gate")
    monkeypatch.setenv("RENDER_GIT_COMMIT", "a" * 40)
    monkeypatch.setenv("RENDER_SERVICE_NAME", "fabinzi-example-web")
    monkeypatch.setenv("DJANGO_SECRET_KEY", "must-not-leak")
    health = client.get(reverse("healthz"))
    payload = health.json()
    assert payload["deployment"]["commit"] == "a" * 40
    assert "must-not-leak" not in health.content.decode()
    ready = client.get(reverse("readyz"))
    assert ready.status_code == 200
    assert ready.json() == {"status": "ready", "database": "ok"}


def test_production_source_contracts_fail_closed_and_keep_demo_out_of_blueprint():
    root = Path(settings.BASE_DIR)
    settings_source = (root / "config" / "settings.py").read_text()
    assert "DJANGO_SECRET_KEY must be explicitly configured outside DEBUG mode" in settings_source
    assert "FABINZI_PUBLIC_BASE_URL must use HTTPS outside DEBUG mode" in settings_source
    assert 'CSRF_FAILURE_VIEW = "apps.platform_ops.launch_views.csrf_failure"' in settings_source

    blueprint = (root / "render.yaml").read_text()
    assert "PRIVATE_MEDIA_STORAGE_MODE\n        value: s3" in blueprint
    assert "FABINZI_DEMO_SEED_ENABLED\n        value: \"false\"" in blueprint
    assert "DEMO_ADMIN_PASSWORD" not in blueprint
    assert "DEMO_CUSTOMER_PASSWORD" not in blueprint
    assert "branch: main" in blueprint


def test_deferred_live_e2e_register_remains_explicitly_unresolved():
    text = (Path(settings.BASE_DIR) / "docs" / "DEFERRED_LIVE_E2E.md").read_text()
    assert "4adf44afbf777bacdf8377f1bb65d6522ce36ac7" in text
    assert "#309" in text and "33278567789" in text
    assert "232 passed / 0 failed" in text
    assert "A — QA environment/configuration failure" in text
    assert "- [ ] actual remote Chrome Global Live E2E execution" in text
    assert "- [ ] manual review of all 20 live screenshots" in text
