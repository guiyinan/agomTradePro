"""Shared lifecycle metadata for deprecated Filter capabilities."""

FILTER_LIFECYCLE = {
    "lifecycle_status": "deprecated",
    "deprecated_since": "0.8.0",
    "sunset_on": "2026-09-30",
    "replacement_hint": (
        "Use the owning data workflow or shared trend-filter implementation; "
        "do not add new Filter API, SDK, or MCP consumers."
    ),
}

__all__ = ["FILTER_LIFECYCLE"]
