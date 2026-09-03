import json
import re
from importlib import metadata
from pathlib import Path

import pytest
from django.conf import settings
from django.urls import reverse
from packaging.utils import canonicalize_name

from config.release import (
    APP_VERSION,
    PRODUCTION_LAUNCH_GATE_CI,
    PRODUCTION_LAUNCH_GATE_RUN_ID,
    PRODUCTION_LAUNCH_GATE_SHA,
    RELEASE_INTEGRATION_BASE_SHA,
    RELEASE_LABEL,
    RELEASE_PYTHON_VERSION,
)


ROOT = Path(settings.BASE_DIR)


def _manifest():
    return json.loads((ROOT / "release-manifest.json").read_text())


def _constraints():
    pins = {}
    for raw in (ROOT / "constraints-release.txt").read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name, version = line.split("==", 1)
        pins[canonicalize_name(name)] = version
    return pins


def test_semantic_release_identity_has_one_authoritative_source():
    assert APP_VERSION == "1.0.0"
    assert RELEASE_LABEL == "FABINZI WEB v1.0"
    assert RELEASE_PYTHON_VERSION == "3.12.14"
    assert RELEASE_INTEGRATION_BASE_SHA == "802dc0f091287f778d4e623caa375a32c67f97dc"
    assert PRODUCTION_LAUNCH_GATE_SHA == "b05b2b0f3bed174aaf867bff9d10ef0b7cb3fbaa"
    assert PRODUCTION_LAUNCH_GATE_CI == 342
    assert PRODUCTION_LAUNCH_GATE_RUN_ID == 33281214335
    assert (ROOT / ".python-version").read_text().strip() == RELEASE_PYTHON_VERSION

    docker = (ROOT / "Dockerfile").read_text()
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()
    assert "FROM python:3.12.14-slim" in docker
    assert 'python-version: "3.12.14"' in workflow
    assert "requirements.txt -c constraints-release.txt" in docker
    assert "requirements.txt -c constraints-release.txt" in workflow


def test_machine_release_manifest_is_consistent_and_not_self_referential():
    manifest = _manifest()
    assert manifest["version"] == APP_VERSION
    assert manifest["release_label"] == RELEASE_LABEL
    assert manifest["integration_base_sha"] == RELEASE_INTEGRATION_BASE_SHA
    assert manifest["runtime"]["python"] == RELEASE_PYTHON_VERSION
    assert manifest["production_launch_gate"]["accepted_sha"] == PRODUCTION_LAUNCH_GATE_SHA
    assert manifest["production_launch_gate"]["ci_number"] == PRODUCTION_LAUNCH_GATE_CI
    assert manifest["production_launch_gate"]["run_id"] == PRODUCTION_LAUNCH_GATE_RUN_ID
    assert manifest["candidate_identity"]["policy"] == "git_commit_containing_this_manifest"
    assert manifest["candidate_identity"]["embedded_sha"] is None
    assert manifest["deferred_live_e2e"]["status"] == "UNRESOLVED"


def test_exact_dependency_constraints_match_installed_release_environment():
    pins = _constraints()
    assert len(pins) >= 50
    for name, expected in pins.items():
        assert metadata.version(name) == expected, f"{name} did not match release constraint"

    requirements = (ROOT / "requirements.txt").read_text().splitlines()
    for raw in requirements:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        top_level_name = re.split(r"[<>=!~\[]", line, maxsplit=1)[0]
        assert canonicalize_name(top_level_name) in pins


def test_web_v1_release_manifest_migration_baseline_remains_present():
    manifest_migrations = _manifest()["local_migrations"]
    assert len(manifest_migrations) == len(set(manifest_migrations))
    for relative in manifest_migrations:
        path = ROOT / relative
        assert path.is_file(), relative
        assert path.match("apps/*/migrations/[0-9]*.py"), relative


