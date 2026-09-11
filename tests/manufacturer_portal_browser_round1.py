import os

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select

from apps.finance.models import PayoutProfile
from apps.organizations.models import Membership, PublicProfileRevision

from .manufacturer_portal_browser_core import (
    _chrome,
    _click,
    _login,
    _no_overflow,
    _replace,
    _shot,
    _wait,
    manufacturer,
)


@pytest.mark.django_db(transaction=True)
def test_manufacturer_round1_real_chrome(client, live_server, monkeypatch, tmp_path):
    if os.getenv("CI") != "true":
        pytest.skip("Real Chrome Manufacturer QA is CI-only.")
    from unittest.mock import Mock
    from PIL import Image
    from apps.integrations.models import IntegrationConfig
    from apps.media import manufacturer_public_services as images
    from apps.media.models import MediaAsset

    owner, org, _, _ = manufacturer("round1-browser")
    IntegrationConfig.objects.update_or_create(
        provider=IntegrationConfig.Provider.CLOUDFLARE_IMAGES,
        defaults={"enabled": True, "config": {"account_id": "a" * 32}},
    )
    monkeypatch.setattr(IntegrationConfig, "get_secrets", lambda self: {"api_token": "round1-test-token"})
    responses = [
        Mock(
            ok=True,
            json=lambda purpose=purpose: {
                "success": True,
                "result": {
                    "id": f"browser-{purpose}",
                    "requireSignedURLs": False,
                    "variants": [f"https://imagedelivery.net/browser/browser-{purpose}/public"],
                },
            },
        )
        for purpose in ("profile", "cover")
    ]
    post = Mock(side_effect=responses)
    monkeypatch.setattr(images.requests, "post", post)
    monkeypatch.setattr(images.requests, "delete", Mock())
    file = tmp_path / "round1-public.png"
    Image.new("RGB", (48, 32), "purple").save(file)

    driver = _chrome()
    try:
        _login(driver, live_server, client, owner)
        for path in (
            "", "profile/", "public-profile/", "public-products/", "public-inquiries/",
            "team/", "capabilities/", "opportunities/", "quotes/", "production/",
            "finance/", "notifications/",
        ):
            driver.get(f"{live_server.url}/manufacturer/{path}?org={org.pk}&lang=en")
            _wait(driver).until(EC.presence_of_element_located((By.CSS_SELECTOR, ".mfr-nav")))
            active = driver.find_elements(By.CSS_SELECTOR, '.mfr-nav a[aria-current="page"]')
            assert len(active) == 1, path
            assert _no_overflow(driver), path
        _shot(driver, "round1-notifications-desktop.png")

        from apps.public_inquiries.models import PublicInquiry
        inquiry = PublicInquiry.objects.create(
            target_kind="manufacturer",
            target_organization=org,
            sender_user=owner,
            status="submitted",
        )
        driver.get(f"{live_server.url}/manufacturer/public-inquiries/{inquiry.pk}/?org={org.pk}&lang=en")
        selected = driver.find_elements(By.CSS_SELECTOR, '.mfr-nav a[aria-current="page"]')
        assert len(selected) == 1 and "/manufacturer/public-inquiries/?" in selected[0].get_attribute("href")
        _shot(driver, "round1-public-inquiry-child.png")

        driver.get(f"{live_server.url}/manufacturer/profile/?org={org.pk}&lang=en")
        assert not driver.find_elements(By.NAME, "display_name")
        _shot(driver, "round1-profile-readonly.png")
        _click(driver, By.CSS_SELECTOR, 'a[href*="edit=1"]')
        _replace(driver, driver.find_element(By.NAME, "display_name"), "Cancelled change")
        _click(driver, By.LINK_TEXT, "Cancel")
        org.refresh_from_db()
        assert org.display_name == "Factory round1-browser"
        _click(driver, By.CSS_SELECTOR, 'a[href*="edit=1"]')
        _replace(driver, driver.find_element(By.NAME, "display_name"), "Pending public name")
        _click(driver, By.CSS_SELECTOR, 'form button[type="submit"]')
        _wait(driver).until(EC.presence_of_element_located((By.LINK_TEXT, "Edit profile")))
        org.refresh_from_db()
        assert org.display_name == "Factory round1-browser"
        assert "Pending public name" in driver.page_source
        _shot(driver, "round1-profile-pending-review.png")

        # A separate organization keeps media draft evidence independent of the submitted review.
        upload_owner, upload_org, _, _ = manufacturer("round1-upload-browser")
        _login(driver, live_server, client, upload_owner)
        driver.get(f"{live_server.url}/manufacturer/public-profile/?org={upload_org.pk}&lang=en")
        assert not driver.find_elements(By.NAME, "profile_image_upload")
        assert not driver.find_elements(By.NAME, "cover_image_upload")
        edit_link = _wait(driver).until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'a[href*="edit=1"]')))
        edit_link.click()
        _wait(driver).until(EC.presence_of_element_located((By.NAME, "profile_image_upload")))
        for purpose in ("profile", "cover"):
            driver.find_element(By.NAME, f"{purpose}_image_upload").send_keys(str(file))
        assert "round1-public.png" in driver.find_element(By.ID, "profile-upload-name").text
        _click(driver, By.CSS_SELECTOR, 'button[value="save_revision"]')
        _wait(driver).until(lambda _d: PublicProfileRevision.objects.filter(organization=upload_org).exists())
        revision = PublicProfileRevision.objects.get(organization=upload_org)
        for purpose in ("profile", "cover"):
            asset = MediaAsset.objects.get(provider_asset_id=f"browser-{purpose}")
            assert revision.proposed_data["public_state"][f"{purpose}_image_id"] == asset.pk
            assert Select(driver.find_element(By.NAME, f"{purpose}_image_id")).first_selected_option.get_attribute("value") == str(asset.pk)
        assert revision.status == PublicProfileRevision.Status.DRAFT
        assert upload_org.public_state.profile_image_id is None
        assert post.call_count == 2
        assert "imagedelivery.net" not in driver.page_source
        assert "round1-test-token" not in driver.page_source
        _shot(driver, "round1-public-media-desktop.png")

        driver.get(f"{live_server.url}/manufacturer/finance/?org={upload_org.pk}&lang=en")
        assert not driver.find_elements(By.NAME, "amount")
        iban = "EG380019000500000000263180002"
        for name, value in {
            "account_holder": "Synthetic Browser Holder",
            "bank_name": "Synthetic Bank",
            "iban": iban,
            "country": "EG",
            "payout_currency": "EGP",
        }.items():
            _replace(driver, driver.find_element(By.NAME, name), value)
        _click(driver, By.CSS_SELECTOR, 'button[value="save_payout"]')
        _wait(driver).until(lambda _d: PayoutProfile.objects.filter(organization=upload_org).exists())
        assert iban not in driver.page_source
        assert driver.find_element(By.NAME, "iban").get_attribute("value") == ""
        payout = PayoutProfile.objects.get(organization=upload_org)
        cipher = payout.iban_encrypted
        _click(driver, By.CSS_SELECTOR, 'button[value="save_payout"]')
        _wait(driver).until(EC.presence_of_element_located((By.NAME, "iban")))
        payout.refresh_from_db()
        assert payout.iban_encrypted == cipher
        _shot(driver, "round1-bank-saved-mask.png")
        payout.status = PayoutProfile.Status.VERIFIED
        payout.save()
        driver.refresh()
        assert not driver.find_elements(By.NAME, "iban")
        _shot(driver, "round1-bank-verified.png")
        for role in (Membership.Role.MANAGER, Membership.Role.ACCOUNTANT):
            Membership.objects.filter(organization=upload_org, user=upload_owner).update(role=role)
            driver.refresh()
            assert not driver.find_elements(By.NAME, "amount")
            assert not driver.find_elements(By.NAME, "iban")
        Membership.objects.filter(organization=upload_org, user=upload_owner).update(role=Membership.Role.OWNER)

        driver.set_window_size(390, 844)
        for path, name in (("public-profile", "media"), ("finance", "finance"), ("profile", "profile"), ("notifications", "notifications")):
            driver.get(f"{live_server.url}/manufacturer/{path}/?org={upload_org.pk}&lang=ar")
            assert driver.find_element(By.TAG_NAME, "html").get_attribute("dir") == "rtl"
            assert _no_overflow(driver)
            assert len(driver.find_elements(By.CSS_SELECTOR, '.mfr-nav a[aria-current="page"]')) == 1
            _shot(driver, f"round1-{name}-mobile-ar.png")
    finally:
        driver.quit()
