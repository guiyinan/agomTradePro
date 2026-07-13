"""alpha runtime capability handlers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from agomtradepro_mcp.registry.runtime_handlers.common import _call_registered_tool


def _fallback_alpha_read_stock_scores(
    universe: str = "csi300",
    trade_date: str | None = None,
    top_n: int = 20,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    result = client.alpha.get_stock_scores(
        universe=universe,
        trade_date=trade_date,
        top_n=top_n,
    )
    if not isinstance(result, dict):
        raise ValueError("alpha.read.stock_scores returned an invalid payload")
    return result


def _fallback_alpha_read_factor_exposure(
    stock_code: str,
    trade_date: str | None = None,
    provider: str = "simple",
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    result = client.alpha.get_factor_exposure(
        stock_code,
        trade_date=trade_date,
        provider=provider,
    )
    if not isinstance(result, dict):
        raise ValueError("alpha.read.factor_exposure returned an invalid payload")
    return result


def _fallback_get_alpha_provider_status() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.alpha.get_provider_status()


def _fallback_get_alpha_available_universes() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    result = client.alpha.get_available_universes()
    universes = result.get("universes", []) if isinstance(result, dict) else []
    return {"universes": universes}


def _fallback_check_alpha_health() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.alpha.check_health()


def _fallback_alpha_read_inference_ops_overview() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    result = client.alpha.get_ops_inference_overview()
    if (
        isinstance(result, dict)
        and result.get("success") is True
        and isinstance(result.get("data"), dict)
    ):
        return result["data"]
    return result


def _fallback_alpha_read_qlib_data_ops_overview() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    result = client.alpha.get_ops_qlib_data_overview()
    if (
        isinstance(result, dict)
        and result.get("success") is True
        and isinstance(result.get("data"), dict)
    ):
        return result["data"]
    return result


def _internal_handler_alpha_start_inference(
    mode: str,
    trade_date: str | None = None,
    top_n: int = 30,
    universe_id: str | None = None,
    portfolio_id: int | None = None,
    pool_mode: str | None = None,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    arguments = {
        "mode": mode,
        "trade_date": trade_date,
        "top_n": top_n,
        "universe_id": universe_id,
        "portfolio_id": portfolio_id,
        "pool_mode": pool_mode,
    }
    if preview_only:
        overview = AgomTradeProClient().alpha.get_ops_inference_overview()
        return {
            "success": True,
            "preview_only": True,
            "request": arguments,
            "active_model": overview.get("active_model"),
            "recent_task_count": len(overview.get("recent_tasks") or []),
        }
    return _call_registered_tool("trigger_alpha_ops_inference", arguments)


def _internal_handler_alpha_refresh_qlib_data(
    mode: str,
    target_date: str,
    lookback_days: int = 400,
    universes: list[str] | None = None,
    portfolio_ids: list[int] | None = None,
    all_active_portfolios: bool = False,
    pool_mode: str | None = None,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    arguments = {
        "mode": mode,
        "target_date": target_date,
        "lookback_days": lookback_days,
        "universes": universes,
        "portfolio_ids": portfolio_ids,
        "all_active_portfolios": all_active_portfolios,
        "pool_mode": pool_mode,
    }
    if preview_only:
        overview = AgomTradeProClient().alpha.get_ops_qlib_data_overview()
        return {
            "success": True,
            "preview_only": True,
            "request": arguments,
            "local_data_status": overview.get("local_data_status"),
            "recent_task_count": len(overview.get("recent_tasks") or []),
        }
    return _call_registered_tool("refresh_alpha_qlib_data", arguments)


LEGACY_TOOL_FALLBACKS: dict[str, Callable[..., Any]] = {
    "alpha_read_stock_scores": _fallback_alpha_read_stock_scores,
    "alpha_read_factor_exposure": _fallback_alpha_read_factor_exposure,
    "get_alpha_provider_status": _fallback_get_alpha_provider_status,
    "get_alpha_available_universes": _fallback_get_alpha_available_universes,
    "check_alpha_health": _fallback_check_alpha_health,
    "alpha_read_inference_ops_overview": _fallback_alpha_read_inference_ops_overview,
    "alpha_read_qlib_data_ops_overview": _fallback_alpha_read_qlib_data_ops_overview,
}

GOVERNED_HANDLERS: dict[str, Callable[..., Any]] = {
    "alpha_start_inference": _internal_handler_alpha_start_inference,
    "alpha_refresh_qlib_data": _internal_handler_alpha_refresh_qlib_data,
}
