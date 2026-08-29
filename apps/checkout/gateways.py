import hashlib
import hmac
import json
import time
import requests
from django.core.exceptions import ValidationError
from apps.integrations.models import IntegrationConfig


def get_payment_config(provider):
    try:
        cfg = IntegrationConfig.objects.get(provider=provider)
    except IntegrationConfig.DoesNotExist as exc:
        raise ValidationError("Payment provider is not configured.") from exc
    if not cfg.enabled:
        raise ValidationError("Payment provider is disabled.")
    if provider != IntegrationConfig.Provider.COD and cfg.last_test_status != IntegrationConfig.TestStatus.SUCCESS:
        raise ValidationError("Payment provider must pass Test Connection before use.")
    return cfg


def _payment_context(attempt):
    if attempt.purchase_id:
        return attempt.purchase.number, attempt.purchase.checkout
    if attempt.order_id:
        order = attempt.order
        if order.purchase_id:
            return order.purchase.number, order.purchase.checkout
        return order.number, order.checkout
    raise ValidationError("Payment attempt has no commercial transaction.")


def create_remote_payment(attempt, *, return_url=""):
    cfg = get_payment_config(attempt.provider)
    secrets = cfg.get_secrets()
    timeout = int(cfg.config.get("timeout_seconds", 15))
    public_number, checkout = _payment_context(attempt)
    if attempt.provider == IntegrationConfig.Provider.STRIPE:
        secret = secrets.get("secret_key") or secrets.get("api_key")
        if not secret:
            raise ValidationError("Stripe secret key is missing.")
        response = requests.post("https://api.stripe.com/v1/payment_intents", auth=(secret, ""), data={"amount": int(attempt.amount * 100), "currency": attempt.currency.lower(), "metadata[order_number]": str(public_number), "automatic_payment_methods[enabled]": "true"}, headers={"Idempotency-Key": attempt.idempotency_key}, timeout=timeout)
        response.raise_for_status()
        data = response.json()
        return {"reference": data.get("id", ""), "status": data.get("status", "pending"), "client_secret": data.get("client_secret", "")}
    if attempt.provider == IntegrationConfig.Provider.PAYMOB:
        secret = secrets.get("secret_key") or secrets.get("api_key")
        if not secret:
            raise ValidationError("Paymob secret key is missing.")
        endpoint = cfg.config.get("intent_endpoint", "https://accept.paymob.com/v1/intention/")
        payload = {"amount": int(attempt.amount * 100), "currency": attempt.currency, "payment_methods": cfg.config.get("payment_methods", []), "items": [], "billing_data": {"first_name": "FABINZI", "last_name": "Customer", "email": checkout.shipping_email or "NA", "phone_number": checkout.shipping_phone or "NA"}, "extras": {"order_number": str(public_number)}}
        response = requests.post(endpoint, json=payload, headers={"Authorization": f"Token {secret}", "Idempotency-Key": attempt.idempotency_key}, timeout=timeout)
        response.raise_for_status()
        data = response.json()
        return {"reference": str(data.get("id") or data.get("intention_order_id") or ""), "status": data.get("status", "pending"), "client_secret": data.get("client_secret", ""), "redirect_url": data.get("redirection_url", "")}
    raise ValidationError("Unsupported online payment provider.")


def verify_stripe_signature(raw_body, signature_header, secret, tolerance=300):
    if not signature_header or not secret:
        return False
    parts = dict(part.split("=", 1) for part in signature_header.split(",") if "=" in part)
    try:
        timestamp = int(parts.get("t", "0"))
    except ValueError:
        return False
    if abs(int(time.time()) - timestamp) > tolerance:
        return False
    expected = hmac.new(secret.encode(), f"{timestamp}.".encode() + raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, parts.get("v1", ""))


def verify_paymob_signature(raw_body, signature, secret):
    if not signature or not secret:
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, signature)


def parse_webhook(provider, raw_body):
    payload = json.loads(raw_body.decode("utf-8"))
    if provider == "stripe":
        event_id = str(payload.get("id", ""))
        event_type = payload.get("type", "")
        obj = payload.get("data", {}).get("object", {})
        reference = str(obj.get("id", ""))
        success = event_type == "payment_intent.succeeded"
        failed = event_type in {"payment_intent.payment_failed", "payment_intent.canceled"}
    else:
        obj = payload.get("obj", payload)
        event_id = str(payload.get("id") or obj.get("id") or hashlib.sha256(raw_body).hexdigest())
        reference = str(obj.get("id") or obj.get("order", {}).get("id") or "")
        success = bool(obj.get("success"))
        failed = bool(obj.get("pending") is False and not success)
    return payload, event_id, reference, success, failed
