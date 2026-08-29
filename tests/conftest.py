import base64
import sys

import pytest


VALID_PNG_2X2 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAFUlEQVR4nGP8////fwYGBgYmBigAAD34BADaOyqcAAAAAElFTkSuQmCC"
)


@pytest.fixture(autouse=True)
def _valid_png_upload_bytes(monkeypatch):
    """Keep image-upload fixtures genuinely decodable by Pillow.

    Several browser/security test modules expose a PNG_1X1 module constant so
    they can create real multipart uploads without checking binary fixtures
    into the repository. Patch only those test constants after collection.
    """
    for module in list(sys.modules.values()):
        if module is not None and hasattr(module, "PNG_1X1"):
            monkeypatch.setattr(module, "PNG_1X1", VALID_PNG_2X2)
