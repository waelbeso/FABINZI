import io
import os
import threading
from pathlib import Path

import pytest
from PIL import Image
from django.contrib.auth import get_user_model
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from apps.design.models import DecorationZone
from apps.integrations.models import IntegrationConfig
from apps.storefront.designer_services import hide_store_product
from apps.storefront.models import StoreProduct
from apps.storefront.services import publish_store_product, publish_storefront
from .test_designer_account_phase6 import _catalog
from .test_designer_portal_browser import _chrome, _click_element, _login, _no_overflow, _shot

User = get_user_model()
ARTIFACT_DIR = Path("artifacts/designer-browser-qa")


def _wait(driver, seconds=20):
    return WebDriverWait(driver, seconds)


def _shot_checked(driver, name):
    _shot(driver, name)
    assert (ARTIFACT_DIR / name).exists()
    assert _no_overflow(driver)


def _large_png(path):
    # Real, incompressible-enough raster payload so Chrome's throttled multipart
    # upload remains observable between 0 and 100 percent.
    width = height = 900
    image = Image.frombytes("RGB", (width, height), os.urandom(width * height * 3))
    image.save(path, format="PNG", compress_level=1)
    assert 1_500_000 < path.stat().st_size < 10 * 1024 * 1024


def _small_png(path, color):
    image = Image.new("RGB", (420, 520), color)
    image.save(path, format="PNG")


