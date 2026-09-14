import http.client
import io
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from PIL import Image
from django.contrib.auth import get_user_model
from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
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
UPLOAD_THROUGHPUT_BYTES_PER_SECOND = 512 * 1024


class _UploadProxyServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class _UploadObservationProxy:
    """Observe real Store-media multipart POSTs without fabricating progress."""

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
        self._connection_count = 0
        self._product_posts = []
        self._upload_received = 0
        self._upload_total = 0
        self._upload_connection_id = None
        self._upload_request_path = None
        self._upload_seen = False
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def setup(self):
                super().setup()
                with outer._lock:
                    outer._connection_count += 1
                    self._connection_id = outer._connection_count

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
                    self.close_connection = True
                    self.send_error(502, "Unexpected proxy destination")
                    return

                content_length = int(self.headers.get("Content-Length") or 0)
                product_post = self.command == "POST" and "/designer/store/products/" in path
                post_record = None
                if product_post:
                    post_record = {
                        "connection_id": self._connection_id,
                        "path": path,
                        "content_length": content_length,
                        "received_bytes": 0,
                        "body_complete": False,
                        "response_status": None,
                        "response_complete": False,
                    }
                    with outer._lock:
                        outer._product_posts.append(post_record)

                evidence_upload = product_post and content_length > 7_000_000 and not outer._upload_seen
                if evidence_upload:
                    with outer._lock:
                        outer._upload_seen = True
                        outer._upload_total = content_length
                        outer._upload_received = 0
                        outer._upload_connection_id = self._connection_id
                        outer._upload_request_path = path

                remaining = content_length
                body = bytearray()
                while remaining:
                    chunk = self.rfile.read(min(16 * 1024, remaining))
                    if not chunk:
                        break
                    body.extend(chunk)
                    remaining -= len(chunk)
                    if post_record is not None:
                        with outer._lock:
                            post_record["received_bytes"] += len(chunk)
                    if evidence_upload:
                        with outer._lock:
                            outer._upload_received += len(chunk)

                if remaining:
                    self.close_connection = True
                    self.send_error(400, "Incomplete proxied request body")
                    return

                if post_record is not None:
                    with outer._lock:
                        post_record["body_complete"] = True

                headers = {
                    key: value
                    for key, value in self.headers.items()
                    if key.lower() not in outer._HOP_BY_HOP and key.lower() != "content-length"
                }
                if content_length:
                    headers["Content-Length"] = str(len(body))
                headers["Connection"] = "close"

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
                    if post_record is not None:
                        with outer._lock:
                            post_record["response_status"] = response.status
                    response_body = response.read()
                    self.send_response(response.status, response.reason)
                    for key, value in response.getheaders():
                        if key.lower() in outer._HOP_BY_HOP or key.lower() == "content-length":
                            continue
                        self.send_header(key, value)
                    self.send_header("Content-Length", str(len(response_body)))
                    self.send_header("Connection", "close")
                    self.end_headers()
                    if self.command != "HEAD":
                        self.wfile.write(response_body)
                    if post_record is not None:
                        with outer._lock:
                            post_record["response_complete"] = True
                    self.close_connection = True
                finally:
                    connection.close()

        self._server = _UploadProxyServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_port}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def connection_count(self):
        with self._lock:
            return self._connection_count

    def product_posts(self):
        with self._lock:
            return [dict(row) for row in self._product_posts]

    def upload_snapshot(self):
        with self._lock:
            return (
                self._upload_received,
                self._upload_total,
                self._upload_connection_id,
                self._upload_request_path,
            )

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
    options.add_argument("--proxy-bypass-list=<-loopback>")
    options.add_experimental_option("prefs", {"intl.accept_languages": language})
    options.set_capability("goog:loggingPrefs", {"performance": "ALL", "browser": "ALL"})
    return webdriver.Chrome(options=options)


def _enable_native_upload_throttle(driver, upload_url):
    """Apply the same by-rule condition shape used by current Chrome DevTools."""
    driver.execute_cdp_cmd("Network.enable", {})
    result = driver.execute_cdp_cmd(
        "Network.emulateNetworkConditionsByRule",
        {
            "offline": False,
            "emulateOfflineServiceWorker": False,
            "matchedNetworkConditions": [
                {
                    "urlPattern": upload_url,
                    "latency": 0,
                    # Keep the runner-proven DevTools by-rule representation here;
                    # the evidence test records the actual Chrome/protocol build and
                    # requires appliedNetworkConditionsId on the real multipart POST.
                    "downloadThroughput": 0,
                    "uploadThroughput": UPLOAD_THROUGHPUT_BYTES_PER_SECOND,
                    "packetLoss": 0,
                    "offline": False,
                }
            ],
        },
    )
    rule_ids = result.get("ruleIds") or []
    assert len(rule_ids) == 1, result
    return rule_ids[0]


