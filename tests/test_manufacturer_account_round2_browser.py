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
from apps.subscriptions.models import ManufacturerSubscriptionUpgradeRequest
from apps.subscriptions.services import MANUFACTURER_PRO, confirm_subscription_billing, entitlement_summary, get_effective_plan

from .test_manufacturer_portal_acceptance import manufacturer
from .test_manufacturer_portal_browser import _chrome, _click_element, _login, _no_overflow, _replace, _wait

User = get_user_model()
ARTIFACT_DIR = Path("artifacts/manufacturer-browser-qa/round2")
EXPECTED = [
    "01a-subscription-entitlement-usage-desktop-en.png",
    "01b-subscription-renewal-desktop-en.png",
    "01c-subscription-comparison-desktop-en.png",
    "01d-subscription-request-status-desktop-en.png",
    "01e-subscription-billing-history-desktop-en.png",
    "02-team-inline-error-desktop-en.png",
    "03-public-profile-readonly-desktop-en.png",
    "04a-public-profile-edit-fields-desktop-en.png",
    "04b-public-profile-edit-media-actions-desktop-en.png",
    "05-public-profile-locked-pending-desktop-en.png",
    "06-capabilities-records-desktop-en.png",
    "07-directory-media-states-corrected-desktop-en.png",
    "08-public-detail-approved-media-desktop-en.png",
    "09-public-detail-no-media-desktop-en.png",
    "10-public-detail-failed-media-corrected-desktop-en.png",
    "11-maneg-capability-verified-desktop-en.png",
    "12-maneg-capability-revoked-desktop-en.png",
    "13-maneg-subscription-navigation-queue-desktop-en.png",
    "14-directory-mobile-ar-rtl-dark.png",
    "15-public-detail-mobile-ar-rtl-dark.png",
    "16a-public-profile-pending-mobile-ar-rtl-dark.png",
    "16b-public-profile-lock-mobile-ar-rtl-dark.png",
    "17a-subscription-entitlement-mobile-ar-rtl-dark.png",
    "17b-subscription-comparison-request-mobile-ar-rtl-dark.png",
    "17c-subscription-history-controls-mobile-ar-rtl-dark.png",
]


def _shot(driver, name):
    assert _no_overflow(driver), (name, driver.current_url)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    assert driver.save_screenshot(str(ARTIFACT_DIR / name))


def _focus_state(driver, element):
    return driver.execute_script(
        """
        const el = arguments[0];
        const r = el.getBoundingClientRect();
        const x = Math.min(Math.max(r.left + r.width / 2, 1), window.innerWidth - 1);
        const y = Math.min(Math.max(r.top + r.height / 2, 1), window.innerHeight - 1);
        const top = document.elementFromPoint(x, y);
        return {
          intersects: r.bottom > 0 && r.top < window.innerHeight && r.right > 0 && r.left < window.innerWidth,
          unobscured: !!top && (top === el || el.contains(top)),
        };
        """,
        element,
    )


def _focus(driver, element):
    driver.execute_script("arguments[0].scrollIntoView({block: 'center', inline: 'nearest'});", element)
    state = {}

    def settled(_driver):
        state.update(_focus_state(_driver, element))
        return state.get("intersects") and state.get("unobscured")

    try:
        _wait(driver).until(settled)
    except Exception as exc:
        raise AssertionError((driver.current_url, state)) from exc


def _shot_focused(driver, name, element):
    _focus(driver, element)
    _shot(driver, name)


def _layout_state(driver, element):
    return driver.execute_script(
        """
        const el = arguments[0];
        const r = el.getBoundingClientRect();
        const style = getComputedStyle(el);
        return {
          display: style.display,
          width: r.width,
          height: r.height,
          rects: el.getClientRects().length,
          naturalWidth: el.naturalWidth || 0,
          naturalHeight: el.naturalHeight || 0,
        };
        """,
        element,
    )


def _assert_hidden_image(driver, image):
    assert image.get_attribute("hidden") is not None
    state = _layout_state(driver, image)
    assert state["display"] == "none"
    assert state["rects"] == 0
    assert state["width"] == 0 and state["height"] == 0
    assert not image.is_displayed()


