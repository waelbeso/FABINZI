from urllib.parse import urljoin

from django.conf import settings


def absolute_public_url(path: str = "") -> str:
    """Build an absolute public URL from the single configured FABINZI base URL."""
    base = settings.FABINZI_PUBLIC_BASE_URL.rstrip("/") + "/"
    return urljoin(base, str(path or "").lstrip("/"))
