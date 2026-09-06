import os

import pytest
from django.contrib.auth import get_user_model
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select

from apps.artwork.models import ArtworkAsset
from apps.artwork.services import create_artwork
from apps.design.models import DesignAsset, GarmentDesignVersion
from apps.design.services import create_design
from apps.media.models import MediaAsset
from apps.public_inquiries.models import PublicInquiry
from apps.public_inquiries.services import designer_public_references
from apps.public_profiles.models import ProfessionalPublicState
from apps.public_profiles.services import ensure_public_state
from apps.storefront.models import Storefront

from .conftest import VALID_PNG
from .test_designer_portal_browser import (
    _active_designer,
    _approved_artwork,
    _chrome,
    _click_element,
    _login,
    _no_overflow,
    _replace,
    _shot,
    _wait,
)
from .v2_3_support import v2_3_reference_rows


User = get_user_model()


def _upload_form(container):
    return container.find_element(
        By.XPATH,
        './/form[.//input[@type="hidden" and @name="action" and @value="upload_asset"]]',
    )


def _submit_form_and_wait_for_navigation(driver, form):
    """Use the established native interaction, then synchronize on the real response document."""
    button = form.find_element(By.CSS_SELECTOR, 'button[type="submit"]')
    _click_element(driver, button)
    _wait(driver).until(EC.staleness_of(form))


