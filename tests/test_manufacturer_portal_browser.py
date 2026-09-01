import os
from decimal import Decimal
from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from selenium import webdriver
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait

from apps.artwork.models import ArtworkPlacement
from apps.design.models import DesignAsset
from apps.finance.models import FinanceAccount, LedgerEntry, PayoutProfile, SettlementRequest
from apps.manufacturer_marketplace.models import ManufacturerCapability, ManufacturerQuote
from apps.operations.models import FulfillmentRecord, ProductionJob, ProductionMilestone, QCInspection
from apps.organizations.models import Membership, PublicProfileRevision
from apps.organizations.public_profile_services import review_public_profile_revision, start_public_profile_review
from apps.storefront.models import CustomizationElement

from .test_manufacturer_portal_acceptance import assigned_job, invited_rfq, manufacturer, private_asset
from .v2_3_support import v2_3_reference_rows

User = get_user_model()
ARTIFACT_DIR = Path("artifacts/manufacturer-browser-qa")
EXPECTED_SCREENSHOTS = [
    "01-manufacturer-dashboard-desktop-en-light.png",
    "02-manufacturer-profile-desktop-en-light.png",
    "03-manufacturer-team-desktop-en-light.png",
    "04-manufacturer-capabilities-desktop-en-light.png",
    "05-manufacturer-opportunities-desktop-en-light.png",
    "06-manufacturer-rfq-detail-desktop-en-light.png",
    "07-manufacturer-quote-desktop-en-light.png",
    "08-manufacturer-production-list-desktop-en-light.png",
    "09-manufacturer-production-detail-desktop-en-light.png",
    "10-manufacturer-qc-desktop-en-light.png",
    "11-manufacturer-ready-to-ship-desktop-en-light.png",
    "12-manufacturer-shipment-desktop-en-light.png",
    "13-manufacturer-finance-desktop-en-light.png",
    "14-manufacturer-dashboard-tablet-en-light.png",
    "15-manufacturer-dashboard-mobile-ar-rtl-dark.png",
    "16-manufacturer-production-mobile-ar-rtl-dark.png",
    "17-manufacturer-finance-mobile-ar-rtl-dark.png",
]


def _chrome(*, language="en-US,en", width=1440, height=1000):
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument(f"--window-size={width},{height}")
    options.add_experimental_option("prefs", {"intl.accept_languages": language})
    return webdriver.Chrome(options=options)


def _wait(driver):
    return WebDriverWait(driver, 12)


def _login(driver, live_server, client, user):
    client.force_login(user)
    session_cookie = client.cookies[settings.SESSION_COOKIE_NAME].value
    driver.get(live_server.url + "/")
    driver.add_cookie({"name": settings.SESSION_COOKIE_NAME, "value": session_cookie, "path": "/"})


def _click_element(driver, element):
    ActionChains(driver).scroll_to_element(element).move_to_element(element).pause(0.06).click().perform()
    return element


def _click(driver, by, locator):
    element = _wait(driver).until(EC.element_to_be_clickable((by, locator)))
    return _click_element(driver, element)


def _replace(driver, element, value):
    ActionChains(driver).scroll_to_element(element).move_to_element(element).pause(0.03).click().perform()
    element.send_keys(Keys.CONTROL, "a")
    element.send_keys(str(value))


def _shot(driver, name):
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    assert driver.save_screenshot(str(ARTIFACT_DIR / name))


def _no_overflow(driver):
    return bool(driver.execute_script("return document.documentElement.scrollWidth <= window.innerWidth + 1"))


def _form_with_hidden(driver, name, value):
    return driver.find_element(By.XPATH, f'//form[.//input[@type="hidden" and @name="{name}" and @value="{value}"]]')


def _clear_artifacts():
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    for path in ARTIFACT_DIR.glob("*.png"):
        path.unlink()


