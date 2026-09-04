import base64
import json
import os
import time
from pathlib import Path
from urllib.request import urlopen

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from apps.artwork.models import Artwork, ArtworkAsset, ArtworkVersion, DesignedProduct
from apps.design.models import GarmentDesign, GarmentDesignVersion
from apps.manufacturer_marketplace.models import ManufacturerCapability, ManufacturerListing
from apps.media.models import MediaAsset
from apps.organizations.models import Membership, Organization
from apps.storefront.models import ProductVariant, StoreProduct, StoreProductImage, Storefront

User = get_user_model()
ARTIFACT_DIR = Path("artifacts/browser-qa")


def _seed_public_site(prefix="publicqa"):
    owner = User.objects.create_user(username=f"{prefix}-owner", password="password12345")
    org = Organization.objects.create(kind=Organization.Kind.DESIGNER, display_name="Public QA Design House", email=f"{prefix}@brand.test", verification_status=Organization.VerificationStatus.ACTIVE, created_by=owner)
    Membership.objects.create(organization=org, user=owner, role=Membership.Role.OWNER)
    garment = GarmentDesign.objects.create(organization=org, title="Public QA Garment", status=GarmentDesign.Status.APPROVED, created_by=owner)
    garment_version = GarmentDesignVersion.objects.create(design=garment, version_number=1, status=GarmentDesignVersion.Status.APPROVED, created_by=owner)
    artwork = Artwork.objects.create(organization=org, title="Public QA Artwork", description="A browser acceptance artwork.", tags=["graphic", "fashion"], status=Artwork.Status.APPROVED, created_by=owner)
    artwork_version = ArtworkVersion.objects.create(artwork=artwork, version_number=1, status=ArtworkVersion.Status.APPROVED, metadata={"public_suitability": "T-shirts and casual apparel"}, created_by=owner)
    designed = DesignedProduct.objects.create(organization=org, garment_version=garment_version, artwork_version=artwork_version, title="Public QA Designed Product", status=DesignedProduct.Status.PUBLISHED, created_by=owner)
    store = Storefront.objects.create(organization=org, slug=f"{prefix}-store", status=Storefront.Status.PUBLISHED, name_en="Public QA Store", name_ar="متجر اختبار الواجهة", about_en="A published designer store used for browser acceptance.", about_ar="متجر مصمم منشور لاختبار الواجهة.")
    product = StoreProduct.objects.create(storefront=store, designed_product=designed, slug=f"{prefix}-product", status=StoreProduct.Status.PUBLISHED, title_en="Public QA Product", title_ar="منتج اختبار الواجهة", description_en="A real database-backed product used for browser acceptance.", description_ar="منتج حقيقي من قاعدة البيانات لاختبار الواجهة.", base_price="640.00", currency="EGP", featured=True, customization_enabled=True)
    ProductVariant.objects.create(product=product, sku=f"{prefix.upper()}-M", size="M", color_name="Black", color_hex="#111111", stock_quantity=4)
    image = MediaAsset.objects.create(provider=MediaAsset.Provider.LOCAL_DEV, provider_asset_id="/static/brand/fabinzi-logo.svg", original_filename="public-qa.svg", mime_type="image/svg+xml", size_bytes=1, access=MediaAsset.Access.PUBLIC, uploaded_by=owner)
    StoreProductImage.objects.create(product=product, media_asset=image, alt_en="FABINZI Public QA Product", alt_ar="منتج FABINZI لاختبار الواجهة")
    ArtworkAsset.objects.create(version=artwork_version, kind=ArtworkAsset.Kind.PREVIEW, media_asset=image, label="Public browser preview")

    manufacturer_owner = User.objects.create_user(username=f"{prefix}-manufacturer-owner", password="password12345")
    manufacturer_org = Organization.objects.create(kind=Organization.Kind.MANUFACTURER, display_name="Public QA Manufacturing", email=f"{prefix}-manufacturer@factory.test", city="Cairo", region="Cairo", country="EG", verification_status=Organization.VerificationStatus.ACTIVE, created_by=manufacturer_owner)
    Membership.objects.create(organization=manufacturer_org, user=manufacturer_owner, role=Membership.Role.OWNER)
    listing = ManufacturerListing.objects.create(organization=manufacturer_org, status=ManufacturerListing.Status.PUBLISHED, headline_en="Print, embroidery and cut-and-sew partner", headline_ar="شريك للطباعة والتطريز والقص والخياطة")
    ManufacturerCapability.objects.create(listing=listing, capability_type=ManufacturerCapability.CapabilityType.PRINT, name="Digital printing", is_active=True)
    ManufacturerCapability.objects.create(listing=listing, capability_type=ManufacturerCapability.CapabilityType.EMBROIDERY, name="Embroidery", is_active=True)
    ManufacturerCapability.objects.create(listing=listing, capability_type=ManufacturerCapability.CapabilityType.CUT_SEW, name="Cut & sew", is_active=True)
    return product, artwork, listing