@pytest.mark.django_db(transaction=True)
def test_designer_phase6_store_product_media_browser_evidence(client, live_server, tmp_path, monkeypatch):
    if os.getenv("CI") != "true":
        pytest.skip("Phase 6 real-browser evidence is CI-only.")

    from apps.media import designer_public_services as media_service

    owner, org, store, product = _catalog("phase6-browser")
    # Keep the Store public while the Store product remains Draft and editable.
    publish_storefront(storefront=store, actor=owner)
    product.customization_enabled = True
    product.save(update_fields=["customization_enabled", "updated_at"])
    garment_version = product.designed_product.garment_version
    DecorationZone.objects.get_or_create(
        version=garment_version,
        name="Front",
        defaults={
            "method": DecorationZone.Method.PRINT,
            "placement": {"x": 0.2, "y": 0.2, "width": 0.6, "height": 0.6},
            "max_width_mm": 220,
            "max_height_mm": 260,
        },
    )

    IntegrationConfig.objects.update_or_create(
        provider=IntegrationConfig.Provider.CLOUDFLARE_IMAGES,
        defaults={"enabled": True, "config": {"account_id": "a" * 32}},
    )
    monkeypatch.setattr(IntegrationConfig, "get_secrets", lambda self: {"api_token": "phase6-browser-secret"})

    provider_started = threading.Event()
    release_provider = threading.Event()
    provider_calls = []

    class ProviderResponse:
        ok = True
        def __init__(self, image_id):
            self.image_id = image_id
        def json(self):
            return {
                "success": True,
                "result": {
                    "id": self.image_id,
                    "requireSignedURLs": False,
                    "variants": [f"https://imagedelivery.net/browser/{self.image_id}/public"],
                },
            }

    def provider_post(*args, **kwargs):
        image_id = f"phase6-browser-{len(provider_calls) + 1}"
        provider_calls.append((args, kwargs))
        if len(provider_calls) == 1:
            provider_started.set()
            assert release_provider.wait(timeout=30), "Browser QA provider gate was never released"
        return ProviderResponse(image_id)

    class DeleteResponse:
        ok = True
        def json(self):
            return {"success": True}

    monkeypatch.setattr(media_service.requests, "post", provider_post)
    monkeypatch.setattr(media_service.requests, "delete", lambda *a, **k: DeleteResponse())

    large = tmp_path / "phase6-real-product-large.png"
    second = tmp_path / "phase6-real-product-second.png"
    invalid = tmp_path / "phase6-invalid-product.png"
    _large_png(large)
    _small_png(second, (32, 80, 170))
    invalid.write_bytes(b"not an image")

    driver = _chrome(width=1440, height=1000)
    try:
        _login(driver, live_server, client, owner)
        wait = _wait(driver)
        manage_url = f"{live_server.url}/designer/store/products/{product.pk}/?org={org.pk}&lang=en"
        driver.get(manage_url)
        wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "[data-store-media-upload-form]")))
        assert driver.find_element(By.CSS_SELECTOR, "[data-store-media-empty]")
        assert driver.find_element(By.CSS_SELECTOR, "[data-store-media-upload-form]").get_attribute("enctype").lower() == "multipart/form-data"
        _shot_checked(driver, "p6-01-product-images-empty-en-desktop.png")

        file_input = driver.find_element(By.CSS_SELECTOR, "[data-store-media-file]")
        file_input.send_keys(str(large))
        wait.until(lambda _d: large.name in driver.find_element(By.CSS_SELECTOR, "[data-store-media-filename]").text)
        _shot_checked(driver, "p6-02-product-image-selected-file-en.png")

        # Real Chrome network throttling + the real multipart/XHR request are used
        # for evidence. No JavaScript progress value is injected by the test.
        driver.execute_cdp_cmd("Network.enable", {})
        driver.execute_cdp_cmd(
            "Network.emulateNetworkConditions",
            {
                "offline": False,
                "latency": 40,
                "downloadThroughput": 1024 * 1024,
                "uploadThroughput": 256 * 1024,
                "connectionType": "cellular3g",
            },
        )
        upload_form = driver.find_element(By.CSS_SELECTOR, "[data-store-media-upload-form]")
        _click_element(driver, upload_form.find_element(By.CSS_SELECTOR, "[data-store-media-submit]"))
        progress = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "[data-store-media-progress]")))
        wait.until(lambda _d: 0 < float(progress.get_attribute("value") or 0) < 100)
        percent_text = driver.find_element(By.CSS_SELECTOR, "[data-store-media-percent]").text
        assert "%" in percent_text and percent_text != "100%"
        _shot_checked(driver, "p6-03-product-image-upload-progress-en.png")

        assert provider_started.wait(timeout=25), "Provider was not reached after real multipart upload"
        wait.until(lambda _d: "Processing image" in driver.find_element(By.CSS_SELECTOR, "[data-store-media-status]").text)
        assert float(progress.get_attribute("value") or 0) == 100
        _shot_checked(driver, "p6-04-product-image-processing-en.png")
        release_provider.set()
        wait.until(lambda _d: product.images.count() == 1)
        wait.until(lambda _d: "/designer/store/products/" in driver.current_url)
        driver.execute_cdp_cmd(
            "Network.emulateNetworkConditions",
            {"offline": False, "latency": 0, "downloadThroughput": -1, "uploadThroughput": -1},
        )
        driver.refresh()
        wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "[data-store-media-item]")))
        assert "phase6-browser-secret" not in driver.page_source
        assert "api.cloudflare.com" not in driver.page_source
        assert "phase6-browser-1" not in driver.find_element(By.CSS_SELECTOR, "[data-store-media-item]").text
        _shot_checked(driver, "p6-05-product-image-upload-success-en.png")
        assert driver.find_element(By.CSS_SELECTOR, "[data-store-media-primary]").text == "Primary"
        _shot_checked(driver, "p6-06-product-image-primary-en.png")

        # Upload a second real image through the same canonical multipart form.
        driver.find_element(By.CSS_SELECTOR, "[data-store-media-file]").send_keys(str(second))
        _click_element(driver, driver.find_element(By.CSS_SELECTOR, "[data-store-media-submit]"))
        wait.until(lambda _d: product.images.count() == 2)
        driver.refresh()
        wait.until(lambda _d: len(driver.find_elements(By.CSS_SELECTOR, "[data-store-media-item]")) == 2)
        set_primary = driver.find_element(By.XPATH, "//button[normalize-space(.)='Set primary']")
        _click_element(driver, set_primary)
        wait.until(lambda _d: "Primary product image updated" in driver.page_source)
        product.refresh_from_db()
        ordered = list(product.images.order_by("sort_order", "id"))
        assert ordered[0].media_asset.original_filename == second.name
        assert [row.sort_order for row in ordered] == [0, 1]
        _shot_checked(driver, "p6-07-product-images-primary-reassigned-en.png")

        before_provider_calls = len(provider_calls)
        driver.find_element(By.CSS_SELECTOR, "[data-store-media-file]").send_keys(str(invalid))
        submit = driver.find_element(By.CSS_SELECTOR, "[data-store-media-submit]")
        _click_element(driver, submit)
        wait.until(lambda _d: "valid PNG, JPEG or WebP" in driver.find_element(By.CSS_SELECTOR, "[data-store-media-status]").text)
        assert len(provider_calls) == before_provider_calls
        assert submit.is_enabled()
        _shot_checked(driver, "p6-08-product-image-invalid-retry-en.png")

        publish_store_product(product=product, actor=owner)
        product.refresh_from_db()
        assert product.status == StoreProduct.Status.PUBLISHED
        driver.get(manage_url)
        wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "[data-store-media-readonly]")))
        assert not driver.find_elements(By.CSS_SELECTOR, "[data-store-media-upload-form]")
        assert "Hide the product before" in driver.find_element(By.CSS_SELECTOR, "[data-store-media-readonly]").text
        _shot_checked(driver, "p6-09-product-images-published-readonly-en.png")

        driver.get(f"{live_server.url}/?lang=en")
        wait.until(lambda _d: product.title_en in driver.page_source)
        primary_url = ordered[0].media_asset.metadata["public_url"]
        assert primary_url in driver.page_source
        _shot_checked(driver, "p6-10-marketplace-primary-image-en.png")

        public_url = f"{live_server.url}/store/{store.slug}/{product.slug}/?lang=en"
        driver.get(public_url)
        hero = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, ".gallery__main img")))
        assert hero.get_attribute("src") == primary_url
        thumbs = driver.find_elements(By.CSS_SELECTOR, ".product-thumb img")
        assert thumbs and thumbs[0].get_attribute("src") == primary_url
        _shot_checked(driver, "p6-11-public-product-primary-gallery-en.png")

        driver.get(f"{live_server.url}/studio/?product={product.pk}&lang=en")
        wait.until(lambda _d: product.title_en in driver.page_source)
        assert primary_url in driver.page_source
        _shot_checked(driver, "p6-12-studio-primary-image-en.png")

        driver.get(public_url)
        _click_element(driver, driver.find_element(By.CSS_SELECTOR, "#product-purchase-form button[type='submit']"))
        wait.until(lambda _d: "/cart" in driver.current_url)
        assert primary_url in driver.page_source
        _shot_checked(driver, "p6-13-cart-primary-image-en.png")

        owner.language_preference = "ar"
        owner.theme_preference = "dark"
        owner.save(update_fields=["language_preference", "theme_preference"])
        driver.set_window_size(390, 844)
        driver.get(f"{live_server.url}/designer/store/products/{product.pk}/?org={org.pk}&lang=ar")
        wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "[data-store-media-readonly]")))
        assert driver.find_element(By.TAG_NAME, "html").get_attribute("dir") == "rtl"
        assert "صور المنتج العامة" in driver.page_source
        assert _no_overflow(driver)
        _shot_checked(driver, "p6-14-product-images-ar-rtl-mobile-dark.png")

        hide_store_product(product=product, actor=owner)
        product.refresh_from_db()
        driver.set_window_size(1440, 1000)
        driver.get(manage_url)
        wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "[data-store-media-upload-form]")))
        assert driver.find_elements(By.CSS_SELECTOR, ".designer-product-media__actions")
        assert _no_overflow(driver)
        _shot_checked(driver, "p6-15-product-images-en-desktop-no-overflow.png")

        assert len(provider_calls) == 2
    finally:
        release_provider.set()
        driver.quit()
