import os
import re
import unicodedata
from decimal import Decimal
from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from django_otp.plugins.otp_totp.models import TOTPDevice
from selenium import webdriver
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait

from apps.artwork.models import Artwork, ArtworkVersion, IPCase
from apps.checkout.models import CustomerPurchase
from apps.design.models import GarmentDesign, GarmentDesignVersion
from apps.finance.models import FinanceAccount, LedgerEntry, PayoutProfile, SettlementRequest
from apps.finance.services import account_balance
from apps.integrations.models import IntegrationConfig
from apps.organizations.models import Membership, OnboardingApplication, Organization
from apps.platform_ops.models import MaintenanceWindow, PlatformAnnouncement

from .test_manufacturer_portal_acceptance import assigned_job, manufacturer
from .v2_3_support import v2_3_reference_rows

User = get_user_model()
ARTIFACT_DIR = Path("artifacts/maneg-browser-qa")
EXPECTED_SCREENSHOTS = [
    "01-maneg-dashboard-desktop-en-light.png",
    "02-maneg-users-desktop-en-light.png",
    "03-maneg-organizations-desktop-en-light.png",
    "04-maneg-verification-desktop-en-light.png",
    "05-maneg-design-review-desktop-en-light.png",
    "06-maneg-artwork-ip-desktop-en-light.png",
    "07-maneg-catalog-desktop-en-light.png",
    "08-maneg-orders-desktop-en-light.png",
    "09-maneg-production-desktop-en-light.png",
    "10-maneg-finance-desktop-en-light.png",
    "11-maneg-integrations-desktop-en-light.png",
    "12-maneg-announcement-desktop-en-light.png",
    "13-maneg-maintenance-desktop-en-light.png",
    "14-maneg-audit-desktop-en-light.png",
    "15-maneg-dashboard-tablet-en-light.png",
    "16-maneg-dashboard-mobile-ar-rtl-dark.png",
    "17-maneg-finance-mobile-ar-rtl-dark.png",
]


def _chrome(*, width=1440, height=1000):
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument(f"--window-size={width},{height}")
    options.add_experimental_option("prefs", {"intl.accept_languages": "en-US,en,ar"})
    return webdriver.Chrome(options=options)


def _wait(driver):
    return WebDriverWait(driver, 12)


def _otp_login(client, user):
    device = TOTPDevice.objects.create(user=user, name="maneg-browser", confirmed=True)
    client.force_login(user)
    session = client.session
    session["otp_device_id"] = device.persistent_id
    session.save()


def _login_browser(driver, live_server, client, user):
    _otp_login(client, user)
    session_cookie = client.cookies[settings.SESSION_COOKIE_NAME].value
    driver.get(live_server.url + "/")
    driver.add_cookie({"name": settings.SESSION_COOKIE_NAME, "value": session_cookie, "path": "/"})


def _click_element(driver, element):
    ActionChains(driver).scroll_to_element(element).move_to_element(element).pause(0.05).click().perform()
    return element


def _click(driver, by, locator):
    return _click_element(driver, _wait(driver).until(EC.element_to_be_clickable((by, locator))))


def _replace(driver, element, value):
    ActionChains(driver).scroll_to_element(element).move_to_element(element).pause(0.03).click().perform()
    element.send_keys(Keys.CONTROL, "a")
    element.send_keys(str(value))


def _shot(driver, name):
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    assert driver.save_screenshot(str(ARTIFACT_DIR / name))


def _no_page_overflow(driver):
    return bool(driver.execute_script("return document.documentElement.scrollWidth <= window.innerWidth + 1"))


def _clear_artifacts():
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    for path in ARTIFACT_DIR.glob("*.png"):
        path.unlink()


def _form_with_hidden(driver, name, value):
    return driver.find_element(By.XPATH, f'//form[.//input[@type="hidden" and @name="{name}" and @value="{value}"]]')


def _confirm_visible_action(driver, element, *, expected_text=None):
    _click_element(driver, element)
    alert = _wait(driver).until(EC.alert_is_present())
    actual_text = alert.text
    if expected_text is not None:
        assert expected_text in actual_text
    alert.accept()
    return actual_text


def _decimal_values(text):
    normalized = []
    for char in text:
        try:
            normalized.append(str(unicodedata.decimal(char)))
            continue
        except (TypeError, ValueError):
            pass
        if char in {",", "\u066b"}:
            normalized.append(".")
        elif char in {"\u066c", "\u00a0", "\u202f"}:
            continue
        else:
            normalized.append(char)
    return {
        Decimal(token)
        for token in re.findall(r"-?\d+(?:\.\d+)?", "".join(normalized))
    }


