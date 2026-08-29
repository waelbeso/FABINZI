import os
from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.urls import reverse
from selenium import webdriver
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait

from apps.artwork.models import Artwork, ArtworkAsset, ArtworkVersion, DesignedProduct
from apps.checkout.models import CartItem
from apps.design.models import DecorationZone, GarmentDesign, GarmentDesignVersion
from apps.media.models import MediaAsset
from apps.organizations.models import Membership, Organization
from apps.storefront.models import CustomizationElement, StudioProject
from apps.storefront.services import add_product_image, add_variant, create_store_product, create_storefront, publish_store_product, publish_storefront

User = get_user_model()
ARTIFACT_DIR = Path("artifacts/browser-qa")
PRIVATE_UPLOAD_PATH = Path("/tmp/fabinzi-browser-private.png")
PNG_1X1 = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010804000000b51c0c020000000b4944415478da63fcff1f0002eb01f58f59975b0000000049454e44ae426082")


def _creative_catalog(prefix="visualqa"):
    owner = User.objects.create_user(username=f"{prefix}-owner", password="password12345")
    org = Organization.objects.create(kind=Organization.Kind.DESIGNER, display_name="Northstar Creative", email=f"{prefix}@creative.test", verification_status=Organization.VerificationStatus.ACTIVE, created_by=owner)
    Membership.objects.create(organization=org, user=owner, role=Membership.Role.OWNER)
    design = GarmentDesign.objects.create(organization=org, title="Essential Tee", category="apparel", status=GarmentDesign.Status.APPROVED, created_by=owner)
    garment = GarmentDesignVersion.objects.create(design=design, version_number=1, status=GarmentDesignVersion.Status.APPROVED, created_by=owner)
    zone = DecorationZone.objects.create(version=garment, name="Front Center", method=DecorationZone.Method.BOTH, placement={"x": .50, "y": .38}, max_width_mm=260, max_height_mm=300)
    artwork = Artwork.objects.create(organization=org, title="Northstar Lines", description="Geometric line artwork for supported apparel decoration.", tags=["geometric", "line"], status=Artwork.Status.APPROVED, created_by=owner)
    version = ArtworkVersion.objects.create(artwork=artwork, version_number=1, status=ArtworkVersion.Status.APPROVED, metadata={"suitable_for_print": True, "suitable_for_embroidery": True, "public_production_methods": ["print", "embroidery"], "public_product_types": ["apparel"], "public_suitability": ["front placement"]}, created_by=owner)
    art_preview = MediaAsset.objects.create(provider=MediaAsset.Provider.LOCAL_DEV, provider_asset_id="/static/brand/fabinzi-logo.svg", original_filename="northstar-lines.svg", mime_type="image/svg+xml", size_bytes=100, access=MediaAsset.Access.PUBLIC, uploaded_by=owner, metadata={"public_url": "/static/brand/fabinzi-logo.svg"})
    ArtworkAsset.objects.create(version=version, kind=ArtworkAsset.Kind.PREVIEW, media_asset=art_preview)
    designed = DesignedProduct.objects.create(organization=org, garment_version=garment, artwork_version=version, title="Northstar Essential Tee", status=DesignedProduct.Status.PUBLISHED, created_by=owner)
    store = create_storefront(organization=org, actor=owner, slug=f"{prefix}-store", name_en="Northstar Store", name_ar="متجر نورث ستار")
    publish_storefront(storefront=store, actor=owner)
    product = create_store_product(storefront=store, actor=owner, designed_product=designed, slug=f"{prefix}-tee", title_en="Northstar Essential Tee", title_ar="تيشيرت نورث ستار", description_en="Real browser QA customizable product.", description_ar="منتج فعلي لاختبار التخصيص عبر المتصفح.", base_price="650.00", customization_enabled=True)
    variant = add_variant(product=product, actor=owner, sku=f"{prefix.upper()}-M-BLK", size="M", color_name="Black", color_hex="#111111")
    product_image = MediaAsset.objects.create(provider=MediaAsset.Provider.LOCAL_DEV, provider_asset_id="/static/brand/fabinzi-logo.svg", original_filename="product-reference.svg", mime_type="image/svg+xml", size_bytes=100, access=MediaAsset.Access.PUBLIC, uploaded_by=owner, metadata={"public_url": "/static/brand/fabinzi-logo.svg"})
    add_product_image(product=product, actor=owner, media_asset=product_image, alt_en=product.title_en, alt_ar=product.title_ar)
    publish_store_product(product=product, actor=owner)
    return {"owner": owner, "org": org, "zone": zone, "artwork": artwork, "version": version, "store": store, "product": product, "variant": variant}


