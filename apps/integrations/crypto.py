import base64
import hashlib
from cryptography.fernet import Fernet
from django.conf import settings

def _fernet():
    configured = settings.INTEGRATION_ENCRYPTION_KEY
    if configured:
        key = configured.encode()
    else:
        key = base64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode()).digest())
    return Fernet(key)

def encrypt_text(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()

def decrypt_text(value: str) -> str:
    return _fernet().decrypt(value.encode()).decode()