@pytest.mark.django_db(transaction=True)
def test_maneg_control_center_real_chrome_a_to_l(client, live_server, v2_3_reference_rows):
    if os.getenv("CI") != "true":
        pytest.skip("Real Chrome /Maneg/ QA is CI-only.")

    _clear_artifacts()
    root = User.objects.create_superuser(username="maneg-browser-root", email="maneg-root@example.test", password="strong-pass-123")
    root.theme_preference = User.Theme.LIGHT
    root.language_preference = User.Language.ENGLISH
    root.save(update_fields=["theme_preference", "language_preference"])
    for provider, _label in IntegrationConfig.Provider.choices:
        IntegrationConfig.objects.get_or_create(
            provider=provider,
            defaults={"enabled": provider == IntegrationConfig.Provider.COD},
        )
    suspend_target = User.objects.create_user(username="maneg-browser-target", email="target@example.test", password="strong-pass-123")

    # Real submitted onboarding case for Designer verification.
    applicant = User.objects.create_user(username="maneg-browser-applicant", email="applicant@example.test", password="strong-pass-123")
    review_org = Organization.objects.create(
        kind=Organization.Kind.DESIGNER,
        display_name="Browser Review Studio",
        email="review-studio@example.test",
        verification_status=Organization.VerificationStatus.PENDING,
        created_by=applicant,
    )
    Membership.objects.create(organization=review_org, user=applicant, role=Membership.Role.OWNER)
    application = OnboardingApplication.objects.create(
        organization=review_org,
        status=OnboardingApplication.Status.SUBMITTED,
        submitted_at=timezone.now(),
    )

    # Real Manufacturer + canonical order/production/fulfillment chain.
    _, manufacturer_org, _, _ = manufacturer("maneg-browser-manufacturer")
    production = assigned_job(manufacturer_org, prefix="maneg-browser-design")
    purchase = CustomerPurchase.objects.create(
        checkout=production["order"].checkout,
        customer=production["customer"],
        status=CustomerPurchase.Status.CONFIRMED,
        payment_method=CustomerPurchase.PaymentMethod.COD,
        subtotal=production["order"].subtotal,
        total=production["order"].total,
        currency=production["order"].currency,
        shipping_snapshot=production["order"].shipping_snapshot,
        confirmed_at=timezone.now(),
    )
    production["order"].purchase = purchase
    production["order"].save(update_fields=["purchase"])

    # Real submitted technical design review case.
    review_design = GarmentDesign.objects.create(
        organization=production["designer"],
        title="Browser Technical Jacket",
        status=GarmentDesign.Status.IN_REVIEW,
        created_by=production["owner"],
    )
    review_version = GarmentDesignVersion.objects.create(
        design=review_design,
        version_number=1,
        status=GarmentDesignVersion.Status.SUBMITTED,
        base_material="Cotton twill",
        technical_specs={"gsm": 260, "seam_mm": 8},
        created_by=production["owner"],
        submitted_at=timezone.now(),
    )

    # Real Artwork review/IP moderation state.
    review_artwork = Artwork.objects.create(
        organization=production["designer"],
        title="Browser Rights Mark",
        status=Artwork.Status.IN_REVIEW,
        created_by=production["owner"],
    )
    ArtworkVersion.objects.create(
        artwork=review_artwork,
        version_number=1,
        status=ArtworkVersion.Status.SUBMITTED,
        created_by=production["owner"],
        submitted_at=timezone.now(),
    )
    ip_case = IPCase.objects.create(
        artwork=review_artwork,
        reporter_name="Browser Rights Holder",
        reporter_email="rights-browser@example.test",
        claimant_rights="Persisted rights statement",
        allegation="Persisted IP claim",
    )

    # Real ledger-backed Manufacturer finance and a requested settlement.
    account = FinanceAccount.objects.create(
        account_type=FinanceAccount.AccountType.ORGANIZATION,
        organization=manufacturer_org,
        currency="EGP",
    )
    LedgerEntry.objects.create(
        account=account,
        entry_type=LedgerEntry.EntryType.MANUFACTURER_EARNING,
        amount=Decimal("500.00"),
        currency="EGP",
        available_at=timezone.now(),
        memo="Browser QA persisted manufacturing payable",
    )
    payout = PayoutProfile.objects.create(
        organization=manufacturer_org,
        method=PayoutProfile.Method.BANK,
        account_holder=manufacturer_org.display_name,
        destination_hint="•••• 7788",
        status=PayoutProfile.Status.VERIFIED,
        verified_by=root,
        verified_at=timezone.now(),
    )
    settlement = SettlementRequest.objects.create(
        organization=manufacturer_org,
        account=account,
        payout_profile=payout,
        amount=Decimal("150.00"),
        currency="EGP",
        payout_snapshot={"method": "bank", "account_holder": manufacturer_org.display_name, "destination_hint": "•••• 7788"},
        requested_by=root,
    )

    driver = _chrome()
    try:
        _login_browser(driver, live_server, client, root)
        wait = _wait(driver)

        # A. Control Center dashboard.
        driver.get(f"{live_server.url}/Maneg/?lang=en")
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".maneg-layout")))
        assert "Control Center" in driver.page_source
        assert "Django administration" not in driver.page_source
        assert _no_page_overflow(driver)
        _shot(driver, EXPECTED_SCREENSHOTS[0])

        # B. User + organization review.
        driver.get(f"{live_server.url}/Maneg/users/?lang=en")
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), suspend_target.username))
        assert _no_page_overflow(driver)
        _shot(driver, EXPECTED_SCREENSHOTS[1])
        user_form = _form_with_hidden(driver, "user_id", suspend_target.pk)
        _confirm_visible_action(
            driver,
            user_form.find_element(By.CSS_SELECTOR, 'button[type="submit"]'),
            expected_text="Suspend this account?",
        )
        wait.until(lambda _d: not User.objects.get(pk=suspend_target.pk).is_active)

        driver.get(f"{live_server.url}/Maneg/organizations/?lang=en")
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), manufacturer_org.display_name))
        assert _no_page_overflow(driver)
        _shot(driver, EXPECTED_SCREENSHOTS[2])
        _click(driver, By.XPATH, f'//a[.//strong[normalize-space(.)="{manufacturer_org.display_name}"]]')
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "Members & roles"))
        assert manufacturer_org.display_name in driver.page_source

        driver.get(f"{live_server.url}/Maneg/verification/?lang=en")
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), review_org.display_name))
        assert _no_page_overflow(driver)
        _shot(driver, EXPECTED_SCREENSHOTS[3])
        _click(driver, By.CSS_SELECTOR, f'a[href="/Maneg/verification/{application.pk}/"]')
        wait.until(EC.presence_of_element_located((By.NAME, "review_notes")))
        _replace(driver, driver.find_element(By.NAME, "review_notes"), "Browser evidence reviewed")
        _click(driver, By.CSS_SELECTOR, 'button[name="decision"][value="approved"]')
        wait.until(lambda _d: OnboardingApplication.objects.get(pk=application.pk).status == OnboardingApplication.Status.APPROVED)

        # C. Designer verification / Garment Design review.
        driver.get(f"{live_server.url}/Maneg/design-review/?lang=en")
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), review_design.title))
        assert _no_page_overflow(driver)
        _shot(driver, EXPECTED_SCREENSHOTS[4])
        _click(driver, By.CSS_SELECTOR, f'a[href="/Maneg/design-review/{review_version.pk}/"]')
        wait.until(EC.presence_of_element_located((By.NAME, "review_notes")))
        _replace(driver, driver.find_element(By.NAME, "review_notes"), "Browser technical review accepted")
        _click(driver, By.CSS_SELECTOR, 'button[name="decision"][value="approved"]')
        wait.until(lambda _d: GarmentDesignVersion.objects.get(pk=review_version.pk).status == GarmentDesignVersion.Status.APPROVED)

        # D/E. Manufacturer inspection plus Artwork/IP moderation.
        driver.get(f"{live_server.url}/Maneg/artwork-ip/?lang=en")
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), review_artwork.title))
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), f"IP #{ip_case.pk}"))
        assert _no_page_overflow(driver)
        _shot(driver, EXPECTED_SCREENSHOTS[5])
        _click(driver, By.CSS_SELECTOR, f'a[href="/Maneg/artwork-ip/case/{ip_case.pk}/"]')
        wait.until(EC.presence_of_element_located((By.NAME, "staff_notes")))
        _replace(driver, driver.find_element(By.NAME, "staff_notes"), "Browser moderation evidence reviewed")
        _click(driver, By.CSS_SELECTOR, 'button[name="action"][value="takedown"]')
        wait.until(lambda _d: IPCase.objects.get(pk=ip_case.pk).resolution == IPCase.Resolution.TAKEDOWN)

        # Store/catalog uses the existing Storefront/StoreProduct domain.
        driver.get(f"{live_server.url}/Maneg/catalog/?lang=en")
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), production["store_product"].title_en))
        assert _no_page_overflow(driver)
        _shot(driver, EXPECTED_SCREENSHOTS[6])

        # F. Parent purchase -> child order -> canonical production/fulfillment inspection.
        driver.get(f"{live_server.url}/Maneg/orders/?lang=en")
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), str(purchase.number)))
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), str(production["order"].number)))
        assert "CustomerPurchase" in driver.page_source and "CustomerOrder" in driver.page_source
        assert _no_page_overflow(driver)
        _shot(driver, EXPECTED_SCREENSHOTS[7])

        driver.get(f"{live_server.url}/Maneg/production/?lang=en")
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), str(production["order"].number)))
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), manufacturer_org.display_name))
        assert _no_page_overflow(driver)
        _shot(driver, EXPECTED_SCREENSHOTS[8])

        # G. Real finance / settlement.
        driver.get(f"{live_server.url}/Maneg/finance/?lang=en")
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "500.00"))
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "150.00"))
        assert "•••• 7788" in driver.page_source
        assert _no_page_overflow(driver)
        _shot(driver, EXPECTED_SCREENSHOTS[9])
        settlement_form = _form_with_hidden(driver, "settlement_id", settlement.pk)
        approve = settlement_form.find_element(By.CSS_SELECTOR, 'button[name="action"][value="approve_settlement"]')
        _click_element(driver, approve)
        wait.until(lambda _d: SettlementRequest.objects.get(pk=settlement.pk).status == SettlementRequest.Status.APPROVED)

        # H. Integrations and a real internal COD test.
        driver.get(f"{live_server.url}/Maneg/integrations/?lang=en")
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "Cash on Delivery"))
        assert "api_key" not in driver.page_source.lower()
        assert _no_page_overflow(driver)
        _shot(driver, EXPECTED_SCREENSHOTS[10])
        cod = IntegrationConfig.objects.get(provider=IntegrationConfig.Provider.COD)
        driver.get(f"{live_server.url}/Maneg/integrations/{cod.pk}/?lang=en")
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'button[name="action"][value="test"]')))
        _click(driver, By.CSS_SELECTOR, 'button[name="action"][value="test"]')
        wait.until(lambda _d: IntegrationConfig.objects.get(pk=cod.pk).last_test_status == IntegrationConfig.TestStatus.SUCCESS)

        # I. Announcement Banner through visible form controls.
        driver.get(f"{live_server.url}/Maneg/announcements/?lang=en")
        wait.until(EC.presence_of_element_located((By.NAME, "title_en")))
        enabled = driver.find_element(By.NAME, "enabled")
        if not enabled.is_selected():
            _click_element(driver, enabled)
        _replace(driver, driver.find_element(By.NAME, "title_en"), "Browser service notice")
        _replace(driver, driver.find_element(By.NAME, "title_ar"), "تنبيه خدمة المتصفح")
        _replace(driver, driver.find_element(By.NAME, "message_en"), "Persisted browser announcement")
        _replace(driver, driver.find_element(By.NAME, "message_ar"), "إعلان محفوظ من اختبار المتصفح")
        Select(driver.find_element(By.NAME, "severity")).select_by_value("info")
        Select(driver.find_element(By.NAME, "audience")).select_by_value("all")
        assert driver.find_element(By.NAME, "starts_at").get_attribute("value")
        _click(driver, By.CSS_SELECTOR, "form.stack-form button.button")
        wait.until(lambda _d: PlatformAnnouncement.objects.filter(title_en="Browser service notice").exists())
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "Browser service notice"))
        assert _no_page_overflow(driver)
        _shot(driver, EXPECTED_SCREENSHOTS[11])

        # J. Maintenance Mode, including real restrict state and /Maneg/ bypass.
        driver.get(f"{live_server.url}/Maneg/maintenance/?lang=en")
        wait.until(EC.presence_of_element_located((By.NAME, "message_en")))
        enabled = driver.find_element(By.NAME, "enabled")
        if not enabled.is_selected():
            _click_element(driver, enabled)
        Select(driver.find_element(By.NAME, "mode")).select_by_value("restrict")
        _replace(driver, driver.find_element(By.NAME, "message_en"), "Browser scheduled maintenance")
        _replace(driver, driver.find_element(By.NAME, "message_ar"), "صيانة مجدولة من المتصفح")
        assert driver.find_element(By.NAME, "starts_at").get_attribute("value")
        _click(driver, By.CSS_SELECTOR, "form.stack-form button.button")
        wait.until(lambda _d: MaintenanceWindow.objects.filter(message_en="Browser scheduled maintenance", enabled=True).exists())
        window = MaintenanceWindow.objects.get(message_en="Browser scheduled maintenance")
        assert client.get("/").status_code == 503
        driver.get(f"{live_server.url}/Maneg/maintenance/?lang=en")
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "Maintenance window active now"))
        assert _no_page_overflow(driver)
        _shot(driver, EXPECTED_SCREENSHOTS[12])

        # K. Audit history from the visible operations above.
        driver.get(f"{live_server.url}/Maneg/audit/?lang=en")
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "User suspended"))
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "Integration connection tested"))
        audit_text = driver.find_element(By.TAG_NAME, "body").text
        assert "control_center.user.suspended" not in audit_text
        assert "integration.connection.tested" not in audit_text
        assert "platform_ops.MaintenanceWindow" not in audit_text
        assert _no_page_overflow(driver)
        _shot(driver, EXPECTED_SCREENSHOTS[13])

        # Tablet evidence.
        driver.set_window_size(900, 1000)
        driver.get(f"{live_server.url}/Maneg/?lang=en")
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".maneg-layout")))
        assert _no_page_overflow(driver)
        _shot(driver, EXPECTED_SCREENSHOTS[14])

        # L. Arabic RTL + Dark + responsive Control Center.
        root.theme_preference = User.Theme.DARK
        root.language_preference = User.Language.ARABIC
        root.save(update_fields=["theme_preference", "language_preference"])
        driver.set_window_size(390, 844)
        driver.get(f"{live_server.url}/Maneg/?lang=ar")
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".maneg-layout")))
        assert driver.find_element(By.TAG_NAME, "html").get_attribute("dir") == "rtl"
        assert driver.find_element(By.TAG_NAME, "html").get_attribute("data-theme") == "dark"
        assert "مركز التحكم" in driver.page_source
        assert _no_page_overflow(driver)
        _shot(driver, EXPECTED_SCREENSHOTS[15])

        driver.get(f"{live_server.url}/Maneg/finance/?lang=ar")
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".finance-cards.mobile-only")))
        html = driver.find_element(By.TAG_NAME, "html")
        assert html.get_attribute("dir") == "rtl"
        assert html.get_attribute("data-theme") == "dark"
        assert "المالية والمدفوعات والتسويات" in driver.page_source

        balance = account_balance(account)
        assert balance["total"] == Decimal("500.00")
        assert balance["available"] == Decimal("500.00")
        assert balance["reserved"] == Decimal("150.00")
        assert balance["withdrawable"] == Decimal("350.00")

        account_card = wait.until(lambda d: next((
            card for card in d.find_elements(By.CSS_SELECTOR, ".finance-cards.mobile-only .subcard")
            if manufacturer_org.display_name in card.text and "متاح" in card.text and "قابل للسحب" in card.text
        ), False))
        account_values = _decimal_values(account_card.text)
        assert manufacturer_org.display_name in account_card.text
        assert "EGP" in account_card.text
        assert "متاح" in account_card.text
        assert "قابل للسحب" in account_card.text
        assert balance["available"] in account_values
        assert balance["withdrawable"] in account_values

        settlement.refresh_from_db()
        assert settlement.status == SettlementRequest.Status.APPROVED
        settlement_card = wait.until(lambda d: next((
            card for card in d.find_elements(By.XPATH, '//section[.//h2[contains(normalize-space(.), "طلبات التسوية")]]//article[contains(@class,"subcard")]')
            if manufacturer_org.display_name in card.text
        ), False))
        assert settlement.amount in _decimal_values(settlement_card.text)
        assert "EGP" in settlement_card.text
        assert "معتمد" in settlement_card.text

        payout_card = wait.until(lambda d: next((
            card for card in d.find_elements(By.XPATH, '//section[.//h2[contains(normalize-space(.), "ملفات التحويل")]]//article[contains(@class,"subcard")]')
            if manufacturer_org.display_name in card.text
        ), False))
        assert "•••• 7788" in payout_card.text
        assert "موثّق" in payout_card.text
        assert _no_page_overflow(driver)
        _shot(driver, EXPECTED_SCREENSHOTS[16])
    finally:
        driver.quit()

    inventory = sorted(path.name for path in ARTIFACT_DIR.glob("*.png"))
    assert inventory == EXPECTED_SCREENSHOTS
