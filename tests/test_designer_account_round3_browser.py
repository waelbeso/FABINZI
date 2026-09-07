import os
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connection
from django.utils import timezone
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC

from apps.finance.models import PayoutProfile
from apps.finance.services import review_payout_profile
from apps.notifications.models import Notification
from apps.storefront.models import Storefront
from apps.subscriptions.services import entitlement_summary

from .test_designer_portal_browser import (
    _active_designer,
    _chrome,
    _click,
    _click_element,
    _login,
    _no_overflow,
    _replace,
    _shot,
    _wait,
)

User = get_user_model()


def _only_active_nav(driver):
    return len(driver.find_elements(By.CSS_SELECTOR, ".designer-nav a[aria-current='page']")) == 1


def _payout_form(driver):
    return driver.find_element(By.XPATH, '//form[.//input[@type="hidden" and @name="action" and @value="payout_profile"]]')


@pytest.mark.django_db(transaction=True)
def test_entitlement_summary_owns_subscription_lock_transaction_and_rolls_starter_period(v2_3_reference_rows):
    owner = User.objects.create_user(
        username="designer-round3-transaction-owner",
        password="password12345",
        email="round3-transaction@designer.test",
    )
    org = _active_designer(owner)
    assert connection.in_atomic_block is False
    subscription = entitlement_summary(org)["subscription"]
    now = timezone.now()
    stale_end = now - timedelta(days=1)
    subscription.current_period_start = stale_end - timedelta(days=31)
    subscription.current_period_end = stale_end
    subscription.save(update_fields=["current_period_start", "current_period_end", "updated_at"])
    period_count = subscription.periods.count()

    assert connection.in_atomic_block is False
    summary = entitlement_summary(org, now=now)

    subscription.refresh_from_db()
    assert summary["plan_code"] == "designer_starter"
    assert subscription.current_period_start == stale_end
    assert subscription.current_period_end > now
    assert subscription.periods.count() == period_count + 1
    assert connection.in_atomic_block is False