def test_release_docs_and_known_limitations_are_explicit():
    required_docs = [
        "RELEASE_MANIFEST.md",
        "CHANGELOG.md",
        "docs/WEB_V1_LIMITATIONS.md",
        "docs/WEB_V1_ROUTE_INVENTORY.md",
        "docs/WEB_V1_CAPABILITY_INVENTORY.md",
        "docs/WEB_V1_MIGRATION_BASELINE.md",
        "docs/WEB_V1_CONFIGURATION_CONTRACT.md",
        "docs/WEB_V1_DEPLOYMENT_ROLLBACK.md",
        "docs/WEB_V1_BUILD_REPRODUCIBILITY.md",
        "docs/WEB_V1_API_V1_INVENTORY.md",
    ]
    for relative in required_docs:
        assert (ROOT / relative).is_file(), relative

    limitations = (ROOT / "docs/WEB_V1_LIMITATIONS.md").read_text().lower()
    for phrase in (
        "password reset",
        "email verification/account activation",
        "legal review",
        "support email/phone/address",
        "amazon s3 account connectivity",
        "production health",
        "restore drill",
        "deferred_live_e2e.md",
    ):
        assert phrase in limitations

    deferred = (ROOT / "docs/DEFERRED_LIVE_E2E.md").read_text()
    assert "UNRESOLVED" in deferred
    assert "- [ ] actual remote Chrome Global Live E2E execution" in deferred
    assert "- [ ] manual review of all 20 live screenshots" in deferred


def test_route_and_capability_inventories_preserve_architecture_locks():
    route_text = (ROOT / "docs/WEB_V1_ROUTE_INVENTORY.md").read_text()
    capability_text = (ROOT / "docs/WEB_V1_CAPABILITY_INVENTORY.md").read_text()
    for route in ("/cart/", "/studio/", "/designer/", "/manufacturer/", "/Maneg/", "/api/v1/"):
        assert route in route_text
    assert "production partner" in capability_text
    assert "canonical `FulfillmentRecord`" in capability_text
    assert "one parent `customerpurchase`" in capability_text.lower()


@pytest.mark.django_db
def test_health_exposes_only_safe_release_traceability(client, monkeypatch):
    monkeypatch.setenv("RENDER_GIT_BRANCH", "work/web-v1-release-preparation")
    monkeypatch.setenv("RENDER_GIT_COMMIT", "b" * 40)
    monkeypatch.setenv("RENDER_SERVICE_NAME", "fabinzi-release-check")
    monkeypatch.setenv("INTEGRATION_ENCRYPTION_KEY", "do-not-leak")

    response = client.get(reverse("healthz"))
    payload = response.json()
    assert payload["version"] == APP_VERSION
    assert payload["deployment"] == {
        "branch": "work/web-v1-release-preparation",
        "commit": "b" * 40,
        "service": "fabinzi-release-check",
    }
    body = response.content.decode()
    assert "do-not-leak" not in body

    ready = client.get(reverse("readyz"))
    assert ready.json() == {"status": "ready", "database": "ok"}


def test_ci_v2_engineering_baseline_uses_narrow_locks_and_real_regression():
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()
    assert "github.event.pull_request.head.sha || github.sha" in workflow
    assert "branches: [main, feature/v2]" in workflow

    assert "Verify release static and migration freeze" not in workflow
    assert 'git diff --exit-code "$RELEASE_INTEGRATION_BASE_SHA"...HEAD -- static/' not in workflow
    assert "Verify frozen Customer API v1 contract" in workflow
    assert "CUSTOMER_API_V1_FREEZE_BASE_SHA" in workflow
    for relative in (
        "contracts/customer-api-v1-manifest.json",
        "contracts/customer-api-v1-fixtures.json",
        "docs/api/fabinzi-customer-api-v1.openapi.json",
        "docs/API_V1_CUSTOMER_CONTRACT.md",
        "docs/FLUTTER_API_HANDOFF.md",
        "docs/CUSTOMER_API_V1_ENDPOINT_INVENTORY.md",
        "docs/API_V1_CUSTOMER_REPRODUCIBILITY.md",
    ):
        assert relative in workflow

    assert "Validate Golden reference integrity metadata" in workflow
    assert "golden-reference-v1-integrity.json" in workflow
    assert "--metadata-only" in workflow
    assert "Golden package bytes NOT VERIFIED" not in workflow

    assert "python manage.py makemigrations --check --dry-run" in workflow
    assert "Verify fresh PostgreSQL migration start" in workflow
    assert "python manage.py migrate --noinput" in workflow
    assert "python manage.py check" in workflow
    assert "python manage.py collectstatic --noinput" in workflow
    assert "python manage.py check --deploy" in workflow
    assert "pytest -q" in workflow
    assert "web-v1-release-contract" in workflow
    assert "customer-api-v1-contract" in workflow
    assert "release-evidence.json" in workflow
