import os
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import RequestFactory
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select

from apps.media.models import MediaAsset
from apps.organizations.models import Membership, Organization
from apps.storefront.models import CustomizationElement
from apps.subscriptions.models import SubscriptionBillingConfirmation
from apps.subscriptions.services import ensure_subscription_for_organization
from apps.subscriptions.views import _subscription_action

from .test_artwork_studio_browser import (
    PRIVATE_UPLOAD_PATH,
    PNG_1X1,
    _assert_no_overflow,
    _chrome,
    _click,
    _creative_catalog,
    _login,
    _shot,
    _start_project_from_studio_entry,
    _url,
    _wait,
)

User = get_user_model()
ROOT = Path(__file__).resolve().parents[1]

EN_UPGRADE = (
    "Pro can be activated only after payment is confirmed through FABINZI's authorized billing process. "
    "Until confirmation, your current subscription remains unchanged."
)
AR_UPGRADE = (
    "لا يمكن تفعيل خطة Pro إلا بعد تأكيد الدفع عبر مسار الفوترة المعتمد في FABINZI. "
    "وحتى يتم التأكيد، سيظل اشتراكك الحالي دون تغيير."
)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "kind,language,expected",
    [
        (Organization.Kind.DESIGNER, "en", EN_UPGRADE),
        (Organization.Kind.DESIGNER, "ar", AR_UPGRADE),
        (Organization.Kind.MANUFACTURER, "en", EN_UPGRADE),
        (Organization.Kind.MANUFACTURER, "ar", AR_UPGRADE),
    ],
)
def test_round4_upgrade_message_is_localized_and_cannot_activate_paid_entitlement(
    v2_3_reference_rows,
    kind,
    language,
    expected,
):
    owner = User.objects.create_user(
        username=f"round4-{kind}-{language}-owner",
        password="password12345",
    )
    organization = Organization.objects.create(
        kind=kind,
        display_name=f"Round 4 {kind} {language}",
        email=f"round4-{kind}-{language}@example.test",
        verification_status=Organization.VerificationStatus.ACTIVE,
        created_by=owner,
    )
    Membership.objects.create(
        organization=organization,
        user=owner,
        role=Membership.Role.OWNER,
    )
    subscription = ensure_subscription_for_organization(organization)
    before_plan_id = subscription.current_plan_id
    billing_before = SubscriptionBillingConfirmation.objects.filter(organization=organization).count()

    request = RequestFactory().post("/subscription/", {"action": "upgrade"})
    request.user = owner
    request.LANGUAGE_CODE = language

    with pytest.raises(ValidationError) as exc_info:
        _subscription_action(
            request,
            organization,
            {},
            designer=kind == Organization.Kind.DESIGNER,
        )

    assert exc_info.value.messages == [expected]
    subscription.refresh_from_db()
    assert subscription.current_plan_id == before_plan_id
    assert SubscriptionBillingConfirmation.objects.filter(organization=organization).count() == billing_before

    views_source = (ROOT / "apps/subscriptions/views.py").read_text(encoding="utf-8")
    assert "activate_paid_pro(" not in views_source
    assert "browser/client requests cannot activate paid entitlement" not in views_source


def test_round4_studio_file_picker_keeps_real_input_and_safe_filename_contract():
    template = (ROOT / "templates/storefront/studio_project.html").read_text(encoding="utf-8")
    javascript = (ROOT / "static/js/studio-editor.js").read_text(encoding="utf-8")
    stylesheet = (ROOT / "static/css/artwork-studio.css").read_text(encoding="utf-8")

    assert 'id="private-art-file"' in template
    assert 'name="file"' in template
    assert 'type="file"' in template
    assert 'accept="image/png,image/jpeg,image/webp"' in template
    assert 'aria-describedby="private-art-file-help private-art-file-status"' in template
    assert 'required>' in template
    assert 'for="private-art-file"' in template
    assert "Choose image" in template
    assert "No image selected" in template
    assert "اختر صورة" in template
    assert "لم يتم اختيار صورة" in template
    assert 'id="private-art-file-status"' in template
    assert 'aria-live="polite"' in template
    assert 'dir="auto"' in template

    assert "privateFileInput.files?.[0]?.name" in javascript
    assert "privateFileStatus.textContent" in javascript
    assert "privateFileInput.value" not in javascript
    assert "innerHTML" not in javascript
    assert ".studio-file-picker__input" in stylesheet
    assert ".studio-file-picker__input:focus-visible+.studio-file-picker__trigger" in stylesheet
    assert "overflow-wrap:anywhere" in stylesheet


