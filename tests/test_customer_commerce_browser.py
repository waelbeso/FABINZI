import os
from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.urls import reverse
from selenium import webdriver
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait

from apps.artwork.models import Artwork, ArtworkPlacement, ArtworkVersion, DesignedProduct
from apps.checkout.models import CartItem, CustomerPurchase
from apps.design.models import DecorationZone, GarmentDesign, GarmentDesignVersion
from apps.media.models import MediaAsset
from apps.organizations.models import Membership, Organization
from apps.storefront.models import StudioProject
from apps.storefront.services import add_product_image, add_variant, create_store_product, create_storefront, publish_store_product, publish_storefront

User = get_user_model()
ARTIFACT_DIR = Path("artifacts/browser-qa")


def _catalog(prefix, *, customization=False, ready_designed=False):
    owner = User.objects.create_user(username=f"{prefix}-browser-owner", password="password12345")
    org = Organization.objects.create(kind=Organization.Kind.DESIGNER, display_name=f"{prefix} Browser Brand", email=f"{prefix}-browser@brand.test", verification_status=Organization.VerificationStatus.ACTIVE, created_by=owner)
    Membership.objects.create(organization=org, user=owner, role=Membership.Role.OWNER)
    design = GarmentDesign.objects.create(organization=org, title=f"{prefix} Browser Tee", status=GarmentDesign.Status.APPROVED, created_by=owner)
    version = GarmentDesignVersion.objects.create(design=design, version_number=1, status=GarmentDesignVersion.Status.APPROVED, created_by=owner)
    zone = None
    if customization or ready_designed:
        zone = DecorationZone.objects.create(version=version, name="Front", method=DecorationZone.Method.BOTH, placement={"x": 0.45, "y": 0.35}, max_width_mm=240, max_height_mm=300)
    artwork = Artwork.objects.create(organization=org, title=f"{prefix} Browser Artwork", status=Artwork.Status.APPROVED, created_by=owner)
    artwork_version = ArtworkVersion.objects.create(artwork=artwork, version_number=1, status=ArtworkVersion.Status.APPROVED, created_by=owner)
    designed = DesignedProduct.objects.create(organization=org, garment_version=version, artwork_version=artwork_version, title=f"{prefix} Browser Designed", status=DesignedProduct.Status.PUBLISHED, created_by=owner)
    if ready_designed:
        ArtworkPlacement.objects.create(product=designed, decoration_zone=zone, transform={"x": 0.5, "y": 0.5, "scale": .4, "rotation": 0}, production_method="print")
    store = create_storefront(organization=org, actor=owner, slug=f"{prefix}-browser-store", name_en=f"{prefix} Browser Store", name_ar=f"متجر {prefix} للمتصفح", about_en="Browser QA storefront backed by real test database rows.", about_ar="متجر اختبار متصفح يعتمد على سجلات قاعدة البيانات الفعلية للاختبار.")
    publish_storefront(storefront=store, actor=owner)
    product = create_store_product(storefront=store, actor=owner, designed_product=designed, slug=f"{prefix}-browser-product", title_en=f"{prefix} Browser Product", title_ar=f"منتج {prefix} للمتصفح", description_en="Customer commerce browser QA product.", description_ar="منتج لاختبار رحلة شراء العميل عبر المتصفح.", base_price="500.00", customization_enabled=customization)
    variant = add_variant(product=product, actor=owner, sku=f"{prefix.upper()}-BROWSER-M", size="M", color_name="Black", color_hex="#111111")
    image = MediaAsset.objects.create(provider=MediaAsset.Provider.LOCAL_DEV, provider_asset_id="/static/brand/fabinzi-logo.svg", original_filename=f"{prefix}-browser.svg", mime_type="image/svg+xml", size_bytes=1, access=MediaAsset.Access.PUBLIC, uploaded_by=owner, metadata={"public_url": "/static/brand/fabinzi-logo.svg"})
    add_product_image(product=product, actor=owner, media_asset=image, alt_en=product.title_en, alt_ar=product.title_ar)
    publish_store_product(product=product, actor=owner)
    return product, variant, zone


