from __future__ import annotations

import base64
import json
import os
import secrets
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


ENCRYPTED_PREFIX = "enc:v1:"


def get_encryption_key_material() -> bytes | None:
    value = (
        os.getenv("CONFIG_ENCRYPTION_KEY", "").strip()
        or os.getenv("TEMU_WORKBENCH_CONFIG_ENCRYPTION_KEY", "").strip()
    )
    if not value:
        return None
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except Exception:
        decoded = value.encode("utf-8")
    if len(decoded) == 32:
        return decoded
    if len(value.encode("utf-8")) == 32:
        return value.encode("utf-8")
    raise ValueError("CONFIG_ENCRYPTION_KEY must decode to 32 bytes for AES-256-GCM")


def encryption_enabled() -> bool:
    return get_encryption_key_material() is not None


def generate_encryption_key() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii").rstrip("=")


def encrypt_text(value: str) -> str:
    key = get_encryption_key_material()
    if key is None or value == "":
        return value
    nonce = secrets.token_bytes(12)
    encrypted = AESGCM(key).encrypt(nonce, value.encode("utf-8"), None)
    payload = {
        "alg": "AES-256-GCM",
        "nonce": base64.urlsafe_b64encode(nonce).decode("ascii").rstrip("="),
        "ciphertext": base64.urlsafe_b64encode(encrypted).decode("ascii").rstrip("="),
    }
    return ENCRYPTED_PREFIX + base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).decode("ascii").rstrip("=")


def is_encrypted_text(value: str) -> bool:
    return str(value or "").startswith(ENCRYPTED_PREFIX)


def decrypt_text(value: str) -> str:
    clean_value = str(value or "")
    if not is_encrypted_text(clean_value):
        return clean_value
    key = get_encryption_key_material()
    if key is None:
        raise ValueError("CONFIG_ENCRYPTION_KEY is required to decrypt stored secrets")
    raw = clean_value.removeprefix(ENCRYPTED_PREFIX)
    payload = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8"))
    nonce_text = str(payload.get("nonce") or "")
    ciphertext_text = str(payload.get("ciphertext") or "")
    nonce = base64.urlsafe_b64decode(nonce_text + "=" * (-len(nonce_text) % 4))
    ciphertext = base64.urlsafe_b64decode(ciphertext_text + "=" * (-len(ciphertext_text) % 4))
    return AESGCM(key).decrypt(nonce, ciphertext, None).decode("utf-8")


def encrypt_secret_value(value: str, *, enabled: bool) -> str:
    return encrypt_text(value) if enabled else value


def decrypt_secret_value(value: str) -> str:
    return decrypt_text(value) if is_encrypted_text(value) else str(value or "")


def mask_secret(value: str) -> str:
    clean_value = str(value or "")
    if not clean_value:
        return ""
    if is_encrypted_text(clean_value):
        try:
            clean_value = decrypt_text(clean_value)
        except Exception:
            return "****"
    if len(clean_value) <= 8:
        return "****"
    return f"{clean_value[:4]}****{clean_value[-4:]}"


def decrypt_mapping_values(items: dict[str, Any]) -> dict[str, Any]:
    return {
        key: decrypt_secret_value(value) if isinstance(value, str) and is_encrypted_text(value) else value
        for key, value in items.items()
    }