def _disable_native_upload_throttle(driver):
    driver.execute_cdp_cmd(
        "Network.emulateNetworkConditionsByRule",
        {"offline": False, "matchedNetworkConditions": []},
    )
    driver.execute_cdp_cmd("Network.disable", {})


def _collect_upload_network_state(driver, *, upload_url, state):
    for entry in driver.get_log("performance"):
        try:
            message = json.loads(entry["message"])["message"]
        except (KeyError, TypeError, json.JSONDecodeError):
            continue
        method = message.get("method")
        params = message.get("params") or {}
        request_id = params.get("requestId")

        if method == "Network.requestWillBeSent":
            request = params.get("request") or {}
            if request.get("method") == "POST":
                state.setdefault("post_urls", []).append(request.get("url"))
            if request.get("method") == "POST" and request.get("url") == upload_url:
                state["request_id"] = request_id
                state["request_url"] = request.get("url")
                state.setdefault("events", []).append(f"requestWillBeSent:{request_id}")
        elif method == "Network.requestWillBeSentExtraInfo" and request_id:
            applied = params.get("appliedNetworkConditionsId")
            state["extra_by_request"][request_id] = applied
            if request_id == state.get("request_id"):
                state.setdefault("events", []).append(
                    f"requestWillBeSentExtraInfo:{request_id}:{applied or 'none'}"
                )
        elif request_id and request_id == state.get("request_id"):
            if method == "Network.responseReceived":
                response = params.get("response") or {}
                state["response_status"] = response.get("status")
                state.setdefault("events", []).append(
                    f"responseReceived:{request_id}:{response.get('status')}"
                )
            elif method == "Network.loadingFailed":
                state["loading_failed"] = params.get("errorText") or "unknown"
                state.setdefault("events", []).append(
                    f"loadingFailed:{request_id}:{state['loading_failed']}"
                )
            elif method == "Network.loadingFinished":
                state["loading_finished"] = True
                state.setdefault("events", []).append(f"loadingFinished:{request_id}")

    request_id = state.get("request_id")
    if request_id:
        state["applied_rule_id"] = state["extra_by_request"].get(request_id)
    return state


def _browser_console_errors(driver):
    errors = []
    for entry in driver.get_log("browser"):
        if str(entry.get("level", "")).upper() in {"SEVERE", "ERROR"}:
            message = str(entry.get("message", ""))
            errors.append(message.replace("phase6-browser-secret", "[redacted]")[:600])
    return errors


def _upload_form_runtime_state(driver):
    return driver.execute_script(
        """
        const form = document.querySelector('[data-store-media-upload-form]');
        const input = form && form.querySelector('[data-store-media-file]');
        const selected = input && input.files && input.files[0];
        const progressWrap = form && form.querySelector('[data-store-media-progress-wrap]');
        const progress = form && form.querySelector('[data-store-media-progress]');
        const status = form && form.querySelector('[data-store-media-status]');
        const submit = form && form.querySelector('[data-store-media-submit]');
        return {
          href: window.location.href,
          action: form ? form.getAttribute('action') : null,
          endpoint: form ? (form.getAttribute('action') || window.location.href) : null,
          fileName: selected ? selected.name : null,
          fileSize: selected ? selected.size : null,
          progressValue: progress && progress.hasAttribute('value') ? Number(progress.value) : null,
          progressVisible: progressWrap ? !progressWrap.hidden : null,
          statusText: status ? status.textContent.trim() : null,
          submitEnabled: submit ? !submit.disabled : null,
          fileInputEnabled: input ? !input.disabled : null,
          documentReadyState: document.readyState
        };
        """
    )


def _wait(driver, seconds=20):
    return WebDriverWait(driver, seconds)


def _frame(driver, element):
    driver.execute_script(
        "arguments[0].scrollIntoView({block: 'center', inline: 'nearest'});",
        element,
    )


