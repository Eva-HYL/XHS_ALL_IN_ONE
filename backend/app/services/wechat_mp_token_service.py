from __future__ import annotations

import math
import time

from cryptography.fernet import InvalidToken

from backend.app.core.security import decrypt_text, encrypt_text


TOKEN_EXPIRY_SAFETY_BUFFER_SECONDS = 60


def normalize_token_cache(payload: dict) -> dict:
    """Store token payloads with a buffered absolute expiry timestamp."""
    expires_in = payload.get("expires_in", 0)
    if isinstance(expires_in, bool):
        expires_in = 0
    try:
        expires_in = int(expires_in)
    except (TypeError, ValueError):
        expires_in = 0
    cache = {
        key: value for key, value in payload.items() if key != "access_token"
    }
    token = payload.get("access_token")
    if isinstance(token, str) and token:
        cache["encrypted_access_token"] = encrypt_text(token)
    return {
        **cache,
        "expires_at": time.time() + max(expires_in - TOKEN_EXPIRY_SAFETY_BUFFER_SECONDS, 0),
    }


def get_cached_access_token(token_cache: dict | None) -> str | None:
    cached = token_cache if isinstance(token_cache, dict) else {}
    encrypted_token = cached.get("encrypted_access_token")
    expires_at = cached.get("expires_at")
    if (
        isinstance(encrypted_token, str)
        and encrypted_token
        and isinstance(expires_at, (int, float))
        and not isinstance(expires_at, bool)
        and math.isfinite(expires_at)
        and expires_at > time.time()
    ):
        try:
            token = decrypt_text(encrypted_token)
        except (InvalidToken, ValueError, TypeError):
            return None
        return token or None
    return None
