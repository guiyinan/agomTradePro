"""backtest runtime capability handlers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def _backtest_result_payload(result: Any) -> dict[str, Any]:
    return {
        "id": result.id,
        "status": result.status,
        "total_return": result.total_return,
        "annual_return": result.annual_return,
        "max_drawdown": result.max_drawdown,
        "sharpe_ratio": result.sharpe_ratio,
    }


def _fallback_get_backtest_result(backtest_id: int) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return _backtest_result_payload(client.backtest.get_result(backtest_id))


def _fallback_list_backtests(
    status: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    backtests = client.backtest.list_backtests(status=status, limit=limit)
    payload = [_backtest_result_payload(result) for result in backtests]
    return {
        "backtests": payload,
        "total_count": len(payload),
    }


def _fallback_backtest_read_equity_curve(backtest_id: int) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    payload = client.backtest.get_equity_curve_payload(backtest_id)
    curve = payload.get("curve")
    if not isinstance(curve, list):
        raise ValueError("backtest.read.equity_curve must contain a curve array")
    return {
        "backtest_id": int(payload.get("backtest_id", backtest_id)),
        "status": str(payload.get("status") or "unknown"),
        "curve": [dict(point) for point in curve if isinstance(point, dict)],
        "point_count": int(payload.get("point_count", len(curve))),
    }


LEGACY_TOOL_FALLBACKS: dict[str, Callable[..., Any]] = {
    "get_backtest_result": _fallback_get_backtest_result,
    "list_backtests": _fallback_list_backtests,
    "backtest_read_equity_curve": _fallback_backtest_read_equity_curve,
}

GOVERNED_HANDLERS: dict[str, Callable[..., Any]] = {}
