"""factor runtime capability handlers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


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


LEGACY_TOOL_FALLBACKS: dict[str, Callable[..., Any]] = {
    "factor_compute_top_stocks": _fallback_factor_compute_top_stocks,
    "factor_compute_stock_explanation": _fallback_factor_compute_stock_explanation,
    "factor_read_definition_catalog": _fallback_factor_read_definition_catalog,
    "factor_read_config_catalog": _fallback_factor_read_config_catalog,
}

GOVERNED_HANDLERS: dict[str, Callable[..., Any]] = {}
