import os
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from apps.media.models import MediaAsset
from apps.organizations.models import DesignerProfile, Membership, OnboardingApplication, Organization
from apps.public_profiles.services import ensure_public_state
from apps.subscriptions.designer_upgrade_services import create_designer_upgrade_request
from apps.subscriptions.models import DesignerSubscriptionUpgradeRequest
from apps.subscriptions.services import ensure_subscription_for_organization
from .conftest import VALID_PNG
from .test_designer_portal_browser import _chrome, _click_element, _login, _no_overflow, _shot
from .test_maneg_control_center_browser import _login_browser
from .v2_3_support import v2_3_reference_rows

User = get_user_model()
ARTIFACT_DIR = Path("artifacts/designer-browser-qa")
pytestmark = pytest.mark.usefixtures("v2_3_reference_rows")


def _designer(owner, name):
    org = Organization.objects.create(
        kind=Organization.Kind.DESIGNER,
        display_name=name,
        email=f"{owner.username}@phase4-browser.test",
        phone="01000555555",
        website="https://example.test",
        address_line1="53-D6 Al-maqsad residence",
        city="Cairo",
        region="Cairo Governorate",
        country="EG",
        verification_status=Organization.VerificationStatus.ACTIVE,
        created_by=owner,
    )
    Membership.objects.create(organization=org, user=owner, role=Membership.Role.OWNER, is_active=True)
    DesignerProfile.objects.create(
        organization=org,
        studio_name=f"{name} Studio",
        portfolio_url="https://www.linkedin.com/in/example/",
        terms_accepted=True,
    )
    OnboardingApplication.objects.create(
        organization=org,
        status=OnboardingApplication.Status.APPROVED,
        reviewed_at=timezone.now(),
    )
    ensure_subscription_for_organization(org)
    ensure_public_state(org)
    return org


def _fake_public_creator(*, upload, organization, actor, purpose, request=None):
    payload = upload.read()
    return MediaAsset.objects.create(
        provider=MediaAsset.Provider.LOCAL_DEV,
        provider_asset_id=f"phase4-browser-{organization.pk}-{purpose}-{MediaAsset.objects.count()}",
        original_filename=upload.name,
        mime_type="image/png",
        size_bytes=len(payload),
        access=MediaAsset.Access.PUBLIC,
        uploaded_by=actor,
        metadata={
            "organization_id": organization.pk,
            "purpose": purpose,
            "designer_public_upload": True,
            "public_url": f"https://imagedelivery.net/test/{organization.pk}/{purpose}",
        },
    )


def _wait(driver):
    return WebDriverWait(driver, 12)


def _screenshot(driver, name):
    _shot(driver, name)
    assert (ARTIFACT_DIR / name).exists()
    assert _no_overflow(driver)