def _store_media_submit_geometry(driver, submit):
    """Return effective viewport, hit-test and pointer geometry for submit."""
    return driver.execute_script(
        """
        const submit = arguments[0];
        const rect = submit.getBoundingClientRect();
        const centerX = rect.left + (rect.width / 2);
        const centerY = rect.top + (rect.height / 2);
        const centerInsideViewport = (
          centerX >= 0 && centerY >= 0 &&
          centerX < window.innerWidth && centerY < window.innerHeight
        );
        const topmost = centerInsideViewport ? document.elementFromPoint(centerX, centerY) : null;
        const describe = function (node) {
          if (!node) return null;
          return {
            tag: node.tagName,
            id: node.id || null,
            className: String(node.className || '').slice(0, 240),
            text: String(node.textContent || '').trim().slice(0, 160),
            isSubmit: node === submit,
            containedBySubmit: submit.contains(node)
          };
        };
        return {
          innerWidth: window.innerWidth,
          innerHeight: window.innerHeight,
          scrollX: window.scrollX,
          scrollY: window.scrollY,
          rect: {
            left: rect.left,
            top: rect.top,
            right: rect.right,
            bottom: rect.bottom,
            width: rect.width,
            height: rect.height
          },
          centerX: centerX,
          centerY: centerY,
          fullyInsideViewport: (
            rect.width > 0 && rect.height > 0 &&
            rect.left >= 0 && rect.top >= 0 &&
            rect.right <= window.innerWidth && rect.bottom <= window.innerHeight
          ),
          centerInsideViewport: centerInsideViewport,
          centerHitsSubmit: Boolean(topmost && (topmost === submit || submit.contains(topmost))),
          topmost: describe(topmost)
        };
        """,
        submit,
    )


