from dataclasses import dataclass
import boto3
import requests
from botocore.config import Config

@dataclass(frozen=True)
class TestResult:
    ok: bool
    message: str

def _safe_request(method, url, **kwargs):
    return requests.request(method, url, timeout=10, **kwargs)

def test_connection(obj) -> TestResult:
    cfg = obj.config or {}
    sec = obj.get_secrets()
    p = obj.provider
    try:
        if p == "cod":
            return TestResult(True, "COD is an internal payment method and requires no external connection.")
        if p == "stripe":
            r = _safe_request("GET", "https://api.stripe.com/v1/account", headers={"Authorization": f"Bearer {sec.get('secret_key','')}"})
            return TestResult(r.ok, "Stripe authentication succeeded." if r.ok else f"Stripe rejected the configuration (HTTP {r.status_code}).")
        if p == "paymob":
            base = cfg.get("api_base", "https://accept.paymob.com")
            r = _safe_request("POST", f"{base.rstrip('/')}/api/auth/tokens", json={"api_key": sec.get("api_key", "")})
            return TestResult(r.ok, "Paymob authentication succeeded." if r.ok else f"Paymob rejected the configuration (HTTP {r.status_code}).")
        if p == "mailgun":
            base = cfg.get("api_base", "https://api.mailgun.net")
            domain = cfg.get("domain", "")
            r = _safe_request("GET", f"{base.rstrip('/')}/v3/domains/{domain}", auth=("api", sec.get("api_key", "")))
            return TestResult(r.ok, "Mailgun authentication succeeded." if r.ok else f"Mailgun rejected the configuration (HTTP {r.status_code}).")
        if p == "twilio":
            sid = cfg.get("account_sid", "")
            r = _safe_request("GET", f"https://api.twilio.com/2010-04-01/Accounts/{sid}.json", auth=(sid, sec.get("auth_token", "")))
            return TestResult(r.ok, "Twilio authentication succeeded." if r.ok else f"Twilio rejected the configuration (HTTP {r.status_code}).")
        if p == "amazon_s3":
            client = boto3.client("s3", aws_access_key_id=sec.get("access_key_id"), aws_secret_access_key=sec.get("secret_access_key"), region_name=cfg.get("region"), endpoint_url=cfg.get("endpoint_url") or None, config=Config(connect_timeout=5, read_timeout=10, retries={"max_attempts": 1}))
            client.head_bucket(Bucket=cfg.get("bucket", ""))
            return TestResult(True, "S3 authentication and bucket access succeeded.")
        if p == "cloudflare_images":
            account = cfg.get("account_id", "")
            r = _safe_request("GET", f"https://api.cloudflare.com/client/v4/accounts/{account}/images/v1", params={"per_page": 1}, headers={"Authorization": f"Bearer {sec.get('api_token','')}"})
            return TestResult(r.ok, "Cloudflare Images authentication succeeded." if r.ok else f"Cloudflare rejected the configuration (HTTP {r.status_code}).")
        if p == "sentry":
            return TestResult(bool(sec.get("dsn") or cfg.get("dsn")), "Sentry configuration is present; runtime event delivery remains controlled by deployment configuration.")
        return TestResult(False, "Unsupported provider.")
    except Exception as exc:
        return TestResult(False, f"Connection failed: {exc.__class__.__name__}")
