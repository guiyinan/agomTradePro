"""Bridge helpers for cross-app asset name resolution."""

from __future__ import annotations

from apps.asset_analysis.application.asset_name_service import (
    resolve_asset_names as _resolve_asset_names,
)


def resolve_asset_names_for_signals(asset_codes: list[str]) -> dict[str, str]:
    """Return asset names for signal-facing asset codes."""

    return _resolve_asset_names(asset_codes)