def _activate_store_media_submit(driver, form, expected_file):
    """Activate the real enhanced form through standards-based browser submission."""
    expected_file = Path(expected_file)
    file_input = form.find_element(By.CSS_SELECTOR, "[data-store-media-file]")
    submit = form.find_element(By.CSS_SELECTOR, "[data-store-media-submit]")
    filename = form.find_element(By.CSS_SELECTOR, "[data-store-media-filename]")
    _wait(driver).until(lambda _d: submit.is_displayed() and submit.is_enabled())
    _wait(driver).until(lambda _d: expected_file.name in filename.text)

    geometry_before = _store_media_submit_geometry(driver, submit)
    driver.execute_script(
        """
        const submit = arguments[0];
        submit.scrollIntoView({block: 'center', inline: 'center', behavior: 'instant'});
        const rect = submit.getBoundingClientRect();
        const dx = (rect.left + rect.width / 2) - (window.innerWidth / 2);
        const dy = (rect.top + rect.height / 2) - (window.innerHeight / 2);
        if (Math.abs(dx) > 1 || Math.abs(dy) > 1) {
          window.scrollBy({left: dx, top: dy, behavior: 'instant'});
        }
        """,
        submit,
    )
    time.sleep(0.05)
    geometry_positioned = _store_media_submit_geometry(driver, submit)

    runtime = _upload_form_runtime_state(driver)
    relationship = driver.execute_script(
        """
        const form = arguments[0];
        const submit = arguments[1];
        const input = arguments[2];
        const script = Array.from(document.scripts).find(function (node) {
          return (node.src || '').includes('designer-store-product-media.js');
        });
        return {
          formMatches: form.matches('[data-store-media-upload-form]'),
          formConnected: form.isConnected,
          submitConnected: submit.isConnected,
          submitFormMatches: submit.form === form,
          inputFormMatches: input.form === form,
          submitType: submit.type,
          filenameText: form.querySelector('[data-store-media-filename]').textContent.trim(),
          productionScriptPresent: Boolean(script),
          productionScriptSrc: script ? script.src : null,
          xhrAvailable: Boolean(window.XMLHttpRequest),
          formDataAvailable: Boolean(window.FormData),
          requestSubmitAvailable: typeof form.requestSubmit === 'function',
          activeTagBefore: document.activeElement ? document.activeElement.tagName : null,
          activeIsSubmitBefore: document.activeElement === submit
        };
        """,
        form,
        submit,
        file_input,
    )

    assert submit.is_displayed(), relationship
    assert submit.is_enabled(), relationship
    assert str(submit.get_attribute("type") or "").lower() == "submit", relationship
    assert runtime["fileName"] == expected_file.name, (runtime, relationship)
    assert runtime["fileSize"] == expected_file.stat().st_size, (runtime, relationship)
    assert relationship["formMatches"] and relationship["formConnected"], relationship
    assert relationship["submitConnected"] and relationship["submitFormMatches"], relationship
    assert relationship["inputFormMatches"], relationship
    assert str(relationship["submitType"]).lower() == "submit", relationship
    assert expected_file.name in relationship["filenameText"], relationship
    # The custom filename text is written only by initForm's change listener;
    # together with the loaded script element this proves the production asset
    # initialized this exact form before the test attempts submit activation.
    assert relationship["productionScriptPresent"], relationship
    assert "designer-store-product-media.js" in str(relationship["productionScriptSrc"]), relationship
    assert relationship["xhrAvailable"] and relationship["formDataAvailable"], relationship
    assert relationship["requestSubmitAvailable"], relationship

    driver.execute_script(
        """
        const form = arguments[0];
        const submit = arguments[1];
        window.__phase6StoreSubmitObservation = null;
        form.addEventListener('submit', function () {
          const input = form.querySelector('[data-store-media-file]');
          const selected = input.files && input.files[0];
          const progressWrap = form.querySelector('[data-store-media-progress-wrap]');
          const progress = form.querySelector('[data-store-media-progress]');
          const percent = form.querySelector('[data-store-media-percent]');
          const status = form.querySelector('[data-store-media-status]');
          window.__phase6StoreSubmitObservation = {
            progressVisible: !progressWrap.hidden,
            progressValue: progress.hasAttribute('value') ? Number(progress.value) : null,
            percentText: percent.textContent.trim(),
            statusText: status.textContent.trim(),
            submitDisabled: submit.disabled,
            fileInputDisabled: input.disabled,
            selectedFileName: selected ? selected.name : null,
            selectedFileSize: selected ? selected.size : null,
            activeTag: document.activeElement ? document.activeElement.tagName : null,
            activeIsSubmit: document.activeElement === submit
          };
        }, {once: true});
        """,
        form,
        submit,
    )

    activation_mode = None
    activation_errors = []
    pointer_eligible = bool(
        geometry_positioned["fullyInsideViewport"]
        and geometry_positioned["centerInsideViewport"]
        and geometry_positioned["centerHitsSubmit"]
    )

    if pointer_eligible:
        try:
            submit.click()
        except WebDriverException as exc:
            activation_errors.append(
                f"pointer:{type(exc).__name__}:{str(exc).splitlines()[0][:240]}"
            )
        if driver.execute_script("return window.__phase6StoreSubmitObservation") is not None:
            activation_mode = "native_webelement_click"

    if activation_mode is None:
        try:
            driver.execute_script("arguments[0].focus({preventScroll: true});", submit)
            submit.send_keys(Keys.ENTER)
        except WebDriverException as exc:
            activation_errors.append(
                f"keyboard_enter:{type(exc).__name__}:{str(exc).splitlines()[0][:240]}"
            )
        if driver.execute_script("return window.__phase6StoreSubmitObservation") is not None:
            activation_mode = "native_keyboard_enter"

    if activation_mode is None:
        try:
            driver.execute_script("arguments[0].focus({preventScroll: true});", submit)
            submit.send_keys(Keys.SPACE)
        except WebDriverException as exc:
            activation_errors.append(
                f"keyboard_space:{type(exc).__name__}:{str(exc).splitlines()[0][:240]}"
            )
        if driver.execute_script("return window.__phase6StoreSubmitObservation") is not None:
            activation_mode = "native_keyboard_space"

    if activation_mode is None:
        try:
            driver.execute_script(
                """
                const form = arguments[0];
                const submit = arguments[1];
                form.requestSubmit(submit);
                """,
                form,
                submit,
            )
        except WebDriverException as exc:
            activation_errors.append(
                f"request_submit:{type(exc).__name__}:{str(exc).splitlines()[0][:240]}"
            )
        if driver.execute_script("return window.__phase6StoreSubmitObservation") is not None:
            activation_mode = "form_requestSubmit"

    synchronous = driver.execute_script("return window.__phase6StoreSubmitObservation")
    immediate = _upload_form_runtime_state(driver)
    geometry_after = _store_media_submit_geometry(driver, submit)
    if synchronous is None:
        active = driver.execute_script(
            """
            const submit = arguments[0];
            return {
              activeTag: document.activeElement ? document.activeElement.tagName : null,
              activeText: document.activeElement ? document.activeElement.textContent.trim().slice(0, 160) : null,
              activeIsSubmit: document.activeElement === submit
            };
            """,
            submit,
        )
        pytest.fail(
            "Standards-based Store-media activation did not dispatch the production submit event: "
            f"relationship={relationship!r}, runtime_before={runtime!r}, runtime_after={immediate!r}, "
            f"geometry_before={geometry_before!r}, geometry_positioned={geometry_positioned!r}, "
            f"geometry_after={geometry_after!r}, pointer_eligible={pointer_eligible!r}, "
            f"activation_errors={activation_errors!r}, active={active!r}"
        )

    # This passive listener was registered after the production listener. Its
    # same-event snapshot therefore proves the production handler synchronously
    # revealed progress, wrote Uploading, and disabled submit before XHR progress.
    assert synchronous["progressVisible"] is True, (synchronous, relationship, immediate)
    assert synchronous["progressValue"] == 0, (synchronous, relationship, immediate)
    assert synchronous["percentText"] == "0%", (synchronous, relationship, immediate)
    assert "Uploading" in synchronous["statusText"], (synchronous, relationship, immediate)
    assert synchronous["submitDisabled"] is True, (synchronous, relationship, immediate)
    assert synchronous["fileInputDisabled"] is False, (synchronous, relationship, immediate)
    assert synchronous["selectedFileName"] == expected_file.name, (synchronous, relationship, immediate)
    assert synchronous["selectedFileSize"] == expected_file.stat().st_size, (synchronous, relationship, immediate)
    assert activation_mode is not None
    return {
        "activation": activation_mode,
        "activation_errors": activation_errors,
        "pointer_eligible": pointer_eligible,
        "geometry_before": geometry_before,
        "geometry_positioned": geometry_positioned,
        "geometry_after": geometry_after,
        "relationship": relationship,
        "synchronous": synchronous,
        "immediate": immediate,
    }


