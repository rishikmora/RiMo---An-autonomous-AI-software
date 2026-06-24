"""Per-IP rate limiting for sensitive endpoints (auth).

Backed by the Redis instance the system already depends on, so limits hold
across multiple API replicas rather than per-process. The storage backend is
env-driven (``RATELIMIT_STORAGE_URI``) so tests and single-process runs can use
in-memory storage.

The limiter is configured to *fail open*: if the limiter backend is briefly
unreachable, requests are allowed rather than rejected, so a Redis blip cannot
take down authentication entirely. Rate limiting is a mitigation, not a
correctness gate, so availability wins when the backend is down.
"""
from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings


def _storage_uri() -> str:
    # Explicit override (tests use memory://) takes precedence over Redis.
    override = getattr(settings, "ratelimit_storage_uri", "") or ""
    if override:
        return override
    try:
        return str(settings.redis_url)
    except Exception:  # pragma: no cover - defensive
        return "memory://"


# Shared limiter. Routes opt in via @limiter.limit(...); the key is the client IP.
# in_memory_fallback_enabled keeps auth available if the Redis backend errors.
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=_storage_uri(),
    default_limits=[],  # no global limit; sensitive routes opt in explicitly
    in_memory_fallback_enabled=True,
)
