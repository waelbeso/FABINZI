import json
import re
from pathlib import Path

from rest_framework_simplejwt.authentication import JWTAuthentication

from api.customer_urls import urlpatterns

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "contracts/customer-api-v1-manifest.json"
OPENAPI = ROOT / "docs/api/fabinzi-customer-api-v1.openapi.json"
FIXTURES = ROOT / "contracts/customer-api-v1-fixtures.json"
HTTP_METHODS = ("get", "post", "patch", "delete")


def _route_path(pattern):
    route = pattern.pattern._route
    route = re.sub(r"<(?:(?:int|slug|uuid|str):)?([^>]+)>", r"{\1}", route)
    return "/api/v1/customer/" + route


def _actual_operations():
    rows = []
    for pattern in urlpatterns:
        view = pattern.callback.view_class
        auth_classes = list(getattr(view, "authentication_classes", []))
        auth = "public" if not auth_classes else "jwt"
        if auth == "jwt":
            assert auth_classes == [JWTAuthentication], f"Unexpected Customer auth classes on {view.__name__}: {auth_classes}"
        for method in HTTP_METHODS:
            if hasattr(view, method):
                rows.append({"method": method.upper(), "path": _route_path(pattern), "auth": auth})
    return rows


def _openapi_operations(spec):
    rows = []
    global_security = spec.get("security")
    for path, item in spec["paths"].items():
        for method in HTTP_METHODS:
            if method not in item:
                continue
            operation = item[method]
            security = operation.get("security", global_security)
            auth = "public" if security == [] else "jwt"
            rows.append({"method": method.upper(), "path": path, "auth": auth})
    return rows


def test_manifest_openapi_and_django_routes_are_exactly_synchronized():
    manifest = json.loads(MANIFEST.read_text())
    spec = json.loads(OPENAPI.read_text())
    expected = sorted(manifest["operations"], key=lambda row: (row["path"], row["method"]))
    actual = sorted(_actual_operations(), key=lambda row: (row["path"], row["method"]))
    machine = sorted(_openapi_operations(spec), key=lambda row: (row["path"], row["method"]))

    assert manifest["operation_count"] == 41
    assert len(expected) == len(actual) == len(machine) == 41
    assert actual == expected
    assert machine == expected
    assert spec["openapi"] == "3.1.0"
    assert spec["info"]["title"] == manifest["contract"]
    assert spec["info"]["version"] == manifest["backend"]["app_version"] == "1.0.0"


def test_openapi_auth_pagination_upload_errors_and_idempotency_are_frozen():
    spec = json.loads(OPENAPI.read_text())
    manifest = json.loads(MANIFEST.read_text())

    security = spec["components"]["securitySchemes"]["bearerAuth"]
    assert security["type"] == "http" and security["scheme"] == "bearer" and security["bearerFormat"] == "JWT"
    assert manifest["auth"]["access_seconds"] == 900
    assert manifest["auth"]["refresh_seconds"] == 2592000
    assert manifest["auth"]["rotate_refresh"] is True
    assert manifest["auth"]["blacklist_after_rotation"] is True

    page = spec["components"]["schemas"]["Page"]
    assert page["required"] == ["count", "next", "previous", "results"]
    assert spec["components"]["parameters"]["PageSize"]["schema"]["maximum"] == 50
    assert manifest["pagination"]["default_page_size"] == 20

    upload = spec["paths"]["/api/v1/customer/studio-projects/{project_id}/uploads/"]["post"]
    assert set(upload["requestBody"]["content"]) == {"multipart/form-data"}
    assert {"201", "400", "401", "404", "409", "413", "415", "429", "503"} == set(upload["responses"])
    upload_schema = spec["components"]["schemas"]["PrivateUpload"]
    assert upload_schema["properties"]["size_bytes"]["maximum"] == 10485760
    assert set(upload_schema["properties"]["mime_type"]["enum"]) == {"image/png", "image/jpeg", "image/webp"}

    placement = spec["paths"]["/api/v1/customer/checkouts/{checkout_id}/place/"]["post"]
    header = next(p for p in placement["parameters"] if p.get("name") == "Idempotency-Key")
    assert header["required"] is True
    assert header["schema"] == {"type": "string", "minLength": 8, "maxLength": 80, "pattern": "^[A-Za-z0-9._:-]{8,80}$"}
    assert {"200", "201", "400", "401", "404", "409", "429", "503"} == set(placement["responses"])

    money = spec["components"]["schemas"]["Money"]
    assert money["properties"]["amount"]["type"] == "string"
    assert money["properties"]["amount"]["pattern"] == "^-?[0-9]+\\.[0-9]{2}$"

    error = spec["components"]["schemas"]["ErrorEnvelope"]
    assert error["properties"]["error"]["required"] == ["code", "message", "fields", "request_id"]

    advertised_204 = {
        (path, method.upper())
        for path, item in spec["paths"].items()
        for method in HTTP_METHODS
        if method in item and "204" in item[method].get("responses", {})
    }
    assert advertised_204 == {
        ("/api/v1/customer/auth/logout/", "POST"),
        ("/api/v1/customer/studio-projects/{project_id}/elements/{element_id}/", "DELETE"),
        ("/api/v1/customer/cart/items/{item_id}/", "DELETE"),
    }


def test_openapi_has_no_supply_side_or_internal_paths():
    spec = json.loads(OPENAPI.read_text())
    joined = "\n".join(spec["paths"])
    forbidden = ("manufacturer", "rfq", "finance", "settlement", "operations", "production-jobs", "payment-webhooks", "maneg")
    assert all(word not in joined.lower() for word in forbidden)
    assert all(path.startswith("/api/v1/customer/") for path in spec["paths"])


def test_sanitized_contract_fixtures_match_core_types_and_contain_no_secret_or_storage_material():
    fixtures = json.loads(FIXTURES.read_text())
    assert fixtures["metadata"]["synthetic_only"] is True
    assert fixtures["auth"]["login_response"]["access_expires_in"] == 900
    assert fixtures["auth"]["login_response"]["refresh_expires_in"] == 2592000
    assert fixtures["pagination"].keys() == {"count", "next", "previous", "results"}
    assert fixtures["product"]["base_price"] == {"amount": "500.00", "currency": "EGP"}
    assert fixtures["private_upload"]["access_url"].startswith("/api/v1/customer/media/")
    assert fixtures["purchase"]["reference"] == "11111111-1111-4111-8111-111111111111"
    assert fixtures["notification"]["target"] == {"resource": "purchase", "reference": fixtures["purchase"]["reference"]}

    raw = FIXTURES.read_text().lower()
    forbidden = (
        "password123",
        "sk_test_",
        "whsec_",
        "akia",
        "provider_asset_id",
        "studio-private/",
        "secret_key",
        "access_key_id",
        "database_url",
        "redis_url",
    )
    assert all(value not in raw for value in forbidden)
    assert "@example.test" in raw


def test_all_contract_files_declared_by_manifest_exist_and_deferred_live_e2e_stays_unresolved():
    manifest = json.loads(MANIFEST.read_text())
    for path in manifest["contract_files"]:
        assert (ROOT / path).is_file(), path
    deferred = (ROOT / manifest["deferred_live_e2e"]["document"]).read_text()
    assert manifest["deferred_live_e2e"]["status"] == "UNRESOLVED"
    assert "UNRESOLVED" in deferred
