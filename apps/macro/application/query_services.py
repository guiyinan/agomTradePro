"""Application-level query helpers for macro diagnostics."""

from __future__ import annotations

from datetime import date
from typing import Any

from apps.macro.application.repository_provider import get_macro_repository
from apps.macro.application.use_cases import (
    SyncMacroDataRequest,
    build_sync_macro_data_use_case,
)


def get_latest_macro_indicator_date(indicator_code: str) -> date | None:
    """Return the latest date for one macro indicator."""

    return get_macro_repository().get_latest_observation_date(indicator_code)


def get_legacy_macro_series(
    *,
    code: str,
    start_date: date | None,
    end_date: date | None,
    source: str | None,
):
    """Return legacy macro series rows through the macro boundary."""

    return get_macro_repository().get_series(
        code=code,
        start_date=start_date,
        end_date=end_date,
        source=source,
    )


def sync_macro_indicators(
    *,
    start_date: date,
    end_date: date,
    indicators: list[str],
) -> dict[str, Any]:
    """Sync macro indicators and return a command-friendly payload."""

    result = build_sync_macro_data_use_case().execute(
        SyncMacroDataRequest(
            start_date=start_date,
            end_date=end_date,
            indicators=indicators,
        )
    )
    return {
        "success": result.success,
        "synced_count": result.synced_count,
        "skipped_count": result.skipped_count,
        "errors": list(result.errors or []),
    }
