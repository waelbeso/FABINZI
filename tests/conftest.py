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
