import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.urls import reverse
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC

from apps.manufacturer_marketplace.models import ManufacturerCapability, ManufacturerListing
from apps.media.models import MediaAsset
from apps.organizations.models import PublicProfileRevision
from apps.public_profiles.models import ManufacturerCapabilityVerification, ProfessionalPublicState
from apps.public_profiles.services import ensure_public_state, verify_manufacturer_capability
from apps.subscriptions.models import ManufacturerSubscriptionUpgradeRequest, OrganizationSubscription
from apps.subscriptions.services import MANUFACTURER_PRO, confirm_subscription_billing, entitlement_summary, get_effective_plan

from .test_manufacturer_portal_acceptance import manufacturer
from .test_manufacturer_portal_browser import _chrome, _login, _no_overflow, _replace, _wait

User = get_user_model()
ARTIFACT_DIR = Path("artifacts/manufacturer-browser-qa/round2")
EXPECTED = [
    "01-subscription-request-history-desktop-en.png",
    "02-team-inline-error-desktop-en.png",
    "03-public-profile-readonly-desktop-en.png",
    "04-public-profile-edit-desktop-en.png",
    "05-public-profile-locked-pending-desktop-en.png",
    "06-capabilities-desktop-en.png",
    "07-directory-three-media-states-desktop-en.png",
    "08-public-detail-approved-media-desktop-en.png",
    "09-public-detail-no-media-desktop-en.png",
    "10-public-detail-failed-media-desktop-en.png",
    "11-maneg-capability-verified-desktop-en.png",
    "12-maneg-capability-revoked-desktop-en.png",
    "13-maneg-subscription-queue-desktop-en.png",
    "14-directory-mobile-ar-rtl-dark.png",
    "15-public-detail-mobile-ar-rtl-dark.png",
    "16-public-profile-locked-mobile-ar-rtl-dark.png",
    "17-subscription-mobile-ar-rtl-dark.png",
]


def _shot(driver, name):
    assert _no_overflow(driver), (name, driver.current_url)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    assert driver.save_screenshot(str(ARTIFACT_DIR / name))


def _failure_evidence(driver):
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        driver.save_screenshot(str(ARTIFACT_DIR / "failure.png"))
    except Exception:
        pass
    try:
        (ARTIFACT_DIR / "failure.html").write_text(driver.page_source, encoding="utf-8")
        (ARTIFACT_DIR / "failure-url.txt").write_text(driver.current_url, encoding="utf-8")
    except Exception:
        pass


def _public_asset(owner, organization, *, name, url):
    return MediaAsset.objects.create(
        provider=MediaAsset.Provider.LOCAL_DEV,
        provider_asset_id=url,
        original_filename=name,
        mime_type="image/svg+xml",
        size_bytes=1,
        access=MediaAsset.Access.PUBLIC,
        uploaded_by=owner,
        metadata={"organization_id": organization.pk, "public_url": url},
    )


def _publish_state(organization, *, name_en, name_ar, profile=None, cover=None, categories=None):
    state = ensure_public_state(organization)
    state.public_name_en = name_en
    state.public_name_ar = name_ar
    state.public_categories = categories or ["Apparel"]
    state.public_certifications = ["ISO 9001"]
    state.profile_image = profile
    state.cover_image = cover
    state.visibility = ProfessionalPublicState.Visibility.VISIBLE
    state.save()
    return state


