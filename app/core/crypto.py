from __future__ import annotations

import hashlib
import hmac
import re
from cryptography.fernet import Fernet, InvalidToken


def _fernet(key: str) -> Fernet:
    try:
        return Fernet(key.encode("ascii"))
    except Exception as exc:
        raise ValueError("PHONE_ENCRYPTION_KEY Fernet formatida bo‘lishi kerak.") from exc


def normalize_resource(value: str) -> str:
    value = " ".join((value or "").strip().split())
    if not value or len(value) > 256:
        raise ValueError("Resurs qiymati 1–256 belgidan iborat bo‘lishi kerak.")
    return value


def encrypt_resource(value: str, key: str) -> tuple[str, str, str]:
    normalized = normalize_resource(value)
    ciphertext = _fernet(key).encrypt(normalized.encode("utf-8")).decode("ascii")
    fingerprint_key = hashlib.sha256(key.encode("ascii")).digest()
    fingerprint = hmac.new(fingerprint_key, normalized.casefold().encode("utf-8"), hashlib.sha256).hexdigest()
    digits = re.sub(r"\D", "", normalized)
    if len(digits) >= 4:
        mask = f"••••{digits[-4:]}"
    else:
        mask = normalized[:2] + "•••" if len(normalized) > 2 else "•••"
    return ciphertext, fingerprint, mask


def decrypt_resource(ciphertext: str, key: str) -> str:
    try:
        return _fernet(key).decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeError) as exc:
        raise ValueError("Resursni ochib bo‘lmadi: encryption key mos emas.") from exc


def encrypt_sensitive_text(value: str, key: str) -> str:
    """Encrypt an arbitrary message without normalizing its whitespace."""
    if not isinstance(value, str) or not value:
        raise ValueError("Sensitive message bo‘sh bo‘lishi mumkin emas.")
    return _fernet(key).encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_sensitive_text(ciphertext: str, key: str) -> str:
    try:
        return _fernet(key).decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeError) as exc:
        raise ValueError("Shifrlangan xabarni ochib bo‘lmadi: encryption key mos emas.") from exc
