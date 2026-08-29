import base64
import hashlib

from cryptography.fernet import Fernet
from django.conf import settings


def _fernet():
    configured = settings.INTEGRATION_ENCRYPTION_KEY
    if configured:
        candidate = configured.encode()
        try:
            return Fernet(candidate)
        except (ValueError, TypeError):
            # Render and other secret managers commonly generate arbitrary
            # high-entropy strings. Derive a stable Fernet key while preserving
            # compatibility with already-valid Fernet keys.
            candidate = base64.urlsafe_b64encode(hashlib.sha256(candidate).digest())
            return Fernet(candidate)

    fallback = base64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode()).digest())
    return Fernet(fallback)


def encrypt_text(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_text(value: str) -> str:
    return _fernet().decrypt(value.encode()).decode()
