"""Bridge helpers for runtime asset proxy settings."""

from __future__ import annotations

from apps.config_center.application.config_summary_service import (
    get_config_center_summary_service,
)


def get_runtime_asset_proxy_map() -> dict[str, str]:
    """Return the configured asset-class proxy mapping."""

    return get_config_center_summary_service().get_runtime_asset_proxy_map()
