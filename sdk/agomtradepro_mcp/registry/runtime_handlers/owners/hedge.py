"""hedge runtime capability handlers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def _fallback_hedge_read_pair_catalog() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    pairs = client.hedge.get_all_pairs()
    return {
        "pairs": pairs,
        "total_count": len(pairs),
    }


def _fallback_hedge_compute_correlation_matrix(
    asset_codes: list[str],
    window_days: int = 60,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.hedge.get_correlation_matrix(asset_codes, window_days)


def _fallback_hedge_read_pair_detail(pair_name: str) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    pair = client.hedge.get_pair_info(pair_name)
    if pair is None:
        raise ValueError(f"Hedge pair not found: {pair_name}")
    return {
        "pair_name": pair_name,
        "pair": pair,
    }


def _fallback_hedge_read_alert_list() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    alerts = client.hedge.get_alerts()
    return {
        "alerts": alerts,
        "total_count": len(alerts),
        "query": {
            "days": 7,
            "is_resolved": False,
        },
    }


def _fallback_hedge_read_portfolio_state(pair_name: str) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    state = client.hedge.get_portfolio_state(pair_name)
    if state is None:
        raise ValueError(f"Hedge portfolio state not found: {pair_name}")
    return {
        "pair_name": pair_name,
        "state": state,
    }


def _fallback_hedge_compute_effectiveness(pair_name: str) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    normalized_name = str(pair_name or "").strip()
    if not normalized_name or len(normalized_name) > 100:
        raise ValueError("pair_name must contain 1 to 100 characters")
    client = AgomTradeProClient()
    result = client.hedge.check_effectiveness(normalized_name)
    if not isinstance(result, dict) or result.get("error"):
        raise ValueError(
            str((result or {}).get("error") or f"Hedge pair not found: {normalized_name}")
        )
    effectiveness = float(result.get("effectiveness") or 0.0)
    return {
        **result,
        "pair_name": result.get("pair_name") or normalized_name,
        "is_effective": effectiveness >= 0.5,
    }


LEGACY_TOOL_FALLBACKS: dict[str, Callable[..., Any]] = {
    "hedge_compute_correlation_matrix": _fallback_hedge_compute_correlation_matrix,
    "hedge_read_pair_catalog": _fallback_hedge_read_pair_catalog,
    "hedge_read_pair_detail": _fallback_hedge_read_pair_detail,
    "hedge_read_alert_list": _fallback_hedge_read_alert_list,
    "hedge_read_portfolio_state": _fallback_hedge_read_portfolio_state,
    "hedge_compute_effectiveness": _fallback_hedge_compute_effectiveness,
}

GOVERNED_HANDLERS: dict[str, Callable[..., Any]] = {}
