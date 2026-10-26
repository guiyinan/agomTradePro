"""Serializer for the effective performance projection in account responses."""

from __future__ import annotations

from typing import Any

from apps.simulated_trading.application.use_cases import AccountPerformanceResult


def apply_account_performance_projection(
    account_payload: dict[str, Any],
    result: AccountPerformanceResult,
) -> dict[str, Any]:
    """Return an account payload with the same performance projection as its response."""

    payload = dict(account_payload)
    performance = result["performance"]
    payload.update(
        {
            "total_return": performance["total_return"],
            "annual_return": performance["annual_return"],
            "max_drawdown": performance["max_drawdown"],
            "sharpe_ratio": performance["sharpe_ratio"],
            "win_rate": result["win_rate"],
            "total_trades": result["total_trades"],
            "winning_trades": result["winning_trades"],
            "realized_trade_metrics_known": result["win_rate_known"],
        }
    )
    return payload


__all__ = ["apply_account_performance_projection"]
