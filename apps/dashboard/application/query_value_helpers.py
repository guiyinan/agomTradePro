"""Value normalization helpers for dashboard queries."""

from collections.abc import Mapping
from typing import Any

from django.core.exceptions import ImproperlyConfigured
from django.db import DatabaseError

DEGRADED_DASHBOARD_QUERY_EXCEPTIONS = (
    AttributeError,
    ConnectionError,
    DatabaseError,
    ImportError,
    ImproperlyConfigured,
    LookupError,
    RuntimeError,
    TimeoutError,
    TypeError,
    ValueError,
)


def _string_keyed_mapping(value: object) -> dict[str, Any]:
    """Copy only string-keyed mapping data from dynamic provider metadata."""

    if not isinstance(value, Mapping):
        return {}
    return {key: item for key, item in value.items() if isinstance(key, str)}


def _bounded_text(value: object, *, default: str, max_length: int = 500) -> str:
    """Return bounded single-line user-facing metadata or a stable fallback."""

    if not isinstance(value, str):
        return default
    normalized = value.strip()
    if not normalized or len(normalized) > max_length or "\n" in normalized or "\r" in normalized:
        return default
    return normalized
