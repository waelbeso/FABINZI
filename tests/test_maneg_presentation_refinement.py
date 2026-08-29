import os
from pathlib import Path

import pytest
from django.urls import reverse
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC

from apps.audit.models import AuditEvent
from apps.platform_ops.templatetags.maneg import audit_action_label, audit_object_label

from .test_maneg_control_center import otp_login, staff
from .test_maneg_control_center_browser import _chrome, _login_browser, _no_page_overflow, _wait


@pytest.mark.parametrize(
    ("value", "language", "expected"),
    [
        ("control_center.user.suspended", "en", "User suspended"),
        ("control_center.user.suspended", "ar", "تم إيقاف المستخدم"),
        ("platform_ops.maintenancewindow.updated", "en", "Maintenance settings updated"),
        ("platform_ops.maintenancewindow.updated", "ar", "تم تحديث إعدادات الصيانة"),
        ("future_domain.future_widget.activated", "en", "Future widget — Activated"),
        ("future_domain.future_widget.activated", "ar", "Future widget — Activated"),
    ],
)
def test_audit_action_presentation_labels_and_safe_fallback(value, language, expected):
    assert audit_action_label(value, language) == expected
    assert "." not in audit_action_label(value, language)


@pytest.mark.parametrize(
    ("value", "language", "expected"),
    [
        ("accounts.User", "en", "User"),
        ("accounts.User", "ar", "مستخدم"),
        ("platform_ops.MaintenanceWindow", "en", "Maintenance window"),
        ("platform_ops.MaintenanceWindow", "ar", "نافذة الصيانة"),
        ("future_app.FutureWidget", "en", "Future widget"),
        ("future_app.FutureWidget", "ar", "Future widget"),
    ],
)
def test_audit_object_presentation_labels_and_safe_fallback(value, language, expected):
    assert audit_object_label(value, language) == expected
    assert "." not in audit_object_label(value, language)


@pytest.mark.django_db
def test_audit_page_humanizes_without_mutating_storage_and_stays_read_only(client):
    root = staff("presentation-audit-root", superuser=True)
    otp_login(client, root)
    known = AuditEvent.objects.create(
        actor=root,
        action="platform_ops.maintenancewindow.updated",
        object_type="platform_ops.MaintenanceWindow",
        object_id="3",
        metadata={
            "safe_note": "visible-safe",
            "api_key": "must-never-render",
            "nested": {"password": "also-never-render", "safe": "nested-safe"},
        },
    )
    unknown = AuditEvent.objects.create(
        actor=root,
        action="future_domain.future_widget.activated",
        object_type="future_app.FutureWidget",
        object_id="9",
        metadata={"safe_note": "future-safe"},
    )
    original_known = (known.action, known.object_type)
    original_unknown = (unknown.action, unknown.object_type)

    en = client.get(reverse("fabinzi_admin:maneg-audit"), {"lang": "en"})
    assert en.status_code == 200
    en_html = en.content.decode()
    assert "Maintenance settings updated" in en_html
    assert "Maintenance window" in en_html and "#3" in en_html
    assert "Future widget — Activated" in en_html
    assert "Future widget" in en_html and "#9" in en_html
    assert "platform_ops.maintenancewindow.updated" not in en_html
    assert "platform_ops.MaintenanceWindow" not in en_html
    assert "future_domain.future_widget.activated" not in en_html
    assert "future_app.FutureWidget" not in en_html
    assert "visible-safe" in en_html and "nested-safe" in en_html and "future-safe" in en_html
    assert "must-never-render" not in en_html and "also-never-render" not in en_html
    assert en_html.count("Hidden") >= 2

    ar = client.get(reverse("fabinzi_admin:maneg-audit"), {"lang": "ar"})
    assert ar.status_code == 200
    ar_html = ar.content.decode()
    assert "تم تحديث إعدادات الصيانة" in ar_html
    assert "نافذة الصيانة" in ar_html and "#3" in ar_html
    assert "platform_ops.maintenancewindow.updated" not in ar_html
    assert "platform_ops.MaintenanceWindow" not in ar_html

    filtered = client.get(
        reverse("fabinzi_admin:maneg-audit"),
        {"lang": "en", "action": "platform_ops.maintenancewindow.updated"},
    )
    assert filtered.status_code == 200
    assert "Maintenance settings updated" in filtered.content.decode()

    before_count = AuditEvent.objects.count()
    post = client.post(reverse("fabinzi_admin:maneg-audit"), {"action": "delete", "event_id": known.pk})
    assert post.status_code == 200
    assert AuditEvent.objects.count() == before_count

    known.refresh_from_db()
    unknown.refresh_from_db()
    assert (known.action, known.object_type) == original_known
    assert (unknown.action, unknown.object_type) == original_unknown


