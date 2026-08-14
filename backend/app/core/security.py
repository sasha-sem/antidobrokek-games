from __future__ import annotations

import hashlib
import secrets


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_token(token: str, expected_hash: str) -> bool:
    return secrets.compare_digest(hash_token(token), expected_hash)


def verify_secret(candidate: str, expected: str) -> bool:
    return secrets.compare_digest(candidate.encode("utf-8"), expected.encode("utf-8"))