@pytest.mark.django_db(transaction=True)
def test_manufacturer_portal_real_chrome_a_to_h(client, live_server, v2_3_reference_rows):
    if os.getenv("CI") != "true":
        pytest.skip("Real Chrome Manufacturer QA is CI-only.")

    _clear_artifacts()
    owner, org, profile, _ = manufacturer("browser-owner")
    reviewer = User.objects.create_user(
        username="browser-profile-reviewer",
        email="browser-profile-reviewer@example.test",
        password="password123",
        is_staff=True,
    )
    owner.theme_preference = User.Theme.LIGHT
    owner.language_preference = User.Language.ENGLISH
    owner.save(update_fields=["theme_preference", "language_preference"])
    teammate = User.objects.create_user(
        username="browser-operator",
        email="browser-operator@example.test",
        password="password123",
    )

    _, _, _, rfq, invitation = invited_rfq(org, prefix="browser-rfq")
    production = assigned_job(org, prefix="browser-job")
    size_row = production["garment"].size_rows.get(size_label="M")
    size_row.measurements = {
        "chest_cm": 52,
        "length_cm": 70,
        "custom_drop_mm": 147.25,
    }
    size_row.save(update_fields=["measurements"])
    ArtworkPlacement.objects.create(
        product=production["product"],
        decoration_zone=production["zone"],
        production_method="print",
        transform={"x": 0.5, "y": 0.35, "scale": 0.4, "rotation": 0},
    )
    CustomizationElement.objects.create(
        customization=production["customization"],
        decoration_zone=production["zone"],
        kind=CustomizationElement.Kind.TEXT,
        text="Browser placement",
        production_method="print",
        transform={"x": 0.62, "y": 0.38, "scale": 0.27, "rotation": -12.5},
    )
    tech_media = private_asset(production["owner"], "browser-tech-pack.pdf")
    DesignAsset.objects.create(
        version=production["garment"],
        kind=DesignAsset.Kind.TECH_PACK,
        media_asset=tech_media,
        label="Approved technical pack",
    )

    account = FinanceAccount.objects.create(
        account_type=FinanceAccount.AccountType.ORGANIZATION,
        organization=org,
        currency="EGP",
    )
    LedgerEntry.objects.create(
        account=account,
        entry_type=LedgerEntry.EntryType.MANUFACTURER_EARNING,
        amount=Decimal("500.00"),
        currency="EGP",
        available_at=timezone.now(),
        memo="Browser QA manufacturing payable",
    )
    PayoutProfile.objects.create(
        organization=org,
        method=PayoutProfile.Method.BANK,
        account_holder=org.display_name,
        destination_hint="•••• 7788",
        status=PayoutProfile.Status.VERIFIED,
    )

    driver = _chrome()
    try:
        _login(driver, live_server, client, owner)
        wait = _wait(driver)

        # A. Dashboard / Profile / Team.
        driver.get(f"{live_server.url}/manufacturer/?org={org.pk}&lang=en")
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".mfr-workspace")))
        assert "Manufacturer workspace" in driver.page_source
        assert _no_overflow(driver)
        _shot(driver, EXPECTED_SCREENSHOTS[0])

        driver.get(f"{live_server.url}/manufacturer/profile/?org={org.pk}&lang=en")
        wait.until(EC.presence_of_element_located((By.NAME, "display_name")))
        _replace(driver, driver.find_element(By.NAME, "display_name"), "Browser Factory Works")
        _replace(driver, driver.find_element(By.NAME, "city"), "New Cairo")
        _replace(driver, driver.find_element(By.NAME, "primary_contact_person"), "Browser Operations Lead")
        _click(driver, By.CSS_SELECTOR, 'form button[type="submit"]')
        wait.until(
            lambda _d: PublicProfileRevision.objects.filter(
                organization=org, status=PublicProfileRevision.Status.SUBMITTED
            ).exists()
        )
        revision = PublicProfileRevision.objects.get(organization=org)
        org.refresh_from_db(); profile.refresh_from_db()
        assert org.display_name == "Factory browser-owner"
        assert org.city == "Cairo"
        assert profile.primary_contact_person == "Browser Operations Lead"
        assert revision.proposed_data["organization"]["display_name"] == "Browser Factory Works"
        assert revision.proposed_data["organization"]["city"] == "New Cairo"
        assert "Manufacturer profile updated." in driver.page_source
        start_public_profile_review(revision=revision, reviewer=reviewer)
        review_public_profile_revision(
            revision=revision,
            reviewer=reviewer,
            decision=PublicProfileRevision.Status.APPROVED,
            notes="Browser QA manufacturer public identity approved",
        )
        wait.until(lambda _d: org.__class__.objects.filter(pk=org.pk, display_name="Browser Factory Works", city="New Cairo").exists())
        driver.refresh()
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "Browser Factory Works"))
        assert _no_overflow(driver)
        _shot(driver, EXPECTED_SCREENSHOTS[1])

        driver.get(f"{live_server.url}/manufacturer/team/?org={org.pk}&lang=en")
        wait.until(EC.presence_of_element_located((By.NAME, "email")))
        team_form = _form_with_hidden(driver, "action", "upsert")
        team_form.find_element(By.NAME, "email").send_keys(teammate.email)
        Select(team_form.find_element(By.NAME, "role")).select_by_value(Membership.Role.OPERATOR)
        _click_element(driver, team_form.find_element(By.CSS_SELECTOR, 'button[type="submit"]'))
        wait.until(lambda _d: Membership.objects.filter(organization=org, user=teammate, role=Membership.Role.OPERATOR, is_active=True).exists())
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), teammate.email))
        assert _no_overflow(driver)
        _shot(driver, EXPECTED_SCREENSHOTS[2])

        # B. Actual Manufacturer capability model through visible controls.
        driver.get(f"{live_server.url}/manufacturer/capabilities/?org={org.pk}&lang=en")
        capability_form = _form_with_hidden(driver, "action", "create")
        Select(capability_form.find_element(By.NAME, "capability_type")).select_by_value(ManufacturerCapability.CapabilityType.PRINT)
        capability_form.find_element(By.NAME, "name").send_keys("Screen printing")
        capability_form.find_element(By.NAME, "methods").send_keys("screen print")
        _click_element(driver, capability_form.find_element(By.CSS_SELECTOR, 'button[type="submit"]'))
        wait.until(lambda _d: ManufacturerCapability.objects.filter(listing__organization=org, name="Screen printing", is_active=True).exists())
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "Screen printing"))
        assert _no_overflow(driver)
        _shot(driver, EXPECTED_SCREENSHOTS[3])

        # C. Invitation -> real Manufacturer Quote. Selection remains a Designer-side setup boundary.
        driver.get(f"{live_server.url}/manufacturer/opportunities/?org={org.pk}&lang=en")
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), rfq.title))
        assert _no_overflow(driver)
        _shot(driver, EXPECTED_SCREENSHOTS[4])

        _click(driver, By.CSS_SELECTOR, f'a[href^="/manufacturer/opportunities/{invitation.pk}/"]')
        wait.until(EC.presence_of_element_located((By.NAME, "unit_price")))
        assert "120" in driver.page_source
        assert _no_overflow(driver)
        _shot(driver, EXPECTED_SCREENSHOTS[5])
        quote_form = driver.find_element(By.XPATH, '//form[.//input[@name="unit_price"]]')
        _replace(driver, quote_form.find_element(By.NAME, "unit_price"), "125.00")
        _replace(driver, quote_form.find_element(By.NAME, "minimum_order_quantity"), "25")
        _replace(driver, quote_form.find_element(By.NAME, "production_lead_days"), "10")
        _click_element(driver, quote_form.find_element(By.CSS_SELECTOR, 'button[type="submit"]'))
        wait.until(lambda _d: ManufacturerQuote.objects.filter(invitation=invitation, status=ManufacturerQuote.Status.SUBMITTED).exists())
        quote = ManufacturerQuote.objects.get(invitation=invitation)
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "Submitted"))
        assert quote.unit_price == Decimal("125.00")
        assert quote.minimum_order_quantity == 25
        assert _no_overflow(driver)
        _shot(driver, EXPECTED_SCREENSHOTS[6])

        # D. Assigned production exposes persisted technical data and the exact authorized production asset.
        job = production["job"]
        driver.get(f"{live_server.url}/manufacturer/production/?org={org.pk}&lang=en")
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), production["item"].title))
        assert _no_overflow(driver)
        _shot(driver, EXPECTED_SCREENSHOTS[7])

        driver.get(f"{live_server.url}/manufacturer/production/{job.pk}/?org={org.pk}&lang=en")
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "Approved technical pack"))
        asset_link = driver.find_element(By.XPATH, '//a[.//strong[normalize-space(.)="Approved technical pack"]]')
        assert f"/manufacturer/production/{job.pk}/media/design/" in asset_link.get_attribute("href")
        assert "private-customer@example.test" not in driver.page_source
        assert "Chest" in driver.page_source
        assert "Custom drop" in driver.page_source
        assert "&#x27;chest_cm&#x27;" not in driver.page_source
        assert driver.find_element(By.CSS_SELECTOR, '[data-transform-source="designed-product"] [data-tech-key="x"] dd').text == "50%"
        assert driver.find_element(By.CSS_SELECTOR, '[data-transform-source="studio"] [data-tech-key="x"] dd').text == "62%"
        assert _no_overflow(driver)
        _shot(driver, EXPECTED_SCREENSHOTS[8])

        # E. Production -> all actual milestones -> QC -> pack/ready-to-ship.
        _click(driver, By.XPATH, '//button[normalize-space(.)="Start production"]')
        wait.until(lambda _d: ProductionJob.objects.filter(pk=job.pk, status=ProductionJob.Status.IN_PRODUCTION).exists())
        job.refresh_from_db()
        for milestone in job.milestones.order_by("id"):
            form = _form_with_hidden(driver, "milestone_id", milestone.pk)
            Select(form.find_element(By.NAME, "status")).select_by_value(ProductionMilestone.Status.COMPLETED)
            _replace(driver, form.find_element(By.NAME, "notes"), f"{milestone.get_kind_display()} completed")
            _click_element(driver, form.find_element(By.CSS_SELECTOR, 'button[type="submit"]'))
            wait.until(lambda _d, pk=milestone.pk: ProductionMilestone.objects.filter(pk=pk, status=ProductionMilestone.Status.COMPLETED).exists())
        _click(driver, By.XPATH, '//button[normalize-space(.)="Request QC"]')
        wait.until(lambda _d: ProductionJob.objects.filter(pk=job.pk, status=ProductionJob.Status.QC_PENDING).exists())

        driver.get(f"{live_server.url}/manufacturer/production/{job.pk}/qc/?org={org.pk}&lang=en")
        wait.until(EC.presence_of_element_located((By.NAME, "decision")))
        assert _no_overflow(driver)
        _shot(driver, EXPECTED_SCREENSHOTS[9])
        qc_form = driver.find_element(By.XPATH, '//form[.//select[@name="decision"]]')
        Select(qc_form.find_element(By.NAME, "decision")).select_by_value(QCInspection.Decision.PASSED)
        qc_form.find_element(By.NAME, "notes").send_keys("Browser final inspection passed")
        _click_element(driver, qc_form.find_element(By.CSS_SELECTOR, 'button[type="submit"]'))
        wait.until(lambda _d: ProductionJob.objects.filter(pk=job.pk, status=ProductionJob.Status.READY).exists())
        production["fulfillment"].refresh_from_db()
        assert production["fulfillment"].status == FulfillmentRecord.Status.READY_TO_PACK

        driver.get(f"{live_server.url}/manufacturer/production/{job.pk}/ready-to-ship/?org={org.pk}&lang=en")
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "Ready to pack"))
        assert _no_overflow(driver)
        _shot(driver, EXPECTED_SCREENSHOTS[10])
        _click(driver, By.XPATH, '//button[contains(normalize-space(.), "Confirm packed")]')
        wait.until(lambda _d: FulfillmentRecord.objects.filter(pk=production["fulfillment"].pk, status=FulfillmentRecord.Status.PACKED).exists())

        # F. Canonical shipment record through visible form.
        driver.get(f"{live_server.url}/manufacturer/production/{job.pk}/shipment/?org={org.pk}&lang=en")
        wait.until(EC.presence_of_element_located((By.NAME, "carrier")))
        assert "private-customer@example.test" not in driver.page_source
        assert _no_overflow(driver)
        _shot(driver, EXPECTED_SCREENSHOTS[11])
        shipment_form = driver.find_element(By.XPATH, '//form[.//input[@name="tracking_number"]]')
        shipment_form.find_element(By.NAME, "carrier").send_keys("Browser Carrier")
        shipment_form.find_element(By.NAME, "tracking_number").send_keys("FAB-MFR-1001")
        shipment_form.find_element(By.NAME, "tracking_url").send_keys("https://tracking.example.test/FAB-MFR-1001")
        _click_element(driver, shipment_form.find_element(By.CSS_SELECTOR, 'button[type="submit"]'))
        wait.until(lambda _d: FulfillmentRecord.objects.filter(pk=production["fulfillment"].pk, status=FulfillmentRecord.Status.SHIPPED, tracking_number="FAB-MFR-1001").exists())
        production["fulfillment"].refresh_from_db()
        assert production["order"].fulfillment.pk == production["fulfillment"].pk

        # G. Real ledger-backed Manufacturer finance and settlement.
        driver.get(f"{live_server.url}/manufacturer/finance/?org={org.pk}&lang=en")
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "500.00"))
        settlement_form = _form_with_hidden(driver, "action", "request_settlement")
        _replace(driver, settlement_form.find_element(By.NAME, "amount"), "150.00")
        _replace(driver, settlement_form.find_element(By.NAME, "currency"), "EGP")
        _click_element(driver, settlement_form.find_element(By.CSS_SELECTOR, 'button[type="submit"]'))
        wait.until(lambda _d: SettlementRequest.objects.filter(organization=org, amount=Decimal("150.00")).exists())
        assert _no_overflow(driver)
        _shot(driver, EXPECTED_SCREENSHOTS[12])

        # Tablet evidence.
        driver.set_window_size(900, 1000)
        driver.get(f"{live_server.url}/manufacturer/?org={org.pk}&lang=en")
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".mfr-workspace")))
        assert _no_overflow(driver)
        _shot(driver, EXPECTED_SCREENSHOTS[13])

        # H. Arabic RTL + Dark + Mobile on dashboard, production and finance.
        owner.theme_preference = User.Theme.DARK
        owner.language_preference = User.Language.ARABIC
        owner.save(update_fields=["theme_preference", "language_preference"])
        driver.set_window_size(390, 844)
        driver.get(f"{live_server.url}/manufacturer/?org={org.pk}&lang=ar")
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".mfr-workspace")))
        assert driver.find_element(By.TAG_NAME, "html").get_attribute("dir") == "rtl"
        assert driver.find_element(By.TAG_NAME, "html").get_attribute("data-theme") == "dark"
        assert "مساحة التصنيع" in driver.page_source
        assert _no_overflow(driver)
        _shot(driver, EXPECTED_SCREENSHOTS[14])

        driver.get(f"{live_server.url}/manufacturer/production/{job.pk}/?org={org.pk}&lang=ar")
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".mfr-workspace")))
        assert driver.find_element(By.TAG_NAME, "html").get_attribute("dir") == "rtl"
        assert "الصدر" in driver.page_source
        assert driver.find_element(By.CSS_SELECTOR, '[data-transform-source="designed-product"] [data-tech-key="x"] dd').text == "50%"
        assert driver.find_element(By.CSS_SELECTOR, '[data-transform-source="studio"] [data-tech-key="x"] dd').text == "62%"
        assert _no_overflow(driver)
        _shot(driver, EXPECTED_SCREENSHOTS[15])

        driver.get(f"{live_server.url}/manufacturer/finance/?org={org.pk}&lang=ar")
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".mfr-workspace")))
        assert driver.find_element(By.TAG_NAME, "html").get_attribute("dir") == "rtl"
        assert _no_overflow(driver)
        _shot(driver, EXPECTED_SCREENSHOTS[16])
    finally:
        driver.quit()

    inventory = sorted(path.name for path in ARTIFACT_DIR.glob("*.png"))
    assert inventory == EXPECTED_SCREENSHOTS