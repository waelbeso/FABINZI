import json
import os
import time
from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from apps.artwork.models import Artwork, ArtworkVersion, DesignedProduct
from apps.design.models import GarmentDesign, GarmentDesignVersion
from apps.media.models import MediaAsset
from apps.organizations.models import Membership, Organization
from apps.storefront.models import ProductVariant, StoreProduct, StoreProductImage, Storefront

User = get_user_model()
ARTIFACT_DIR = Path("artifacts/browser-qa")


def _seed_product(prefix="publicqa"):
    owner = User.objects.create_user(username=f"{prefix}-owner", password="password12345")
    org = Organization.objects.create(kind=Organization.Kind.DESIGNER, display_name="Public QA Design House", email=f"{prefix}@brand.test", verification_status=Organization.VerificationStatus.ACTIVE, created_by=owner)
    Membership.objects.create(organization=org, user=owner, role=Membership.Role.OWNER)
    garment = GarmentDesign.objects.create(organization=org, title="Public QA Garment", status=GarmentDesign.Status.APPROVED, created_by=owner)
    garment_version = GarmentDesignVersion.objects.create(design=garment, version_number=1, status=GarmentDesignVersion.Status.APPROVED, created_by=owner)
    artwork = Artwork.objects.create(organization=org, title="Public QA Artwork", status=Artwork.Status.APPROVED, created_by=owner)
    artwork_version = ArtworkVersion.objects.create(artwork=artwork, version_number=1, status=ArtworkVersion.Status.APPROVED, created_by=owner)
    designed = DesignedProduct.objects.create(organization=org, garment_version=garment_version, artwork_version=artwork_version, title="Public QA Designed Product", status=DesignedProduct.Status.PUBLISHED, created_by=owner)
    store = Storefront.objects.create(organization=org, slug=f"{prefix}-store", status=Storefront.Status.PUBLISHED, name_en="Public QA Store", name_ar="متجر اختبار الواجهة", about_en="A published designer store used for browser acceptance.", about_ar="متجر مصمم منشور لاختبار الواجهة.")
    product = StoreProduct.objects.create(storefront=store, designed_product=designed, slug=f"{prefix}-product", status=StoreProduct.Status.PUBLISHED, title_en="Public QA Product", title_ar="منتج اختبار الواجهة", description_en="A real database-backed product used for browser acceptance.", description_ar="منتج حقيقي من قاعدة البيانات لاختبار الواجهة.", base_price="640.00", currency="EGP", featured=True, customization_enabled=True)
    ProductVariant.objects.create(product=product, sku=f"{prefix.upper()}-M", size="M", color_name="Black", color_hex="#111111", stock_quantity=4)
    image = MediaAsset.objects.create(provider=MediaAsset.Provider.LOCAL_DEV, provider_asset_id="/static/brand/fabinzi-logo.svg", original_filename="public-qa.svg", mime_type="image/svg+xml", size_bytes=1, access=MediaAsset.Access.PUBLIC, uploaded_by=owner)
    StoreProductImage.objects.create(product=product, media_asset=image, alt_en="FABINZI Public QA Product", alt_ar="منتج FABINZI لاختبار الواجهة")
    return product


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


def _shot(driver, name):
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    assert driver.save_screenshot(str(ARTIFACT_DIR / name))


