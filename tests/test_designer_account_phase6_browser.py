import http.client
import io
import os
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from PIL import Image
from django.contrib.auth import get_user_model
from selenium import webdriver
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


class _UploadProxyServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def get_request(self):
        request, client_address = super().get_request()
        # Keep the kernel receive window small before the request body arrives so
        # a multi-megabyte browser upload must experience real TCP backpressure.
        request.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 16 * 1024)
        return request, client_address


class _SlowUploadForwardProxy:
    """Test-only HTTP forward proxy that slows the first large Store-media POST.

    Chromium still requests the actual Django LiveServer URL. The proxy only
    controls transport pacing, reads the genuine multipart body in bounded
    chunks, and forwards those exact bytes to the original application endpoint.
    """

    _HOP_BY_HOP = {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "proxy-connection",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
        "expect",
    }

    def __init__(self, target_url):
        target = urlsplit(target_url)
        assert target.scheme == "http" and target.hostname
        self.target_host = target.hostname
        self.target_port = target.port or 80
        self._lock = threading.Lock()
        self._upload_received = 0
        self._upload_total = 0
        self._slow_upload_seen = False
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                return

            def do_GET(self):
                self._forward()

            def do_HEAD(self):
                self._forward()

            def do_POST(self):
                self._forward()

            def _forward(self):
                parsed = urlsplit(self.path)
                if parsed.scheme:
                    request_host = parsed.hostname
                    request_port = parsed.port or (443 if parsed.scheme == "https" else 80)
                    path = parsed.path or "/"
                    if parsed.query:
                        path = f"{path}?{parsed.query}"
                else:
                    request_host = outer.target_host
                    request_port = outer.target_port
                    path = self.path

                if (request_host, request_port) != (outer.target_host, outer.target_port):
                    self.send_error(502, "Unexpected proxy destination")
                    return

                content_length = int(self.headers.get("Content-Length") or 0)
                slow_upload = (
                    self.command == "POST"
                    and "/designer/store/products/" in path
                    and content_length > 7_000_000
                    and not outer._slow_upload_seen
                )
                if slow_upload:
                    with outer._lock:
                        outer._slow_upload_seen = True
                        outer._upload_total = content_length
                        outer._upload_received = 0

                remaining = content_length
                body = bytearray()
                while remaining:
                    chunk = self.rfile.read(min(16 * 1024, remaining))
                    if not chunk:
                        break
                    body.extend(chunk)
                    remaining -= len(chunk)
                    if slow_upload:
                        with outer._lock:
                            outer._upload_received += len(chunk)
                        # This delay affects real socket reads only; no browser
                        # progress value or ProgressEvent is injected or altered.
                        time.sleep(0.01)

                if remaining:
                    self.send_error(400, "Incomplete proxied request body")
                    return

                headers = {
                    key: value
                    for key, value in self.headers.items()
                    if key.lower() not in outer._HOP_BY_HOP and key.lower() != "content-length"
                }
                if content_length:
                    headers["Content-Length"] = str(len(body))

                connection = http.client.HTTPConnection(
                    outer.target_host,
                    outer.target_port,
                    timeout=60,
                )
                try:
                    connection.request(
                        self.command,
                        path,
                        body=bytes(body) if content_length else None,
                        headers=headers,
                    )
                    response = connection.getresponse()
                    response_body = response.read()
                    self.send_response(response.status, response.reason)
                    for key, value in response.getheaders():
                        if key.lower() in outer._HOP_BY_HOP or key.lower() == "content-length":
                            continue
                        self.send_header(key, value)
                    self.send_header("Content-Length", str(len(response_body)))
                    self.end_headers()
                    if self.command != "HEAD":
                        self.wfile.write(response_body)
                finally:
                    connection.close()

        self._server = _UploadProxyServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_port}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def upload_snapshot(self):
        with self._lock:
            return self._upload_received, self._upload_total

    def close(self):
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


def _chrome_through_proxy(proxy_url, *, language="en-US,en", width=1440, height=1000):
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-background-networking")
    options.add_argument(f"--window-size={width},{height}")
    options.add_argument(f"--proxy-server={proxy_url}")
    # Chrome normally bypasses proxies for localhost; this forces the real
    # LiveServer request through the test-only pacing proxy instead.
    options.add_argument("--proxy-bypass-list=<-loopback>")
    options.add_experimental_option("prefs", {"intl.accept_languages": language})
    return webdriver.Chrome(options=options)


