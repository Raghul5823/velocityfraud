"""SHA-256-based PII tokenizer with a per-tenant salt.

POC implementation: the salt is loaded from an env var. In production this
would come from HashiCorp Vault (see BastionGuard proposal §5).
"""
from __future__ import annotations

import hashlib
import os


_DEFAULT_SALT = "velocityfraud-poc-salt-do-not-use-in-prod"


def _salt() -> str:
    return os.getenv("VF_TOKEN_SALT", _DEFAULT_SALT)


def tokenize(value: str | int | float | None) -> str:
    """Deterministic SHA-256 hash of value+salt. Returns 16-hex-char prefix."""
    if value is None:
        return "null"
    payload = f"{value}|{_salt()}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]