@pytest.mark.django_db(transaction=True)
def test_round4_studio_private_upload_real_chrome_en_mobile_and_ar(client, live_server):
    if os.getenv("CI") != "true":
        pytest.skip("Real Chrome FABINZI UX Round 4 QA is CI-only.")

    data = _creative_catalog("round4upload")
    customer = User.objects.create_user(
        username="round4-upload-customer",
        password="password12345",
        theme_preference="light",
        language_preference="en",
    )
    PRIVATE_UPLOAD_PATH.write_bytes(PNG_1X1)

    driver = _chrome(width=1440, height=1050)
    try:
        _login(driver, live_server, client, customer)
        wait = _wait(driver)
        driver.get(_url(live_server, "public-store-product", data["store"].slug, data["product"].slug))
        _click(driver, By.ID, "product-customize-link")
        project = _start_project_from_studio_entry(driver, data)

        _click(driver, By.CSS_SELECTOR, '[data-studio-tab="upload"]')
        wait.until(EC.visibility_of_element_located((By.ID, "private-upload-form")))
        file_input = driver.find_element(By.ID, "private-art-file")
        trigger = driver.find_element(By.CSS_SELECTOR, 'label[for="private-art-file"]')
        status = driver.find_element(By.ID, "private-art-file-status")
        assert trigger.is_displayed() and trigger.text.strip() == "Choose image"
        assert status.text.strip() == "No image selected"
        assert file_input.get_attribute("accept") == "image/png,image/jpeg,image/webp"
        assert file_input.get_attribute("required") == "true"
        rect = driver.execute_script(
            "const r=arguments[0].getBoundingClientRect(); return {w:r.width,h:r.height};",
            file_input,
        )
        assert rect["w"] <= 1 and rect["h"] <= 1
        driver.execute_script("arguments[0].focus()", file_input)
        assert driver.execute_script("return document.activeElement === arguments[0]", file_input)
        _assert_no_overflow(driver)
        _shot(driver, "round4-03-studio-upload-desktop-en-empty.png")

        file_input.send_keys(str(PRIVATE_UPLOAD_PATH))
        wait.until(lambda d: d.find_element(By.ID, "private-art-file-status").text.strip() == PRIVATE_UPLOAD_PATH.name)
        visible_body = driver.find_element(By.TAG_NAME, "body").text
        assert str(PRIVATE_UPLOAD_PATH) not in visible_body
        assert "fakepath" not in visible_body.lower()
        _shot(driver, "round4-04-studio-upload-desktop-en-selected.png")

        Select(driver.find_element(By.ID, "upload-zone")).select_by_value(str(data["zone"].pk))
        Select(driver.find_element(By.ID, "upload-method")).select_by_value("print")
        _click(driver, By.ID, "rights-confirmed")
        assert driver.find_element(By.ID, "rights-confirmed").is_selected()
        _click(driver, By.CSS_SELECTOR, "#private-upload-form button[type='submit']")
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, '[data-studio-element][data-kind="image"]')))
        private_images = CustomizationElement.objects.filter(
            customization__project=project,
            kind=CustomizationElement.Kind.IMAGE,
        )
        assert private_images.count() == 1
        first_image = private_images.get()
        assert first_image.media_asset.access == MediaAsset.Access.PRIVATE
        assert first_image.media_asset.original_filename == PRIVATE_UPLOAD_PATH.name
        assert first_image.rights_confirmed is True
        assert first_image.media_asset.provider_asset_id not in driver.find_element(By.TAG_NAME, "body").text
        _assert_no_overflow(driver)
        _shot(driver, "round4-05-studio-upload-desktop-en-complete.png")

        driver.set_window_size(390, 844)
        driver.get(_url(live_server, "studio-project", project.pk) + "?lang=en")
        wait.until(EC.presence_of_element_located((By.ID, "studio-editor")))
        _click(driver, By.CSS_SELECTOR, '[data-studio-tab="upload"]')
        wait.until(EC.visibility_of_element_located((By.ID, "private-upload-form")))
        assert driver.find_element(By.CSS_SELECTOR, 'label[for="private-art-file"]').text.strip() == "Choose image"
        assert driver.find_element(By.ID, "private-art-file-status").text.strip() == "No image selected"
        _assert_no_overflow(driver)
        mobile_input = driver.find_element(By.ID, "private-art-file")
        mobile_input.send_keys(str(PRIVATE_UPLOAD_PATH))
        wait.until(lambda d: d.find_element(By.ID, "private-art-file-status").text.strip() == PRIVATE_UPLOAD_PATH.name)
        visible_body = driver.find_element(By.TAG_NAME, "body").text
        assert str(PRIVATE_UPLOAD_PATH) not in visible_body
        assert "fakepath" not in visible_body.lower()
        assert driver.find_element(By.ID, "rights-confirmed").is_displayed()
        assert driver.find_element(By.CSS_SELECTOR, "#private-upload-form button[type='submit']").is_displayed()
        _assert_no_overflow(driver)
        _shot(driver, "round4-06-studio-upload-mobile-en-selected.png")
        Select(driver.find_element(By.ID, "upload-zone")).select_by_value(str(data["zone"].pk))
        Select(driver.find_element(By.ID, "upload-method")).select_by_value("print")
        _click(driver, By.ID, "rights-confirmed")
        _click(driver, By.CSS_SELECTOR, "#private-upload-form button[type='submit']")
        wait.until(lambda _d: private_images.count() == 2)
        _assert_no_overflow(driver)

        driver.set_window_size(1440, 1050)
        driver.get(_url(live_server, "studio-project", project.pk) + "?lang=ar")
        wait.until(EC.presence_of_element_located((By.ID, "studio-editor")))
        html = driver.find_element(By.TAG_NAME, "html")
        assert html.get_attribute("lang") == "ar"
        assert html.get_attribute("dir") == "rtl"
        _click(driver, By.CSS_SELECTOR, '[data-studio-tab="upload"]')
        wait.until(EC.visibility_of_element_located((By.ID, "private-upload-form")))
        assert driver.find_element(By.CSS_SELECTOR, 'label[for="private-art-file"]').text.strip() == "اختر صورة"
        assert driver.find_element(By.ID, "private-art-file-status").text.strip() == "لم يتم اختيار صورة"
        workspace = driver.find_element(By.ID, "zone-workspace")
        assert driver.execute_script("return getComputedStyle(arguments[0]).direction", workspace) == "ltr"
        arabic_input = driver.find_element(By.ID, "private-art-file")
        arabic_input.send_keys(str(PRIVATE_UPLOAD_PATH))
        wait.until(lambda d: d.find_element(By.ID, "private-art-file-status").text.strip() == PRIVATE_UPLOAD_PATH.name)
        visible_body = driver.find_element(By.TAG_NAME, "body").text
        assert str(PRIVATE_UPLOAD_PATH) not in visible_body
        assert "fakepath" not in visible_body.lower()
        _assert_no_overflow(driver)
        _shot(driver, "round4-07-studio-upload-ar-rtl-selected.png")
        Select(driver.find_element(By.ID, "upload-zone")).select_by_value(str(data["zone"].pk))
        Select(driver.find_element(By.ID, "upload-method")).select_by_value("print")
        _click(driver, By.ID, "rights-confirmed")
        _click(driver, By.CSS_SELECTOR, "#private-upload-form button[type='submit']")
        wait.until(lambda _d: private_images.count() == 3)
        assert all(
            element.media_asset.access == MediaAsset.Access.PRIVATE and element.rights_confirmed
            for element in private_images.select_related("media_asset")
        )
        _assert_no_overflow(driver)
        _shot(driver, "round4-08-studio-upload-ar-rtl-complete.png")
    finally:
        driver.quit()
