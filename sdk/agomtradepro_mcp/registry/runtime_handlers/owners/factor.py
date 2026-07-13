"""factor runtime capability handlers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from agomtradepro_mcp.registry.runtime_handlers.common import _call_registered_tool


def _fallback_factor_read_definition_catalog() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    raw_factors = client.factor.get_all_factors()
    if not isinstance(raw_factors, list):
        raise ValueError("factor.read.definition_catalog returned an invalid payload")

    factors = [dict(item) for item in raw_factors if isinstance(item, dict)]
    by_category: dict[str, list[dict[str, Any]]] = {}
    for factor in factors:
        category = str(factor.get("category") or "unknown")
        by_category.setdefault(category, []).append(factor)
    return {
        "factors": factors,
        "by_category": by_category,
        "total_count": len(factors),
    }


def _fallback_factor_compute_top_stocks(
    value_preference: str = "medium",
    quality_preference: str = "medium",
    growth_preference: str = "medium",
    momentum_preference: str = "medium",
    top_n: int = 30,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    result = client.factor.get_top_stocks(
        {
            "value": value_preference,
            "quality": quality_preference,
            "growth": growth_preference,
            "momentum": momentum_preference,
        },
        top_n,
    )
    if not isinstance(result, dict):
        raise ValueError("factor.compute.top_stocks returned an invalid payload")
    stocks = result.get("stocks", [])
    if not isinstance(stocks, list):
        raise ValueError("factor.compute.top_stocks returned invalid stocks")
    return {
        "total_stocks": len(stocks),
        "stocks": stocks,
    }


def _fallback_factor_compute_stock_explanation(
    stock_code: str,
    focus: str = "balanced",
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    result = client.factor.explain_stock_by_focus(stock_code, focus)
    if not isinstance(result, dict):
        raise ValueError("factor.compute.stock_explanation returned an invalid payload")
    required_keys = {
        "stock_code",
        "stock_name",
        "composite_score",
        "percentile_rank",
        "factor_breakdown",
        "category_breakdown",
    }
    if not required_keys.issubset(result):
        raise ValueError("factor.compute.stock_explanation returned an incomplete payload")
    return result


def _fallback_factor_read_config_catalog() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    raw_configs = client.factor.get_all_configs()
    if not isinstance(raw_configs, list):
        raise ValueError("factor.read.config_catalog returned an invalid payload")
    configs = [dict(item) for item in raw_configs if isinstance(item, dict)]
    return {
        "configs": configs,
        "total_count": len(configs),
    }


def _fallback_factor_read_portfolio(config_name: str) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    portfolio = client.factor.get_portfolio(config_name)
    if portfolio is not None and not isinstance(portfolio, dict):
        raise ValueError("factor.read.portfolio returned an invalid payload")
    return {
        "config_name": config_name,
        "exists": portfolio is not None,
        "portfolio": portfolio,
    }


def _internal_handler_factor_create_portfolio(
    config_name: str,
    trade_date: str | None = None,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    if preview_only:
        configs = AgomTradeProClient().factor.get_all_configs()
        matched = next(
            (
                item
                for item in configs
                if isinstance(item, dict) and str(item.get("name")) == config_name
            ),
            None,
        )
        if matched is None:
            raise ValueError(f"Unknown factor config: {config_name}")
        return {
            "success": True,
            "preview_only": True,
            "config_name": config_name,
            "trade_date": trade_date,
            "config_found": True,
            "will_persist_holdings": True,
        }
    return _call_registered_tool(
        "create_factor_portfolio",
        {"config_name": config_name, "trade_date": trade_date},
    )


LEGACY_TOOL_FALLBACKS: dict[str, Callable[..., Any]] = {
    "factor_compute_top_stocks": _fallback_factor_compute_top_stocks,
    "factor_compute_stock_explanation": _fallback_factor_compute_stock_explanation,
    "factor_read_definition_catalog": _fallback_factor_read_definition_catalog,
    "factor_read_config_catalog": _fallback_factor_read_config_catalog,
    "factor_read_portfolio": _fallback_factor_read_portfolio,
}

GOVERNED_HANDLERS: dict[str, Callable[..., Any]] = {
    "factor_create_portfolio": _internal_handler_factor_create_portfolio,
}