def _chrome(*, language="en", width=1440, height=1000):
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument(f"--window-size={width},{height}")
    options.add_experimental_option("prefs", {"intl.accept_languages": language})
    return webdriver.Chrome(options=options)


def _login_browser(driver, live_server, client, user):
    client.force_login(user)
    session_cookie = client.cookies[settings.SESSION_COOKIE_NAME].value
    driver.get(live_server.url + "/")
    driver.add_cookie({"name": settings.SESSION_COOKIE_NAME, "value": session_cookie, "path": "/"})


def _url(live_server, name, *args):
    return live_server.url + reverse(name, args=args)


def _wait(driver):
    return WebDriverWait(driver, 12)


def _shot(driver, name):
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    assert driver.save_screenshot(str(ARTIFACT_DIR / name))


def _user_click(driver, by, locator):
    element = _wait(driver).until(EC.element_to_be_clickable((by, locator)))
    ActionChains(driver).scroll_to_element(element).move_to_element(element).pause(0.08).click().perform()


def _add_direct_product(driver, live_server, product, variant):
    driver.get(_url(live_server, "public-store-product", product.storefront.slug, product.slug))
    wait = _wait(driver)
    wait.until(EC.presence_of_element_located((By.ID, "variant")))
    Select(driver.find_element(By.ID, "variant")).select_by_value(str(variant.pk))
    quantity = driver.find_element(By.ID, "quantity")
    quantity.clear(); quantity.send_keys("1")
    _user_click(driver, By.CSS_SELECTOR, f'form[action="{reverse("cart-add-product", args=[product.pk])}"] button[type="submit"]')
    wait.until(EC.url_contains(reverse("cart")))


def _fill_checkout(driver):
    values = {
        "shipping_name": "Browser Customer",
        "shipping_phone": "01000000000",
        "shipping_email": "browser@example.test",
        "shipping_address1": "1 Browser Street",
        "shipping_address2": "",
        "shipping_city": "Cairo",
        "shipping_region": "Cairo",
        "shipping_country": "EG",
        "postal_code": "",
    }
    for field, value in values.items():
        element = driver.find_element(By.NAME, field)
        element.clear()
        if value:
            element.send_keys(value)
    payment = driver.find_element(By.CSS_SELECTOR, 'input[name="payment_method"][value="cod"]')
    if not payment.is_selected():
        _user_click(driver, By.CSS_SELECTOR, 'input[name="payment_method"][value="cod"]')
    assert payment.is_selected()


def _create_text_customization_visually(driver, live_server, custom, custom_variant, custom_zone):
    wait = _wait(driver)
    driver.get(_url(live_server, "public-store-product", custom.storefront.slug, custom.slug))
    _user_click(driver, By.CSS_SELECTOR, f'a[href="{reverse("studio")}?product={custom.pk}"]')
    wait.until(EC.presence_of_element_located((By.ID, "studio-variant")))
    Select(driver.find_element(By.ID, "studio-variant")).select_by_value(str(custom_variant.pk))
    _user_click(driver, By.CSS_SELECTOR, 'form[aria-label="Start customization project"] button[type="submit"]')
    wait.until(EC.presence_of_element_located((By.ID, "studio-editor")))

    _user_click(driver, By.CSS_SELECTOR, '[data-studio-tab="text"]')
    wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, '[data-studio-pane="text"]')))
    Select(driver.find_element(By.ID, "text-zone")).select_by_value(str(custom_zone.pk))
    Select(driver.find_element(By.ID, "text-method")).select_by_value("print")
    driver.find_element(By.ID, "studio-text").send_keys("FABINZI")
    _shot(driver, "02-studio-desktop-light.png")
    _user_click(driver, By.CSS_SELECTOR, '[data-studio-pane="text"] button[type="submit"]')
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, '[data-studio-element]')))
    _user_click(driver, By.ID, "mark-ready")
    wait.until(EC.presence_of_element_located((By.ID, "add-studio-cart")))
    project = StudioProject.objects.get(customer__username="chrome-commerce-customer", product=custom)
    _user_click(driver, By.ID, "add-studio-cart")
    wait.until(EC.url_contains(reverse("cart")))
    return project


