"""
Security helpers for authentication hardening.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Optional

from django.conf import settings
from django.contrib.auth.backends import ModelBackend
from django.core.cache import cache
from django.core.exceptions import PermissionDenied

try:
    from redis.exceptions import RedisError
except ImportError:  # pragma: no cover - redis is optional in local envs
    RedisError = Exception  # type: ignore[misc,assignment]

logger = logging.getLogger(__name__)


def _request_ip(request) -> str:
    """Best-effort client IP extraction for lockout keying."""
    if request is None:
        return "unknown"
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if xff:
        return xff.split(",")[0].strip() or "unknown"
    return request.META.get("REMOTE_ADDR", "unknown")


def _user_key(username: str, ip: str) -> str:
    raw = f"{username}|{ip}".encode()
    digest = hashlib.sha256(raw).hexdigest()
    return f"auth_lockout:{digest}"


def _get_limits() -> tuple[int, int]:
    max_attempts = int(getattr(settings, "LOGIN_LOCKOUT_MAX_ATTEMPTS", 5))
    window_seconds = int(getattr(settings, "LOGIN_LOCKOUT_WINDOW_SECONDS", 900))
    return max_attempts, window_seconds


def _cache_get_int(key: str) -> int:
    """Best-effort cache read; degrade gracefully when cache backend is unavailable."""
    try:
        return int(cache.get(key, 0))
    except (RedisError, ConnectionError, TimeoutError, OSError, ValueError) as exc:
        logger.warning("Login lockout cache read failed, falling back to in-process auth flow: %s", exc)
        return 0


def _cache_record_failure(key: str, window_seconds: int) -> None:
    """Best-effort failure increment without making Redis a hard dependency."""
    try:
        cache.incr(key)
    except ValueError:
        try:
            cache.set(key, 1, timeout=window_seconds)
        except (RedisError, ConnectionError, TimeoutError, OSError, ValueError) as exc:
            logger.warning("Login lockout cache set failed, skipping lockout counter: %s", exc)
    except (RedisError, ConnectionError, TimeoutError, OSError) as exc:
        logger.warning("Login lockout cache increment failed, skipping lockout counter: %s", exc)


def _cache_clear(key: str) -> None:
    """Best-effort cache delete."""
    try:
        cache.delete(key)
    except (RedisError, ConnectionError, TimeoutError, OSError) as exc:
        logger.warning("Login lockout cache delete failed, skipping cache reset: %s", exc)


class LockoutModelBackend(ModelBackend):
    """
    Default model backend with basic brute-force lockout.

    Uses cache counters keyed by (username, ip).
    """

    def authenticate(self, request, username: str | None = None, password: str | None = None, **kwargs):
        username = username or kwargs.get("username")
        ip = _request_ip(request)

        if username:
            key = _user_key(username, ip)
            max_attempts, window_seconds = _get_limits()
            failed_count = _cache_get_int(key)
            if failed_count >= max_attempts:
                raise PermissionDenied("Too many failed login attempts. Please try again later.")
        else:
            key = None
            window_seconds = _get_limits()[1]

        user = super().authenticate(request, username=username, password=password, **kwargs)

        if key:
            if user is None:
                _cache_record_failure(key, window_seconds)
            else:
                _cache_clear(key)

        return user