def test_responsive_maneg_nav_css_preserves_scroll_and_suppresses_native_scrollbar():
    css = Path("static/css/maneg-control-center.css").read_text(encoding="utf-8")
    assert ".maneg-nav{display:flex;overflow:auto;" in css
    assert "scrollbar-width:none" in css
    assert "-ms-overflow-style:none" in css
    assert ".maneg-nav::-webkit-scrollbar{display:none}" in css
    responsive_rule = css.split("@media(max-width:820px)", 1)[1].split("@media(max-width:580px)", 1)[0]
    assert "overflow:hidden" not in responsive_rule


def _assert_mobile_nav_contract(driver, *, expected_dir):
    wait = _wait(driver)
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".maneg-layout")))
    html = driver.find_element(By.TAG_NAME, "html")
    assert html.get_attribute("dir") == expected_dir
    nav = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, ".maneg-nav")))
    metrics = driver.execute_script(
        """
        const nav = arguments[0];
        const style = getComputedStyle(nav);
        const webkit = getComputedStyle(nav, '::-webkit-scrollbar');
        return {
            scrollWidth: nav.scrollWidth,
            clientWidth: nav.clientWidth,
            overflowX: style.overflowX,
            scrollbarWidth: style.scrollbarWidth,
            webkitDisplay: webkit.display,
        };
        """,
        nav,
    )
    assert metrics["scrollWidth"] > metrics["clientWidth"]
    assert metrics["overflowX"] in {"auto", "scroll"}
    assert metrics["scrollbarWidth"] == "none"
    assert metrics["webkitDisplay"] == "none"
    active = nav.find_element(By.CSS_SELECTOR, 'a[aria-current="page"]')
    assert active.is_displayed()
    assert active.get_attribute("href")
    assert _no_page_overflow(driver)
    return nav


@pytest.mark.django_db(transaction=True)
def test_responsive_maneg_nav_scroll_contract_in_real_chrome_ltr_and_rtl(client, live_server):
    if os.getenv("CI") != "true":
        pytest.skip("Real Chrome /Maneg/ presentation QA is CI-only.")

    root = staff("presentation-nav-root", superuser=True)
    root.theme_preference = "light"
    root.language_preference = "en"
    root.save(update_fields=["theme_preference", "language_preference"])
    driver = _chrome(width=390, height=844)
    try:
        _login_browser(driver, live_server, client, root)
        driver.get(f"{live_server.url}/Maneg/?lang=en")
        nav = _assert_mobile_nav_contract(driver, expected_dir="ltr")
        before = driver.execute_script("return arguments[0].scrollLeft", nav)
        driver.execute_script("arguments[0].scrollLeft = arguments[0].scrollWidth", nav)
        after = driver.execute_script("return arguments[0].scrollLeft", nav)
        assert after != before

        root.theme_preference = "dark"
        root.language_preference = "ar"
        root.save(update_fields=["theme_preference", "language_preference"])
        driver.get(f"{live_server.url}/Maneg/?lang=ar")
        _assert_mobile_nav_contract(driver, expected_dir="rtl")
        assert driver.find_element(By.TAG_NAME, "html").get_attribute("data-theme") == "dark"
    finally:
        driver.quit()
