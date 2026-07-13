"""asset_analysis runtime capability handlers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def _fallback_asset_analysis_read_weight_config_catalog() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    result = client.asset_analysis.get_weight_configs()
    configs = result.get("configs", {})
    return {
        "configs": configs,
        "active": result.get("active"),
        "total_count": len(configs),
    }


def _fallback_asset_analysis_read_current_weight() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.asset_analysis.get_current_weight()


def _fallback_asset_analysis_read_pool_summary(
    asset_type: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    params = {"asset_type": asset_type} if asset_type else None
    return client.asset_analysis.pool_summary(params)


LEGACY_TOOL_FALLBACKS: dict[str, Callable[..., Any]] = {
    "asset_analysis_read_weight_config_catalog": _fallback_asset_analysis_read_weight_config_catalog,
    "asset_analysis_read_current_weight": _fallback_asset_analysis_read_current_weight,
    "asset_analysis_read_pool_summary": _fallback_asset_analysis_read_pool_summary,
}

GOVERNED_HANDLERS: dict[str, Callable[..., Any]] = {}