@pytest.mark.django_db(transaction=True)
def test_real_chrome_mixed_customer_commerce_journey(client, live_server):
    if os.getenv("CI") != "true":
        pytest.skip("Real Chrome QA is CI-only.")

    customer = User.objects.create_user(username="chrome-commerce-customer", password="password12345", theme_preference="light")
    plain, plain_variant, _ = _catalog("chromeplain")
    custom, custom_variant, custom_zone = _catalog("chromecustom", customization=True)
    ready, ready_variant, _ = _catalog("chromeready", ready_designed=True)

    driver = _chrome(language="en-US,en")
    try:
        _login_browser(driver, live_server, client, customer)
        wait = _wait(driver)
        driver.get(_url(live_server, "public-store-product", plain.storefront.slug, plain.slug))
        wait.until(EC.presence_of_element_located((By.ID, "variant")))
        assert "Add to Cart" in driver.page_source
        assert driver.execute_script("return document.styleSheets.length") >= 2
        _shot(driver, "01-product-desktop-light.png")
        _add_direct_product(driver, live_server, plain, plain_variant)
        assert StudioProject.objects.filter(customer=customer).count() == 0

        project = _create_text_customization_visually(driver, live_server, custom, custom_variant, custom_zone)
        assert CartItem.objects.filter(cart__customer=customer, kind=CartItem.Kind.STUDIO, studio_project=project).exists()

        _add_direct_product(driver, live_server, ready, ready_variant)
        assert CartItem.objects.filter(cart__customer=customer).count() == 3
        assert set(CartItem.objects.filter(cart__customer=customer).values_list("kind", flat=True)) == {CartItem.Kind.PLAIN, CartItem.Kind.STUDIO, CartItem.Kind.READY_DESIGNED}
        _shot(driver, "03-mixed-cart-desktop-light.png")

        _user_click(driver, By.CSS_SELECTOR, f'a[href="{reverse("cart-checkout-start")}"]')
        wait.until(EC.presence_of_element_located((By.NAME, "shipping_name")))
        assert "Cash on Delivery" in driver.page_source
        _fill_checkout(driver)
        _shot(driver, "04-checkout-desktop-light.png")
        _user_click(driver, By.ID, "place-order")
        wait.until(EC.url_contains("/confirmation/"))
        purchase = CustomerPurchase.objects.get(customer=customer)
        assert purchase.status == CustomerPurchase.Status.CONFIRMED
        assert purchase.child_orders.count() == 3
        assert all(order.production_job.manufacturer_id is None for order in purchase.child_orders.all())
        assert str(purchase.number) in driver.page_source
        _shot(driver, "05-confirmation-desktop-light.png")

        driver.get(_url(live_server, "purchase-detail", purchase.pk))
        wait.until(EC.presence_of_element_located((By.CLASS_NAME, "purchase-number")))
        assert plain.title_en in driver.page_source
        assert custom.title_en in driver.page_source
        assert ready.title_en in driver.page_source
        _shot(driver, "06-purchase-detail-desktop-light.png")
    finally:
        driver.quit()

    customer.theme_preference = "dark"
    customer.language_preference = "ar"
    customer.save(update_fields=["theme_preference", "language_preference"])
    rtl_driver = _chrome(language="ar,en", width=390, height=844)
    try:
        _login_browser(rtl_driver, live_server, client, customer)
        rtl_driver.get(_url(live_server, "public-store-product", custom.storefront.slug, custom.slug))
        _wait(rtl_driver).until(EC.presence_of_element_located((By.TAG_NAME, "html")))
        html = rtl_driver.find_element(By.TAG_NAME, "html")
        assert html.get_attribute("dir") == "rtl"
        assert html.get_attribute("data-theme") == "dark"
        assert "أضف إلى السلة" in rtl_driver.page_source
        assert rtl_driver.execute_script("return document.documentElement.scrollWidth <= window.innerWidth + 1")
        _shot(rtl_driver, "07-product-mobile-rtl-dark.png")
    finally:
        rtl_driver.quit()
