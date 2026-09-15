"""Argon2id password hashing; unknown users still incur a verification cost."""

import secrets

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher(
    time_cost=3, memory_cost=65536, parallelism=4, hash_len=32, salt_len=16,
    type=Type.ID,
)
# Random, process-local timing substitute; never a usable account credential.
_dummy_hash = _hasher.hash(secrets.token_urlsafe(32))


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    candidate = password_hash or _dummy_hash
    try:
        valid = _hasher.verify(candidate, password)
    except InvalidHashError:
        _dummy_verify(password)
        return False
    except VerificationError:
        return False
    return bool(password_hash) and valid


def _dummy_verify(password: str) -> None:
    try:
        _hasher.verify(_dummy_hash, password)
    except VerificationError:
        pass


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)