def _wait(driver, seconds=20):
    return WebDriverWait(driver, seconds)


def _frame(driver, element):
    driver.execute_script(
        "arguments[0].scrollIntoView({block: 'center', inline: 'nearest'});",
        element,
    )


def _shot_checked(driver, name):
    _shot(driver, name)
    assert (ARTIFACT_DIR / name).exists()
    assert _no_overflow(driver)


def _large_png(path):
    # Use a near-limit, genuinely decoded random raster so native upload progress
    # spans enough real bytes for the transport-pacing harness to observe it.
    width = height = 1650
    image = Image.frombytes("RGB", (width, height), os.urandom(width * height * 3))
    image.save(path, format="PNG", compress_level=1)
    assert 7_000_000 < path.stat().st_size < 10 * 1024 * 1024


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

    slow_proxy = _SlowUploadForwardProxy(live_server.url)
    driver = None
    try:
        driver = _chrome_through_proxy(slow_proxy.url, width=1440, height=1000)
        _login(driver, live_server, client, owner)
        wait = _wait(driver)
        manage_url = f"{live_server.url}/designer/store/products/{product.pk}/?org={org.pk}&lang=en"
        driver.get(manage_url)
        upload_form = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "[data-store-media-upload-form]")))
        assert driver.find_element(By.CSS_SELECTOR, "[data-store-media-empty]")
        assert upload_form.get_attribute("enctype").lower() == "multipart/form-data"
        _frame(driver, driver.find_element(By.CSS_SELECTOR, "[data-store-media-section]"))
        _shot_checked(driver, "p6-01-product-images-empty-en-desktop.png")

        file_input = driver.find_element(By.CSS_SELECTOR, "[data-store-media-file]")
        file_input.send_keys(str(large))
        wait.until(lambda _d: large.name in driver.find_element(By.CSS_SELECTOR, "[data-store-media-filename]").text)
        _frame(driver, upload_form)
        _shot_checked(driver, "p6-02-product-image-selected-file-en.png")

        # The browser sends the real multipart XHR to the actual LiveServer URL.
        # The forward proxy only applies TCP backpressure while reading those bytes;
        # it never injects, synthesizes or edits an xhr.upload progress event/value.
        upload_form = driver.find_element(By.CSS_SELECTOR, "[data-store-media-upload-form]")
        _click_element(driver, upload_form.find_element(By.CSS_SELECTOR, "[data-store-media-submit]"))
        progress = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "[data-store-media-progress]")))

        def genuine_intermediate_progress(_driver):
            value = float(progress.get_attribute("value") or 0)
            received, total = slow_proxy.upload_snapshot()
            if 0 < value < 100 and 0 < received < total:
                return value, received, total
            return False

        progress_wait = WebDriverWait(driver, 30, poll_frequency=0.05)
        intermediate_percent, intermediate_received, upload_total = progress_wait.until(genuine_intermediate_progress)
        percent_text = driver.find_element(By.CSS_SELECTOR, "[data-store-media-percent]").text
        upload_status = driver.find_element(By.CSS_SELECTOR, "[data-store-media-status]")
        assert "%" in percent_text and percent_text != "100%"
        assert "Uploading" in upload_status.text
        assert 0 < intermediate_received < upload_total
        progress_wrap = driver.find_element(By.CSS_SELECTOR, "[data-store-media-progress-wrap]")
        _frame(driver, progress_wrap)
        _shot_checked(driver, "p6-03-product-image-upload-progress-en.png")

        assert provider_started.wait(timeout=45), "Provider was not reached after real multipart upload"
        processing_status = wait.until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, "[data-store-media-status]"))
        )
        wait.until(lambda _d: "Processing image" in processing_status.text)
        completed_received, completed_total = slow_proxy.upload_snapshot()
        assert completed_total == upload_total
        assert completed_received == completed_total
        assert completed_total > large.stat().st_size
        assert not release_provider.is_set()
        assert float(progress.get_attribute("value") or 0) == 100
        assert driver.find_element(By.CSS_SELECTOR, "[data-store-media-percent]").text == "100%"
        _frame(driver, processing_status)
        _shot_checked(driver, "p6-04-product-image-processing-en.png")

        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        (ARTIFACT_DIR / "p6-native-upload-progress-evidence.txt").write_text(
            "native xhr.upload evidence via real multipart transport\n"
            f"intermediate_visible_percent={intermediate_percent:g}\n"
            f"intermediate_transport_received={intermediate_received}\n"
            f"transport_total={upload_total}\n"
            f"completed_transport_received={completed_received}\n"
            f"provider_started={provider_started.is_set()}\n"
            f"provider_release_pending={not release_provider.is_set()}\n",
            encoding="utf-8",
        )

        release_provider.set()
        wait.until(lambda _d: product.images.count() == 1)
        wait.until(lambda _d: "/designer/store/products/" in driver.current_url)
        driver.refresh()
        media_item = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "[data-store-media-item]")))
        assert "phase6-browser-secret" not in driver.page_source
        assert "api.cloudflare.com" not in driver.page_source
        assert "phase6-browser-1" not in media_item.text
        _frame(driver, media_item)
        _shot_checked(driver, "p6-05-product-image-upload-success-en.png")
        primary_badge = driver.find_element(By.CSS_SELECTOR, "[data-store-media-primary]")
        assert primary_badge.text == "Primary"
        _frame(driver, primary_badge)
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
        gallery = driver.find_element(By.CSS_SELECTOR, "[data-store-media-gallery]")
        _frame(driver, gallery)
        _shot_checked(driver, "p6-07-product-images-primary-reassigned-en.png")

        before_provider_calls = len(provider_calls)
        driver.find_element(By.CSS_SELECTOR, "[data-store-media-file]").send_keys(str(invalid))
        submit = driver.find_element(By.CSS_SELECTOR, "[data-store-media-submit]")
        _click_element(driver, submit)
        wait.until(lambda _d: "valid PNG, JPEG or WebP" in driver.find_element(By.CSS_SELECTOR, "[data-store-media-status]").text)
        assert len(provider_calls) == before_provider_calls
        assert submit.is_enabled()
        _frame(driver, submit)
        _shot_checked(driver, "p6-08-product-image-invalid-retry-en.png")

        publish_store_product(product=product, actor=owner)
        product.refresh_from_db()
        assert product.status == StoreProduct.Status.PUBLISHED
        driver.get(manage_url)
        readonly = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "[data-store-media-readonly]")))
        assert not driver.find_elements(By.CSS_SELECTOR, "[data-store-media-upload-form]")
        assert "Hide the product before" in readonly.text
        _frame(driver, readonly)
        _shot_checked(driver, "p6-09-product-images-published-readonly-en.png")

        driver.get(f"{live_server.url}/?lang=en")
        wait.until(lambda _d: product.title_en in driver.page_source)
        primary_url = ordered[0].media_asset.metadata["public_url"]
        assert primary_url in driver.page_source
        marketplace_image = driver.find_element(By.XPATH, f"//img[@src='{primary_url}']")
        _frame(driver, marketplace_image)
        _shot_checked(driver, "p6-10-marketplace-primary-image-en.png")

        public_url = f"{live_server.url}/store/{store.slug}/{product.slug}/?lang=en"
        driver.get(public_url)
        hero = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, ".gallery__main img")))
        assert hero.get_attribute("src") == primary_url
        thumbs = driver.find_elements(By.CSS_SELECTOR, ".product-thumb img")
        assert thumbs and thumbs[0].get_attribute("src") == primary_url
        _frame(driver, hero)
        _shot_checked(driver, "p6-11-public-product-primary-gallery-en.png")

        driver.get(f"{live_server.url}/studio/?product={product.pk}&lang=en")
        wait.until(lambda _d: product.title_en in driver.page_source)
        assert primary_url in driver.page_source
        studio_image = driver.find_element(By.XPATH, f"//img[@src='{primary_url}']")
        _frame(driver, studio_image)
        _shot_checked(driver, "p6-12-studio-primary-image-en.png")

        driver.get(public_url)
        _click_element(driver, driver.find_element(By.CSS_SELECTOR, "#product-purchase-form button[type='submit']"))
        wait.until(lambda _d: "/cart" in driver.current_url)
        assert primary_url in driver.page_source
        cart_image = driver.find_element(By.XPATH, f"//img[@src='{primary_url}']")
        _frame(driver, cart_image)
        _shot_checked(driver, "p6-13-cart-primary-image-en.png")

        owner.language_preference = "ar"
        owner.theme_preference = "dark"
        owner.save(update_fields=["language_preference", "theme_preference"])
        driver.set_window_size(390, 844)
        driver.get(f"{live_server.url}/designer/store/products/{product.pk}/?org={org.pk}&lang=ar")
        readonly = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "[data-store-media-readonly]")))
        assert driver.find_element(By.TAG_NAME, "html").get_attribute("dir") == "rtl"
        assert "صور المنتج العامة" in driver.page_source
        assert _no_overflow(driver)
        _frame(driver, readonly)
        _shot_checked(driver, "p6-14-product-images-ar-rtl-mobile-dark.png")

        hide_store_product(product=product, actor=owner)
        product.refresh_from_db()
        driver.set_window_size(1440, 1000)
        driver.get(manage_url)
        wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "[data-store-media-upload-form]")))
        actions = driver.find_elements(By.CSS_SELECTOR, ".designer-product-media__actions")
        assert actions
        assert _no_overflow(driver)
        _frame(driver, actions[0])
        _shot_checked(driver, "p6-15-product-images-en-desktop-no-overflow.png")

        assert len(provider_calls) == 2
    finally:
        release_provider.set()
        if driver is not None:
            driver.quit()
        slow_proxy.close()


