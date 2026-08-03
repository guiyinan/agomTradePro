"""Application-level query helpers for cross-app equity access."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

from apps.data_center.application.public import (
    get_published_financial_facts,
    get_published_price_bar_series,
    get_published_valuation_facts,
)
from apps.equity.application.repository_provider import (
    get_equity_asset_master_query_repository,
    get_equity_market_data_repository,
    get_equity_stock_repository,
    get_equity_valuation_repair_repository,
)
from shared.numeric import safe_float


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


def get_stock_name_map(stock_codes: list[str]) -> dict[str, str]:
    """Return display names without loading any market or fundamental facts."""

    master_rows = get_equity_stock_repository().get_stock_master_rows(stock_codes)
    return {
        code: str(row.get("name") or "")
        for code, row in master_rows.items()
        if str(row.get("name") or "")
    }


def _context_date(value: object) -> date | None:
    """Normalize a canonical fact date without accepting malformed values."""

    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _payload_rows(payload: object) -> list[Mapping[str, object]]:
    """Extract mapping rows from a publication-gated payload."""

    if not isinstance(payload, Mapping) or bool(payload.get("must_not_use_for_decision")):
        return []
    rows = payload.get("rows")
    if not isinstance(rows, (list, tuple)):
        return []
    return [row for row in rows if isinstance(row, Mapping)]


def _payload_gate(payload: object) -> dict[str, object]:
    """Keep stable freshness/provenance evidence for a context row."""

    if not isinstance(payload, Mapping):
        return {
            "must_not_use_for_decision": True,
            "blocked_reason": "published_payload_invalid",
        }
    return {
        key: payload[key]
        for key in (
            "publication_id",
            "published_at",
            "observed_at",
            "age_seconds",
            "max_age_seconds",
            "freshness_status",
            "must_not_use_for_decision",
            "blocked_reason",
        )
        if key in payload
    }


def _published_financial_context(payload: object) -> dict[str, object]:
    """Aggregate one published financial fact payload by its newest period."""

    rows = _payload_rows(payload)
    grouped: dict[date, list[Mapping[str, object]]] = {}
    for row in rows:
        period_end = _context_date(row.get("period_end"))
        if period_end is not None:
            grouped.setdefault(period_end, []).append(row)
    if not grouped:
        return {}

    latest_period = max(grouped)
    metrics = {
        str(row.get("metric_code") or ""): row
        for row in grouped[latest_period]
        if str(row.get("metric_code") or "")
    }

    def metric_value(metric_code: str) -> float | None:
        row = metrics.get(metric_code)
        return safe_float(row.get("value"), default=None) if row else None

    report_date = next(
        (
            report_date
            for report_date in (
                _context_date(row.get("report_date")) for row in grouped[latest_period]
            )
            if report_date is not None
        ),
        latest_period,
    )
    return {
        "report_date": report_date,
        "roe": metric_value("roe"),
        "debt_ratio": metric_value("debt_ratio"),
        "revenue_growth": metric_value("revenue_growth"),
        "profit_growth": metric_value("net_profit_growth"),
    }


def _published_price_context(payload: object) -> dict[str, object]:
    """Select the newest row from a published daily-price payload."""

    rows = _payload_rows(payload)
    if not rows:
        return {}
    latest = rows[-1]
    return {
        "trade_date": _context_date(latest.get("timestamp")),
        "close": safe_float(latest.get("close"), default=None),
        "volume": safe_float(latest.get("volume"), default=None),
    }


def _published_valuation_context(payload: object) -> dict[str, object]:
    """Select the newest row from a published valuation payload."""

    rows = _payload_rows(payload)
    if not rows:
        return {}
    latest = rows[-1]
    pe_value = latest.get("pe_ttm")
    return {
        "valuation_trade_date": _context_date(latest.get("val_date")),
        "pe": safe_float(
            pe_value if pe_value is not None else latest.get("pe_static"),
            default=None,
        ),
        "pb": safe_float(latest.get("pb"), default=None),
        "ps": safe_float(latest.get("ps_ttm"), default=None),
        "dividend_yield": safe_float(latest.get("dv_ratio"), default=None),
    }


def get_published_stock_context_map(
    stock_codes: list[str],
    *,
    publication_key: str = "current",
    include_price: bool = True,
) -> dict[str, dict[str, Any]]:
    """Return stock context using only publication-gated canonical facts.

    Asset metadata is read from the canonical master table, while price,
    financial, and valuation values are read through Data Center Public Ports.
    A blocked dataset contributes no values and its stable gate evidence is
    retained in the row so callers can fail closed instead of mistaking an
    empty payload for a valid zero.
    """

    normalized_codes = [str(code).strip().upper() for code in stock_codes if code]
    if not normalized_codes:
        return {}

    requested_codes = list(dict.fromkeys(normalized_codes))
    master_map = get_equity_stock_repository().get_stock_master_rows(requested_codes)
    context: dict[str, dict[str, Any]] = {}
    for requested_code in requested_codes:
        master = master_map.get(requested_code, {})
        asset_code = str(master.get("asset_code") or requested_code).upper()
        price_payload: object = {}
        if include_price:
            price_payload = get_published_price_bar_series(
                asset_code,
                publication_key=publication_key,
                limit=1,
            )
        financial_payload = get_published_financial_facts(
            asset_code,
            publication_key=publication_key,
            limit=100,
        )
        valuation_payload = get_published_valuation_facts(
            asset_code,
            publication_key=publication_key,
            limit=1,
        )
        gates: dict[str, dict[str, object]] = {
            "financial": _payload_gate(financial_payload),
            "valuation": _payload_gate(valuation_payload),
        }
        if include_price:
            gates["price"] = _payload_gate(price_payload)
        blocked_gates = [gate for gate in gates.values() if gate.get("must_not_use_for_decision")]
        blocked_reason = next(
            (
                str(gate.get("blocked_reason") or "")
                for gate in blocked_gates
                if str(gate.get("blocked_reason") or "")
            ),
            "",
        )
        row: dict[str, Any] = {
            "name": str(master.get("name") or ""),
            "sector": str(master.get("sector") or ""),
            "market": str(master.get("market") or ""),
            "publication_gates": gates,
            "must_not_use_for_decision": bool(blocked_gates),
            "blocked_reason": blocked_reason or None,
        }
        missing_datasets = [
            dataset_name
            for dataset_name, payload in (
                [("financial", financial_payload), ("valuation", valuation_payload)]
                + ([("price", price_payload)] if include_price else [])
            )
            if not _payload_rows(payload)
        ]
        if missing_datasets and not blocked_gates:
            row["must_not_use_for_decision"] = True
            row["blocked_reason"] = "canonical_publication_members_missing"
            row["missing_datasets"] = missing_datasets
        if include_price:
            row.update(_published_price_context(price_payload))
        row.update(_published_financial_context(financial_payload))
        row.update(_published_valuation_context(valuation_payload))
        context[requested_code] = row
    return context


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