def _shot_checked(driver, name):
    _shot(driver, name)
    assert (ARTIFACT_DIR / name).exists()
    assert _no_overflow(driver)


def _large_png(path):
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

    proxy = _UploadObservationProxy(live_server.url)
    driver = None
    native_throttle_enabled = False
    manage_url = f"{live_server.url}/designer/store/products/{product.pk}/?org={org.pk}&lang=en"
    try:
        driver = _chrome_through_proxy(proxy.url, width=1440, height=1000)
        _login(driver, live_server, client, owner)
        wait = _wait(driver)
        driver.get(manage_url)
        upload_form = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "[data-store-media-upload-form]")))
        assert driver.find_element(By.CSS_SELECTOR, "[data-store-media-empty]")
        assert upload_form.get_attribute("enctype").lower() == "multipart/form-data"
        assert driver.current_url == manage_url
        _frame(driver, driver.find_element(By.CSS_SELECTOR, "[data-store-media-section]"))
        _shot_checked(driver, "p6-01-product-images-empty-en-desktop.png")

        # Control: prove the production submit handler reaches the application
        # through a genuine multipart POST before installing any throttling rule.
        # Completion is established from CDP + proxy transport, not a localized
        # text wait; the controlled validator message is asserted afterwards.
        driver.execute_cdp_cmd("Network.enable", {})
        browser_version = driver.execute_cdp_cmd("Browser.getVersion", {})
        driver.get_log("performance")
        driver.get_log("browser")
        probe_posts_before = len(proxy.product_posts())
        probe_input = driver.find_element(By.CSS_SELECTOR, "[data-store-media-file]")
        probe_input.send_keys(str(invalid))
        probe_runtime = _upload_form_runtime_state(driver)
        assert probe_runtime["href"] == manage_url
        assert probe_runtime["endpoint"] == manage_url
        assert probe_runtime["fileName"] == invalid.name
        assert probe_runtime["fileSize"] == invalid.stat().st_size

        probe_state = {"extra_by_request": {}, "events": [], "post_urls": []}
        probe_started_at = time.monotonic()
        probe_activation = _activate_store_media_submit(driver, upload_form, invalid)
        probe_complete = None
        while time.monotonic() - probe_started_at < 30:
            _collect_upload_network_state(driver, upload_url=manage_url, state=probe_state)
            probe_posts = proxy.product_posts()
            probe_runtime_after = _upload_form_runtime_state(driver)
            new_posts = probe_posts[probe_posts_before:]
            if len(new_posts) == 1:
                row = new_posts[0]
                transport_complete = bool(
                    row["content_length"] > invalid.stat().st_size
                    and row["received_bytes"] == row["content_length"]
                    and row["body_complete"]
                    and row["response_status"] is not None
                    and row["response_complete"]
                )
                network_complete = bool(
                    probe_state.get("request_url") == manage_url
                    and probe_state.get("loading_failed") is None
                    and (
                        probe_state.get("loading_finished")
                        or probe_state.get("response_status") is not None
                    )
                )
                ui_complete = bool(
                    probe_runtime_after["submitEnabled"]
                    and probe_runtime_after["fileInputEnabled"]
                    and probe_runtime_after["progressVisible"] is False
                )
                if transport_complete and network_complete and ui_complete:
                    probe_complete = (
                        row,
                        probe_runtime_after,
                        time.monotonic() - probe_started_at,
                    )
                    break
            time.sleep(0.05)

        if probe_complete is None:
            _collect_upload_network_state(driver, upload_url=manage_url, state=probe_state)
            probe_posts = proxy.product_posts()
            probe_runtime_after = _upload_form_runtime_state(driver)
            probe_errors = _browser_console_errors(driver)
            probe_received, probe_total, probe_connection, probe_path = proxy.upload_snapshot()
            pytest.fail(
                "Unthrottled Store-product multipart control did not complete deterministically: "
                f"activation={probe_activation!r}, runtime={probe_runtime_after!r}, "
                f"post_urls={probe_state.get('post_urls', [])[-8:]!r}, "
                f"network_events={probe_state.get('events', [])[-16:]!r}, "
                f"request_url={probe_state.get('request_url')!r}, "
                f"response_status={probe_state.get('response_status')!r}, "
                f"loading_finished={probe_state.get('loading_finished')!r}, "
                f"loading_failed={probe_state.get('loading_failed')!r}, "
                f"proxy_product_posts={probe_posts[-6:]!r}, "
                f"proxy_large_snapshot={probe_received}/{probe_total},"
                f"connection={probe_connection!r},path={probe_path!r}, "
                f"browser_errors={probe_errors!r}, provider_calls={len(provider_calls)}, "
                f"browser_product={browser_version.get('product')!r}, "
                f"protocol_version={browser_version.get('protocolVersion')!r}, "
                f"elapsed={time.monotonic() - probe_started_at:.3f}s"
            )

        probe_post, probe_runtime_after, probe_elapsed = probe_complete
        probe_errors = _browser_console_errors(driver)
        assert probe_state.get("request_url") == manage_url, (probe_state, probe_errors)
        assert probe_state.get("loading_failed") is None, (probe_state, probe_errors)
        assert probe_post["content_length"] > invalid.stat().st_size
        assert probe_post["received_bytes"] == probe_post["content_length"]
        assert probe_post["body_complete"] and probe_post["response_complete"]
        assert "valid PNG, JPEG or WebP" in probe_runtime_after["statusText"], (
            probe_runtime_after,
            probe_state,
            probe_post,
            probe_errors,
        )
        assert len(provider_calls) == 0
        assert product.images.count() == 0

        file_input = driver.find_element(By.CSS_SELECTOR, "[data-store-media-file]")
        file_input.clear()
        file_input.send_keys(str(large))
        wait.until(lambda _d: large.name in driver.find_element(By.CSS_SELECTOR, "[data-store-media-filename]").text)
        selected_runtime = _upload_form_runtime_state(driver)
        assert selected_runtime["endpoint"] == manage_url
        assert selected_runtime["fileName"] == large.name
        assert selected_runtime["fileSize"] == large.stat().st_size
        _frame(driver, upload_form)
        _shot_checked(driver, "p6-02-product-image-selected-file-en.png")

        # Install the rule only after the successful unthrottled control. The
        # proxy forces Connection: close, so the evidence upload necessarily uses
        # a fresh browser-to-proxy connection created after the rule is active.
        throttle_rule_id = _enable_native_upload_throttle(driver, manage_url)
        native_throttle_enabled = True
        driver.get_log("performance")
        driver.get_log("browser")
        connections_before_upload = proxy.connection_count()
        posts_before_upload = len(proxy.product_posts())
        network_state = {"extra_by_request": {}, "events": [], "post_urls": []}
        observed_progress = []
        upload_started_at = time.monotonic()
        upload_runtime_before = _upload_form_runtime_state(driver)
        upload_activation = _activate_store_media_submit(driver, upload_form, large)
        progress = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "[data-store-media-progress]")))

        deadline = upload_started_at + 45
        intermediate = None
        while time.monotonic() < deadline:
            _collect_upload_network_state(driver, upload_url=manage_url, state=network_state)
            value = float(progress.get_attribute("value") or 0)
            if not observed_progress or observed_progress[-1] != value:
                observed_progress.append(value)
            received, total, connection_id, request_path = proxy.upload_snapshot()
            if (
                network_state.get("applied_rule_id") == throttle_rule_id
                and 0 < value < 100
                and 0 < received < total
            ):
                intermediate = (
                    value,
                    received,
                    total,
                    time.monotonic() - upload_started_at,
                    connection_id,
                    request_path,
                )
                break
            time.sleep(0.05)

        if intermediate is None:
            received, total, connection_id, request_path = proxy.upload_snapshot()
            _collect_upload_network_state(driver, upload_url=manage_url, state=network_state)
            upload_runtime_after = _upload_form_runtime_state(driver)
            browser_errors = _browser_console_errors(driver)
            recent_posts = proxy.product_posts()[-4:]
            pytest.fail(
                "No genuine intermediate native upload state observed: "
                f"rule={throttle_rule_id!r}, applied={network_state.get('applied_rule_id')!r}, "
                f"request_url={network_state.get('request_url')!r}, "
                f"post_urls={network_state.get('post_urls', [])[-6:]!r}, "
                f"network_events={network_state.get('events', [])[-12:]!r}, "
                f"loading_failed={network_state.get('loading_failed')!r}, "
                f"progress_values={observed_progress[-12:]!r}, "
                f"proxy_bytes={received}/{total}, upload_connection={connection_id!r}, "
                f"connections_before_upload={connections_before_upload}, "
                f"posts_before_upload={posts_before_upload}, recent_proxy_posts={recent_posts!r}, "
                f"request_path={request_path!r}, runtime_before={upload_runtime_before!r}, "
                f"activation={upload_activation!r}, runtime_after={upload_runtime_after!r}, browser_errors={browser_errors!r}, "
                f"browser_product={browser_version.get('product')!r}, "
                f"protocol_version={browser_version.get('protocolVersion')!r}, "
                f"elapsed={time.monotonic() - upload_started_at:.3f}s"
            )

        (
            intermediate_percent,
            intermediate_received,
            upload_total,
            intermediate_elapsed,
            upload_connection_id,
            upload_request_path,
        ) = intermediate
        assert len(proxy.product_posts()) == posts_before_upload + 1
        assert upload_connection_id is not None and upload_connection_id > connections_before_upload
        assert network_state["request_url"] == manage_url
        assert network_state["applied_rule_id"] == throttle_rule_id
        percent_text = driver.find_element(By.CSS_SELECTOR, "[data-store-media-percent]").text
        upload_status = driver.find_element(By.CSS_SELECTOR, "[data-store-media-status]")
        assert "%" in percent_text and percent_text != "100%"
        assert "Uploading" in upload_status.text
        assert 0 < intermediate_received < upload_total
        assert not provider_started.is_set()
        progress_wrap = driver.find_element(By.CSS_SELECTOR, "[data-store-media-progress-wrap]")
        _frame(driver, progress_wrap)
        _shot_checked(driver, "p6-03-product-image-upload-progress-en.png")

        assert provider_started.wait(timeout=60), "Provider was not reached after real multipart upload"
        processing_status = wait.until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, "[data-store-media-status]"))
        )
        wait.until(lambda _d: "Processing image" in processing_status.text)
        completed_received, completed_total, completed_connection_id, completed_path = proxy.upload_snapshot()
        upload_complete_elapsed = time.monotonic() - upload_started_at
        assert completed_total == upload_total
        assert completed_received == completed_total
        assert completed_total > large.stat().st_size
        assert completed_connection_id == upload_connection_id
        assert completed_path == upload_request_path
        assert not release_provider.is_set()
        assert float(progress.get_attribute("value") or 0) == 100
        assert driver.find_element(By.CSS_SELECTOR, "[data-store-media-percent]").text == "100%"
        _frame(driver, processing_status)
        _shot_checked(driver, "p6-04-product-image-processing-en.png")

        final_console_errors = _browser_console_errors(driver)
        probe_geometry = probe_activation["geometry_positioned"]
        upload_geometry = upload_activation["geometry_positioned"]
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        (ARTIFACT_DIR / "p6-native-upload-progress-evidence.txt").write_text(
            "native xhr.upload evidence via real multipart transport\n"
            f"browser_product={browser_version.get('product', '')}\n"
            f"browser_protocol_version={browser_version.get('protocolVersion', '')}\n"
            f"unthrottled_probe_activation={probe_activation['activation']}\n"
            f"unthrottled_probe_activation_errors={probe_activation['activation_errors']}\n"
            f"unthrottled_probe_pointer_eligible={probe_activation['pointer_eligible']}\n"
            f"unthrottled_probe_viewport={probe_geometry['innerWidth']}x{probe_geometry['innerHeight']}\n"
            f"unthrottled_probe_scroll={probe_geometry['scrollX']},{probe_geometry['scrollY']}\n"
            f"unthrottled_probe_submit_rect={json.dumps(probe_geometry['rect'], sort_keys=True)}\n"
            f"unthrottled_probe_submit_center={probe_geometry['centerX']:.3f},{probe_geometry['centerY']:.3f}\n"
            f"unthrottled_probe_center_hits_submit={probe_geometry['centerHitsSubmit']}\n"
            f"unthrottled_probe_topmost={json.dumps(probe_geometry['topmost'], sort_keys=True)}\n"
            f"unthrottled_probe_js_initialized={probe_activation['relationship']['productionScriptPresent']}\n"
            f"unthrottled_probe_sync_percent={probe_activation['synchronous']['percentText']}\n"
            f"unthrottled_probe_sync_status={probe_activation['synchronous']['statusText']}\n"
            f"unthrottled_probe_request_url={probe_state['request_url']}\n"
            f"unthrottled_probe_content_length={probe_post['content_length']}\n"
            f"unthrottled_probe_received_bytes={probe_post['received_bytes']}\n"
            f"unthrottled_probe_response_status={probe_post['response_status']}\n"
            f"unthrottled_probe_elapsed_seconds={probe_elapsed:.3f}\n"
            f"unthrottled_probe_status_text={probe_runtime_after['statusText']}\n"
            f"unthrottled_probe_provider_calls=0\n"
            f"evidence_upload_activation={upload_activation['activation']}\n"
            f"evidence_upload_activation_errors={upload_activation['activation_errors']}\n"
            f"evidence_upload_pointer_eligible={upload_activation['pointer_eligible']}\n"
            f"evidence_upload_viewport={upload_geometry['innerWidth']}x{upload_geometry['innerHeight']}\n"
            f"evidence_upload_scroll={upload_geometry['scrollX']},{upload_geometry['scrollY']}\n"
            f"evidence_upload_submit_rect={json.dumps(upload_geometry['rect'], sort_keys=True)}\n"
            f"evidence_upload_submit_center={upload_geometry['centerX']:.3f},{upload_geometry['centerY']:.3f}\n"
            f"evidence_upload_center_hits_submit={upload_geometry['centerHitsSubmit']}\n"
            f"evidence_upload_topmost={json.dumps(upload_geometry['topmost'], sort_keys=True)}\n"
            f"browser_network_rule_id={throttle_rule_id}\n"
            f"browser_rule_applied_id={network_state['applied_rule_id']}\n"
            f"browser_request_url={network_state['request_url']}\n"
            f"browser_upload_throughput_bytes_per_second={UPLOAD_THROUGHPUT_BYTES_PER_SECOND}\n"
            f"native_progress_values_observed={','.join(f'{value:g}' for value in observed_progress)}\n"
            f"intermediate_visible_percent={intermediate_percent:g}\n"
            f"intermediate_transport_received={intermediate_received}\n"
            f"transport_total={upload_total}\n"
            f"intermediate_elapsed_seconds={intermediate_elapsed:.3f}\n"
            f"completed_transport_received={completed_received}\n"
            f"upload_complete_elapsed_seconds={upload_complete_elapsed:.3f}\n"
            f"proxy_connections_before_upload={connections_before_upload}\n"
            f"upload_connection_id={upload_connection_id}\n"
            f"upload_request_path={upload_request_path}\n"
            f"provider_started={provider_started.is_set()}\n"
            f"provider_release_pending={not release_provider.is_set()}\n"
            f"browser_console_error_count={len(final_console_errors)}\n",
            encoding="utf-8",
        )

        _disable_native_upload_throttle(driver)
        native_throttle_enabled = False
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

        second_form = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "[data-store-media-upload-form]")))
        second_form.find_element(By.CSS_SELECTOR, "[data-store-media-file]").send_keys(str(second))
        _activate_store_media_submit(driver, second_form, second)
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
        retry_form = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "[data-store-media-upload-form]")))
        retry_form.find_element(By.CSS_SELECTOR, "[data-store-media-file]").send_keys(str(invalid))
        retry_submit = retry_form.find_element(By.CSS_SELECTOR, "[data-store-media-submit]")
        _activate_store_media_submit(driver, retry_form, invalid)
        wait.until(lambda _d: "valid PNG, JPEG or WebP" in driver.find_element(By.CSS_SELECTOR, "[data-store-media-status]").text)
        assert len(provider_calls) == before_provider_calls
        assert retry_submit.is_enabled()
        _frame(driver, retry_submit)
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
            if native_throttle_enabled:
                _disable_native_upload_throttle(driver)
            driver.quit()
        proxy.close()


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
        progress_wrap = driver.find_element(By.CSS_SELECTOR, "[data-store-media-progress-wrap]")
        assert progress_wrap.get_attribute("hidden") is not None
    finally:
        driver.quit()
