"""AES-256-GCM envelopes; key parsing also works without application settings."""
import base64
import binascii
import secrets

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def decode_key(value: str) -> bytes:
    try:
        raw = base64.b64decode(value, altchars=b'-_', validate=True)
        if len(raw) != 32 or base64.urlsafe_b64encode(raw).decode('ascii') != value:
            raise ValueError()
        return raw
    except (ValueError, binascii.Error, UnicodeError):
        raise ValueError('MFA key must be canonical padded URL-safe base64 encoding of 32 random bytes.') from None


def generate_key() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('ascii')


def encrypt_secret(secret: str, key: bytes, user_id: int) -> tuple[str, bytes]:
    nonce = secrets.token_bytes(12)
    ciphertext = AESGCM(key).encrypt(nonce, secret.encode('ascii'), f'rhu:totp:v1:{user_id}'.encode())
    return base64.b64encode(ciphertext).decode('ascii'), nonce


def decrypt_secret(ciphertext: str, nonce: bytes, key: bytes, user_id: int) -> str:
    try:
        if len(nonce) != 12:
            raise ValueError()
        raw = base64.b64decode(ciphertext, validate=True)
        return AESGCM(key).decrypt(nonce, raw, f'rhu:totp:v1:{user_id}'.encode()).decode('ascii')
    except (InvalidTag, ValueError, UnicodeError, TypeError):
        raise ValueError('MFA secret is unavailable.') from None
