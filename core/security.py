"""
Security helpers for authentication hardening.
"""

from __future__ import annotations

import hashlib
import logging
import unicodedata
from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest

if TYPE_CHECKING:
    from redis.exceptions import RedisError as _RedisError
else:
    try:
        from redis.exceptions import RedisError as _RedisError
    except ImportError:  # pragma: no cover - redis is optional in local envs
        _RedisError = ConnectionError


logger = logging.getLogger(__name__)


def _request_ip(request: HttpRequest | None) -> str:
    """Best-effort client IP extraction for lockout keying."""
    if request is None:
        return "unknown"

    trust_forwarded_for = getattr(
        settings,
        "LOGIN_LOCKOUT_TRUST_X_FORWARDED_FOR",
        False,
    )
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if trust_forwarded_for is True and isinstance(xff, str) and xff.strip():
        return xff.split(",")[0].strip() or "unknown"

    remote_addr = request.META.get("REMOTE_ADDR", "")
    if isinstance(remote_addr, str) and remote_addr.strip():
        return remote_addr.strip()
    return "unknown"


def _user_key(username: str, ip: str) -> str:
    normalized_username = unicodedata.normalize("NFKC", username).strip()
    raw = f"{normalized_username}|{ip}".encode()
    digest = hashlib.sha256(raw).hexdigest()
    return f"auth_lockout:{digest}"


def _positive_int_setting(name: str, default: int) -> int:
    raw_value = getattr(settings, name, default)
    if isinstance(raw_value, bool):
        logger.warning("Invalid login lockout setting, using default: setting=%s", name)
        return default
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        logger.warning("Invalid login lockout setting, using default: setting=%s", name)
        return default
    if value <= 0:
        logger.warning("Invalid login lockout setting, using default: setting=%s", name)
        return default
    return value


def _get_limits() -> tuple[int, int]:
    max_attempts = _positive_int_setting("LOGIN_LOCKOUT_MAX_ATTEMPTS", 5)
    window_seconds = _positive_int_setting("LOGIN_LOCKOUT_WINDOW_SECONDS", 900)
    return max_attempts, window_seconds


def _cache_get_int(key: str) -> int:
    """Best-effort cache read; degrade gracefully when cache backend is unavailable."""
    try:
        value = cache.get(key, 0)
        if isinstance(value, bool):
            return 0
        if isinstance(value, int):
            return value if value >= 0 else 0
        if isinstance(value, str):
            parsed_value = int(value.strip())
            return parsed_value if parsed_value >= 0 else 0
        return 0
    except (_RedisError, ConnectionError, TimeoutError, OSError, ValueError) as exc:
        logger.warning(
            "Login lockout cache read failed; error_type=%s",
            type(exc).__name__,
        )
        return 0


def _cache_record_failure(key: str, window_seconds: int) -> None:
    """Best-effort failure increment without making Redis a hard dependency."""
    try:
        if cache.add(key, 1, timeout=window_seconds):
            return
        cache.incr(key)
    except (_RedisError, ConnectionError, TimeoutError, OSError, ValueError) as exc:
        logger.warning(
            "Login lockout cache increment failed; error_type=%s",
            type(exc).__name__,
        )


def _cache_clear(key: str) -> None:
    """Best-effort cache delete."""
    try:
        cache.delete(key)
    except (_RedisError, ConnectionError, TimeoutError, OSError) as exc:
        logger.warning(
            "Login lockout cache delete failed; error_type=%s",
            type(exc).__name__,
        )


class LockoutModelBackend(ModelBackend):
    """
    Default model backend with basic brute-force lockout.

    Uses cache counters keyed by (username, ip).
    """

    def authenticate(
        self,
        request: HttpRequest | None,
        username: str | None = None,
        password: str | None = None,
        **kwargs: Any,
    ) -> User | None:
        kwargs_username = kwargs.get("username")
        if username is None and isinstance(kwargs_username, str):
            username = kwargs_username
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
