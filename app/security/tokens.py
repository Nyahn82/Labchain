from __future__ import annotations

import hashlib
import hmac


def hash_token(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def secure_compare(left: str, right: str) -> bool:
    return hmac.compare_digest(left, right)