def _assert_dom_accessibility_baseline(driver):
    audit = driver.execute_script("""
      const duplicateIds=[...document.querySelectorAll('[id]')]
        .map(el=>el.id).filter((id,i,a)=>id && a.indexOf(id)!==i);
      const unlabeledControls=[...document.querySelectorAll('input:not([type=hidden]):not([type=submit]):not([type=button]),select,textarea')]
        .filter(el=>!(el.labels&&el.labels.length)&&!el.getAttribute('aria-label')&&!el.getAttribute('aria-labelledby'))
        .map(el=>el.id||el.name||el.outerHTML.slice(0,80));
      const unnamedInteractive=[...document.querySelectorAll('a[href],button,summary')]
        .filter(el=>{
          const text=(el.textContent||'').trim();
          const aria=(el.getAttribute('aria-label')||'').trim();
          const labelled=(el.getAttribute('aria-labelledby')||'').trim();
          const imgAlt=[...el.querySelectorAll('img')].some(img=>(img.alt||'').trim());
          return !text&&!aria&&!labelled&&!imgAlt;
        }).map(el=>el.outerHTML.slice(0,120));
      return {
        duplicateIds:[...new Set(duplicateIds)],
        unlabeledControls,
        unnamedInteractive,
        main:document.querySelectorAll('main').length,
        h1:document.querySelectorAll('h1').length,
        missingAlt:document.querySelectorAll('img:not([alt])').length,
        skipLink:!!document.querySelector('.skip-link[href="#main-content"]')
      };
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

    product = _seed_product()
    customer = User.objects.create_user(username="public-site-customer", password="password12345", theme_preference="light", language_preference="en")
    driver = _chrome()
    try:
        driver.get(live_server.url + "/?lang=en")
        wait = WebDriverWait(driver, 10)
        wait.until(EC.presence_of_element_located((By.ID, "home-hero-title")))
        time.sleep(0.5)
        assert "The idea starts with a designer" in driver.page_source
        assert product.title_en in driver.page_source
        _assert_dom_accessibility_baseline(driver)
        assert driver.execute_script("return document.documentElement.scrollWidth <= window.innerWidth + 1")
        assert driver.execute_script("return performance.getEntriesByType('resource').filter(e=>!e.name.startsWith(location.origin)).length") == 0
        nav = driver.execute_script("const n=performance.getEntriesByType('navigation')[0];return {ttfb:n?Math.max(0,n.responseStart-n.requestStart):0,dom:n?n.domContentLoadedEventEnd:0};")
        vitals = driver.execute_script("return window.__fabinziVitals || {cls:0,lcp:0}")
        assert vitals["cls"] < 0.10
        assert vitals["lcp"] == 0 or vitals["lcp"] < 4000
        assert nav["ttfb"] < 1500
        _shot(driver, "08-home-desktop-light.png")

        _login(driver, live_server, client, customer)
        driver.get(live_server.url + "/app/")
        wait.until(EC.presence_of_element_located((By.CLASS_NAME, "customer-welcome")))
        assert "Live products to explore" in driver.page_source
        assert product.title_en in driver.page_source
        _assert_dom_accessibility_baseline(driver)
        assert driver.execute_script("return document.documentElement.scrollWidth <= window.innerWidth + 1")
        _shot(driver, "09-customer-home-desktop-light.png")

        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
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
        assert "منتجات منشورة الآن" in mobile.page_source
        _assert_dom_accessibility_baseline(mobile)
        assert mobile.execute_script("return getComputedStyle(document.querySelector('.brand-logo--dark')).display !== 'none'")
        assert mobile.execute_script("return document.documentElement.scrollWidth <= window.innerWidth + 1")
        _shot(mobile, "10-customer-home-mobile-rtl-dark.png")

        mobile.get(live_server.url + "/?lang=ar")
        WebDriverWait(mobile, 10).until(EC.presence_of_element_located((By.ID, "home-hero-title")))
        assert "الفكرة تبدأ عند المصمم" in mobile.page_source
        _assert_dom_accessibility_baseline(mobile)
        assert mobile.execute_script("return document.documentElement.scrollWidth <= window.innerWidth + 1")
        _shot(mobile, "11-home-mobile-rtl-dark.png")
    finally:
        mobile.quit()

    tablet = _chrome(width=820, height=1180, language="en-US,en")
    try:
        tablet.get(live_server.url + "/?lang=en")
        WebDriverWait(tablet, 10).until(EC.presence_of_element_located((By.ID, "home-hero-title")))
        assert tablet.execute_script("return getComputedStyle(document.querySelector('.mobile-menu')).display !== 'none'")
        _assert_dom_accessibility_baseline(tablet)
        assert tablet.execute_script("return document.documentElement.scrollWidth <= window.innerWidth + 1")
        _shot(tablet, "12-home-tablet-light.png")
    finally:
        tablet.quit()