def _assert_fallback_fills_frame(driver, frame, fallback):
    assert fallback.get_attribute("hidden") is None
    assert fallback.is_displayed()
    frame_box = driver.execute_script("const r=arguments[0].getBoundingClientRect(); return {w:r.width,h:r.height};", frame)
    fallback_box = driver.execute_script("const r=arguments[0].getBoundingClientRect(); return {w:r.width,h:r.height};", fallback)
    assert abs(frame_box["w"] - fallback_box["w"]) <= 1
    assert abs(frame_box["h"] - fallback_box["h"]) <= 1


def _assert_healthy_image(driver, image, fallback):
    state = _layout_state(driver, image)
    assert image.is_displayed()
    assert state["display"] != "none"
    assert state["naturalWidth"] > 0 and state["naturalHeight"] > 0
    assert fallback.get_attribute("hidden") is not None
    assert not fallback.is_displayed()
    fallback_state = _layout_state(driver, fallback)
    assert fallback_state["display"] == "none" and fallback_state["rects"] == 0


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


def _public_asset(owner, organization, *, name, url, mime_type="image/svg+xml"):
    return MediaAsset.objects.create(
        provider=MediaAsset.Provider.LOCAL_DEV,
        provider_asset_id=url,
        original_filename=name,
        mime_type=mime_type,
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
    assert not operator.has_perm("subscriptions.view_organizationsubscription")
    assert not operator.has_perm("subscriptions.view_subscriptionplanpolicy")
    assert not operator.has_perm("subscriptions.view_subscriptionbillingconfirmation")

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
    broken_logo = _public_asset(
        owner,
        org,
        name="round2-missing-logo.png",
        url="/round2-intentionally-missing-logo.png",
        mime_type="image/png",
    )
    broken_cover = _public_asset(
        owner,
        org,
        name="round2-missing-cover.png",
        url="/round2-intentionally-missing-cover.png",
        mime_type="image/png",
    )
    state = _publish_state(
        org,
        name_en="Round 2 Approved Factory",
        name_ar="مصنع الجولة الثانية المعتمد",
        profile=broken_logo,
        cover=broken_cover,
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

        # M2-02: visible, section-specific evidence for entitlement, renewal, comparison, request and billing history.
        driver.get(f"{live_server.url}/manufacturer/subscription/?org={org.pk}&lang=en")
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, '[data-page="manufacturer-subscription"]')))
        assert urlsplit(driver.current_url).path == "/manufacturer/subscription/"
        assert "Subscription & Usage" in driver.title
        entitlement_section = driver.find_element(By.XPATH, '//section[.//h2[normalize-space(.)="Actual entitlement"]]')
        usage_section = driver.find_element(By.XPATH, '//section[.//h2[normalize-space(.)="Usage & limits"]]')
        _focus(driver, entitlement_section)
        assert usage_section.is_displayed()
        _shot(driver, EXPECTED[0])

        request_button = wait.until(EC.element_to_be_clickable((By.XPATH, '//button[normalize-space(.)="Request Pro upgrade"]')))
        _focus(driver, request_button)
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

        renewal_section = driver.find_element(By.XPATH, '//section[.//h2[normalize-space(.)="Renewal & timing"]]')
        _shot_focused(driver, EXPECTED[1], renewal_section)
        comparison_section = driver.find_element(By.XPATH, '//section[.//h2[normalize-space(.)="Current Starter vs Pro"]]')
        _shot_focused(driver, EXPECTED[2], comparison_section)
        request_section = driver.find_element(By.ID, "upgrade-request-status")
        _shot_focused(driver, EXPECTED[3], request_section)
        history_section = driver.find_element(By.XPATH, '//section[.//h2[normalize-space(.)="Billing history"]]')
        _shot_focused(driver, EXPECTED[4], history_section)

        # M2-03: inline identity error keeps entered data and never leaves the workspace.
        driver.get(f"{live_server.url}/manufacturer/team/?org={org.pk}&lang=en")
        form = driver.find_element(By.XPATH, '//form[.//input[@name="action" and @value="upsert"]]')
        form.find_element(By.NAME, "email").send_keys("missing-browser@example.test")
        form.find_element(By.CSS_SELECTOR, 'button[type="submit"]').click()
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "No FABINZI identity was found"))
        assert urlsplit(driver.current_url).path == "/manufacturer/team/"
        assert driver.find_element(By.NAME, "email").get_attribute("value") == "missing-browser@example.test"
        _shot(driver, EXPECTED[5])

        # M2-04: approved read-only -> explicit edit with visible fields/media/actions -> submitted locked proposal.
        driver.get(f"{live_server.url}/manufacturer/public-profile/?org={org.pk}&lang=en")
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "Approved public information"))
        assert not driver.find_elements(By.NAME, "public_name_en")
        _shot(driver, EXPECTED[6])
        driver.find_element(By.LINK_TEXT, "Edit Public Profile").click()
        public_name_input = wait.until(EC.presence_of_element_located((By.NAME, "public_name_en")))
        assert "edit=1" in driver.current_url
        _shot_focused(driver, EXPECTED[7], public_name_input)
        profile_upload = driver.find_element(By.NAME, "profile_image_upload")
        submit_button = driver.find_element(By.CSS_SELECTOR, 'button[value="submit_revision"]')
        _focus(driver, profile_upload)
        assert profile_upload.is_displayed() and submit_button.is_displayed()
        _shot(driver, EXPECTED[8])

        _replace(driver, public_name_input, "Round 2 Pending Factory Name")
        _replace(driver, driver.find_element(By.NAME, "headline_en"), "Pending production headline")
        _replace(driver, driver.find_element(By.NAME, "overview_en"), "Pending overview that must remain unpublished until approval.")
        _replace(driver, driver.find_element(By.NAME, "city"), "Pending City")
        _replace(driver, driver.find_element(By.NAME, "public_categories"), "Pending category, Apparel")
        _replace(driver, driver.find_element(By.NAME, "public_certifications"), "Pending certificate, ISO 9001")
        _click_element(driver, submit_button)
        wait.until(lambda _d: PublicProfileRevision.objects.filter(organization=org, status=PublicProfileRevision.Status.SUBMITTED).exists())
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "Editing is locked during review"))
        assert "Round 2 Pending Factory Name" in driver.page_source
        assert "Pending production headline" in driver.page_source
        assert "Pending overview that must remain unpublished until approval." in driver.page_source
        assert "Pending category" in driver.page_source and "Pending certificate" in driver.page_source
        assert "Round 2 Approved Factory" in driver.page_source
        assert not driver.find_elements(By.NAME, "public_name_en")
        proposal = driver.find_element(By.CSS_SELECTOR, ".mfr-proposal-preview")
        _shot_focused(driver, EXPECTED[9], proposal)

        # M2-05: actual capability record and canonical verification badge must be visible in evidence.
        driver.get(f"{live_server.url}/manufacturer/capabilities/?org={org.pk}&lang=en")
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "FABINZI canonical verification"))
        capability_card = driver.find_element(By.XPATH, f'//article[contains(@class,"capability-card")][.//*[contains(normalize-space(.),"Capability ID: #{capability.pk}")]]')
        assert "Garment Manufacturing" in capability_card.text
        _shot_focused(driver, EXPECTED[10], capability_card)

        # M2-01/M2-06: directory positive, absent-media and cached/early failed-image states.
        driver.get(f"{live_server.url}{reverse('manufacturer-marketplace')}?lang=en")
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "Round 2 Approved Media Factory"))
        assert "Round 2 Pending Factory Name" not in driver.page_source
        assert "must-not-render@example.test" not in driver.page_source and "private-method" not in driver.page_source

        healthy_card = driver.find_element(By.XPATH, '//article[contains(@class,"v25-manufacturer-card")][.//h2[normalize-space(.)="Round 2 Approved Media Factory"]]')
        healthy_frame = healthy_card.find_element(By.CSS_SELECTOR, "[data-public-image-frame]")
        healthy_img = healthy_frame.find_element(By.CSS_SELECTOR, "[data-public-profile-image]")
        healthy_fallback = healthy_frame.find_element(By.CSS_SELECTOR, "[data-public-image-fallback]")
        wait.until(lambda _d: _layout_state(driver, healthy_img)["naturalWidth"] > 0)
        _assert_healthy_image(driver, healthy_img, healthy_fallback)

        no_media_card = driver.find_element(By.XPATH, '//article[contains(@class,"v25-manufacturer-card")][.//h2[contains(normalize-space(.),"Round 2 Manufacturer With An Intentionally Very Long Approved Public Name")]]')
        no_media_frame = no_media_card.find_element(By.CSS_SELECTOR, "[data-public-image-frame]")
        assert not no_media_frame.find_elements(By.CSS_SELECTOR, "[data-public-profile-image]")
        _assert_fallback_fills_frame(driver, no_media_frame, no_media_frame.find_element(By.CSS_SELECTOR, "[data-public-image-fallback]"))

        failed_card = driver.find_element(By.XPATH, '//article[contains(@class,"v25-manufacturer-card")][.//h2[normalize-space(.)="Round 2 Approved Factory"]]')
        failed_frame = failed_card.find_element(By.CSS_SELECTOR, "[data-public-image-frame]")
        failed_img = failed_frame.find_element(By.CSS_SELECTOR, "[data-public-profile-image]")
        failed_fallback = failed_frame.find_element(By.CSS_SELECTOR, "[data-public-image-fallback]")
        wait.until(lambda _d: failed_img.get_attribute("hidden") is not None)
        assert _layout_state(driver, failed_img)["naturalWidth"] == 0
        _assert_hidden_image(driver, failed_img)
        _assert_fallback_fills_frame(driver, failed_frame, failed_fallback)
        _shot_focused(driver, EXPECTED[11], failed_card)

        # Healthy detail logo + cover; then trigger normal error events after listeners are attached.
        driver.get(f"{live_server.url}{reverse('manufacturer-public-detail', args=[media_state.slug])}?lang=en")
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "Round 2 Approved Media Factory"))
        healthy_images = driver.find_elements(By.CSS_SELECTOR, "[data-public-profile-image]")
        assert len(healthy_images) == 2
        wait.until(lambda _d: all(_layout_state(driver, image)["naturalWidth"] > 0 for image in healthy_images))
        logo_frame = driver.find_element(By.CSS_SELECTOR, ".v25-manufacturer-logo-frame")
        logo_image = logo_frame.find_element(By.CSS_SELECTOR, "[data-public-profile-image]")
        logo_fallback = logo_frame.find_element(By.CSS_SELECTOR, "[data-public-image-fallback]")
        cover_frame = driver.find_element(By.CSS_SELECTOR, ".v25-manufacturer-cover")
        cover_image = cover_frame.find_element(By.CSS_SELECTOR, "[data-public-profile-image]")
        cover_fallback = cover_frame.find_element(By.CSS_SELECTOR, "[data-public-image-fallback]")
        _assert_healthy_image(driver, logo_image, logo_fallback)
        _assert_healthy_image(driver, cover_image, cover_fallback)
        _shot(driver, EXPECTED[12])

        driver.execute_script("arguments[0].src='/round2-runtime-missing-logo.png';", logo_image)
        wait.until(lambda _d: logo_image.get_attribute("hidden") is not None)
        _assert_hidden_image(driver, logo_image)
        _assert_fallback_fills_frame(driver, logo_frame, logo_fallback)
        driver.execute_script("arguments[0].src='/round2-runtime-missing-cover.png';", cover_image)
        wait.until(lambda _d: cover_image.get_attribute("hidden") is not None)
        _assert_hidden_image(driver, cover_image)
        _assert_fallback_fills_frame(driver, cover_frame, cover_fallback)

        # Missing detail media: logo fallback is full-frame and cover is intentionally absent.
        driver.get(f"{live_server.url}{reverse('manufacturer-public-detail', args=[no_media_state.slug])}?lang=en")
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "Round 2 Manufacturer With An Intentionally Very Long Approved Public Name"))
        missing_logo_frame = driver.find_element(By.CSS_SELECTOR, ".v25-manufacturer-logo-frame")
        assert not missing_logo_frame.find_elements(By.CSS_SELECTOR, "[data-public-profile-image]")
        _assert_fallback_fills_frame(driver, missing_logo_frame, missing_logo_frame.find_element(By.CSS_SELECTOR, "[data-public-image-fallback]"))
        assert not driver.find_elements(By.CSS_SELECTOR, ".v25-manufacturer-cover")
        _shot(driver, EXPECTED[13])

        # Persisted failed detail logo + cover exercises already-failed/complete state and must show only fallbacks.
        driver.get(f"{live_server.url}{reverse('manufacturer-public-detail', args=[state.slug])}?lang=en")
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "Round 2 Approved Factory"))
        assert "Round 2 Pending Factory Name" not in driver.page_source
        failed_logo_frame = driver.find_element(By.CSS_SELECTOR, ".v25-manufacturer-logo-frame")
        failed_logo = failed_logo_frame.find_element(By.CSS_SELECTOR, "[data-public-profile-image]")
        failed_logo_fallback = failed_logo_frame.find_element(By.CSS_SELECTOR, "[data-public-image-fallback]")
        failed_cover_frame = driver.find_element(By.CSS_SELECTOR, ".v25-manufacturer-cover")
        failed_cover = failed_cover_frame.find_element(By.CSS_SELECTOR, "[data-public-profile-image]")
        failed_cover_fallback = failed_cover_frame.find_element(By.CSS_SELECTOR, "[data-public-image-fallback]")
        wait.until(lambda _d: failed_logo.get_attribute("hidden") is not None and failed_cover.get_attribute("hidden") is not None)
        _assert_hidden_image(driver, failed_logo)
        _assert_hidden_image(driver, failed_cover)
        _assert_fallback_fills_frame(driver, failed_logo_frame, failed_logo_fallback)
        _assert_fallback_fills_frame(driver, failed_cover_frame, failed_cover_fallback)
        assert "must-not-render@example.test" not in driver.page_source and "99999" not in driver.page_source and "private-method" not in driver.page_source
        _shot(driver, EXPECTED[14])

        # M2-05 operational controls: inspect same capability ID, then record-specific revoke.
        _login(driver, live_server, client, reviewer)
        control_url = reverse("fabinzi_admin:maneg-v2-5-manufacturer-public-controls")
        driver.get(f"{live_server.url}{control_url}")
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "Canonical capability verification"))
        assert f"Capability ID: #{capability.pk}" in driver.find_element(By.TAG_NAME, "body").text
        assert "Garment Manufacturing · Verified" in driver.find_element(By.TAG_NAME, "body").text
        _shot(driver, EXPECTED[15])
        revoke_form = driver.find_element(By.XPATH, f'//form[.//input[@name="verification_id" and @value="{verification.pk}"]]')
        _click_element(driver, revoke_form.find_element(By.CSS_SELECTOR, 'button[value="revoke_capability"]'))
        wait.until(lambda _d: ManufacturerCapabilityVerification.objects.filter(pk=verification.pk, status=ManufacturerCapabilityVerification.Status.REVOKED).exists())
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "Garment Manufacturing · Revoked"))
        _shot(driver, EXPECTED[16])

        # R41-03: an operator with ONLY lifecycle permission discovers and clicks Subscriptions from normal Control Center entry.
        _login(driver, live_server, client, operator)
        control_center_index = reverse("fabinzi_admin:index")
        driver.get(f"{live_server.url}{control_center_index}")
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".maneg-nav")))
        subscriptions_link = wait.until(EC.element_to_be_clickable((By.LINK_TEXT, "Subscriptions")))
        assert urlsplit(subscriptions_link.get_attribute("href")).path == reverse("fabinzi_admin:maneg-v2-9-subscriptions")
        subscriptions_link.click()
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "Manufacturer Pro upgrade requests"))
        active_subscriptions = driver.find_element(By.CSS_SELECTOR, '.maneg-nav a[aria-current="page"]')
        assert active_subscriptions.text.strip() == "Subscriptions"
        assert f"#{upgrade.pk}" in driver.find_element(By.TAG_NAME, "body").text
        assert "round2-browser-confirmation" in driver.page_source
        process_form = driver.find_element(By.XPATH, '//form[.//input[@name="action" and @value="process_manufacturer_upgrade"]]')
        assert process_form.find_element(By.CSS_SELECTOR, 'button[type="submit"]').is_enabled()
        _shot_focused(driver, EXPECTED[17], process_form)

        # Mobile/RTL/dark representative evidence across public and changed internal surfaces.
        owner.theme_preference = User.Theme.DARK
        owner.language_preference = User.Language.ARABIC
        owner.save(update_fields=["theme_preference", "language_preference"])
        _login(driver, live_server, client, owner)
        driver.set_window_size(390, 844)
        driver.get(f"{live_server.url}{reverse('manufacturer-marketplace')}?lang=ar")
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "مصنع الجولة الثانية بوسائط معتمدة"))
        assert driver.find_element(By.TAG_NAME, "html").get_attribute("dir") == "rtl"
        assert driver.find_element(By.TAG_NAME, "html").get_attribute("data-theme") == "dark"
        _shot(driver, EXPECTED[18])

        driver.get(f"{live_server.url}{reverse('manufacturer-public-detail', args=[media_state.slug])}?lang=ar")
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "مصنع الجولة الثانية بوسائط معتمدة"))
        assert driver.find_element(By.TAG_NAME, "html").get_attribute("dir") == "rtl"
        _shot(driver, EXPECTED[19])

        driver.get(f"{live_server.url}/manufacturer/public-profile/?org={org.pk}&lang=ar")
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "التحرير متوقف أثناء المراجعة"))
        assert "Pending production headline" in driver.page_source
        assert not driver.find_elements(By.NAME, "public_name_en")
        mobile_proposal = driver.find_element(By.CSS_SELECTOR, ".mfr-proposal-preview")
        _shot_focused(driver, EXPECTED[20], mobile_proposal)
        lock_notice = driver.find_element(By.XPATH, '//section[contains(@class,"mfr-panel")][.//strong[contains(normalize-space(.),"التحرير متوقف أثناء المراجعة")]]')
        _shot_focused(driver, EXPECTED[21], lock_notice)
        assert not driver.find_elements(By.NAME, "public_name_en")

        driver.get(f"{live_server.url}/manufacturer/subscription/?org={org.pk}&lang=ar")
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, '[data-page="manufacturer-subscription"]')))
        assert driver.find_element(By.TAG_NAME, "html").get_attribute("dir") == "rtl"
        assert driver.find_element(By.TAG_NAME, "html").get_attribute("data-theme") == "dark"
        assert f"#{upgrade.pk}" in driver.find_element(By.TAG_NAME, "body").text
        mobile_entitlement = driver.find_element(By.XPATH, '//section[.//h2[normalize-space(.)="الصلاحية الفعلية"]]')
        _shot_focused(driver, EXPECTED[22], mobile_entitlement)
        mobile_comparison = driver.find_element(By.XPATH, '//section[.//h2[normalize-space(.)="مقارنة Starter وPro الحالية"]]')
        _shot_focused(driver, EXPECTED[23], mobile_comparison)
        mobile_history = driver.find_element(By.XPATH, '//section[.//h2[normalize-space(.)="سجل الفوترة"]]')
        _shot_focused(driver, EXPECTED[24], mobile_history)
    except Exception:
        _failure_evidence(driver)
        raise
    finally:
        driver.quit()

    assert sorted(path.name for path in ARTIFACT_DIR.glob("*.png")) == EXPECTED
