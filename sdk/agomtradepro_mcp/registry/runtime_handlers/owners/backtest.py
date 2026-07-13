"""backtest runtime capability handlers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from agomtradepro_mcp.registry.runtime_handlers.common import _call_registered_tool


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


def _validate_backtest_window(start_date: str, end_date: str) -> None:
    from datetime import date

    parsed_start = date.fromisoformat(start_date)
    parsed_end = date.fromisoformat(end_date)
    if parsed_start > parsed_end:
        raise ValueError("start_date must not be after end_date")


def _internal_handler_backtest_run_strategy(
    strategy_name: str,
    start_date: str,
    end_date: str,
    initial_capital: float = 1_000_000.0,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    _validate_backtest_window(start_date, end_date)
    arguments = {
        "strategy_name": strategy_name,
        "start_date": start_date,
        "end_date": end_date,
        "initial_capital": initial_capital,
    }
    if preview_only:
        return {"success": True, "preview_only": True, "run_target": arguments}
    return _call_registered_tool("run_backtest", arguments)


def _internal_handler_backtest_run_decision_replay(
    portfolio_id: int,
    start_date: str,
    end_date: str,
    branch_type: str,
    initial_capital: float = 1_000_000.0,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    _validate_backtest_window(start_date, end_date)
    if branch_type not in {"actual", "no_action", "system_plan", "delayed_1d"}:
        raise ValueError("Unsupported decision replay branch_type")
    arguments = {
        "portfolio_id": portfolio_id,
        "start_date": start_date,
        "end_date": end_date,
        "branch_type": branch_type,
        "initial_capital": initial_capital,
    }
    if preview_only:
        return {"success": True, "preview_only": True, "run_target": arguments}
    return _call_registered_tool("run_decision_replay_backtest", arguments)


LEGACY_TOOL_FALLBACKS: dict[str, Callable[..., Any]] = {
    "get_backtest_result": _fallback_get_backtest_result,
    "list_backtests": _fallback_list_backtests,
    "backtest_read_equity_curve": _fallback_backtest_read_equity_curve,
}

GOVERNED_HANDLERS: dict[str, Callable[..., Any]] = {
    "backtest_run_strategy": _internal_handler_backtest_run_strategy,
    "backtest_run_decision_replay": _internal_handler_backtest_run_decision_replay,
}
