"""Application-level query helpers for cross-app equity access."""

from __future__ import annotations

from datetime import date
from typing import Any

from apps.equity.application.repository_provider import (
    get_equity_asset_master_query_repository,
    get_equity_market_data_repository,
    get_equity_stock_repository,
    get_equity_valuation_repair_repository,
)


def _resolved_financial_period_type(financial: Any) -> str:
    """Return canonical period type for Data Center and legacy financial records."""

    if financial.period_type:
        return str(financial.period_type)
    return {3: "quarterly", 6: "semi_annual", 9: "quarterly", 12: "annual"}.get(
        financial.report_date.month,
        "",
    )


def get_valuation_repair_snapshot_map(stock_codes: list[str]) -> dict[str, dict[str, Any]]:
    """Return valuation repair snapshots keyed by upper security code."""
    normalized_codes = [code for code in stock_codes if code]
    if not normalized_codes:
        return {}
    return get_equity_valuation_repair_repository().get_snapshot_map(normalized_codes)


def get_stock_context_map(stock_codes: list[str]) -> dict[str, dict[str, Any]]:
    """Return stock info and latest local daily context keyed by requested code."""

    normalized_codes = [str(code).upper() for code in stock_codes if code]
    if not normalized_codes:
        return {}
    return get_equity_stock_repository().get_stock_context_rows(normalized_codes)


def list_asset_master_stock_candidate_codes() -> list[str]:
    """Return stock codes that can seed data-center asset master rows."""

    return get_equity_asset_master_query_repository().list_candidate_codes()


def list_asset_master_stock_rows(lookup_codes: list[str]) -> list[dict[str, Any]]:
    """Return local stock rows for data-center asset master backfill."""

    return get_equity_asset_master_query_repository().list_stock_rows(lookup_codes)


def fetch_index_daily_returns(
    *,
    index_code: str,
    start_date: date,
    end_date: date,
    hydrate: bool = True,
) -> dict[date, float]:
    """Return daily index returns through the equity application boundary."""

    return get_equity_market_data_repository().get_index_daily_returns(
        index_code=index_code,
        start_date=start_date,
        end_date=end_date,
        hydrate=hydrate,
    )


def list_stock_financial_payloads(
    *,
    stock_code: str,
    report_type: str = "all",
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Return persisted financial snapshots through the equity application boundary."""

    financials = get_equity_stock_repository().get_financial_data(
        stock_code,
        limit=max(limit * 4, limit),
        hydrate=False,
    )
    if report_type != "all":
        financials = [
            item for item in financials if _resolved_financial_period_type(item) == report_type
        ]
    financials = financials[:limit]
    return [
        {
            "stock_code": item.stock_code,
            "report_date": item.report_date.isoformat(),
            "period_type": _resolved_financial_period_type(item),
            "revenue": str(item.revenue),
            "net_profit": str(item.net_profit),
            "revenue_growth": item.revenue_growth,
            "net_profit_growth": item.net_profit_growth,
            "total_assets": str(item.total_assets),
            "total_liabilities": str(item.total_liabilities),
            "equity": str(item.equity),
            "roe": item.roe,
            "roa": item.roa,
            "debt_ratio": item.debt_ratio,
            "source": item.source,
        }
        for item in financials
    ]