@pytest.mark.django_db(transaction=True)
def test_designer_phase6_store_product_upload_falls_back_to_normal_multipart_without_javascript(client, live_server, tmp_path, monkeypatch):
    if os.getenv("CI") != "true":
        pytest.skip("Phase 6 real-browser evidence is CI-only.")

    from apps.media import designer_public_services as media_service

    owner, org, _store, product = _catalog("phase6-nojs")
    IntegrationConfig.objects.update_or_create(
        provider=IntegrationConfig.Provider.CLOUDFLARE_IMAGES,
        defaults={"enabled": True, "config": {"account_id": "b" * 32}},
    )
    monkeypatch.setattr(IntegrationConfig, "get_secrets", lambda self: {"api_token": "phase6-nojs-secret"})
    provider_calls = []

    class ProviderResponse:
        ok = True
        def json(self):
            return {
                "success": True,
                "result": {
                    "id": "phase6-nojs-provider-image",
                    "requireSignedURLs": False,
                    "variants": ["https://imagedelivery.net/browser/phase6-nojs-provider-image/public"],
                },
            }

    def provider_post(*args, **kwargs):
        provider_calls.append((args, kwargs))
        return ProviderResponse()

    monkeypatch.setattr(media_service.requests, "post", provider_post)

    upload = tmp_path / "phase6-nojs-product.png"
    _small_png(upload, (80, 120, 40))
    driver = _chrome(width=1280, height=900)
    try:
        _login(driver, live_server, client, owner)
        driver.execute_cdp_cmd("Emulation.setScriptExecutionDisabled", {"value": True})
        manage_url = f"{live_server.url}/designer/store/products/{product.pk}/?org={org.pk}&lang=en"
        driver.get(manage_url)
        wait = _wait(driver)
        form = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "form[data-store-media-upload-form]")))
        assert form.get_attribute("enctype").lower() == "multipart/form-data"
        form.find_element(By.CSS_SELECTOR, "[data-store-media-file]").send_keys(str(upload))
        form.find_element(By.NAME, "alt_en").send_keys("No-JavaScript product photo")
        _click_element(driver, form.find_element(By.CSS_SELECTOR, "[data-store-media-submit]"))
        wait.until(lambda _d: product.images.count() == 1)
        wait.until(lambda _d: "Product image uploaded and attached" in driver.page_source)
        assert len(provider_calls) == 1
        relation = product.images.select_related("media_asset").get()
        assert relation.media_asset.metadata["store_product_id"] == product.pk
        assert relation.media_asset.metadata["purpose"] == "store_product_image"
        assert "phase6-nojs-secret" not in driver.page_source
        assert "api.cloudflare.com" not in driver.page_source
        # JavaScript enhancement is absent, so the browser performed a normal
        # navigation and no byte-progress claim was made.
        progress_wrap = driver.find_element(By.CSS_SELECTOR, "[data-store-media-progress-wrap]")
        assert progress_wrap.get_attribute("hidden") is not None
    finally:
        driver.quit()