def _chrome(*, language="en-US,en", width=1440, height=1050):
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument(f"--window-size={width},{height}")
    options.add_experimental_option("prefs", {"intl.accept_languages": language})
    return webdriver.Chrome(options=options)


def _wait(driver):
    return WebDriverWait(driver, 15)


def _url(live_server, name, *args):
    return live_server.url + reverse(name, args=args)


def _login(driver, live_server, client, user):
    client.force_login(user)
    cookie = client.cookies[settings.SESSION_COOKIE_NAME].value
    driver.get(live_server.url + "/")
    driver.add_cookie({"name": settings.SESSION_COOKIE_NAME, "value": cookie, "path": "/"})


def _click(driver, by, locator):
    element = _wait(driver).until(EC.element_to_be_clickable((by, locator)))
    ActionChains(driver).scroll_to_element(element).move_to_element(element).pause(.08).click().perform()
    return element


def _shot(driver, name):
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    if name in {"10-artwork-marketplace-desktop-en-light.png", "23-private-upload-absent-marketplace-desktop-en-light.png"}:
        card = _wait(driver).until(EC.visibility_of_element_located((By.CSS_SELECTOR, ".artwork-market-card")))
        ActionChains(driver).scroll_to_element(card).pause(.12).perform()
    assert driver.save_screenshot(str(ARTIFACT_DIR / name))


def _assert_no_overflow(driver):
    assert driver.execute_script("return document.documentElement.scrollWidth <= window.innerWidth + 1")


def _start_project_from_studio_entry(driver, data):
    wait = _wait(driver)
    wait.until(EC.presence_of_element_located((By.ID, "studio-variant")))
    Select(driver.find_element(By.ID, "studio-variant")).select_by_value(str(data["variant"].pk))
    _click(driver, By.CSS_SELECTOR, 'form:has(#studio-variant) button[type="submit"]')
    wait.until(EC.presence_of_element_located((By.ID, "studio-editor")))
    return StudioProject.objects.filter(product=data["product"]).latest("id")


def _add_preselected_marketplace_artwork(driver, data):
    wait = _wait(driver)
    wait.until(EC.presence_of_element_located((By.ID, "add-artwork-form")))
    selected = driver.find_element(By.ID, "selected-artwork-version")
    assert selected.get_attribute("value") == str(data["version"].pk)
    Select(driver.find_element(By.ID, "artwork-zone")).select_by_value(str(data["zone"].pk))
    Select(driver.find_element(By.ID, "artwork-method")).select_by_value("print")
    _click(driver, By.ID, "add-selected-artwork")
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, '[data-studio-element][data-kind="artwork"]')))
    project = StudioProject.objects.filter(product=data["product"]).latest("id")
    return project, CustomizationElement.objects.get(customization__project=project, kind=CustomizationElement.Kind.ARTWORK)


def _drag_and_wait_persist(driver, element, db_element, dx, dy):
    before = dict(CustomizationElement.objects.get(pk=db_element.pk).transform)
    ActionChains(driver).move_to_element(element).click_and_hold().move_by_offset(dx, dy).pause(.08).release().perform()
    _wait(driver).until(lambda d: CustomizationElement.objects.get(pk=db_element.pk).transform != before)
    _wait(driver).until(lambda d: d.find_element(By.ID, "studio-save-state").get_attribute("data-state") == "saved")
    return CustomizationElement.objects.get(pk=db_element.pk).transform