@pytest.mark.django_db(transaction=True)
def test_manufacturer_round2_real_chrome(client, live_server, v2_3_reference_rows):
    if os.getenv("CI") != "true":
        pytest.skip("Real Chrome Manufacturer Round 2 QA is CI-only.")

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    for path in ARTIFACT_DIR.iterdir():
        if path.is_file():
            path.unlink()

    owner, org, _profile, _application = manufacturer("round2-browser")
    owner.theme_preference = User.Theme.LIGHT
    owner.language_preference = User.Language.ENGLISH
    owner.save(update_fields=["theme_preference", "language_preference"])
    org.city = "Cairo"
    org.region = "Cairo Governorate"
    org.save(update_fields=["city", "region", "updated_at"])

    reviewer = User.objects.create_superuser(
        username="round2-browser-reviewer",
        email="round2-browser-reviewer@example.test",
        password="password123",
    )
    operator = User.objects.create_user(
        username="round2-browser-subscription-operator",
        email="round2-browser-subscription-operator@example.test",
        password="password123",
        is_staff=True,
    )
    operator.user_permissions.add(
        Permission.objects.get(
            content_type__app_label="subscriptions",
            codename="manage_professional_subscription",
        )
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
    verification = verify_manufacturer_capability(
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
    state = _publish_state(
        org,
        name_en="Round 2 Approved Factory",
        name_ar="مصنع الجولة الثانية المعتمد",
        profile=broken_logo,
        categories=["Apparel", "T-shirts"],
    )

    no_media_owner, no_media_org, _no_profile, _no_app = manufacturer("round2-no-media")
    no_media_org.city = "Alexandria With A Deliberately Long Public Location Label"
    no_media_org.region = "Alexandria Governorate"
    no_media_org.save(update_fields=["city", "region", "updated_at"])
    ManufacturerListing.objects.create(
        organization=no_media_org,
        headline_en="Long-form production partner headline that validates responsive directory wrapping",
        headline_ar="عنوان طويل لشريك إنتاج لاختبار الالتفاف المتجاوب في الدليل",
        overview_en="Approved no-media Manufacturer overview.",
        overview_ar="نبذة مصنع معتمدة بدون وسائط.",
    )
    no_media_state = _publish_state(
        no_media_org,
        name_en="Round 2 Manufacturer With An Intentionally Very Long Approved Public Name",
        name_ar="مصنع الجولة الثانية باسم عام معتمد طويل للغاية",
    )

    media_owner, media_org, _media_profile, _media_app = manufacturer("round2-approved-media")
    media_org.city = "Giza"
    media_org.region = "Giza Governorate"
    media_org.save(update_fields=["city", "region", "updated_at"])
    ManufacturerListing.objects.create(
        organization=media_org,
        headline_en="Approved media production partner",
        headline_ar="شريك إنتاج بوسائط معتمدة",
        overview_en="Approved profile with a real static logo and cover fixture.",
        overview_ar="ملف معتمد بشعار وغلاف ثابتين للاختبار.",
    )
    approved_logo = _public_asset(
        media_owner,
        media_org,
        name="approved-logo.svg",
        url="/static/brand/fabinzi-icon.svg",
    )
    approved_cover = _public_asset(
        media_owner,
        media_org,
        name="approved-cover.svg",
        url="/static/brand/fabinzi-logo.svg",
    )
    media_state = _publish_state(
        media_org,
        name_en="Round 2 Approved Media Factory",
        name_ar="مصنع الجولة الثانية بوسائط معتمدة",
        profile=approved_logo,
        cover=approved_cover,
    )

    driver = _chrome(width=1440, height=1100)
    try:
        _login(driver, live_server, client, owner)
        wait = _wait(driver)

        # M2-02: stable page identity, persisted request, safe billing-history context.
        driver.get(f"{live_server.url}/manufacturer/subscription/?org={org.pk}&lang=en")
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, '[data-page="manufacturer-subscription"]')))
        assert urlsplit(driver.current_url).path == "/manufacturer/subscription/"
        assert "Subscription & Usage" in driver.title
        assert "Manufacturing Offers used" in driver.page_source
        assert "Current Starter vs Pro" in driver.page_source
        request_button = wait.until(EC.element_to_be_clickable((By.XPATH, '//button[normalize-space(.)="Request Pro upgrade"]')))
        driver.execute_script(
            "arguments[0].scrollIntoView({block: 'center', inline: 'nearest'});",
            request_button,
        )
        wait.until(
            lambda d: d.execute_script(
                "const r=arguments[0].getBoundingClientRect();"
                "const x=r.left+r.width/2; const y=r.top+r.height/2;"
                "const top=document.elementFromPoint(x,y);"
                "return top===arguments[0] || arguments[0].contains(top);",
                request_button,
            )
        )
        request_button.click()
        wait.until(EC.presence_of_element_located((By.ID, "upgrade-request-status")))
        upgrade = ManufacturerSubscriptionUpgradeRequest.objects.get(
            organization=org,
            status=ManufacturerSubscriptionUpgradeRequest.Status.REQUESTED,
        )
        assert f"Request reference #{upgrade.pk}" in driver.find_element(By.TAG_NAME, "body").text
        pro = get_effective_plan(MANUFACTURER_PRO)
        confirmation = confirm_subscription_billing(
            organization=org,
            actor=operator,
            plan_code=pro.code,
            amount=pro.monthly_price,
            currency=pro.currency,
            provider="round2-browser-test",
            provider_reference="round2-browser-confirmation",
            idempotency_key="round2-browser-idempotency",
        )
        driver.refresh()
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "Billing history"))
        subscription = entitlement_summary(org)["subscription"]
        assert subscription.current_plan.code != MANUFACTURER_PRO
        confirmation.refresh_from_db()
        assert confirmation.consumed_period_id is None
        _shot(driver, EXPECTED[0])

        # M2-03: inline identity error keeps entered data and never leaves the workspace.
        driver.get(f"{live_server.url}/manufacturer/team/?org={org.pk}&lang=en")
        form = driver.find_element(By.XPATH, '//form[.//input[@name="action" and @value="upsert"]]')
        form.find_element(By.NAME, "email").send_keys("missing-browser@example.test")
        form.find_element(By.CSS_SELECTOR, 'button[type="submit"]').click()
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "No FABINZI identity was found"))
        assert urlsplit(driver.current_url).path == "/manufacturer/team/"
        assert driver.find_element(By.NAME, "email").get_attribute("value") == "missing-browser@example.test"
        _shot(driver, EXPECTED[1])

        # M2-04: approved read-only -> explicit edit -> submitted locked proposal with full review summary.
        driver.get(f"{live_server.url}/manufacturer/public-profile/?org={org.pk}&lang=en")
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "Approved public information"))
        assert not driver.find_elements(By.NAME, "public_name_en")
        _shot(driver, EXPECTED[2])
        driver.find_element(By.LINK_TEXT, "Edit Public Profile").click()
        wait.until(EC.presence_of_element_located((By.NAME, "public_name_en")))
        assert "edit=1" in driver.current_url
        _shot(driver, EXPECTED[3])
        _replace(driver, driver.find_element(By.NAME, "public_name_en"), "Round 2 Pending Factory Name")
        _replace(driver, driver.find_element(By.NAME, "headline_en"), "Pending production headline")
        _replace(driver, driver.find_element(By.NAME, "overview_en"), "Pending overview that must remain unpublished until approval.")
        _replace(driver, driver.find_element(By.NAME, "city"), "Pending City")
        _replace(driver, driver.find_element(By.NAME, "public_categories"), "Pending category, Apparel")
        _replace(driver, driver.find_element(By.NAME, "public_certifications"), "Pending certificate, ISO 9001")
        driver.find_element(By.CSS_SELECTOR, 'button[value="submit_revision"]').click()
        wait.until(lambda _d: PublicProfileRevision.objects.filter(organization=org, status=PublicProfileRevision.Status.SUBMITTED).exists())
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "Editing is locked during review"))
        assert "Round 2 Pending Factory Name" in driver.page_source
        assert "Pending production headline" in driver.page_source
        assert "Pending overview that must remain unpublished until approval." in driver.page_source
        assert "Pending category" in driver.page_source and "Pending certificate" in driver.page_source
        assert "Round 2 Approved Factory" in driver.page_source
        assert not driver.find_elements(By.NAME, "public_name_en")
        driver.get(f"{live_server.url}/manufacturer/public-profile/?org={org.pk}&edit=1&lang=en")
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "Editing is locked during review"))
        assert not driver.find_elements(By.NAME, "public_name_en")
        _shot(driver, EXPECTED[4])

        # M2-05: Manufacturer capability surface separates operational and canonical states.
        driver.get(f"{live_server.url}/manufacturer/capabilities/?org={org.pk}&lang=en")
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "FABINZI canonical verification"))
        assert "Garment Manufacturing" in driver.page_source
        assert f"Capability ID #{capability.pk}" in driver.find_element(By.TAG_NAME, "body").text
        _shot(driver, EXPECTED[5])

        # M2-01/M2-06: directory has approved media, no-media fallback and failed-media fallback.
        driver.get(f"{live_server.url}{reverse('manufacturer-marketplace')}?lang=en")
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "Round 2 Approved Media Factory"))
        assert "Round 2 Pending Factory Name" not in driver.page_source
        assert "Round 2 Approved Factory" in driver.page_source
        assert "Round 2 Manufacturer With An Intentionally Very Long Approved Public Name" in driver.page_source
        assert "must-not-render@example.test" not in driver.page_source
        assert "private-method" not in driver.page_source
        wait.until(lambda d: d.find_element(By.XPATH, '//article[contains(@class,"v25-manufacturer-card")][.//h2[contains(.,"Round 2 Approved Factory")]]//*[@data-public-image-fallback]').is_displayed())
        _shot(driver, EXPECTED[6])

        driver.get(f"{live_server.url}{reverse('manufacturer-public-detail', args=[media_state.slug])}?lang=en")
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "Round 2 Approved Media Factory"))
        wait.until(lambda d: all(d.execute_script("return arguments[0].complete && arguments[0].naturalWidth > 0", image) for image in d.find_elements(By.CSS_SELECTOR, "[data-public-profile-image]")))
        assert len(driver.find_elements(By.CSS_SELECTOR, "[data-public-profile-image]")) == 2
        assert not any(element.is_displayed() for element in driver.find_elements(By.CSS_SELECTOR, "[data-public-image-fallback]"))
        _shot(driver, EXPECTED[7])

        driver.get(f"{live_server.url}{reverse('manufacturer-public-detail', args=[no_media_state.slug])}?lang=en")
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "Round 2 Manufacturer With An Intentionally Very Long Approved Public Name"))
        assert driver.find_element(By.CSS_SELECTOR, ".v25-manufacturer-logo-frame [data-public-image-fallback]").is_displayed()
        assert not driver.find_elements(By.CSS_SELECTOR, ".v25-manufacturer-cover")
        _shot(driver, EXPECTED[8])

        driver.get(f"{live_server.url}{reverse('manufacturer-public-detail', args=[state.slug])}?lang=en")
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "Round 2 Approved Factory"))
        assert "Round 2 Pending Factory Name" not in driver.page_source
        wait.until(lambda d: d.find_element(By.CSS_SELECTOR, ".v25-manufacturer-logo-frame [data-public-image-fallback]").is_displayed())
        assert driver.find_element(By.CSS_SELECTOR, ".v25-manufacturer-logo").get_attribute("hidden") is not None
        assert "must-not-render@example.test" not in driver.page_source and "99999" not in driver.page_source and "private-method" not in driver.page_source
        _shot(driver, EXPECTED[9])

        # M2-05 operational controls: inspect same capability ID, then record-specific revoke.
        _login(driver, live_server, client, reviewer)
        control_url = reverse("fabinzi_admin:maneg-v2-5-manufacturer-public-controls")
        driver.get(f"{live_server.url}{control_url}")
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "Canonical capability verification"))
        assert f"Capability ID: #{capability.pk}" in driver.find_element(By.TAG_NAME, "body").text
        assert "Garment Manufacturing · Verified" in driver.find_element(By.TAG_NAME, "body").text
        _shot(driver, EXPECTED[10])
        revoke_form = driver.find_element(By.XPATH, f'//form[.//input[@name="verification_id" and @value="{verification.pk}"]]')
        revoke_form.find_element(By.CSS_SELECTOR, 'button[value="revoke_capability"]').click()
        wait.until(lambda _d: ManufacturerCapabilityVerification.objects.filter(pk=verification.pk, status=ManufacturerCapabilityVerification.Status.REVOKED).exists())
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "Garment Manufacturing · Revoked"))
        _shot(driver, EXPECTED[11])

        # M2-02 reachable non-superuser operational queue with eligible evidence.
        _login(driver, live_server, client, operator)
        maneg_subscriptions = reverse("fabinzi_admin:maneg-v2-9-subscriptions")
        driver.get(f"{live_server.url}{maneg_subscriptions}")
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "Manufacturer Pro upgrade requests"))
        assert f"#{upgrade.pk}" in driver.find_element(By.TAG_NAME, "body").text
        assert "round2-browser-confirmation" in driver.page_source
        assert driver.find_element(By.CSS_SELECTOR, 'button[value="process_manufacturer_upgrade"]').is_enabled()
        _shot(driver, EXPECTED[12])

        # Mobile/RTL/dark representative evidence across public and internal changed surfaces.
        owner.theme_preference = User.Theme.DARK
        owner.language_preference = User.Language.ARABIC
        owner.save(update_fields=["theme_preference", "language_preference"])
        _login(driver, live_server, client, owner)
        driver.set_window_size(390, 844)
        driver.get(f"{live_server.url}{reverse('manufacturer-marketplace')}?lang=ar")
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "مصنع الجولة الثانية بوسائط معتمدة"))
        assert driver.find_element(By.TAG_NAME, "html").get_attribute("dir") == "rtl"
        assert driver.find_element(By.TAG_NAME, "html").get_attribute("data-theme") == "dark"
        _shot(driver, EXPECTED[13])

        driver.get(f"{live_server.url}{reverse('manufacturer-public-detail', args=[media_state.slug])}?lang=ar")
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "مصنع الجولة الثانية بوسائط معتمدة"))
        assert driver.find_element(By.TAG_NAME, "html").get_attribute("dir") == "rtl"
        _shot(driver, EXPECTED[14])

        driver.get(f"{live_server.url}/manufacturer/public-profile/?org={org.pk}&lang=ar")
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "التحرير متوقف أثناء المراجعة"))
        assert "Pending production headline" in driver.page_source
        assert not driver.find_elements(By.NAME, "public_name_en")
        _shot(driver, EXPECTED[15])

        driver.get(f"{live_server.url}/manufacturer/subscription/?org={org.pk}&lang=ar")
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, '[data-page="manufacturer-subscription"]')))
        assert driver.find_element(By.TAG_NAME, "html").get_attribute("dir") == "rtl"
        assert driver.find_element(By.TAG_NAME, "html").get_attribute("data-theme") == "dark"
        assert f"#{upgrade.pk}" in driver.find_element(By.TAG_NAME, "body").text
        _shot(driver, EXPECTED[16])
    except Exception:
        _failure_evidence(driver)
        raise
    finally:
        driver.quit()

    assert sorted(path.name for path in ARTIFACT_DIR.glob("*.png")) == EXPECTED