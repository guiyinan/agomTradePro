"""Bridge helpers for runtime asset proxy settings."""

from __future__ import annotations

from apps.account.infrastructure.models import SystemSettingsModel


def get_runtime_asset_proxy_map() -> dict[str, str]:
    """Return the configured asset-class proxy mapping."""

    return SystemSettingsModel.get_runtime_asset_proxy_map()
