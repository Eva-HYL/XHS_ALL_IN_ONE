from __future__ import annotations

import time


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
    return {
        **payload,
        "expires_at": time.time() + max(expires_in - TOKEN_EXPIRY_SAFETY_BUFFER_SECONDS, 0),
    }


def get_cached_access_token(token_cache: dict | None) -> str | None:
    cached = token_cache if isinstance(token_cache, dict) else {}
    token = cached.get("access_token")
    expires_at = cached.get("expires_at")
    if isinstance(token, str) and token and isinstance(expires_at, (int, float)) and not isinstance(expires_at, bool) and expires_at > time.time():
        return token
    return None