def _transform_with_pointer_controls(driver, db_element):
    element = _wait(driver).until(EC.element_to_be_clickable((By.CSS_SELECTOR, f'[data-element-id="{db_element.pk}"]')))
    _click(driver, By.CSS_SELECTOR, f'[data-element-id="{db_element.pk}"]')
    moved = _drag_and_wait_persist(driver, element, db_element, 36, 20)

    scale_handle = _wait(driver).until(EC.element_to_be_clickable((By.CSS_SELECTOR, f'[data-element-id="{db_element.pk}"] [data-handle="scale"]')))
    before_scale = dict(moved)
    ActionChains(driver).move_to_element(scale_handle).click_and_hold().move_by_offset(28, 0).pause(.08).release().perform()
    _wait(driver).until(lambda d: CustomizationElement.objects.get(pk=db_element.pk).transform != before_scale)
    _wait(driver).until(lambda d: d.find_element(By.ID, "studio-save-state").get_attribute("data-state") == "saved")

    rotate_handle = _wait(driver).until(EC.element_to_be_clickable((By.CSS_SELECTOR, f'[data-element-id="{db_element.pk}"] [data-handle="rotate"]')))
    before_rotate = dict(CustomizationElement.objects.get(pk=db_element.pk).transform)
    ActionChains(driver).move_to_element(rotate_handle).click_and_hold().move_by_offset(24, -16).pause(.08).release().perform()
    _wait(driver).until(lambda d: CustomizationElement.objects.get(pk=db_element.pk).transform != before_rotate)
    _wait(driver).until(lambda d: d.find_element(By.ID, "studio-save-state").get_attribute("data-state") == "saved")
    return CustomizationElement.objects.get(pk=db_element.pk).transform


def _assert_exact_transform_after_reload(driver, expected, element_id):
    driver.refresh()
    _wait(driver).until(EC.presence_of_element_located((By.CSS_SELECTOR, f'[data-element-id="{element_id}"]')))
    node = driver.find_element(By.CSS_SELECTOR, f'[data-element-id="{element_id}"]')
    actual = {
        "x": float(node.get_attribute("data-x")),
        "y": float(node.get_attribute("data-y")),
        "scale": float(node.get_attribute("data-scale")),
        "rotation": float(node.get_attribute("data-rotation")),
    }
    assert actual == expected


def _ready_and_cart(driver):
    _click(driver, By.ID, "mark-ready")
    _wait(driver).until(EC.presence_of_element_located((By.ID, "add-studio-cart")))
    _click(driver, By.ID, "add-studio-cart")
    _wait(driver).until(EC.url_contains(reverse("cart")))


