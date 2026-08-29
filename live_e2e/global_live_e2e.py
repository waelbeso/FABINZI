#!/usr/bin/env python3
"""FABINZI deployed Global Live E2E QA.

This module is intentionally outside normal pytest discovery. It MUST be invoked
explicitly against a non-production QA deployment. It never starts a local
Django server and never mutates the database directly.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import struct
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait

ARTIFACT_DIR = Path("artifacts/global-live-e2e-qa")
SUMMARY_PATH = ARTIFACT_DIR / "live-e2e-summary.json"
PRIVATE_UPLOAD_PATH = Path(tempfile.gettempdir()) / "fabinzi-global-live-private.png"
PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010804000000b51c0c02"
    "0000000b4944415478da63fcff1f0002eb01f58f59975b0000000049454e44ae426082"
)

SCREENSHOTS = [
    "01-live-home-desktop-en-light.png",
    "02-live-catalog-desktop-en-light.png",
    "03-live-artwork-marketplace-desktop-en-light.png",
    "04-live-studio-desktop-en-light.png",
    "05-live-customer-cart-desktop-en-light.png",
    "06-live-checkout-desktop-en-light.png",
    "07-live-customer-purchase-desktop-en-light.png",
    "08-live-designer-dashboard-desktop-en-light.png",
    "09-live-designer-rfq-desktop-en-light.png",
    "10-live-manufacturer-opportunities-desktop-en-light.png",
    "11-live-manufacturer-production-desktop-en-light.png",
    "12-live-manufacturer-shipment-desktop-en-light.png",
    "13-live-maneg-dashboard-desktop-en-light.png",
    "14-live-maneg-order-chain-desktop-en-light.png",
    "15-live-maneg-audit-desktop-en-light.png",
    "16-live-customer-mobile-ar-rtl-dark.png",
    "17-live-designer-mobile-ar-rtl-dark.png",
    "18-live-manufacturer-mobile-ar-rtl-dark.png",
    "19-live-maneg-mobile-ar-rtl-dark.png",
    "20-live-final-cross-role-state-desktop-en-light.png",
]

REQUIRED_ENV = (
    "FABINZI_LIVE_E2E_ENABLED",
    "FABINZI_LIVE_E2E_BASE_URL",
    "FABINZI_LIVE_E2E_EXPECTED_SHA",
    "FABINZI_LIVE_E2E_EXPECTED_BRANCH",
    "FABINZI_LIVE_E2E_CONFIRM_NON_PRODUCTION",
    "FABINZI_LIVE_E2E_CUSTOMER_PASSWORD",
    "FABINZI_LIVE_E2E_DESIGNER_PASSWORD",
    "FABINZI_LIVE_E2E_MANUFACTURER_PASSWORD",
    "FABINZI_LIVE_E2E_ADMIN_PASSWORD",
    "FABINZI_LIVE_E2E_ADMIN_TOTP_SECRET",
)

QA_USERS = {
    "customer": "fabinzi_demo_customer",
    "designer": "fabinzi_demo_designer",
    "manufacturer": "fabinzi_demo_manufacturer",
    "admin": "fabinzi_demo_admin",
}


@dataclass
class LiveState:
    base_url: str
    expected_sha: str
    expected_branch: str
    deployment: dict[str, Any] = field(default_factory=dict)
    purchase_id: int | None = None
    purchase_number: str = ""
    child_order_ids: list[int] = field(default_factory=list)
    selected_order_id: int | None = None
    job_id: int | None = None
    fulfillment_id: int | None = None
    manufacturer_org_id: int | None = None
    designer_org_id: int | None = None
    selection_id: int | None = None
    rfq_id: int | None = None
    private_media_url: str = ""
    integration_snapshot: str = ""
    provider_truth: dict[str, Any] = field(default_factory=dict)
    cookies: dict[str, dict[str, str]] = field(default_factory=dict)
    results: dict[str, str] = field(default_factory=dict)


def _fail(message: str) -> None:
    raise AssertionError(message)


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        _fail(f"Missing required protected/live E2E value: {name}")
    return value


def _guard_environment() -> LiveState:
    missing = [name for name in REQUIRED_ENV if not os.environ.get(name, "").strip()]
    if missing:
        _fail("Live E2E is not configured. Missing: " + ", ".join(missing))
    if _required_env("FABINZI_LIVE_E2E_ENABLED").lower() != "true":
        _fail("FABINZI_LIVE_E2E_ENABLED must be exactly true.")
    if _required_env("FABINZI_LIVE_E2E_CONFIRM_NON_PRODUCTION").lower() != "true":
        _fail("Explicit non-production confirmation is required.")
    base = _required_env("FABINZI_LIVE_E2E_BASE_URL").rstrip("/") + "/"
    parsed = urlparse(base)
    if parsed.scheme != "https" or not parsed.hostname:
        _fail("Live E2E base URL must be an explicit HTTPS URL.")
    if parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
        _fail("Live E2E cannot target a local server.")
    expected_sha = _required_env("FABINZI_LIVE_E2E_EXPECTED_SHA")
    if not re.fullmatch(r"[0-9a-f]{40}", expected_sha):
        _fail("Expected repository SHA must be a full 40-character lowercase git SHA.")
    return LiveState(
        base_url=base,
        expected_sha=expected_sha,
        expected_branch=_required_env("FABINZI_LIVE_E2E_EXPECTED_BRANCH"),
    )


def _http_get(state: LiveState, path: str, **kwargs) -> requests.Response:
    return requests.get(urljoin(state.base_url, path.lstrip("/")), timeout=40, **kwargs)


def _preflight(state: LiveState) -> None:
    health = _http_get(state, "/healthz/")
    assert health.status_code == 200, f"healthz returned {health.status_code}"
    payload = health.json()
    deployment = payload.get("deployment") or {}
    actual_sha = str(deployment.get("commit") or "")
    actual_branch = str(deployment.get("branch") or "")
    if actual_sha != state.expected_sha:
        _fail(f"STALE/UNKNOWN DEPLOYMENT: expected {state.expected_sha}, healthz reports {actual_sha or '<missing>'}.")
    if actual_branch != state.expected_branch:
        _fail(f"Unexpected deployed branch: expected {state.expected_branch}, got {actual_branch or '<missing>'}.")
    if not deployment.get("service"):
        _fail("Deployment service identity is missing from healthz.")
    state.deployment = deployment

    ready = _http_get(state, "/readyz/")
    assert ready.status_code == 200 and ready.json().get("database") == "ok", "QA database is not ready."
    api_health = _http_get(state, "/api/v1/health/")
    assert api_health.status_code == 200 and api_health.json().get("status") == "ok"

    robots = _http_get(state, "/robots.txt")
    assert robots.status_code == 200
    robots_text = robots.text
    for private_path in ("/Maneg/", "/designer/", "/manufacturer/", "/studio/", "/media/private/"):
        assert f"Disallow: {private_path}" in robots_text

    home = _http_get(state, "/?lang=en")
    assert home.status_code == 200
    assert "FABINZI" in home.text and "Shop" in home.text and "Artwork" in home.text
    assert "Django administration" not in home.text

    headers = {key.lower(): value for key, value in home.headers.items()}
    assert "max-age=" in headers.get("strict-transport-security", "")
    assert headers.get("x-content-type-options", "").lower() == "nosniff"
    assert headers.get("x-frame-options", "").upper() == "DENY"
    assert headers.get("referrer-policy", "")
    state.results["deployment_sha_match"] = "PASS"
    state.results["public_security_headers"] = "PASS"


def _chrome(width: int = 1440, height: int = 1050) -> webdriver.Chrome:
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument(f"--window-size={width},{height}")
    options.add_experimental_option("prefs", {"intl.accept_languages": "en-US,en,ar"})
    return webdriver.Chrome(options=options)


def _wait(driver, seconds: int = 20) -> WebDriverWait:
    return WebDriverWait(driver, seconds)


def _absolute(state: LiveState, path: str) -> str:
    return urljoin(state.base_url, path.lstrip("/"))


def _no_document_overflow(driver) -> bool:
    return bool(driver.execute_script("return document.documentElement.scrollWidth <= window.innerWidth + 1"))


def _assert_page_clean(driver) -> None:
    assert _no_document_overflow(driver), f"Document horizontal overflow at {driver.current_url}"
    text = driver.find_element(By.TAG_NAME, "body").text
    assert "Traceback (most recent call last)" not in text
    assert "DEBUG = True" not in text
    assert "Server Error (500)" not in text


def _shot(driver, name: str) -> None:
    if name not in SCREENSHOTS:
        _fail(f"Unexpected live screenshot name: {name}")
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    _assert_page_clean(driver)
    assert driver.save_screenshot(str(ARTIFACT_DIR / name))


def _click(driver, by, locator):
    node = _wait(driver).until(EC.element_to_be_clickable((by, locator)))
    ActionChains(driver).scroll_to_element(node).move_to_element(node).pause(0.06).click().perform()
    return node


def _fill(driver, by, locator, value: str) -> None:
    node = _wait(driver).until(EC.visibility_of_element_located((by, locator)))
    node.clear()
    node.send_keys(value)


def _totp(secret: str, now: int | None = None) -> str:
    cleaned = re.sub(r"\s+", "", secret).upper()
    padding = "=" * ((8 - len(cleaned) % 8) % 8)
    key = base64.b32decode(cleaned + padding, casefold=True)
    counter = int((now or time.time()) // 30)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF) % 1_000_000
    return f"{code:06d}"


def _login(state: LiveState, driver, role: str) -> None:
    driver.delete_all_cookies()
    driver.get(_absolute(state, "/account/login/"))
    wait = _wait(driver)
    username = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'input[name$="username"]')))
    password = driver.find_element(By.CSS_SELECTOR, 'input[type="password"]')
    username.clear(); username.send_keys(QA_USERS[role])
    password.clear(); password.send_keys(_required_env(f"FABINZI_LIVE_E2E_{role.upper()}_PASSWORD"))
    submit = driver.find_element(By.CSS_SELECTOR, 'button[type="submit"], input[type="submit"]')
    submit.click()

    if role == "admin":
        try:
            token = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, 'input[name$="otp_token"], input[name*="otp"], input[autocomplete="one-time-code"]')))
            token.clear(); token.send_keys(_totp(_required_env("FABINZI_LIVE_E2E_ADMIN_TOTP_SECRET")))
            driver.find_element(By.CSS_SELECTOR, 'button[type="submit"], input[type="submit"]').click()
        except TimeoutException as exc:
            _fail("Controlled QA admin did not present the required OTP step; MFA must not be bypassed.")

    wait.until(lambda d: "/account/login/" not in d.current_url)
    state.cookies[role] = {c["name"]: c["value"] for c in driver.get_cookies()}


def _set_preferences(state: LiveState, driver, language: str, theme: str) -> None:
    driver.get(_absolute(state, "/app/settings/preferences/"))
    _wait(driver).until(EC.presence_of_element_located((By.ID, "preference-language")))
    Select(driver.find_element(By.ID, "preference-language")).select_by_value(language)
    Select(driver.find_element(By.ID, "preference-theme")).select_by_value(theme)
    _click(driver, By.CSS_SELECTOR, 'form button[type="submit"]')
    _wait(driver).until(lambda d: d.find_element(By.TAG_NAME, "html").get_attribute("lang").startswith(language))
    html = driver.find_element(By.TAG_NAME, "html")
    assert html.get_attribute("dir") == ("rtl" if language == "ar" else "ltr")
    assert html.get_attribute("data-theme") == theme


def _ensure_csrf(state: LiveState, driver) -> str:
    cookie = driver.get_cookie("csrftoken")
    if cookie:
        return cookie["value"]
    driver.get(_absolute(state, "/app/settings/preferences/"))
    _wait(driver).until(EC.presence_of_element_located((By.CSS_SELECTOR, 'input[name="csrfmiddlewaretoken"]')))
    cookie = driver.get_cookie("csrftoken")
    if not cookie:
        _fail("CSRF cookie was not established for the authenticated browser session.")
    return cookie["value"]


def _api(state: LiveState, driver, method: str, path: str, payload: dict[str, Any] | None = None, expected=(200, 201, 204)) -> Any:
    csrf = _ensure_csrf(state, driver) if method.upper() not in {"GET", "HEAD", "OPTIONS"} else ""
    script = """
      const done = arguments[arguments.length - 1];
      const method = arguments[0], url = arguments[1], csrf = arguments[2], payload = arguments[3];
      const headers = {'Accept': 'application/json'};
      if (method !== 'GET' && method !== 'HEAD') {
        headers['Content-Type'] = 'application/json';
        if (csrf) headers['X-CSRFToken'] = csrf;
      }
      fetch(url, {method, credentials:'same-origin', headers, body: payload === null ? undefined : JSON.stringify(payload)})
        .then(async r => { const text = await r.text(); let body; try { body = JSON.parse(text); } catch(e) { body = text; } done({status:r.status, body}); })
        .catch(e => done({status:0, body:String(e)}));
    """
    result = driver.execute_async_script(script, method.upper(), _absolute(state, path), csrf, payload)
    if result["status"] not in expected:
        _fail(f"API {method} {path} returned {result['status']}: {result['body']}")
    return result["body"]


def _api_expect_denied(state: LiveState, driver, method: str, path: str, payload: dict[str, Any] | None = None) -> None:
    csrf = _ensure_csrf(state, driver) if method.upper() != "GET" else ""
    script = """
      const done = arguments[arguments.length - 1];
      const method=arguments[0], url=arguments[1], csrf=arguments[2], payload=arguments[3];
      const headers={'Accept':'application/json'};
      if(method!=='GET'){headers['Content-Type']='application/json';headers['X-CSRFToken']=csrf;}
      fetch(url,{method,credentials:'same-origin',headers,body:payload===null?undefined:JSON.stringify(payload)})
        .then(async r=>done({status:r.status,body:await r.text()})).catch(e=>done({status:0,body:String(e)}));
    """
    result = driver.execute_async_script(script, method.upper(), _absolute(state, path), csrf, payload)
    assert result["status"] in {401, 403, 404}, f"Expected denial for {path}; got {result}"


def _clear_cart(state: LiveState, driver) -> None:
    cart = _api(state, driver, "GET", "/api/v1/cart/")
    for item in list(cart.get("items") or []):
        _api(state, driver, "DELETE", f"/api/v1/cart/items/{item['id']}/")
    cart = _api(state, driver, "GET", "/api/v1/cart/")
    assert cart.get("item_count") == 0


def _add_plain_product(state: LiveState, driver, slug: str) -> None:
    driver.get(_absolute(state, f"/store/fabinzi-demo-studio/{slug}/?lang=en"))
    _wait(driver).until(EC.presence_of_element_located((By.ID, "product-purchase-form")))
    form = driver.find_element(By.ID, "product-purchase-form")
    assert form.is_displayed()
    _click(driver, By.CSS_SELECTOR, "#product-purchase-form button[type='submit']")
    _wait(driver).until(EC.url_contains("/cart/"))


def _create_private_studio_item(state: LiveState, driver) -> None:
    PRIVATE_UPLOAD_PATH.write_bytes(PNG_1X1)
    driver.get(_absolute(state, "/store/fabinzi-demo-studio/womens-tshirt-plain/?lang=en"))
    _click(driver, By.ID, "product-customize-link")
    wait = _wait(driver)
    wait.until(EC.presence_of_element_located((By.ID, "studio-variant")))
    _click(driver, By.CSS_SELECTOR, 'form[aria-label="Start customization project"] button[type="submit"]')
    wait.until(EC.presence_of_element_located((By.ID, "studio-editor")))
    _click(driver, By.CSS_SELECTOR, '[data-studio-tab="upload"]')
    wait.until(EC.visibility_of_element_located((By.ID, "private-upload-form")))
    driver.find_element(By.ID, "private-art-file").send_keys(str(PRIVATE_UPLOAD_PATH))
    zone = Select(driver.find_element(By.ID, "upload-zone"))
    if not zone.first_selected_option.get_attribute("value"):
        for option in zone.options:
            if option.get_attribute("value"):
                zone.select_by_value(option.get_attribute("value")); break
    Select(driver.find_element(By.ID, "upload-method")).select_by_value("print")
    rights = driver.find_element(By.ID, "rights-confirmed")
    if not rights.is_selected():
        _click(driver, By.ID, "rights-confirmed")
    _click(driver, By.CSS_SELECTOR, "#private-upload-form button[type='submit']")
    image_element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, '[data-studio-element][data-kind="image"]')))
    try:
        img = image_element.find_element(By.TAG_NAME, "img")
        state.private_media_url = img.get_attribute("src") or ""
    except NoSuchElementException:
        state.private_media_url = ""
    wait.until(lambda d: d.find_element(By.ID, "studio-save-state").get_attribute("data-state") == "saved")
    _shot(driver, SCREENSHOTS[3])
    wait.until(lambda d: "is-valid" in d.find_element(By.ID, "studio-validation").get_attribute("class").split())
    _click(driver, By.ID, "mark-ready")
    wait.until(EC.presence_of_element_located((By.ID, "add-studio-cart")))
    _click(driver, By.ID, "add-studio-cart")
    wait.until(EC.url_contains("/cart/"))


def _customer_purchase(state: LiveState, driver) -> None:
    _login(state, driver, "customer")
    _set_preferences(state, driver, "en", "light")
    _clear_cart(state, driver)
    _add_plain_product(state, driver, "mens-tshirt-plain")
    _add_plain_product(state, driver, "cairo-lines-tee")
    _create_private_studio_item(state, driver)

    driver.get(_absolute(state, "/cart/?lang=en"))
    body = _wait(driver).until(EC.visibility_of_element_located((By.TAG_NAME, "body"))).text
    assert "Plain product" in body
    assert "Private customer customization" in body
    assert "Designer ready-designed product" in body
    _shot(driver, SCREENSHOTS[4])

    cart = _api(state, driver, "GET", "/api/v1/cart/")
    assert cart["item_count"] == 3
    assert {row["kind"] for row in cart["items"]} == {"plain", "studio", "ready_designed"}

    _click(driver, By.LINK_TEXT, "Continue to checkout")
    wait = _wait(driver)
    wait.until(EC.presence_of_element_located((By.ID, "checkout-form")))
    _fill(driver, By.ID, "shipping_name", "FABINZI Global Live QA")
    _fill(driver, By.ID, "shipping_phone", "+201000009999")
    _fill(driver, By.ID, "shipping_email", "global-live-qa@example.invalid")
    _fill(driver, By.ID, "shipping_address1", "Global Live QA Address")
    _fill(driver, By.ID, "shipping_city", "Cairo")
    _fill(driver, By.ID, "shipping_region", "Cairo")
    _fill(driver, By.ID, "shipping_country", "EG")
    cod = driver.find_elements(By.CSS_SELECTOR, 'input[name="payment_method"][value="cod"]')
    if not cod:
        _fail("COD is not enabled on the live QA environment; safe checkout cannot be completed truthfully.")
    if not cod[0].is_selected(): cod[0].click()
    _shot(driver, SCREENSHOTS[5])
    _click(driver, By.ID, "place-order")
    wait.until(EC.url_matches(r".*/purchases/\d+/confirmation/?(?:\?.*)?$"))
    match = re.search(r"/purchases/(\d+)/confirmation", driver.current_url)
    assert match
    state.purchase_id = int(match.group(1))
    _shot(driver, SCREENSHOTS[6])

    purchase = _api(state, driver, "GET", f"/api/v1/purchases/{state.purchase_id}/")
    state.purchase_number = str(purchase["number"])
    assert purchase["status"] == "confirmed"
    assert len(purchase["items"]) == 3
    orders = _api(state, driver, "GET", "/api/v1/orders/")
    children = [row for row in orders if int(row.get("purchase_id") or 0) == state.purchase_id]
    assert len(children) == 3
    state.child_order_ids = [int(row["id"]) for row in children]
    details = [_api(state, driver, "GET", f"/api/v1/orders/{order_id}/") for order_id in state.child_order_ids]
    assert sum(int(row["item"]["quantity"]) for row in details) == 3
    assert len({row["item"]["sku"] for row in details}) == 3
    mens = next(row for row in details if "Men's T-Shirt" in row["item"]["title"])
    state.selected_order_id = int(mens["id"])
    operations = _api(state, driver, "GET", f"/api/v1/orders/{state.selected_order_id}/operations/")
    assert operations["production"] and operations["fulfillment"]
    state.job_id = int(operations["production"]["id"])
    state.fulfillment_id = int(operations["fulfillment"]["id"])
    state.results["commerce_parent_child"] = "PASS"
    state.results["customer_three_purchase_paths"] = "PASS"


def _designer_create_rfq(state: LiveState, driver) -> None:
    _login(state, driver, "designer")
    _set_preferences(state, driver, "en", "light")
    driver.get(_absolute(state, "/designer/?lang=en")); _wait(driver).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    _shot(driver, SCREENSHOTS[7])

    seeded = _api(state, driver, "GET", "/api/v1/rfqs/")
    reference = next(row for row in seeded if row["title"] == "QA Men's T-Shirt Production")
    state.designer_org_id = int(reference["designer_organization"])
    public_manufacturers = _api(state, driver, "GET", "/api/v1/manufacturers/public/")
    demo = next(row for row in public_manufacturers if row["organization_name"] == "FABINZI Demo Manufacturing")
    state.manufacturer_org_id = int(demo["organization"])
    stamp = int(time.time())
    rfq = _api(state, driver, "POST", "/api/v1/rfqs/", {
        "designer_organization": state.designer_org_id,
        "designed_product": reference["designed_product"],
        "title": f"GLOBAL LIVE E2E Men's T-Shirt {stamp}",
        "quantity": 50,
        "size_breakdown": {"M": 25, "L": 25},
        "color_requirements": ["Black", "White"],
        "requested_methods": ["cut_sew", "DTF"],
        "target_unit_price": "185.00",
        "currency": "EGP",
        "desired_delivery_date": str(date.today() + timedelta(days=30)),
        "delivery_country": "EG",
        "delivery_city": "Cairo",
        "notes": "Namespaced Global Live E2E QA RFQ.",
    })
    state.rfq_id = int(rfq["id"])
    _api(state, driver, "POST", f"/api/v1/rfqs/{state.rfq_id}/open/", {"manufacturer_ids": [state.manufacturer_org_id]})
    driver.get(_absolute(state, "/designer/rfqs/?lang=en"))
    _wait(driver).until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "GLOBAL LIVE E2E"))
    _shot(driver, SCREENSHOTS[8])
    _api_expect_denied(state, driver, "GET", f"/api/v1/manufacturers/{state.manufacturer_org_id}/rfq-invitations/")
    state.results["designer_rfq_create_open"] = "PASS"


def _manufacturer_quote(state: LiveState, driver) -> int:
    _login(state, driver, "manufacturer")
    _set_preferences(state, driver, "en", "light")
    invitations = _api(state, driver, "GET", f"/api/v1/manufacturers/{state.manufacturer_org_id}/rfq-invitations/")
    invitation = next(row for row in invitations if int(row["rfq"]) == state.rfq_id)
    quote = _api(state, driver, "POST", f"/api/v1/rfq-invitations/{invitation['id']}/quote/", {
        "unit_price": "160.00",
        "production_lead_days": 10,
        "setup_fee": "250.00",
        "sample_fee": "150.00",
        "shipping_estimate": "500.00",
        "currency": "EGP",
        "minimum_order_quantity": 25,
        "sample_lead_days": 3,
        "valid_until": str(date.today() + timedelta(days=30)),
        "notes": "Global Live E2E QA manufacturing quote.",
    })
    driver.get(_absolute(state, "/manufacturer/marketplace/?lang=en"))
    _wait(driver).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    _shot(driver, SCREENSHOTS[9])
    state.results["manufacturer_quote"] = "PASS"
    return int(quote["id"])


def _designer_select_and_assign(state: LiveState, driver, quote_id: int) -> None:
    _login(state, driver, "designer")
    quotes = _api(state, driver, "GET", f"/api/v1/rfqs/{state.rfq_id}/quotes/")
    assert any(int(q["id"]) == quote_id and q["status"] == "submitted" for q in quotes)
    selection = _api(state, driver, "POST", f"/api/v1/manufacturer-quotes/{quote_id}/select/", {})
    state.selection_id = int(selection["id"])
    assigned = _api(state, driver, "POST", f"/api/v1/production-jobs/{state.job_id}/assign/", {"selection_id": state.selection_id})
    assert int(assigned["manufacturer_id"]) == state.manufacturer_org_id and assigned["status"] == "queued"
    _api_expect_denied(state, driver, "POST", f"/api/v1/production-jobs/{state.job_id}/start/", {})
    state.results["quote_selection_and_assignment"] = "PASS"


def _manufacturer_production_and_ship(state: LiveState, driver) -> None:
    _login(state, driver, "manufacturer")
    started = _api(state, driver, "POST", f"/api/v1/production-jobs/{state.job_id}/start/", {})
    assert started["status"] == "in_production"
    for milestone in started["milestones"]:
        _api(state, driver, "POST", f"/api/v1/production-milestones/{milestone['id']}/", {"status": "completed", "notes": "Global Live E2E QA completed milestone."})
    pending = _api(state, driver, "POST", f"/api/v1/production-jobs/{state.job_id}/request-qc/", {})
    assert pending["status"] == "qc_pending"
    qc = _api(state, driver, "POST", f"/api/v1/production-jobs/{state.job_id}/qc/", {"decision": "passed", "checklist": {"global_live_e2e": True}, "notes": "QA inspection passed."})
    assert qc["decision"] == "passed"
    packed = _api(state, driver, "POST", f"/api/v1/fulfillment/{state.fulfillment_id}/pack/", {})
    assert packed["status"] == "packed"

    driver.get(_absolute(state, "/manufacturer/production/?lang=en"))
    _wait(driver).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    _shot(driver, SCREENSHOTS[10])

    tracking = f"FABINZI-QA-{int(time.time())}"
    shipped = _api(state, driver, "POST", f"/api/v1/fulfillment/{state.fulfillment_id}/ship/", {
        "carrier": "FABINZI QA Carrier",
        "tracking_number": tracking,
        "tracking_url": "https://example.invalid/fabinzi-qa-tracking",
    })
    assert shipped["status"] == "shipped" and shipped["tracking_number"] == tracking
    driver.get(_absolute(state, "/manufacturer/production/?lang=en"))
    _wait(driver).until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), tracking))
    _shot(driver, SCREENSHOTS[11])
    state.results["production_qc_pack_ship"] = "PASS"


def _customer_verify_shipment(state: LiveState, driver) -> None:
    _login(state, driver, "customer")
    operations = _api(state, driver, "GET", f"/api/v1/orders/{state.selected_order_id}/operations/")
    assert operations["fulfillment"]["status"] == "shipped"
    assert operations["fulfillment"]["tracking_number"].startswith("FABINZI-QA-")
    notifications = _api(state, driver, "GET", "/api/v1/notifications/")
    serialized = json.dumps(notifications, ensure_ascii=False)
    assert "shipped" in serialized.lower() or "تم شحن" in serialized
    state.results["customer_shipment_visibility"] = "PASS"
    state.results["in_app_notifications"] = "PASS"


def _manufacturer_deliver_and_finance(state: LiveState, driver) -> None:
    _login(state, driver, "manufacturer")
    delivered = _api(state, driver, "POST", f"/api/v1/fulfillment/{state.fulfillment_id}/deliver/", {})
    assert delivered["status"] == "delivered"
    finance = _api(state, driver, "GET", f"/api/v1/finance/{state.manufacturer_org_id}/")
    assert isinstance(finance, dict)
    state.results["manufacturer_finance_real_state"] = "PASS"


def _private_media_session_status(state: LiveState, cookie_role: str, url: str) -> int:
    session = requests.Session()
    for key, value in state.cookies[cookie_role].items():
        session.cookies.set(key, value)
    response = session.get(url, timeout=30, allow_redirects=False)
    return response.status_code


def _private_media_security(state: LiveState, driver) -> None:
    if not state.private_media_url:
        _fail("Private Studio upload did not expose an application-authorized private media URL for boundary testing.")
    parsed = urlparse(state.private_media_url)
    if parsed.netloc and parsed.netloc != urlparse(state.base_url).netloc:
        _fail("Private media leaked a direct external/storage URL instead of an application authorization URL.")
    private_url = state.private_media_url if parsed.netloc else _absolute(state, state.private_media_url)
    anonymous = requests.get(private_url, timeout=30, allow_redirects=False)
    assert anonymous.status_code in {302, 401, 403, 404}
    assert _private_media_session_status(state, "customer", private_url) in {200, 302}
    for role in ("designer", "manufacturer"):
        assert _private_media_session_status(state, role, private_url) in {401, 403, 404}
    state.results["private_media_isolation"] = "PASS"


def _maneg_live(state: LiveState, driver) -> None:
    _login(state, driver, "admin")
    _set_preferences(state, driver, "en", "light")
    driver.get(_absolute(state, "/Maneg/?lang=en"))
    _wait(driver).until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "Control Center"))
    assert "Django administration" not in driver.find_element(By.TAG_NAME, "body").text
    _shot(driver, SCREENSHOTS[12])

    driver.get(_absolute(state, "/Maneg/orders/?lang=en"))
    _wait(driver).until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), state.purchase_number))
    text = driver.find_element(By.TAG_NAME, "body").text
    assert "CustomerPurchase" in text and "CustomerOrder" in text
    _shot(driver, SCREENSHOTS[13])

    driver.get(_absolute(state, "/Maneg/audit/?lang=en"))
    _wait(driver).until(EC.presence_of_element_located((By.CSS_SELECTOR, ".audit-card")))
    audit_text = driver.find_element(By.TAG_NAME, "body").text
    for raw in ("production_job.", "fulfillment.", "manufacturer_marketplace.", "checkout."):
        assert raw not in audit_text
    _shot(driver, SCREENSHOTS[14])

    driver.get(_absolute(state, "/Maneg/integrations/?lang=en"))
    _wait(driver).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    integration_text = driver.find_element(By.TAG_NAME, "body").text
    state.integration_snapshot = integration_text[:5000]
    assert "api_key" not in driver.page_source.lower()
    state.results["maneg_operational_visibility"] = "PASS"
    state.results["audit_humanized_canonical_chain_visible"] = "PASS"


def _mobile_evidence(state: LiveState, driver, role: str, path: str, screenshot: str) -> None:
    _login(state, driver, role)
    _set_preferences(state, driver, "ar", "dark")
    driver.set_window_size(390, 844)
    driver.get(_absolute(state, path + ("&" if "?" in path else "?") + "lang=ar"))
    _wait(driver).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    html = driver.find_element(By.TAG_NAME, "html")
    assert html.get_attribute("dir") == "rtl"
    assert html.get_attribute("data-theme") == "dark"
    _shot(driver, screenshot)


def _final_customer_state(state: LiveState, driver) -> None:
    _login(state, driver, "customer")
    _set_preferences(state, driver, "en", "light")
    driver.set_window_size(1440, 1050)
    driver.get(_absolute(state, f"/purchases/{state.purchase_id}/?lang=en"))
    _wait(driver).until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "Delivered"))
    _shot(driver, SCREENSHOTS[19])
    purchase = _api(state, driver, "GET", f"/api/v1/purchases/{state.purchase_id}/")
    assert len(purchase["items"]) == 3
    selected = _api(state, driver, "GET", f"/api/v1/orders/{state.selected_order_id}/operations/")
    assert selected["production"]["status"] == "ready"
    assert selected["fulfillment"]["status"] == "delivered"
    state.results["full_cross_role_lifecycle"] = "PASS"
    state.results["data_integrity_visible_state"] = "PASS"


def _write_summary(state: LiveState) -> None:
    inventory = sorted(path.name for path in ARTIFACT_DIR.glob("*.png"))
    missing = [name for name in SCREENSHOTS if name not in inventory]
    extras = [name for name in inventory if name not in SCREENSHOTS]
    if missing or extras:
        _fail(f"Live screenshot inventory mismatch. Missing={missing}, extras={extras}")
    summary = {
        "base_url": state.base_url,
        "expected_sha": state.expected_sha,
        "expected_branch": state.expected_branch,
        "deployment": state.deployment,
        "purchase_id": state.purchase_id,
        "purchase_number": state.purchase_number,
        "child_order_ids": state.child_order_ids,
        "selected_order_id": state.selected_order_id,
        "job_id": state.job_id,
        "fulfillment_id": state.fulfillment_id,
        "rfq_id": state.rfq_id,
        "selection_id": state.selection_id,
        "results": state.results,
        "screenshots": SCREENSHOTS,
        "integration_presentation_excerpt": state.integration_snapshot,
    }
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")


def run() -> int:
    state = _guard_environment()
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    for path in ARTIFACT_DIR.glob("*.png"):
        path.unlink()
    _preflight(state)

    driver = _chrome()
    try:
        driver.get(_absolute(state, "/?lang=en")); _wait(driver).until(EC.presence_of_element_located((By.TAG_NAME, "body"))); _shot(driver, SCREENSHOTS[0])
        driver.get(_absolute(state, "/store/?lang=en")); _wait(driver).until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "FABINZI Demo Studio")); _shot(driver, SCREENSHOTS[1])
        driver.get(_absolute(state, "/artwork/?lang=en")); _wait(driver).until(EC.presence_of_element_located((By.TAG_NAME, "body"))); _shot(driver, SCREENSHOTS[2])

        _customer_purchase(state, driver)
        _designer_create_rfq(state, driver)
        quote_id = _manufacturer_quote(state, driver)
        _designer_select_and_assign(state, driver, quote_id)
        _manufacturer_production_and_ship(state, driver)
        _customer_verify_shipment(state, driver)
        _manufacturer_deliver_and_finance(state, driver)

        # Ensure we have browser-derived sessions for all supply-side roles before
        # the private-media boundary test.
        _login(state, driver, "designer")
        _login(state, driver, "manufacturer")
        _private_media_security(state, driver)
        _maneg_live(state, driver)

        _mobile_evidence(state, driver, "customer", "/purchases/", SCREENSHOTS[15])
        _mobile_evidence(state, driver, "designer", "/designer/", SCREENSHOTS[16])
        _mobile_evidence(state, driver, "manufacturer", "/manufacturer/", SCREENSHOTS[17])
        _mobile_evidence(state, driver, "admin", "/Maneg/", SCREENSHOTS[18])
        _final_customer_state(state, driver)

        state.results["en_ltr_light"] = "PASS"
        state.results["ar_rtl_dark"] = "PASS"
        state.results["desktop_mobile"] = "PASS"
        _write_summary(state)
        print(json.dumps({"status": "PASS", "sha": state.expected_sha, "screenshots": len(SCREENSHOTS), "results": state.results}, ensure_ascii=False))
        return 0
    finally:
        driver.quit()


if __name__ == "__main__":
    try:
        raise SystemExit(run())
    except Exception as exc:
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        (ARTIFACT_DIR / "failure.txt").write_text(f"{type(exc).__name__}: {exc}\n", encoding="utf-8")
        print(f"GLOBAL LIVE E2E FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
