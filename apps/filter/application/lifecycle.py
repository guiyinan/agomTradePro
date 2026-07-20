"""Lifecycle contract for the deprecated Filter service."""

from __future__ import annotations

FILTER_DEPRECATED_SINCE = "0.8.0"
FILTER_SUNSET_DATE = "2026-09-30"
FILTER_SUNSET_HTTP_DATE = "Wed, 30 Sep 2026 00:00:00 GMT"
FILTER_REPLACEMENT_HINT = (
    "Use the owning data workflow or shared trend-filter implementation; "
    "do not add new Filter API, SDK, or MCP consumers."
)


def filter_deprecation_payload() -> dict[str, str]:
    """Return stable machine-readable Filter lifecycle metadata."""

    return {
        "status": "deprecated",
        "deprecated_since": FILTER_DEPRECATED_SINCE,
        "sunset_on": FILTER_SUNSET_DATE,
        "replacement_hint": FILTER_REPLACEMENT_HINT,
    }


__all__ = [
    "FILTER_DEPRECATED_SINCE",
    "FILTER_REPLACEMENT_HINT",
    "FILTER_SUNSET_DATE",
    "FILTER_SUNSET_HTTP_DATE",
    "filter_deprecation_payload",
]