@pytest.mark.django_db(transaction=True)
def test_artwork_marketplace_and_visual_studio_desktop_journeys(client, live_server):
    if os.getenv("CI") != "true":
        pytest.skip("Real Chrome QA is CI-only.")
    data = _creative_catalog("desktopvisual")
    customer = User.objects.create_user(username="visual-browser-customer", password="password12345", theme_preference="light", language_preference="en")
    PRIVATE_UPLOAD_PATH.write_bytes(PNG_1X1)

    driver = _chrome()
    try:
        _login(driver, live_server, client, customer)
        wait = _wait(driver)

        driver.get(_url(live_server, "artwork"))
        wait.until(EC.presence_of_element_located((By.ID, "art-q")))
        search = driver.find_element(By.ID, "art-q"); search.clear(); search.send_keys("Northstar Lines")
        Select(driver.find_element(By.ID, "art-method")).select_by_value("print")
        _click(driver, By.CSS_SELECTOR, 'form[role="search"] button[type="submit"]')
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".artwork-market-card")))
        assert "Northstar Lines" in driver.page_source
        _assert_no_overflow(driver)
        _shot(driver, "10-artwork-marketplace-desktop-en-light.png")
        _click(driver, By.CSS_SELECTOR, ".artwork-market-card h2 a")
        wait.until(EC.presence_of_element_located((By.ID, "use-artwork")))
        assert "Approved Artwork" in driver.page_source and "Northstar Creative" in driver.page_source
        _shot(driver, "11-artwork-detail-desktop-en-light.png")
        _click(driver, By.CSS_SELECTOR, "#use-artwork a.eligible-product")
        project = _start_project_from_studio_entry(driver, data)
        _assert_no_overflow(driver)
        _shot(driver, "12-studio-initial-desktop-en-light.png")
        assert driver.find_element(By.ID, "selected-artwork-version").get_attribute("value") == str(data["version"].pk)
        _shot(driver, "13-studio-marketplace-selected-desktop-en-light.png")

        project, art_element = _add_preselected_marketplace_artwork(driver, data)
        persisted = _transform_with_pointer_controls(driver, art_element)
        assert persisted["x"] != .5 and persisted["scale"] != .35 and persisted["rotation"] != 0
        _shot(driver, "14-studio-transformed-desktop-en-light.png")
        _assert_exact_transform_after_reload(driver, persisted, art_element.pk)
        assert StudioProject.objects.get(pk=project.pk).status == StudioProject.Status.DRAFT

        driver.set_window_size(900, 1000)
        _assert_no_overflow(driver)
        _shot(driver, "19-studio-tablet-en-light.png")
        driver.set_window_size(1440, 1050)
        _click(driver, By.ID, "mark-ready")
        wait.until(EC.presence_of_element_located((By.ID, "add-studio-cart")))
        _shot(driver, "16-studio-ready-desktop-en-light.png")
        _click(driver, By.ID, "add-studio-cart")
        wait.until(EC.url_contains(reverse("cart")))
        assert CartItem.objects.filter(cart__customer=customer, studio_project=project, kind=CartItem.Kind.STUDIO).exists()
        _shot(driver, "17-customized-cart-desktop-en-light.png")

        driver.get(_url(live_server, "public-store-product", data["store"].slug, data["product"].slug))
        _click(driver, By.ID, "product-customize-link")
        private_project = _start_project_from_studio_entry(driver, data)
        _click(driver, By.CSS_SELECTOR, '[data-studio-tab="upload"]')
        wait.until(EC.visibility_of_element_located((By.ID, "private-upload-form")))
        driver.find_element(By.ID, "private-art-file").send_keys(str(PRIVATE_UPLOAD_PATH))
        Select(driver.find_element(By.ID, "upload-zone")).select_by_value(str(data["zone"].pk))
        Select(driver.find_element(By.ID, "upload-method")).select_by_value("print")
        _click(driver, By.ID, "rights-confirmed")
        assert driver.find_element(By.ID, "rights-confirmed").is_selected()
        _click(driver, By.CSS_SELECTOR, "#private-upload-form button[type='submit']")
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, '[data-studio-element][data-kind="image"]')))
        private_element = CustomizationElement.objects.get(customization__project=private_project, kind=CustomizationElement.Kind.IMAGE)
        assert private_element.media_asset.access == MediaAsset.Access.PRIVATE and private_element.rights_confirmed is True
        private_persisted = _transform_with_pointer_controls(driver, private_element)
        _shot(driver, "18-private-upload-desktop-en-light.png")
        _assert_exact_transform_after_reload(driver, private_persisted, private_element.pk)
        _ready_and_cart(driver)
        driver.get(_url(live_server, "artwork"))
        assert private_element.media_asset.original_filename not in driver.page_source
        assert private_element.media_asset.provider_asset_id not in driver.page_source
        _shot(driver, "23-private-upload-absent-marketplace-desktop-en-light.png")

        driver.get(_url(live_server, "public-store-product", data["store"].slug, data["product"].slug))
        _click(driver, By.ID, "product-customize-link")
        invalid_project = _start_project_from_studio_entry(driver, data)
        _click(driver, By.CSS_SELECTOR, '[data-studio-tab="text"]')
        wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, '[data-studio-pane="text"]')))
        driver.find_element(By.ID, "studio-text").send_keys("Placement")
        Select(driver.find_element(By.ID, "text-zone")).select_by_value(str(data["zone"].pk))
        Select(driver.find_element(By.ID, "text-method")).select_by_value("print")
        _click(driver, By.CSS_SELECTOR, '[data-studio-pane="text"] button[type="submit"]')
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, '[data-studio-element][data-kind="text"]')))
        text_element = CustomizationElement.objects.get(customization__project=invalid_project, kind=CustomizationElement.Kind.TEXT)
        _click(driver, By.CSS_SELECTOR, f'[data-element-id="{text_element.pk}"]')
        before_invalid = dict(text_element.transform)
        x_input = driver.find_element(By.ID, "transform-x")
        x_input.clear(); x_input.send_keys("0.98"); x_input.send_keys(Keys.TAB)
        wait.until(lambda d: d.find_element(By.ID, "studio-validation").get_attribute("data-correction-required") == "true")
        assert driver.find_element(By.ID, "studio-save-state").get_attribute("data-state") == "error"
        text_element.refresh_from_db(); assert text_element.transform == before_invalid
        _shot(driver, "15-studio-invalid-desktop-en-light.png")
        x_input = driver.find_element(By.ID, "transform-x")
        x_input.clear(); x_input.send_keys("0.55"); x_input.send_keys(Keys.TAB)
        wait.until(lambda d: CustomizationElement.objects.get(pk=text_element.pk).transform["x"] == .55)
        wait.until(lambda d: d.find_element(By.ID, "studio-save-state").get_attribute("data-state") == "saved")
        assert driver.find_element(By.ID, "studio-validation").get_attribute("data-correction-required") is None
        _ready_and_cart(driver)
        assert CartItem.objects.filter(cart__customer=customer, studio_project=invalid_project).exists()
    finally:
        driver.quit()


