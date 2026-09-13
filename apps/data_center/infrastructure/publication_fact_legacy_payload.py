"""Deterministic legacy normalized-row digests used by fact producers.

These fallbacks preserve the existing source-hash bytes when a source body
digest is unavailable. They describe normalized fact fields and never claim
to be an HTTP response-body hash.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime

from .models import (
    CapitalFlowFactModel,
    FinancialFactModel,
    FundNavFactModel,
    MacroFactModel,
    PriceBarModel,
    QuoteSnapshotModel,
    SectorMembershipFactModel,
    ValuationFactModel,
)


def canonical_news_payload_hash(
    *,
    asset_code: str,
    title: str,
    summary: str,
    url: str,
    published_at: datetime,
    source: str,
    external_id: str,
) -> str:
    """Return the existing deterministic fallback digest for a news row."""

    payload: dict[str, object] = {
        "asset_code": asset_code,
        "title": title,
        "summary": summary,
        "url": url,
        "published_at": str(published_at),
        "source": source,
        "external_id": external_id,
    }
    return _sha256_json(payload)


def financial_payload_hash(row: FinancialFactModel) -> str:
    """Return the existing deterministic financial fallback digest."""

    payload: dict[str, object] = {
        "asset_code": row.asset_code,
        "period_end": row.period_end.isoformat(),
        "period_type": row.period_type,
        "metric_code": row.metric_code,
        "value": str(row.value),
        "unit": row.unit,
        "source": row.source,
        "report_date": row.report_date.isoformat() if row.report_date else None,
        "available_at": row.available_at.isoformat() if row.available_at else None,
    }
    return _sha256_json(payload)


def fund_nav_payload_hash(row: FundNavFactModel) -> str:
    """Return the existing deterministic fund-NAV fallback digest."""

    payload: dict[str, object] = {
        "fund_code": row.fund_code,
        "nav_date": row.nav_date.isoformat(),
        "nav": str(row.nav),
        "acc_nav": str(row.acc_nav) if row.acc_nav is not None else None,
        "daily_return": str(row.daily_return) if row.daily_return is not None else None,
        "source": row.source,
    }
    return _sha256_json(payload)


def macro_payload_hash(row: MacroFactModel) -> str:
    """Return the existing deterministic macro fallback digest."""

    payload: dict[str, object] = {
        "indicator_code": row.indicator_code,
        "reporting_period": row.reporting_period.isoformat(),
        "value": str(row.value),
        "unit": row.unit,
        "source": row.source,
        "revision_number": row.revision_number,
        "published_at": row.published_at.isoformat() if row.published_at else None,
        "quality": row.quality,
    }
    return _sha256_json(payload)


def price_bar_payload_hash(row: PriceBarModel) -> str:
    """Return the existing deterministic price-bar fallback digest."""

    payload: dict[str, object] = {
        "asset_code": row.asset_code,
        "bar_date": row.bar_date.isoformat(),
        "freq": row.freq,
        "adjustment": row.adjustment,
        "open": str(row.open),
        "high": str(row.high),
        "low": str(row.low),
        "close": str(row.close),
        "volume": str(row.volume) if row.volume is not None else None,
        "amount": str(row.amount) if row.amount is not None else None,
        "source": row.source,
    }
    return _sha256_json(payload)


def quote_snapshot_payload_hash(row: QuoteSnapshotModel) -> str:
    """Return the existing deterministic quote fallback digest."""

    payload: dict[str, object] = {
        "asset_code": row.asset_code,
        "snapshot_at": row.snapshot_at.isoformat(),
        "current_price": str(row.current_price),
        "open": str(row.open) if row.open is not None else None,
        "high": str(row.high) if row.high is not None else None,
        "low": str(row.low) if row.low is not None else None,
        "prev_close": str(row.prev_close) if row.prev_close is not None else None,
        "volume": str(row.volume) if row.volume is not None else None,
        "amount": str(row.amount) if row.amount is not None else None,
        "bid": str(row.bid) if row.bid is not None else None,
        "ask": str(row.ask) if row.ask is not None else None,
        "source": row.source,
    }
    return _sha256_json(payload)


def capital_flow_payload_hash(row: CapitalFlowFactModel) -> str:
    """Return the existing deterministic capital-flow fallback digest."""

    payload: dict[str, object] = {
        "asset_code": row.asset_code,
        "flow_date": row.flow_date.isoformat(),
        "main_net": str(row.main_net) if row.main_net is not None else None,
        "retail_net": str(row.retail_net) if row.retail_net is not None else None,
        "super_large_net": str(row.super_large_net) if row.super_large_net is not None else None,
        "large_net": str(row.large_net) if row.large_net is not None else None,
        "medium_net": str(row.medium_net) if row.medium_net is not None else None,
        "small_net": str(row.small_net) if row.small_net is not None else None,
        "source": row.source,
    }
    return _sha256_json(payload)


def sector_membership_payload_hash(row: SectorMembershipFactModel) -> str:
    """Return the existing deterministic membership fallback digest."""

    payload: dict[str, object] = {
        "asset_code": row.asset_code,
        "sector_code": row.sector_code,
        "sector_name": row.sector_name,
        "effective_date": row.effective_date.isoformat(),
        "expiry_date": row.expiry_date.isoformat() if row.expiry_date else None,
        "weight": str(row.weight) if row.weight is not None else None,
        "source": row.source,
    }
    return _sha256_json(payload)


def valuation_payload_hash(row: ValuationFactModel) -> str:
    """Return the existing deterministic valuation fallback digest."""

    payload: dict[str, object] = {
        "asset_code": row.asset_code,
        "val_date": row.val_date.isoformat(),
        "pe_ttm": str(row.pe_ttm) if row.pe_ttm is not None else None,
        "pe_static": str(row.pe_static) if row.pe_static is not None else None,
        "pb": str(row.pb) if row.pb is not None else None,
        "ps_ttm": str(row.ps_ttm) if row.ps_ttm is not None else None,
        "market_cap": str(row.market_cap) if row.market_cap is not None else None,
        "float_market_cap": str(row.float_market_cap) if row.float_market_cap is not None else None,
        "dv_ratio": str(row.dv_ratio) if row.dv_ratio is not None else None,
        "source": row.source,
        "observed_at": row.observed_at.isoformat() if row.observed_at else None,
        "available_at": row.available_at.isoformat() if row.available_at else None,
    }
    return _sha256_json(payload)


def _sha256_json(payload: Mapping[str, object]) -> str:
    """Hash one deterministic JSON payload using the legacy encoding."""

    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "canonical_news_payload_hash",
    "capital_flow_payload_hash",
    "financial_payload_hash",
    "fund_nav_payload_hash",
    "macro_payload_hash",
    "price_bar_payload_hash",
    "quote_snapshot_payload_hash",
    "sector_membership_payload_hash",
    "valuation_payload_hash",
]
