from __future__ import annotations

import hashlib
import hmac
import secrets


def verify_webhook_secret(expected: str, received: str | None) -> bool:
    if not expected or not received:
        return False
    return hmac.compare_digest(expected.encode(), received.encode())


def new_idempotency_key(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(18)}"


def stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def constant_time_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
