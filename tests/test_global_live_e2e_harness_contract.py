import base64
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django_otp.plugins.otp_totp.models import TOTPDevice

from live_e2e.global_live_e2e import SCREENSHOTS, _guard_environment


EXPECTED_SCREENSHOTS = [
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


def _live_env(monkeypatch, *, base_url="https://fabinzi-qa-web.onrender.com"):
    values = {
        "FABINZI_LIVE_E2E_ENABLED": "true",
        "FABINZI_LIVE_E2E_BASE_URL": base_url,
        "FABINZI_LIVE_E2E_EXPECTED_SHA": "a" * 40,
        "FABINZI_LIVE_E2E_EXPECTED_BRANCH": "work/global-live-e2e-qa",
        "FABINZI_LIVE_E2E_CONFIRM_NON_PRODUCTION": "true",
        "FABINZI_LIVE_E2E_CUSTOMER_PASSWORD": "protected-customer",
        "FABINZI_LIVE_E2E_DESIGNER_PASSWORD": "protected-designer",
        "FABINZI_LIVE_E2E_MANUFACTURER_PASSWORD": "protected-manufacturer",
        "FABINZI_LIVE_E2E_ADMIN_PASSWORD": "protected-admin",
        "FABINZI_LIVE_E2E_ADMIN_TOTP_SECRET": "JBSWY3DPEHPK3PXP",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def test_live_screenshot_inventory_is_exact_and_unique():
    assert SCREENSHOTS == EXPECTED_SCREENSHOTS
    assert len(SCREENSHOTS) == 20
    assert len(set(SCREENSHOTS)) == 20


def test_live_harness_refuses_missing_configuration(monkeypatch):
    for key in list(__import__("os").environ):
        if key.startswith("FABINZI_LIVE_E2E_"):
            monkeypatch.delenv(key, raising=False)
    with pytest.raises(AssertionError, match="Live E2E is not configured"):
        _guard_environment()


@pytest.mark.parametrize("base_url", ["http://fabinzi-qa-web.onrender.com", "https://localhost:8000", "https://127.0.0.1:8000"])
def test_live_harness_refuses_non_https_or_local_targets(monkeypatch, base_url):
    _live_env(monkeypatch, base_url=base_url)
    with pytest.raises(AssertionError):
        _guard_environment()


def test_live_harness_accepts_explicit_https_nonproduction_target(monkeypatch):
    _live_env(monkeypatch)
    state = _guard_environment()
    assert state.base_url == "https://fabinzi-qa-web.onrender.com/"
    assert state.expected_sha == "a" * 40
    assert state.expected_branch == "work/global-live-e2e-qa"


def test_live_workflow_is_manual_only_and_never_defaults_a_target():
    workflow = Path(".github/workflows/global-live-e2e.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "pull_request:" not in workflow
    assert "push:" not in workflow
    assert "base_url:" in workflow
    assert "FABINZI_LIVE_E2E_BASE_URL: ${{ inputs.base_url }}" in workflow
    assert "confirm_non_production" in workflow
    assert "python live_e2e/global_live_e2e.py" in workflow


def test_isolated_render_qa_blueprint_targets_work_branch_and_does_not_autoseed():
    blueprint = Path("render-qa.yaml").read_text(encoding="utf-8")
    assert "branch: work/global-live-e2e-qa" in blueprint
    assert "ENVIRONMENT\n        value: qa" in blueprint
    assert "PRIVATE_MEDIA_STORAGE_MODE\n        value: s3" in blueprint
    assert "FABINZI_DEMO_SEED_ENABLED\n        value: \"true\"" in blueprint
    assert "seed_demo" not in blueprint
    assert "DEMO_ADMIN_TOTP_SECRET" in blueprint


@pytest.mark.django_db
def test_demo_admin_otp_provisioning_is_guarded(settings, monkeypatch):
    settings.FABINZI_DEMO_SEED_ENABLED = False
    monkeypatch.setenv("DEMO_ADMIN_TOTP_SECRET", "JBSWY3DPEHPK3PXP")
    with pytest.raises(CommandError, match="Demo QA provisioning is disabled"):
        call_command("provision_demo_admin_otp")


@pytest.mark.django_db
def test_demo_admin_otp_provisioning_uses_protected_base32_secret_without_printing_it(settings, monkeypatch, capsys):
    settings.FABINZI_DEMO_SEED_ENABLED = True
    secret = "JBSWY3DPEHPK3PXP"
    monkeypatch.setenv("DEMO_ADMIN_TOTP_SECRET", secret)
    User = get_user_model()
    admin = User.objects.create_superuser(
        username="fabinzi_demo_admin",
        email="demo-admin@example.invalid",
        password="protected-test-password",
    )

    call_command("provision_demo_admin_otp")
    device = TOTPDevice.objects.get(user=admin, name="global-live-e2e")
    padding = "=" * ((8 - len(secret) % 8) % 8)
    assert device.confirmed is True
    assert device.key == base64.b32decode(secret + padding).hex()
    output = capsys.readouterr().out
    assert secret not in output
    assert "Secret value was not printed" in output