@pytest.mark.django_db(transaction=True)
def test_designer_round2_real_chrome_owner_surfaces_and_upload_inputs(
    client,
    live_server,
    tmp_path,
    settings,
    v2_3_reference_rows,
):
    if os.getenv("CI") != "true":
        pytest.skip("Real Chrome Designer Round 2 QA is CI-only.")

    settings.ENVIRONMENT = "test"
    settings.PRIVATE_MEDIA_STORAGE_MODE = "local"

    owner = User.objects.create_user(
        username="round2-browser-owner",
        password="password12345",
        email="round2-owner@example.test",
        language_preference="en",
        theme_preference="light",
    )
    customer = User.objects.create_user(
        username="round2-browser-customer",
        password="password12345",
        email="round2-customer@example.test",
    )
    staff = User.objects.create_user(
        username="round2-browser-staff",
        password="password12345",
        is_staff=True,
    )
    organization = _active_designer(owner)
    public_artwork, _public_artwork_version, _ip_case = _approved_artwork(owner, staff, organization)
    public_state = ensure_public_state(organization)
    public_state.public_name_en = "Round 2 Studio"
    public_state.public_name_ar = "استوديو الجولة الثانية"
    public_state.bio_en = "Owner-reviewed public Designer profile."
    public_state.bio_ar = "ملف مصمم عام للمراجعة."
    public_state.visibility = ProfessionalPublicState.Visibility.VISIBLE
    public_state.save()
    refs = designer_public_references(organization)
    assert public_artwork in refs[PublicInquiry.DesignerWorkKind.ARTWORK]

    draft_design = create_design(
        organization=organization,
        actor=owner,
        title="Round 2 Browser DXF",
    )
    draft_design_version = draft_design.versions.get()
    draft_artwork = create_artwork(
        organization=organization,
        actor=owner,
        title="Round 2 Browser Artwork Uploads",
    )
    draft_artwork_version = draft_artwork.versions.get()

    dxf_path = tmp_path / "round2-browser-pattern.dxf"
    dxf_path.write_bytes(b"0\nSECTION\n2\nHEADER\n0\nENDSEC\n0\nEOF\n")
    preview_path = tmp_path / "round2-browser-preview.png"
    preview_path.write_bytes(VALID_PNG)
    source_path = tmp_path / "round2-browser-source.svg"
    source_path.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12"></svg>', encoding="utf-8")
    rights_path = tmp_path / "round2-browser-rights.pdf"
    rights_path.write_bytes(b"%PDF-1.4\n% Round 2 rights evidence\n")

    driver = _chrome(width=1440, height=1100)
    try:
        wait = _wait(driver)

        # Owner public-profile management: real rendered controls and draft lifecycle.
        _login(driver, live_server, client, owner)
        driver.get(f"{live_server.url}/designer/public-profile/?org={organization.pk}&lang=en")
        for element_id in (
            "revision-state-title",
            "public-identity-title",
            "location-studio-title",
            "professional-presence-title",
            "public-media-title",
            "revision-actions-title",
            "visibility-actions-title",
        ):
            wait.until(EC.visibility_of_element_located((By.ID, element_id)))
        profile_name = driver.find_element(By.ID, "public-name-en")
        _replace(driver, profile_name, "Round 2 Studio Draft")
        _shot(driver, "round2-01-public-profile-editor-desktop-en.png")
        save_button = driver.find_element(By.CSS_SELECTOR, 'button[name="action"][value="save_revision"]')
        _click_element(driver, save_button)
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "Public profile draft saved."))
        assert organization.public_profile_revisions.filter(status="draft").exists()

        # Current approved public state remains public while the draft revision is pending.
        driver.get(f"{live_server.url}/designers/{public_state.slug}/?lang=en")
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "Round 2 Studio"))
        assert "Round 2 Studio Draft" not in driver.page_source
        assert _no_overflow(driver)
        _shot(driver, "round2-02-public-profile-desktop-en.png")

        # Authenticated customer public inquiry uses the real responsive form.
        _login(driver, live_server, client, customer)
        driver.get(f"{live_server.url}/inquiry/designer/{public_state.slug}/?lang=en")
        wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, ".v25-inquiry-form")))
        assert _no_overflow(driver)
        Select(driver.find_element(By.ID, "inquiry-work-ref")).select_by_value(
            f"artwork:{public_artwork.pk}"
        )
        _replace(driver, driver.find_element(By.ID, "inquiry-quantity"), "2")
        driver.find_element(By.ID, "inquiry-sizes").send_keys("M,L")
        driver.find_element(By.ID, "inquiry-colors").send_keys("Black")
        driver.find_element(By.ID, "inquiry-customization").send_keys("Round 2 browser inquiry")
        _shot(driver, "round2-03-public-inquiry-desktop-en.png")
        _click_element(driver, driver.find_element(By.CSS_SELECTOR, 'button[name="action"][value="submit"]'))
        wait.until(lambda _d: PublicInquiry.objects.filter(sender_user=customer, target_organization=organization).exists())

        # Actual HTML Design file input: real DXF multipart upload and private attachment.
        _login(driver, live_server, client, owner)
        driver.get(f"{live_server.url}/designer/designs/{draft_design.pk}/?org={organization.pk}&version={draft_design_version.pk}&lang=en")
        design_assets = wait.until(EC.visibility_of_element_located((By.ID, "design-assets")))
        design_form = _upload_form(design_assets)
        kind_select = Select(design_form.find_element(By.NAME, "kind"))
        kind_select.select_by_value(DesignAsset.Kind.PATTERN)
        label_input = design_form.find_element(By.NAME, "label")
        label_input.send_keys("Browser DXF Pattern")
        file_input = design_form.find_element(By.CSS_SELECTOR, 'input[type="file"][name="file"]')
        file_input.send_keys(str(dxf_path))

        # Pre-submit evidence proves the rendered multipart form and domain state are correct.
        assert design_form.get_attribute("method").lower() == "post"
        assert design_form.get_attribute("enctype").lower() == "multipart/form-data"
        assert design_form.find_element(By.CSS_SELECTOR, 'input[type="hidden"][name="action"]').get_attribute("value") == "upload_asset"
        assert design_form.find_element(By.CSS_SELECTOR, 'input[type="hidden"][name="version_id"]').get_attribute("value") == str(draft_design_version.pk)
        assert kind_select.first_selected_option.get_attribute("value") == DesignAsset.Kind.PATTERN
        assert label_input.get_attribute("value") == "Browser DXF Pattern"
        assert dxf_path.exists()
        assert dxf_path.stat().st_size > 0
        assert dxf_path.name in file_input.get_attribute("value")
        draft_design.refresh_from_db()
        draft_design_version.refresh_from_db()
        assert draft_design.organization_id == organization.pk
        assert draft_design_version.status == GarmentDesignVersion.Status.DRAFT
        assert organization.memberships.filter(user=owner, is_active=True).exists()
        assert driver.execute_script("return arguments[0].checkValidity();", design_form) is True

        media_count_before = MediaAsset.objects.count()
        design_count_before = DesignAsset.objects.filter(version=draft_design_version).count()
        _shot(driver, "round2-04-design-assets-before-upload-desktop-en.png")

        # Synchronize on the real redirect response before inspecting ORM state.
        _submit_form_and_wait_for_navigation(driver, design_form)
        result_body = driver.find_element(By.TAG_NAME, "body").text
        design_assets = wait.until(EC.visibility_of_element_located((By.ID, "design-assets")))
        assert "Design asset attached privately." in result_body
        assert MediaAsset.objects.count() == media_count_before + 1
        assert DesignAsset.objects.filter(version=draft_design_version).count() == design_count_before + 1
        design_asset = DesignAsset.objects.select_related("media_asset").get(
            version=draft_design_version,
            label="Browser DXF Pattern",
        )
        assert design_asset.media_asset.access == MediaAsset.Access.PRIVATE
        assert design_asset.media_asset.original_filename == dxf_path.name
        assert "Browser DXF Pattern" in design_assets.text
        assert "/media/designer-private/" in driver.page_source
        _shot(driver, "round2-05-design-assets-after-upload-desktop-en.png")

        # Actual HTML Artwork inputs: Preview, Production Source and Rights Evidence.
        driver.get(f"{live_server.url}/designer/artworks/{draft_artwork.pk}/?org={organization.pk}&version={draft_artwork_version.pk}&lang=en")
        artwork_section = wait.until(
            EC.visibility_of_element_located(
                (By.XPATH, '//section[.//h2[normalize-space(.)="Artwork assets"]]')
            )
        )
        for kind, label, path in (
            (ArtworkAsset.Kind.PREVIEW, "Browser Preview", preview_path),
            (ArtworkAsset.Kind.SOURCE, "Browser Production Source", source_path),
            (ArtworkAsset.Kind.RIGHTS_EVIDENCE, "Browser Rights Evidence", rights_path),
        ):
            artwork_section = wait.until(
                EC.visibility_of_element_located(
                    (By.XPATH, '//section[.//h2[normalize-space(.)="Artwork assets"]]')
                )
            )
            form = _upload_form(artwork_section)
            Select(form.find_element(By.NAME, "kind")).select_by_value(kind)
            form.find_element(By.NAME, "label").send_keys(label)
            artwork_file_input = form.find_element(By.CSS_SELECTOR, 'input[type="file"][name="file"]')
            artwork_file_input.send_keys(str(path))
            assert path.exists()
            assert path.stat().st_size > 0
            assert path.name in artwork_file_input.get_attribute("value")
            assert driver.execute_script("return arguments[0].checkValidity();", form) is True
            if kind == ArtworkAsset.Kind.PREVIEW:
                _shot(driver, "round2-06-artwork-assets-before-upload-desktop-en.png")
            _submit_form_and_wait_for_navigation(driver, form)
            result_body = driver.find_element(By.TAG_NAME, "body").text
            assert "Artwork asset attached privately for workflow use." in result_body
            wait.until(
                lambda _d, expected=label: ArtworkAsset.objects.filter(
                    version=draft_artwork_version,
                    label=expected,
                ).exists()
            )
        uploaded_artwork_assets = list(
            ArtworkAsset.objects.filter(version=draft_artwork_version).select_related("media_asset")
        )
        assert {row.kind for row in uploaded_artwork_assets} == {
            ArtworkAsset.Kind.PREVIEW,
            ArtworkAsset.Kind.SOURCE,
            ArtworkAsset.Kind.RIGHTS_EVIDENCE,
        }
        assert all(row.media_asset.access == MediaAsset.Access.PRIVATE for row in uploaded_artwork_assets)
        assert not any((row.media_asset.metadata or {}).get("artwork_public_derivative") for row in uploaded_artwork_assets)
        assert "Submit Artwork for review" in driver.page_source
        _shot(driver, "round2-07-artwork-assets-after-upload-desktop-en.png")

        # Create Store surface: route guidance is real and creation remains Draft until separate Publish.
        driver.get(f"{live_server.url}/designer/store/?org={organization.pk}&lang=en")
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "Store setup"))
        assert driver.find_element(By.CSS_SELECTOR, ".round2-url-preview code").text == "/store/<slug>/"
        assert "Create does not mean Publish" in driver.page_source
        create_form = driver.find_element(By.XPATH, '//form[.//input[@name="action" and @value="create"]]')
        create_form.find_element(By.NAME, "slug").send_keys("round2-browser-store")
        create_form.find_element(By.NAME, "name_en").send_keys("Round 2 Browser Store")
        create_form.find_element(By.NAME, "name_ar").send_keys("متجر الجولة الثانية")
        create_form.find_element(By.NAME, "about_en").send_keys("Round 2 browser Storefront")
        create_form.find_element(By.NAME, "about_ar").send_keys("واجهة متجر الجولة الثانية")
        _shot(driver, "round2-08-create-store-desktop-en.png")

        # Mobile + Arabic RTL screenshots for Owner-relevant corrected surfaces before Store creation.
        driver.set_window_size(390, 844)
        driver.get(f"{live_server.url}/designer/store/?org={organization.pk}&lang=ar")
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "إعداد المتجر"))
        assert driver.find_element(By.TAG_NAME, "html").get_attribute("dir") == "rtl"
        assert _no_overflow(driver)
        _shot(driver, "round2-09-create-store-mobile-ar-rtl.png")
        driver.get(f"{live_server.url}/designer/public-profile/?org={organization.pk}&lang=ar")
        wait.until(EC.visibility_of_element_located((By.ID, "public-identity-title")))
        assert driver.find_element(By.TAG_NAME, "html").get_attribute("dir") == "rtl"
        assert _no_overflow(driver)
        _shot(driver, "round2-10-public-profile-editor-mobile-ar-rtl.png")
        driver.get(f"{live_server.url}/designer/designs/{draft_design.pk}/?org={organization.pk}&version={draft_design_version.pk}&lang=ar")
        wait.until(EC.visibility_of_element_located((By.ID, "design-assets")))
        assert _no_overflow(driver)
        _shot(driver, "round2-11-design-assets-mobile-ar-rtl.png")
        driver.get(f"{live_server.url}/designer/artworks/{draft_artwork.pk}/?org={organization.pk}&version={draft_artwork_version.pk}&lang=ar")
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "html")))
        assert _no_overflow(driver)
        _shot(driver, "round2-12-artwork-assets-mobile-ar-rtl.png")

        _login(driver, live_server, client, customer)
        driver.get(f"{live_server.url}/inquiry/designer/{public_state.slug}/?lang=ar")
        wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, ".v25-inquiry-form")))
        assert driver.find_element(By.TAG_NAME, "html").get_attribute("dir") == "rtl"
        assert _no_overflow(driver)
        _shot(driver, "round2-13-public-inquiry-mobile-ar-rtl.png")

        # Return as owner and perform the actual Store creation; verify Draft and existing management actions.
        driver.set_window_size(1440, 1100)
        _login(driver, live_server, client, owner)
        driver.get(f"{live_server.url}/designer/store/?org={organization.pk}&lang=en")
        create_form = wait.until(
            EC.visibility_of_element_located(
                (By.XPATH, '//form[.//input[@name="action" and @value="create"]]')
            )
        )
        create_form.find_element(By.NAME, "slug").send_keys("round2-browser-store")
        create_form.find_element(By.NAME, "name_en").send_keys("Round 2 Browser Store")
        create_form.find_element(By.NAME, "name_ar").send_keys("متجر الجولة الثانية")
        create_form.find_element(By.NAME, "about_en").send_keys("Round 2 browser Storefront")
        create_form.find_element(By.NAME, "about_ar").send_keys("واجهة متجر الجولة الثانية")
        _click_element(driver, create_form.find_element(By.CSS_SELECTOR, 'button[type="submit"]'))
        wait.until(lambda _d: Storefront.objects.filter(organization=organization).exists())
        store = Storefront.objects.get(organization=organization)
        assert store.status == Storefront.Status.DRAFT
        wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "Publish Store"))
        assert "Products" in driver.page_source
        assert "Add catalog product" in driver.page_source
        _shot(driver, "round2-14-store-management-draft-desktop-en.png")
    finally:
        driver.quit()
