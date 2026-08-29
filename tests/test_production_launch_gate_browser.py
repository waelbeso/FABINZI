import os
from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from apps.platform_ops.models import MaintenanceWindow


User = get_user_model()
ARTIFACT_DIR = Path("artifacts/production-launch-gate")
SCREENSHOTS = [
    "01-home-desktop-en-light.png",
    "02-terms-desktop-en-light.png",
    "03-privacy-desktop-en-light.png",
    "04-returns-desktop-en-light.png",
    "05-support-desktop-en-light.png",
    "06-about-desktop-en-light.png",
    "07-shipping-desktop-en-light.png",
    "08-login-desktop-en-light.png",
    "09-404-desktop-en-light.png",
    "10-maintenance-desktop-en-light.png",
    "11-home-mobile-ar-dark.png",
    "12-private-noindex-desktop-en-light.png",
]


def _chrome(width=1440, height=1000, language="en-US,en"):
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument(f"--window-size={width},{height}")
    options.add_experimental_option("prefs", {"intl.accept_languages": language})
    options.set_capability("goog:loggingPrefs", {"browser": "ALL"})
    return webdriver.Chrome(options=options)


def _url(live_server, name, *, language="en"):
    return live_server.url + reverse(name) + f"?lang={language}"


def _wait_ready(driver):
    WebDriverWait(driver, 12).until(EC.presence_of_element_located((By.TAG_NAME, "body")))


def _assert_healthy_document(driver):
    source = driver.page_source.lower()
    assert "traceback (most recent call last)" not in source
    assert "django debug" not in source
    assert driver.execute_script("return document.documentElement.scrollWidth <= window.innerWidth + 2")
    assert driver.find_elements(By.CSS_SELECTOR, 'img[src*="fabinzi-logo"]')
    severe = [entry for entry in driver.get_log("browser") if entry.get("level") == "SEVERE"]
    assert not severe, severe


def _shot(driver, name):
    assert name in SCREENSHOTS
    _assert_healthy_document(driver)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    assert driver.save_screenshot(str(ARTIFACT_DIR / name))


def _login_browser(driver, live_server, client, user):
    client.force_login(user)
    cookie = client.cookies[settings.SESSION_COOKIE_NAME].value
    driver.get(live_server.url + "/")
    driver.add_cookie({"name": settings.SESSION_COOKIE_NAME, "value": cookie, "path": "/"})


@pytest.mark.django_db(transaction=True)
def test_production_launch_gate_real_chrome_evidence(client, live_server):
    if os.getenv("CI") != "true":
        pytest.skip("Production Launch Gate browser evidence is CI-only.")

    driver = _chrome()
    try:
        pages = [
            ("home", "01-home-desktop-en-light.png"),
            ("terms", "02-terms-desktop-en-light.png"),
            ("privacy", "03-privacy-desktop-en-light.png"),
            ("returns", "04-returns-desktop-en-light.png"),
            ("support", "05-support-desktop-en-light.png"),
            ("about", "06-about-desktop-en-light.png"),
            ("shipping", "07-shipping-desktop-en-light.png"),
        ]
        for route, filename in pages:
            driver.get(_url(live_server, route))
            _wait_ready(driver)
            assert driver.find_element(By.TAG_NAME, "html").get_attribute("dir") == "ltr"
            assert "index,follow" in driver.find_element(By.CSS_SELECTOR, 'meta[name="robots"]').get_attribute("content")
            _shot(driver, filename)

        driver.get(live_server.url + reverse("two_factor:login") + "?lang=en")
        _wait_ready(driver)
        assert "FABINZI" in driver.page_source
        _shot(driver, "08-login-desktop-en-light.png")

        with override_settings(DEBUG=False):
            driver.get(live_server.url + "/this-launch-route-does-not-exist/?lang=en")
            _wait_ready(driver)
            assert "This page is not here" in driver.page_source
            _shot(driver, "09-404-desktop-en-light.png")

        window = MaintenanceWindow.objects.create(
            enabled=True,
            mode=MaintenanceWindow.Mode.RESTRICT,
            message_en="Scheduled launch-readiness maintenance window.",
            message_ar="نافذة صيانة مجدولة للتحقق من جاهزية الإطلاق.",
            starts_at=timezone.now(),
        )
        driver.get(_url(live_server, "terms"))
        _wait_ready(driver)
        assert "Maintenance in progress" in driver.page_source
        _shot(driver, "10-maintenance-desktop-en-light.png")
        window.delete()
    finally:
        driver.quit()

    mobile = _chrome(width=390, height=844, language="ar,en")
    try:
        mobile.get(live_server.url + "/")
        mobile.get_log("browser")
        mobile.execute_script("localStorage.setItem('fabinzi-theme','dark')")
        mobile.get(_url(live_server, "home", language="ar"))
        _wait_ready(mobile)
        html = mobile.find_element(By.TAG_NAME, "html")
        assert html.get_attribute("dir") == "rtl"
        assert html.get_attribute("data-theme") == "dark"
        _shot(mobile, "11-home-mobile-ar-dark.png")
    finally:
        mobile.quit()

    user = User.objects.create_user(username="launch-gate-private-user", password="launch-gate-password-123", theme_preference="light")
    private = _chrome()
    try:
        _login_browser(private, live_server, client, user)
        private.get_log("browser")
        private.get(_url(live_server, "app-home"))
        _wait_ready(private)
        robots = private.find_element(By.CSS_SELECTOR, 'meta[name="robots"]').get_attribute("content")
        assert "noindex" in robots and "nofollow" in robots
        _shot(private, "12-private-noindex-desktop-en-light.png")
    finally:
        private.quit()

    assert sorted(path.name for path in ARTIFACT_DIR.glob("*.png")) == sorted(SCREENSHOTS)