@pytest.mark.django_db(transaction=True)
def test_artwork_studio_mobile_arabic_rtl_dark_journey(client, live_server):
    if os.getenv("CI") != "true":
        pytest.skip("Real Chrome QA is CI-only.")
    data = _creative_catalog("mobilevisual")
    customer = User.objects.create_user(username="visual-mobile-customer", password="password12345", theme_preference="dark", language_preference="ar")
    driver = _chrome(language="ar,en", width=390, height=844)
    try:
        _login(driver, live_server, client, customer)
        wait = _wait(driver)
        driver.get(_url(live_server, "artwork"))
        wait.until(EC.presence_of_element_located((By.ID, "art-q")))
        html = driver.find_element(By.TAG_NAME, "html")
        assert html.get_attribute("dir") == "rtl"
        assert html.get_attribute("data-theme") == "dark"
        assert "سوق FABINZI الإبداعي" in driver.page_source
        _assert_no_overflow(driver)
        art_img = driver.find_element(By.CSS_SELECTOR, ".artwork-market-card img")
        assert driver.execute_script("return getComputedStyle(arguments[0]).filter", art_img) == "none"
        _shot(driver, "21-artwork-mobile-ar-rtl-dark.png")

        _click(driver, By.CSS_SELECTOR, ".artwork-market-card h2 a")
        wait.until(EC.presence_of_element_located((By.ID, "use-artwork")))
        _click(driver, By.CSS_SELECTOR, "#use-artwork a.eligible-product")
        project = _start_project_from_studio_entry(driver, data)
        project, element = _add_preselected_marketplace_artwork(driver, data)
        workspace = driver.find_element(By.ID, "zone-workspace")
        assert driver.execute_script("return getComputedStyle(arguments[0]).direction", workspace) == "ltr"
        node = driver.find_element(By.CSS_SELECTOR, f'[data-element-id="{element.pk}"]')
        before_x = CustomizationElement.objects.get(pk=element.pk).transform["x"]
        _drag_and_wait_persist(driver, node, element, 24, 0)
        after_x = CustomizationElement.objects.get(pk=element.pk).transform["x"]
        assert after_x > before_x, "RTL interface must not mirror physical x coordinates"
        handle = driver.find_element(By.CSS_SELECTOR, f'[data-element-id="{element.pk}"] [data-handle="scale"]')
        rect = driver.execute_script("const r=arguments[0].getBoundingClientRect(); return {w:r.width,h:r.height};", handle)
        assert rect["w"] >= 24 and rect["h"] >= 24
        product_img = driver.find_element(By.CSS_SELECTOR, ".studio-product-preview img")
        assert driver.execute_script("return getComputedStyle(arguments[0]).filter", product_img) == "none"
        assert driver.execute_script("return getComputedStyle(arguments[0]).objectFit", product_img) == "contain"
        _assert_no_overflow(driver)
        _shot(driver, "20-studio-mobile-ar-rtl-dark.png")
        _ready_and_cart(driver)
        assert CartItem.objects.filter(cart__customer=customer, studio_project=project).exists()
        _assert_no_overflow(driver)
        _shot(driver, "22-cart-mobile-ar-rtl-dark.png")
    finally:
        driver.quit()
