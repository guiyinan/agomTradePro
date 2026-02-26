"""
Security helpers for authentication hardening.
"""

from __future__ import annotations

import hashlib
from typing import Optional

from django.conf import settings
from django.contrib.auth.backends import ModelBackend
from django.core.cache import cache
from django.core.exceptions import PermissionDenied


def _request_ip(request) -> str:
    """Best-effort client IP extraction for lockout keying."""
    if request is None:
        return "unknown"
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if xff:
        return xff.split(",")[0].strip() or "unknown"
    return request.META.get("REMOTE_ADDR", "unknown")


def _user_key(username: str, ip: str) -> str:
    raw = f"{username}|{ip}".encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    return f"auth_lockout:{digest}"


def _get_limits() -> tuple[int, int]:
    max_attempts = int(getattr(settings, "LOGIN_LOCKOUT_MAX_ATTEMPTS", 5))
    window_seconds = int(getattr(settings, "LOGIN_LOCKOUT_WINDOW_SECONDS", 900))
    return max_attempts, window_seconds


class LockoutModelBackend(ModelBackend):
    """
    Default model backend with basic brute-force lockout.

    Uses cache counters keyed by (username, ip).
    """

    def authenticate(self, request, username: Optional[str] = None, password: Optional[str] = None, **kwargs):
        username = username or kwargs.get("username")
        ip = _request_ip(request)

        if username:
            key = _user_key(username, ip)
            max_attempts, window_seconds = _get_limits()
            failed_count = int(cache.get(key, 0))
            if failed_count >= max_attempts:
                raise PermissionDenied("Too many failed login attempts. Please try again later.")
        else:
            key = None
            window_seconds = _get_limits()[1]

        user = super().authenticate(request, username=username, password=password, **kwargs)

        if key:
            if user is None:
                try:
                    cache.incr(key)
                except ValueError:
                    cache.set(key, 1, timeout=window_seconds)
            else:
                cache.delete(key)

        return user