@pytest.mark.django_db(transaction=True)
def test_designer_phase4_browser_evidence(client, live_server, tmp_path, monkeypatch):
    if os.getenv("CI") != "true":
        pytest.skip("Phase 4 real-browser evidence is CI-only.")

    monkeypatch.setattr("apps.public_profiles.portal_views.create_designer_public_image", _fake_public_creator)
    owner = User.objects.create_user(
        username="phase4-browser-owner",
        email="phase4-browser-owner@example.test",
        password="password12345",
        language_preference="en",
        theme_preference="light",
    )
    org = _designer(owner, "Phase 4 Atelier")
    operator = User.objects.create_superuser(
        username="phase4-browser-operator",
        email="phase4-browser-operator@example.test",
        password="password12345",
    )
    second_owner = User.objects.create_user(
        username="phase4-browser-second-owner",
        email="phase4-browser-second-owner@example.test",
        password="password12345",
    )
    second_org = _designer(second_owner, "Phase 4 Rejection Atelier")

    valid_path = tmp_path / "phase4-valid.png"
    valid_path.write_bytes(VALID_PNG)
    invalid_path = tmp_path / "phase4-invalid.png"
    invalid_path.write_text("not an image", encoding="utf-8")

    driver = _chrome(width=1440, height=1000)
    try:
        _login(driver, live_server, client, owner)
        wait = _wait(driver)

        driver.get(f"{live_server.url}/designer/profile/?org={org.pk}&lang=en")
        wait.until(EC.visibility_of_element_located((By.ID, "designer-profile-readonly")))
        assert not driver.find_elements(By.ID, "designer-profile-form")
        assert driver.find_element(By.TAG_NAME, "html").get_attribute("dir") == "ltr"
        _screenshot(driver, "p4-01-organization-profile-readonly-en.png")

        _click_element(driver, driver.find_element(By.ID, "profile-edit-action"))
        wait.until(EC.visibility_of_element_located((By.ID, "designer-profile-form")))
        first = driver.find_element(By.ID, "profile-display-name")
        assert first.get_attribute("autofocus") is not None
        persisted_name = org.display_name
        first.clear()
        first.send_keys("Unsaved Phase 4 Name")
        _screenshot(driver, "p4-02-organization-profile-edit-en.png")
        _click_element(driver, driver.find_element(By.ID, "profile-cancel-action"))
        wait.until(EC.visibility_of_element_located((By.ID, "designer-profile-readonly")))
        org.refresh_from_db()
        assert org.display_name == persisted_name
        _screenshot(driver, "p4-03-organization-profile-cancel-en.png")

        driver.get(f"{live_server.url}/designer/team/?org={org.pk}&lang=en")
        driver.find_element(By.ID, "team-email").send_keys("missing-phase4@example.test")
        _click_element(driver, driver.find_element(By.CSS_SELECTOR, "#designer-team-upsert-form button[type='submit']"))
        wait.until(EC.visibility_of_element_located((By.ID, "team-member-error")))
        assert "No FABINZI account exists" in driver.page_source
        _screenshot(driver, "p4-04-team-missing-identity-safe-error-en.png")

        driver.get(f"{live_server.url}/designer/public-profile/?org={org.pk}&lang=en")
        wait.until(EC.visibility_of_element_located((By.ID, "designer-public-profile-readonly")))
        assert not driver.find_elements(By.ID, "designer-public-profile-form")
        assert "REVISION STATE" in driver.page_source
        _screenshot(driver, "p4-05-public-profile-readonly-en.png")

        _click_element(driver, driver.find_element(By.ID, "public-profile-edit-action"))
        wait.until(EC.visibility_of_element_located((By.ID, "designer-public-profile-form")))
        assert driver.find_element(By.ID, "profile-image-upload").get_attribute("type") == "file"
        assert driver.find_element(By.ID, "cover-image-upload").get_attribute("type") == "file"
        _screenshot(driver, "p4-06-public-profile-edit-upload-controls-en.png")

        driver.find_element(By.ID, "profile-image-upload").send_keys(str(invalid_path))
        _click_element(driver, driver.find_element(By.CSS_SELECTOR, "button[name='action'][value='save_revision']"))
        wait.until(EC.visibility_of_element_located((By.ID, "public-profile-error")))
        assert "valid PNG, JPEG or WebP" in driver.page_source
        _screenshot(driver, "p4-07-public-profile-upload-validation-en.png")

        driver.get(f"{live_server.url}/designer/public-profile/?org={org.pk}&edit=1&lang=en")
        wait.until(EC.visibility_of_element_located((By.ID, "designer-public-profile-form")))
        driver.find_element(By.ID, "profile-image-upload").send_keys(str(valid_path))
        driver.find_element(By.ID, "cover-image-upload").send_keys(str(valid_path))
        _click_element(driver, driver.find_element(By.CSS_SELECTOR, "button[name='action'][value='save_revision']"))
        wait.until(lambda _d: org.public_profile_revisions.filter(status="draft").exists())
        wait.until(EC.visibility_of_element_located((By.ID, "designer-public-profile-form")))
        revision = org.public_profile_revisions.get(status="draft")
        assert revision.proposed_data["public_state"]["profile_image_id"]
        assert revision.proposed_data["public_state"]["cover_image_id"]
        _screenshot(driver, "p4-08-public-profile-upload-draft-en.png")

        driver.get(f"{live_server.url}/designer/subscription/?org={org.pk}&lang=en")
        wait.until(EC.visibility_of_element_located((By.ID, "designer-current-plan")))
        assert driver.find_element(By.ID, "designer-usage")
        _screenshot(driver, "p4-09-designer-subscription-usage-en.png")
        request_form = driver.find_element(By.ID, "designer-upgrade-request-form")
        _click_element(driver, request_form.find_element(By.CSS_SELECTOR, "button[type='submit']"))
        wait.until(lambda _d: DesignerSubscriptionUpgradeRequest.objects.filter(organization=org, status="pending").exists())
        wait.until(EC.visibility_of_element_located((By.ID, "designer-upgrade-pending-note")))
        _screenshot(driver, "p4-10-designer-upgrade-pending-en.png")
        upgrade = DesignerSubscriptionUpgradeRequest.objects.get(organization=org, status="pending")

        _login_browser(driver, live_server, client, operator)
        driver.get(live_server.url + reverse("fabinzi_admin:maneg-v2-9-subscriptions"))
        wait.until(EC.visibility_of_element_located((By.ID, "designer-upgrade-requests")))
        assert f"designer-upgrade-{upgrade.pk}" in driver.page_source
        _screenshot(driver, "p4-11-maneg-designer-upgrade-pending-en.png")
        approve_form = driver.find_element(By.XPATH, f'//form[.//input[@name="designer_upgrade_request_id" and @value="{upgrade.pk}"] and .//input[@name="action" and @value="approve_designer_upgrade"]]')
        _click_element(driver, approve_form.find_element(By.CSS_SELECTOR, "button[type='submit']"))
        wait.until(lambda _d: DesignerSubscriptionUpgradeRequest.objects.filter(pk=upgrade.pk, status="approved").exists())
        wait.until(EC.text_to_be_present_in_element((By.ID, f"designer-upgrade-{upgrade.pk}"), "Approved"))
        _screenshot(driver, "p4-12-maneg-designer-upgrade-approved-en.png")

        rejected, _created = create_designer_upgrade_request(organization=second_org, actor=second_owner)
        driver.refresh()
        wait.until(EC.visibility_of_element_located((By.ID, f"designer-upgrade-{rejected.pk}")))
        reject_form = driver.find_element(By.XPATH, f'//form[.//input[@name="designer_upgrade_request_id" and @value="{rejected.pk}"] and .//input[@name="action" and @value="reject_designer_upgrade"]]')
        reject_form.find_element(By.NAME, "rejection_reason").send_keys("Browser QA rejection evidence")
        _click_element(driver, reject_form.find_element(By.CSS_SELECTOR, "button[type='submit']"))
        wait.until(lambda _d: DesignerSubscriptionUpgradeRequest.objects.filter(pk=rejected.pk, status="rejected").exists())
        wait.until(EC.text_to_be_present_in_element((By.ID, f"designer-upgrade-{rejected.pk}"), "Rejected"))
        _screenshot(driver, "p4-13-maneg-designer-upgrade-rejected-en.png")

        _login(driver, live_server, client, owner)
        driver.get(f"{live_server.url}/designer/subscription/?org={org.pk}&lang=en")
        wait.until(EC.text_to_be_present_in_element((By.ID, "designer-upgrade-status-value"), "Approved"))
        _screenshot(driver, "p4-14-designer-upgrade-approved-en.png")

        owner.language_preference = "ar"
        owner.theme_preference = "dark"
        owner.save(update_fields=["language_preference", "theme_preference"])
        _login(driver, live_server, client, owner)
        driver.set_window_size(390, 844)
        driver.get(f"{live_server.url}/designer/profile/?org={org.pk}&lang=ar")
        wait.until(EC.visibility_of_element_located((By.ID, "designer-profile-readonly")))
        html = driver.find_element(By.TAG_NAME, "html")
        assert html.get_attribute("dir") == "rtl"
        assert html.get_attribute("data-theme") == "dark"
        _screenshot(driver, "p4-15-organization-profile-mobile-ar-rtl-dark.png")

        driver.get(f"{live_server.url}/designer/public-profile/?org={org.pk}&lang=ar")
        wait.until(EC.visibility_of_element_located((By.ID, "designer-public-profile-readonly")))
        assert driver.find_element(By.TAG_NAME, "html").get_attribute("dir") == "rtl"
        _screenshot(driver, "p4-16-public-profile-mobile-ar-rtl-dark.png")
    finally:
        driver.quit()
