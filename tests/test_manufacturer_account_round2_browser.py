import os
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC

from apps.manufacturer_marketplace.models import ManufacturerCapability, ManufacturerListing
from apps.media.models import MediaAsset
from apps.organizations.models import Membership
from apps.public_profiles.models import ManufacturerCapabilityVerification, ProfessionalPublicState
from apps.public_profiles.services import ensure_public_state, verify_manufacturer_capability

from .test_manufacturer_portal_acceptance import manufacturer
from .test_manufacturer_portal_browser import _chrome, _login, _no_overflow, _wait

User = get_user_model()
ARTIFACT_DIR = Path("artifacts/manufacturer-browser-qa/round2")
EXPECTED = [
    "01-subscription-desktop-en.png",
    "02-team-inline-error-desktop-en.png",
    "03-public-profile-readonly-desktop-en.png",
    "04-public-profile-edit-desktop-en.png",
    "05-capabilities-desktop-en.png",
    "06-directory-desktop-en.png",
    "07-public-detail-failed-logo-fallback-en.png",
    "08-subscription-mobile-ar-rtl-dark.png",
]


def _shot(driver, name):
    assert _no_overflow(driver)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    assert driver.save_screenshot(str(ARTIFACT_DIR / name))


@pytest.mark.django_db(transaction=True)
def test_manufacturer_round2_real_chrome(client, live_server, v2_3_reference_rows):
    if os.getenv("CI") != "true":
        pytest.skip("Real Chrome Manufacturer Round 2 QA is CI-only.")

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    for path in ARTIFACT_DIR.glob("*.png"):
        path.unlink()

    owner, org, _profile, _application = manufacturer("round2-browser")
    owner.theme_preference = User.Theme.LIGHT
    owner.language_preference = User.Language.ENGLISH
    owner.save(update_fields=["theme_preference", "language_preference"])
    reviewer = User.objects.create_user(
        username="round2-browser-reviewer",
        email="round2-browser-reviewer@example.test",
        password="password123",
        is_staff=True,
    )
    listing = ManufacturerListing.objects.create(
        organization=org,
        headline_en="Precision apparel production",
        headline_ar="إنتاج ملابس بدقة",
        overview_en="Approved public Manufacturer overview for Round 2 browser QA.",
        overview_ar="نبذة عامة معتمدة لاختبار الجولة الثانية.",
        public_email="must-not-render@example.test",
        public_phone="01099999999",
        available_monthly_capacity=99999,
        min_order_quantity=999,
        lead_time_min_days=77,
        production_methods=["private-method"],
    )
    capability = ManufacturerCapability.objects.create(
        listing=listing,
        capability_type=ManufacturerCapability.CapabilityType.CUT_SEW,
        name="Garment assembly",
        is_active=True,
    )
    verify_manufacturer_capability(
        capability=capability,
        canonical_code=ManufacturerCapabilityVerification.CanonicalCode.GARMENT_MANUFACTURING,
        reviewer=reviewer,
    )
    broken_logo = MediaAsset.objects.create(
        provider=MediaAsset.Provider.LOCAL_DEV,
        provider_asset_id="/round2-intentionally-missing-logo.png",
        original_filename="round2-missing-logo.png",
        mime_type="image/png",
        size_bytes=1,
        access=MediaAsset.Access.PUBLIC,
        uploaded_by=owner,
        metadata={"organization_id": org.pk, "public_url": "/round2-intentionally-missing-logo.png"},
    )
    state = ensure_public_state(org)
    state.public_name_en = "Round 2 Approved Factory"
    state.public_name_ar = "مصنع الجولة الثانية المعتمد"
    state.public_categories = ["Apparel", "T-shirts"]
    state.public_certifications = ["ISO 9001"]
    state.profile_image = broken_logo
    state.visibility = ProfessionalPublicState.Visibility.VISIBLE
    state.save()

    driver = _chrome(width=1440, height=1100)
    try:
        _login(driver, live_server, client, owner)
        wait = _wait(driver)

        driver.get(f"{live_server.url}/manufacturer/subscription/?org={org.pk}&lang=en")
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "Subscription & Usage"))
        selected = driver.find_elements(By.CSS_SELECTOR, '.mfr-nav a[aria-current="page"]')
        assert len(selected) == 1
        assert "subscription" in selected[0].get_attribute("href")
        assert "Manufacturing Offers used" in driver.page_source
        assert "Current Starter vs Pro" in driver.page_source
        _shot(driver, EXPECTED[0])

        driver.get(f"{live_server.url}/manufacturer/team/?org={org.pk}&lang=en")
        form = driver.find_element(By.XPATH, '//form[.//input[@name="action" and @value="upsert"]]')
        form.find_element(By.NAME, "email").send_keys("missing-browser@example.test")
        form.find_element(By.CSS_SELECTOR, 'button[type="submit"]').click()
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "No FABINZI identity was found"))
        assert driver.find_element(By.NAME, "email").get_attribute("value") == "missing-browser@example.test"
        _shot(driver, EXPECTED[1])

        driver.get(f"{live_server.url}/manufacturer/public-profile/?org={org.pk}&lang=en")
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "Approved public information"))
        assert not driver.find_elements(By.NAME, "public_name_en")
        _shot(driver, EXPECTED[2])
        driver.find_element(By.LINK_TEXT, "Edit Public Profile").click()
        wait.until(EC.presence_of_element_located((By.NAME, "public_name_en")))
        assert "edit=1" in driver.current_url
        _shot(driver, EXPECTED[3])

        driver.get(f"{live_server.url}/manufacturer/capabilities/?org={org.pk}&lang=en")
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "FABINZI canonical verification"))
        assert "Garment Manufacturing" in driver.page_source
        assert "Capability ID" in driver.page_source
        _shot(driver, EXPECTED[4])

        driver.get(f"{live_server.url}{reverse('manufacturer-marketplace')}?lang=en")
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "Round 2 Approved Factory"))
        assert "must-not-render@example.test" not in driver.page_source
        assert "private-method" not in driver.page_source
        directory_fallback = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, ".v25-manufacturer-card [data-public-image-fallback]")))
        assert directory_fallback.is_displayed()
        _shot(driver, EXPECTED[5])

        driver.get(f"{live_server.url}{reverse('manufacturer-public-detail', args=[state.slug])}?lang=en")
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "Round 2 Approved Factory"))
        wait.until(lambda d: d.find_element(By.CSS_SELECTOR, ".v25-manufacturer-logo-frame [data-public-image-fallback]").is_displayed())
        assert driver.find_element(By.CSS_SELECTOR, ".v25-manufacturer-logo").get_attribute("hidden") is not None
        assert "must-not-render@example.test" not in driver.page_source
        assert "99999" not in driver.page_source
        assert "private-method" not in driver.page_source
        _shot(driver, EXPECTED[6])

        owner.theme_preference = User.Theme.DARK
        owner.language_preference = User.Language.ARABIC
        owner.save(update_fields=["theme_preference", "language_preference"])
        driver.set_window_size(390, 844)
        driver.get(f"{live_server.url}/manufacturer/subscription/?org={org.pk}&lang=ar")
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "الاشتراك والاستخدام"))
        assert driver.find_element(By.TAG_NAME, "html").get_attribute("dir") == "rtl"
        assert driver.find_element(By.TAG_NAME, "html").get_attribute("data-theme") == "dark"
        _shot(driver, EXPECTED[7])
    finally:
        driver.quit()

    assert sorted(path.name for path in ARTIFACT_DIR.glob("*.png")) == EXPECTED
