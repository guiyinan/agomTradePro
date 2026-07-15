"""App-neutral access-token registry for non-Account interfaces."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

_token_reader: Callable[[str], Any | None] | None = None
_token_toucher: Callable[[Any], None] | None = None


def register_access_token_provider(
    *, reader: Callable[[str], Any | None], toucher: Callable[[Any], None]
) -> None:
    """Register Account-owned token operations."""

    global _token_reader, _token_toucher
    _token_reader = reader
    _token_toucher = toucher


def get_active_access_token(key: str) -> Any | None:
    """Resolve an active access token."""

    if _token_reader is None:
        return None
    return _token_reader(key)


def touch_access_token(token: Any) -> None:
    """Update last-used metadata for a resolved token."""

    if _token_toucher is not None:
        _token_toucher(token)


__all__ = [
    "get_active_access_token",
    "register_access_token_provider",
    "touch_access_token",
]
