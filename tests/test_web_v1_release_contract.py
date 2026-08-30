import json
import re
from importlib import metadata
from pathlib import Path

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


def test_local_migration_graph_matches_release_manifest_exactly():
    actual = sorted(
        path.relative_to(ROOT).as_posix()
        for path in ROOT.glob("apps/*/migrations/[0-9]*.py")
    )
    assert actual == sorted(_manifest()["local_migrations"])


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
        "provider health",
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
    assert "one Parent `CustomerPurchase`" in capability_text


def test_health_exposes_only_safe_release_traceability(client, monkeypatch):
    monkeypatch.setenv("RENDER_GIT_BRANCH", "work/web-v1-release-preparation")
    monkeypatch.setenv("RENDER_GIT_COMMIT", "b" * 40)
    monkeypatch.setenv("RENDER_SERVICE_NAME", "fabinzi-release-check")
    monkeypatch.setenv("DATABASE_URL", "postgresql://secret-user:secret-pass@secret-host/db")
    monkeypatch.setenv("REDIS_URL", "redis://:secret@secret-host:6379/0")
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
    for secret in ("secret-user", "secret-pass", "secret-host", "do-not-leak"):
        assert secret not in body

    ready = client.get(reverse("readyz"))
    assert ready.json() == {"status": "ready", "database": "ok"}


def test_ci_release_contract_checks_exact_head_static_and_migration_freeze():
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()
    assert "github.event.pull_request.head.sha || github.sha" in workflow
    assert "Verify release static and migration freeze" in workflow
    assert "git diff --exit-code \"$RELEASE_INTEGRATION_BASE_SHA\"...HEAD -- static/" in workflow
    assert "apps/*/migrations/*.py" in workflow
    assert "web-v1-release-contract" in workflow
    assert "release-evidence.json" in workflow
