"""fund runtime capability handlers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def _normalize_fund_code_for_contract(fund_code: str) -> str:
    normalized = fund_code.strip().upper()
    if normalized.endswith(".OF"):
        return normalized[:-3]
    return normalized


def _fallback_rank_funds(
    regime: str = "Recovery",
    max_count: int = 50,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    funds = client.fund.rank_funds(regime=regime, max_count=max_count)
    return {
        "regime": regime,
        "funds": funds,
        "total_count": len(funds),
    }


def _fallback_fund_compute_screen(
    regime: str | None = None,
    custom_types: list[str] | None = None,
    custom_styles: list[str] | None = None,
    min_scale: float | None = None,
    limit: int = 30,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.fund.screen_funds(
        regime=regime,
        custom_types=custom_types,
        custom_styles=custom_styles,
        min_scale=min_scale,
        limit=limit,
    )


def _fallback_get_fund_detail(fund_code: str) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.fund.get_fund_detail(fund_code)


def _fallback_get_fund_nav_history(
    fund_code: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    from datetime import date

    from agomtradepro import AgomTradeProClient

    parsed_start = date.fromisoformat(start_date) if start_date else None
    parsed_end = date.fromisoformat(end_date) if end_date else None
    client = AgomTradeProClient()
    nav_data = client.fund.get_nav_history(
        fund_code,
        start_date=parsed_start,
        end_date=parsed_end,
    )
    return {
        "fund_code": _normalize_fund_code_for_contract(fund_code),
        "nav_data": nav_data,
        "total_count": len(nav_data),
        "query": {
            "start_date": start_date,
            "end_date": end_date,
        },
    }


def _fallback_get_fund_holdings(
    fund_code: str,
    report_date: str | None = None,
) -> dict[str, Any]:
    from datetime import date

    from agomtradepro import AgomTradeProClient

    parsed_report_date = date.fromisoformat(report_date) if report_date else None
    client = AgomTradeProClient()
    holdings = client.fund.get_holdings(
        fund_code,
        report_date=parsed_report_date,
    )
    return {
        "fund_code": _normalize_fund_code_for_contract(fund_code),
        "report_date": report_date,
        "holdings": holdings,
        "total_count": len(holdings),
    }


LEGACY_TOOL_FALLBACKS: dict[str, Callable[..., Any]] = {
    "rank_funds": _fallback_rank_funds,
    "fund_compute_screen": _fallback_fund_compute_screen,
    "get_fund_detail": _fallback_get_fund_detail,
    "get_fund_nav_history": _fallback_get_fund_nav_history,
    "get_fund_holdings": _fallback_get_fund_holdings,
}

GOVERNED_HANDLERS: dict[str, Callable[..., Any]] = {}
