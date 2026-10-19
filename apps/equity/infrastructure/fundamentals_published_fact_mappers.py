"""Typed mapping from published Data Center fact rows to equity domain values."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from apps.data_center.domain.entities import FinancialFact, PriceBar, ValuationFact
from apps.data_center.domain.enums import FinancialPeriodType, PriceAdjustment
from apps.equity.domain.entities import ValuationMetrics
from apps.equity.infrastructure.fundamentals_fact_helpers import parse_fact_date as _parse_fact_date
from apps.equity.infrastructure.fundamentals_fact_helpers import (
    parse_fact_datetime as _parse_fact_datetime,
)
from shared.numeric import safe_float


def parse_public_price_bar(
    row: Mapping[str, object],
    default_asset_code: str,
) -> PriceBar | None:
    """Convert one publication-bound OHLCV row without fabricating time."""

    asset_code = str(row.get("asset_code") or default_asset_code).strip().upper()
    bar_date = _parse_fact_date(row.get("bar_date", row.get("timestamp")))
    fetched_at = _parse_fact_datetime(row.get("fetched_at"))
    if not asset_code or bar_date is None or fetched_at is None:
        return None

    def _number(field: str) -> float | None:
        return safe_float(row.get(field), default=None)

    open_price = _number("open")
    high = _number("high")
    low = _number("low")
    close = _number("close")
    if open_price is None or high is None or low is None or close is None:
        return None
    volume = _number("volume")
    amount = _number("amount")
    try:
        adjustment = PriceAdjustment(str(row.get("adjustment") or "none"))
        return PriceBar(
            asset_code=asset_code,
            bar_date=bar_date,
            open=open_price,
            high=high,
            low=low,
            close=close,
            freq=str(row.get("freq") or row.get("period") or "1d"),
            adjustment=adjustment,
            volume=volume,
            amount=amount,
            source=str(row.get("source") or ""),
            fetched_at=fetched_at,
        )
    except ValueError:
        return None


def parse_public_financial_fact(row: Mapping[str, object]) -> FinancialFact | None:
    """Convert a publication-bound financial row without fabricating timestamps."""

    asset_code = str(row.get("asset_code") or "").strip().upper()
    metric_code = str(row.get("metric_code") or "").strip()
    period_end = _parse_fact_date(row.get("period_end"))
    fetched_at = _parse_fact_datetime(row.get("fetched_at"))
    value = safe_float(row.get("value"), default=None)
    if not asset_code or not metric_code or period_end is None or fetched_at is None:
        return None
    if value is None:
        return None

    try:
        period_type = FinancialPeriodType(str(row.get("period_type") or ""))
    except ValueError:
        return None

    report_raw = row.get("report_date")
    report_date = _parse_fact_date(report_raw) if report_raw not in (None, "") else None
    available_raw = row.get("available_at")
    available_at = _parse_fact_datetime(available_raw) if available_raw not in (None, "") else None
    if report_raw not in (None, "") and report_date is None:
        return None
    if available_raw not in (None, "") and available_at is None:
        return None
    raw_extra = row.get("extra")
    extra: dict[str, Any] = raw_extra if isinstance(raw_extra, dict) else {}

    try:
        return FinancialFact(
            asset_code=asset_code,
            period_end=period_end,
            period_type=period_type,
            metric_code=metric_code,
            value=value,
            unit=str(row.get("unit") or ""),
            source=str(row.get("source") or ""),
            report_date=report_date,
            available_at=available_at,
            fetched_at=fetched_at,
            extra=extra,
        )
    except ValueError:
        return None


def parse_public_valuation_fact(row: Mapping[str, object]) -> ValuationFact | None:
    """Convert one publication-bound valuation row without fabricating time."""

    val_date = _parse_fact_date(row.get("val_date"))
    observed_raw = row.get("observed_at")
    observed_at = _parse_fact_datetime(observed_raw) if observed_raw not in (None, "") else None
    if observed_raw not in (None, "") and observed_at is None:
        return None
    fetched_at = _parse_fact_datetime(row.get("fetched_at"))
    if val_date is None or fetched_at is None:
        return None
    available_raw = row.get("available_at")
    available_at = _parse_fact_datetime(available_raw) if available_raw not in (None, "") else None
    if available_raw not in (None, "") and available_at is None:
        return None
    raw_extra = row.get("extra")
    extra: dict[str, Any] = raw_extra if isinstance(raw_extra, dict) else {}

    def _number(field: str) -> float | None:
        return safe_float(row.get(field), default=None)

    try:
        return ValuationFact(
            asset_code=str(row.get("asset_code") or "").strip().upper(),
            val_date=val_date,
            pe_ttm=_number("pe_ttm"),
            pe_static=_number("pe_static"),
            pb=_number("pb"),
            ps_ttm=_number("ps_ttm"),
            market_cap=_number("market_cap"),
            float_market_cap=_number("float_market_cap"),
            dv_ratio=_number("dv_ratio"),
            source=str(row.get("source") or ""),
            observed_at=observed_at,
            available_at=available_at,
            fetched_at=fetched_at,
            extra=extra,
        )
    except ValueError:
        return None


def valuation_metrics_from_fact(fact: ValuationFact) -> ValuationMetrics:
    """Map a published valuation fact while preserving source clocks and quality flags."""

    total_mv = Decimal(str(fact.market_cap)) if fact.market_cap is not None else None
    circ_mv = Decimal(str(fact.float_market_cap)) if fact.float_market_cap is not None else total_mv
    quality_is_complete = (
        all(
            value is not None
            for value in (
                fact.pe_ttm if fact.pe_ttm is not None else fact.pe_static,
                fact.pb,
                fact.market_cap,
            )
        )
        and fact.observed_at is not None
    )
    missing_source_observation = fact.observed_at is None
    return ValuationMetrics(
        stock_code=fact.asset_code,
        trade_date=fact.val_date,
        pe=fact.pe_ttm if fact.pe_ttm is not None else fact.pe_static,
        pb=fact.pb,
        ps=fact.ps_ttm,
        total_mv=total_mv,
        circ_mv=circ_mv,
        dividend_yield=fact.dv_ratio,
        source_provider=fact.source,
        source_updated_at=fact.observed_at,
        fetched_at=fact.fetched_at,
        pe_type="ttm" if fact.pe_ttm is not None else "static",
        is_valid=quality_is_complete,
        quality_flag=(
            "missing_source_observation"
            if missing_source_observation
            else ("ok" if quality_is_complete else "missing_required_metric")
        ),
        quality_notes=(
            "missing source observation timestamp"
            if missing_source_observation
            else ("" if quality_is_complete else "missing PE, PB, or market cap")
        ),
    )


__all__ = [
    "parse_public_price_bar",
    "parse_public_financial_fact",
    "parse_public_valuation_fact",
    "valuation_metrics_from_fact",
]
