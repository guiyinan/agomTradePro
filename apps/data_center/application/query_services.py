"""Application-level query helpers for cross-app data-center access."""

from __future__ import annotations

from apps.data_center.application.repository_provider import get_macro_fact_repository


def get_latest_macro_indicator_value(indicator_code: str) -> float | None:
    """Return the latest canonical macro indicator value for one code."""

    latest = get_macro_fact_repository().get_latest(indicator_code)
    return float(latest.value) if latest is not None else None