def _chrome(width=1440, height=1000, language="en-US,en"):
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument(f"--window-size={width},{height}")
    options.add_experimental_option("prefs", {"intl.accept_languages": language})
    driver = webdriver.Chrome(options=options)
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": """
      window.__fabinziVitals={cls:0,lcp:0};
      try { new PerformanceObserver((list)=>{for(const e of list.getEntries()){if(!e.hadRecentInput)window.__fabinziVitals.cls+=e.value;}}).observe({type:'layout-shift',buffered:true}); } catch(e) {}
      try { new PerformanceObserver((list)=>{const es=list.getEntries();if(es.length)window.__fabinziVitals.lcp=es[es.length-1].startTime;}).observe({type:'largest-contentful-paint',buffered:true}); } catch(e) {}
    """})
    return driver


def _login(driver, live_server, client, user):
    client.force_login(user)
    cookie = client.cookies[settings.SESSION_COOKIE_NAME].value
    driver.get(live_server.url + "/")
    driver.add_cookie({"name": settings.SESSION_COOKIE_NAME, "value": cookie, "path": "/"})


def _full_page_shot(driver, name):
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    metrics = driver.execute_cdp_cmd("Page.getLayoutMetrics", {})
    size = metrics.get("cssContentSize") or metrics.get("contentSize")
    result = driver.execute_cdp_cmd("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": True, "fromSurface": True, "clip": {"x": 0, "y": 0, "width": size["width"], "height": size["height"], "scale": 1}})
    (ARTIFACT_DIR / name).write_bytes(base64.b64decode(result["data"]))


def _assert_dom_accessibility_baseline(driver):
    audit = driver.execute_script("""
      const duplicateIds=[...document.querySelectorAll('[id]')].map(el=>el.id).filter((id,i,a)=>id && a.indexOf(id)!==i);
      const unlabeledControls=[...document.querySelectorAll('input:not([type=hidden]):not([type=submit]):not([type=button]),select,textarea')].filter(el=>!(el.labels&&el.labels.length)&&!el.getAttribute('aria-label')&&!el.getAttribute('aria-labelledby')).map(el=>el.id||el.name||el.outerHTML.slice(0,80));
      const unnamedInteractive=[...document.querySelectorAll('a[href],button,summary')].filter(el=>{const text=(el.textContent||'').trim();const aria=(el.getAttribute('aria-label')||'').trim();const labelled=(el.getAttribute('aria-labelledby')||'').trim();const imgAlt=[...el.querySelectorAll('img')].some(img=>(img.alt||'').trim());return !text&&!aria&&!labelled&&!imgAlt;}).map(el=>el.outerHTML.slice(0,120));
      return {duplicateIds:[...new Set(duplicateIds)],unlabeledControls,unnamedInteractive,main:document.querySelectorAll('main').length,h1:document.querySelectorAll('h1').length,missingAlt:document.querySelectorAll('img:not([alt])').length,skipLink:!!document.querySelector('.skip-link[href="#main-content"]')};
    """)
    assert audit["duplicateIds"] == []
    assert audit["unlabeledControls"] == []
    assert audit["unnamedInteractive"] == []
    assert audit["main"] == 1
    assert audit["h1"] == 1
    assert audit["missingAlt"] == 0
    assert audit["skipLink"] is True


@pytest.mark.django_db(transaction=True)
def test_public_and_customer_site_real_chrome_acceptance(client, live_server):
    if os.getenv("CI") != "true":
        pytest.skip("Real Chrome production-site QA is CI-only.")

    product, artwork, manufacturer = _seed_public_site()
    customer = User.objects.create_user(username="public-site-customer", password="password12345", theme_preference="light", language_preference="en")
    driver = _chrome()
    try:
        wait = WebDriverWait(driver, 10)
        driver.get(live_server.url + "/?lang=en")
        wait.until(EC.presence_of_element_located((By.ID, "catalog-results-title")))
        time.sleep(0.5)
        assert product.title_en in driver.page_source
        assert "Discover" in driver.page_source
        assert "How it works" in driver.page_source
        _assert_dom_accessibility_baseline(driver)
        assert driver.execute_script("return document.documentElement.scrollWidth <= window.innerWidth + 1")
        assert driver.execute_script("return performance.getEntriesByType('resource').filter(e=>!e.name.startsWith(location.origin)).length") == 0
        nav = driver.execute_script("const n=performance.getEntriesByType('navigation')[0];return {ttfb:n?Math.max(0,n.responseStart-n.requestStart):0,dom:n?n.domContentLoadedEventEnd:0};")
        vitals = driver.execute_script("return window.__fabinziVitals || {cls:0,lcp:0}")
        assert vitals["cls"] < 0.10
        assert vitals["lcp"] == 0 or vitals["lcp"] < 4000
        assert nav["ttfb"] < 1500
        _full_page_shot(driver, "08-store-desktop-light.png")

        driver.get(live_server.url + "/discover/?lang=en")
        wait.until(EC.presence_of_element_located((By.ID, "home-hero-title")))
        assert "The idea starts with a designer" in driver.page_source
        assert artwork.title in driver.page_source
        assert "T-shirts and casual apparel" in driver.page_source
        assert manufacturer.organization.display_name in driver.page_source
        assert "Digital printing" in driver.page_source
        assert driver.find_element(By.ID, "featured-artwork").is_displayed()
        assert driver.find_element(By.ID, "manufacturing-network").is_displayed()
        _assert_dom_accessibility_baseline(driver)
        _full_page_shot(driver, "09-discover-desktop-light.png")
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        with urlopen(live_server.url + "/share/fabinzi-1200x630.png", timeout=10) as response:
            (ARTIFACT_DIR / "13-social-share-1200x630.png").write_bytes(response.read())

        _login(driver, live_server, client, customer)
        driver.get(live_server.url + "/app/")
        wait.until(EC.presence_of_element_located((By.CLASS_NAME, "customer-welcome")))
        assert "Recent purchases" in driver.page_source
        assert "Customization projects" in driver.page_source
        assert "Account preferences" in driver.page_source
        assert "Live products to explore" not in driver.page_source
        assert "Approved artwork to discover" not in driver.page_source
        assert product.title_en not in driver.page_source
        assert "Save preferences" not in driver.page_source
        _assert_dom_accessibility_baseline(driver)
        _full_page_shot(driver, "10-customer-home-desktop-light.png")

        driver.get(live_server.url + "/app/settings/preferences/")
        wait.until(EC.presence_of_element_located((By.ID, "id_language")))
        assert driver.find_element(By.CSS_SELECTOR, ".account-settings-intro h1").text == "Profile & preferences"
        for control_id in ("id_first_name", "id_last_name", "id_language", "id_theme", "id_email", "id_current_password"):
            assert driver.find_element(By.ID, control_id).is_displayed()
        assert "Secure email change" in driver.page_source
        _assert_dom_accessibility_baseline(driver)
        (ARTIFACT_DIR / "public-performance.json").write_text(json.dumps({"navigation": nav, "vitals": vitals}, indent=2), encoding="utf-8")
    finally:
        driver.quit()

    customer.theme_preference = "dark"
    customer.language_preference = "ar"
    customer.save(update_fields=["theme_preference", "language_preference"])
    mobile = _chrome(width=390, height=844, language="ar,en")
    try:
        _login(mobile, live_server, client, customer)
        mobile.get(live_server.url + "/app/?lang=ar")
        WebDriverWait(mobile, 10).until(EC.presence_of_element_located((By.CLASS_NAME, "customer-welcome")))
        html = mobile.find_element(By.TAG_NAME, "html")
        assert html.get_attribute("dir") == "rtl"
        assert html.get_attribute("data-theme") == "dark"
        assert "آخر المشتريات" in mobile.page_source
        assert "مشاريع التخصيص" in mobile.page_source
        assert "منتجات منشورة الآن" not in mobile.page_source
        _assert_dom_accessibility_baseline(mobile)

        mobile.get(live_server.url + "/discover/?lang=ar")
        WebDriverWait(mobile, 10).until(EC.presence_of_element_located((By.ID, "home-hero-title")))
        assert "الفكرة تبدأ عند المصمم" in mobile.page_source
        assert artwork.title in mobile.page_source
        assert manufacturer.organization.display_name in mobile.page_source
        _assert_dom_accessibility_baseline(mobile)
        assert mobile.execute_script("return document.documentElement.scrollWidth <= window.innerWidth + 1")
        _full_page_shot(mobile, "11-discover-mobile-rtl-dark.png")
    finally:
        mobile.quit()

    tablet = _chrome(width=820, height=1180, language="en-US,en")
    try:
        tablet.get(live_server.url + "/?lang=en")
        WebDriverWait(tablet, 10).until(EC.presence_of_element_located((By.ID, "catalog-results-title")))
        assert tablet.execute_script("return getComputedStyle(document.querySelector('.mobile-menu')).display !== 'none'")
        assert product.title_en in tablet.page_source
        _assert_dom_accessibility_baseline(tablet)
        assert tablet.execute_script("return document.documentElement.scrollWidth <= window.innerWidth + 1")
        _full_page_shot(tablet, "12-store-tablet-light.png")
    finally:
        tablet.quit()