@pytest.mark.django_db(transaction=True)
def test_designer_round3_real_chrome_workspace_payout_subscription_notifications(client, live_server, v2_3_reference_rows):
    if os.getenv("CI") != "true":
        pytest.skip("Real Chrome Designer Round 3 QA is CI-only.")

    owner = User.objects.create_user(
        username="designer-round3-browser-owner",
        password="password12345",
        email="round3-browser@designer.test",
        theme_preference="light",
        language_preference="en",
    )
    org = _active_designer(owner)
    Storefront.objects.create(
        organization=org,
        slug="round3-browser-store",
        status=Storefront.Status.DRAFT,
        name_en="Round 3 Browser Store",
        name_ar="متجر الجولة الثالثة",
        about_en="Read first Store details",
    )
    notification = Notification.objects.create(
        recipient=owner,
        type="round3_browser",
        title_en="Round 3 browser notification",
        title_ar="إشعار متصفح الجولة الثالثة",
        body_en="Canonical notification",
        body_ar="إشعار أصلي",
        destination="/designer/",
    )

    driver = _chrome()
    synthetic_iban = "EG00ROUNDTHREE00001234"
    try:
        _login(driver, live_server, client, owner)
        wait = _wait(driver)

        driver.get(f"{live_server.url}/designer/?org={org.pk}&lang=en")
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".designer-workspace")))
        assert _only_active_nav(driver)
        assert not driver.find_elements(By.XPATH, '//a[normalize-space(.)="New Garment Design"]')
        assert not driver.find_elements(By.XPATH, '//a[normalize-space(.)="New Artwork"]')
        assert _no_overflow(driver)
        _shot(driver, "round3-01-overview-desktop-en.png")

        _click(driver, By.CSS_SELECTOR, 'a[href^="/designer/designs/"]')
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "Garment Designs"))
        assert _only_active_nav(driver)
        assert driver.find_element(By.CSS_SELECTOR, ".designer-nav a[aria-current='page']").text == "Garment Designs"
        _shot(driver, "round3-02-designs-active.png")

        _click(driver, By.CSS_SELECTOR, 'a[href^="/designer/artworks/"]')
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "Artwork"))
        assert _only_active_nav(driver)
        assert driver.find_element(By.CSS_SELECTOR, ".designer-nav a[aria-current='page']").text == "Artwork"
        _shot(driver, "round3-03-artwork-active.png")

        _click(driver, By.CSS_SELECTOR, 'a[href^="/designer/store/"]')
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "Round 3 Browser Store"))
        assert _only_active_nav(driver)
        details = driver.find_element(By.CSS_SELECTOR, "details.round3-store-edit")
        assert details.get_attribute("open") is None
        _shot(driver, "round3-04-store-readonly.png")
        summary = details.find_element(By.TAG_NAME, "summary")
        _click_element(driver, summary)
        wait.until(lambda _d: details.get_attribute("open") is not None)
        form = details.find_element(By.TAG_NAME, "form")
        _replace(driver, form.find_element(By.NAME, "name_en"), "Round 3 Browser Store Updated")
        _click_element(driver, form.find_element(By.CSS_SELECTOR, 'button[type="submit"]'))
        wait.until(lambda _d: Storefront.objects.get(organization=org).name_en == "Round 3 Browser Store Updated")
        details = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "details.round3-store-edit")))
        assert details.get_attribute("open") is None
        assert Storefront.objects.get(organization=org).status == Storefront.Status.DRAFT
        _shot(driver, "round3-05-store-after-save.png")

        _click(driver, By.CSS_SELECTOR, 'a[href^="/designer/finance/"]')
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "Payout profile"))
        assert _only_active_nav(driver)
        form = _payout_form(driver)
        _replace(driver, form.find_element(By.NAME, "account_holder"), "Round Three Browser Owner")
        _replace(driver, form.find_element(By.NAME, "bank_name"), "Round Three Browser Bank")
        _replace(driver, form.find_element(By.NAME, "iban"), synthetic_iban)
        _replace(driver, form.find_element(By.NAME, "country"), "EG")
        _replace(driver, form.find_element(By.NAME, "payout_currency"), "EGP")
        _click_element(driver, form.find_element(By.CSS_SELECTOR, 'button[type="submit"]'))
        wait.until(lambda _d: PayoutProfile.objects.filter(organization=org, iban_last4="1234").exists())
        profile = PayoutProfile.objects.get(organization=org)
        first_ciphertext = profile.iban_encrypted
        assert synthetic_iban not in driver.page_source
        assert "IBAN •••• 1234" in driver.page_source
        assert _payout_form(driver).find_element(By.NAME, "iban").get_attribute("value") == ""
        _shot(driver, "round3-06-finance-masked-after-save.png")

        form = _payout_form(driver)
        _replace(driver, form.find_element(By.NAME, "bank_name"), "Round Three Browser Bank Updated")
        assert form.find_element(By.NAME, "iban").get_attribute("value") == ""
        _click_element(driver, form.find_element(By.CSS_SELECTOR, 'button[type="submit"]'))
        wait.until(lambda _d: PayoutProfile.objects.get(organization=org).bank_name == "Round Three Browser Bank Updated")
        profile.refresh_from_db()
        assert profile.iban_encrypted == first_ciphertext
        assert profile.iban_last4 == "1234"

        form = _payout_form(driver)
        checkbox = form.find_element(By.NAME, "submit_for_verification")
        _click_element(driver, checkbox)
        _click_element(driver, form.find_element(By.CSS_SELECTOR, 'button[type="submit"]'))
        wait.until(lambda _d: PayoutProfile.objects.get(organization=org).status == PayoutProfile.Status.PENDING)
        profile.refresh_from_db()
        assert profile.iban_encrypted == first_ciphertext

        reviewer = User.objects.create_user(username="round3-browser-reviewer", password="password12345", is_staff=True)
        reviewer.user_permissions.add(Permission.objects.get(codename="change_payoutprofile"))
        review_payout_profile(profile=profile, reviewer=reviewer, decision=PayoutProfile.Status.VERIFIED, notes="Browser QA verified")
        driver.get(f"{live_server.url}/designer/finance/?org={org.pk}&lang=en")
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "read-only"))
        assert not driver.find_elements(By.XPATH, '//form[.//input[@name="action" and @value="payout_profile"]]')
        assert synthetic_iban not in driver.page_source
        _shot(driver, "round3-07-finance-verified-readonly.png")

        _click(driver, By.CSS_SELECTOR, 'a[href^="/designer/subscription/"]')
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "Actual entitlement"))
        assert _only_active_nav(driver)
        assert "Designer Starter" in driver.page_source
        assert "Designer Pro" in driver.page_source
        assert "No paid renewal currently due" in driver.page_source
        upgrade_form = driver.find_element(By.XPATH, '//form[.//input[@name="action" and @value="upgrade"]]')
        _click_element(driver, upgrade_form.find_element(By.CSS_SELECTOR, 'button[type="submit"]'))
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "confirmed billing evidence"))
        org.professional_subscription.refresh_from_db()
        assert org.professional_subscription.current_plan.code == "designer_starter"
        _shot(driver, "round3-08-subscription-desktop-en.png")

        _click(driver, By.CSS_SELECTOR, 'a[href^="/designer/notifications/"]')
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "Round 3 browser notification"))
        assert _only_active_nav(driver)
        assert "designer-workspace" in driver.page_source
        mark_form = driver.find_element(By.XPATH, '//form[.//input[@name="action" and @value="mark_all_read"]]')
        _click_element(driver, mark_form.find_element(By.CSS_SELECTOR, 'button[type="submit"]'))
        wait.until(lambda _d: Notification.objects.get(pk=notification.pk).is_read)
        _shot(driver, "round3-09-notifications-designer-shell.png")

        driver.set_window_size(390, 844)
        for path, shot in (
            (f"/designer/?org={org.pk}&lang=en", "round3-10-overview-mobile.png"),
            (f"/designer/finance/?org={org.pk}&lang=en", "round3-11-finance-mobile.png"),
            (f"/designer/subscription/?org={org.pk}&lang=en", "round3-12-subscription-mobile.png"),
            (f"/designer/notifications/?org={org.pk}&lang=en", "round3-13-notifications-mobile.png"),
        ):
            driver.get(live_server.url + path)
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".designer-workspace")))
            assert _no_overflow(driver)
            assert _only_active_nav(driver)
            _shot(driver, shot)

        for path, shot in (
            (f"/designer/?org={org.pk}&lang=ar", "round3-14-overview-ar-rtl.png"),
            (f"/designer/finance/?org={org.pk}&lang=ar", "round3-15-finance-ar-rtl.png"),
            (f"/designer/subscription/?org={org.pk}&lang=ar", "round3-16-subscription-ar-rtl.png"),
            (f"/designer/notifications/?org={org.pk}&lang=ar", "round3-17-notifications-ar-rtl.png"),
        ):
            driver.get(live_server.url + path)
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".designer-workspace")))
            assert '<html lang="ar" dir="rtl"' in driver.page_source
            assert _no_overflow(driver)
            assert _only_active_nav(driver)
            assert synthetic_iban not in driver.page_source
            _shot(driver, shot)
    finally:
        driver.quit()
