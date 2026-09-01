import io
import sys

import pytest
from PIL import Image


def _png_bytes():
    buffer = io.BytesIO()
    Image.new("RGBA", (4, 4), (36, 44, 55, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


VALID_PNG = _png_bytes()


@pytest.fixture(autouse=True)
def _valid_png_upload_bytes(monkeypatch):
    """Keep image-upload fixtures genuinely decodable by the installed Pillow.

    The security/browser modules expose a PNG_1X1 constant only as a compact
    source for real multipart upload tests. Replace those bytes at runtime with
    a PNG produced by the same Pillow installation used by the application.
    """
    for module in list(sys.modules.values()):
        if module is not None and hasattr(module, "PNG_1X1"):
            monkeypatch.setattr(module, "PNG_1X1", VALID_PNG)


def pytest_collection_modifyitems(items):
    """Preserve migration-seeded V2-3 policy rows between concurrency tests.

    pytest-django transaction=True tests flush the database after each test.
    The V2-3 concurrency checks intentionally use real independent PostgreSQL
    connections, so request serialized rollback for those focused tests. This
    restores the migration-seeded reference rows without changing application
    behavior or weakening any assertion.
    """
    target_file = "test_v2_subscriptions_entitlements_team.py"
    for item in items:
        if not str(getattr(item, "fspath", "")).endswith(target_file):
            continue
        for marker in item.iter_markers(name="django_db"):
            if marker.kwargs.get("transaction"):
                marker.kwargs["serialized_rollback"] = True
