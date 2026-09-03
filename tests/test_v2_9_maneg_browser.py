import os

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC

from apps.integrations.models import IntegrationConfig

from .test_maneg_control_center_browser import (
    _chrome,
    _login_browser,
    _no_page_overflow,
    _shot,
    _wait,
)
from .v2_3_support import ensure_v2_3_reference_rows

User = get_user_model()


@pytest.mark.django_db(transaction=True)
def test_v2_9_real_browser_maneg_super_separation(client, live_server):
    if os.getenv("CI") != "true":
        pytest.skip("Real Chrome V2-9 /Maneg/ + /super/ QA is CI-only.")

    # Explicit local setup: this module does not depend on another test module,
    # migration seed visibility, collection order, or pre-existing database rows.
    ensure_v2_3_reference_rows()
    for provider, _label in IntegrationConfig.Provider.choices:
        IntegrationConfig.objects.get_or_create(provider=provider)

    root = User.objects.create_superuser(
        username="v29-browser-root",
        email="v29-browser-root@example.test",
        password="strong-pass-123",
    )
    root.theme_preference = User.Theme.LIGHT
    root.language_preference = User.Language.ENGLISH
    root.save(update_fields=["theme_preference", "language_preference"])

    integration = IntegrationConfig.objects.get(provider=IntegrationConfig.Provider.STRIPE)
    integration.set_secrets({"secret_key": "sk_v29_browser_never_render"})
    integration.save(update_fields=["encrypted_secrets", "updated_at"])

    driver = _chrome(width=1440, height=1000)
    try:
        _login_browser(driver, live_server, client, root)

        driver.get(live_server.url + "/Maneg/subscriptions/?lang=en")
        _wait(driver).until(EC.presence_of_element_located((By.CSS_SELECTOR, ".maneg-layout")))
        assert "Authoritative plan policies" in driver.page_source
        assert "Django administration" not in driver.page_source
        assert _no_page_overflow(driver)
        _shot(driver, "18-maneg-subscriptions-desktop-en-light.png")

        driver.get(live_server.url + "/Maneg/commercial-settings/?lang=en")
        _wait(driver).until(EC.presence_of_element_located((By.CSS_SELECTOR, ".maneg-layout")))
        assert "Application initial-review target" in driver.page_source
        assert "V2 Finance Policy" in driver.page_source
        assert _no_page_overflow(driver)
        _shot(driver, "19-maneg-commercial-settings-desktop-en-light.png")

        driver.get(live_server.url + "/Maneg/integrations/?lang=en")
        _wait(driver).until(EC.presence_of_element_located((By.CSS_SELECTOR, ".maneg-layout")))
        assert "Persisted configuration" in driver.page_source
        assert "sk_v29_browser_never_render" not in driver.page_source
        _shot(driver, "20-maneg-integrations-superuser-desktop-en-light.png")

        driver.get(live_server.url + "/super/")
        _wait(driver).until(EC.presence_of_element_located((By.CSS_SELECTOR, "#site-name")))
        assert "Django administration" in driver.page_source
        assert "FABINZI Control Center" not in driver.page_source
        assert "maneg-layout" not in driver.page_source
        assert "maneg-control-center.css" not in driver.page_source
        _shot(driver, "21-super-stock-django-admin-desktop.png")

        root.theme_preference = User.Theme.DARK
        root.language_preference = User.Language.ARABIC
        root.save(update_fields=["theme_preference", "language_preference"])
        driver.set_window_size(390, 844)
        driver.get(live_server.url + "/Maneg/subscriptions/?lang=ar")
        html = _wait(driver).until(EC.presence_of_element_located((By.TAG_NAME, "html")))
        assert html.get_attribute("dir") == "rtl"
        assert html.get_attribute("data-theme") == "dark"
        assert _no_page_overflow(driver)
        _shot(driver, "22-maneg-subscriptions-mobile-ar-rtl-dark.png")
    finally:
        driver.quit()

    non_super = User.objects.create_user(
        username="v29-browser-integration-denied",
        email="denied@example.test",
        password="strong-pass-123",
        is_staff=True,
    )
    for codename in ("view_integrationconfig", "change_integrationconfig"):
        non_super.user_permissions.add(
            Permission.objects.get(content_type__app_label="integrations", codename=codename)
        )

    denied_driver = _chrome(width=1280, height=900)
    try:
        _login_browser(denied_driver, live_server, client, non_super)
        denied_driver.get(live_server.url + f"/Maneg/integrations/{integration.pk}/")
        _wait(denied_driver).until(lambda d: d.execute_script("return document.readyState") == "complete")
        assert "sk_v29_browser_never_render" not in denied_driver.page_source
        assert "Integration configuration" not in denied_driver.page_source
        assert "/Maneg/integrations/" not in denied_driver.page_source
        assert "/super/" not in denied_driver.page_source
        _shot(denied_driver, "23-maneg-integrations-nonsuper-denied.png")
    finally:
        denied_driver.quit()
