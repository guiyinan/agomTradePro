"""Pure Tushare row normalization shared by production and offline replay."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from apps.data_center.domain.entities import ValuationFact
from apps.data_center.domain.market_time import cn_market_session_close_utc
from apps.data_center.domain.rules import normalize_asset_code
from apps.data_center.infrastructure.market_gateway_entities import QuoteSnapshot
from shared.numeric import safe_float

TUSHARE_MARKET_CAP_MULTIPLIER_TO_CNY = 10_000.0
TUSHARE_DAILY_VOLUME_MULTIPLIER_TO_SHARES = Decimal("100")
TUSHARE_DAILY_AMOUNT_MULTIPLIER_TO_CNY = Decimal("1000")


class ResponseEvidenceLike(Protocol):
    """Minimal immutable evidence consumed by the valuation row mapper."""

    @property
    def body_sha256(self) -> str:
        """Return the digest of the exact provider response body."""

    @property
    def response_completed_at(self) -> datetime:
        """Return the local completion instant for the provider response."""

    @property
    def raw_payload_scope(self) -> str:
        """Return the documented scope covered by the body digest."""


def _safe_decimal(value: object) -> Decimal | None:
    """Parse one finite decimal provider value."""

    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return parsed if parsed.is_finite() else None


def _safe_int(value: object) -> int | None:
    """Parse one finite, nonnegative integral provider value."""

    parsed = safe_float(value)
    if parsed is None or parsed < 0 or not parsed.is_integer():
        return None
    return int(parsed)


def _tushare_daily_volume_shares(value: object) -> int | None:
    """Convert Tushare daily volume from lots (手) to canonical shares."""

    parsed = _safe_decimal(value)
    if parsed is None or parsed < 0:
        return None
    shares = parsed * TUSHARE_DAILY_VOLUME_MULTIPLIER_TO_SHARES
    return int(shares) if shares == shares.to_integral_value() else None


def _tushare_daily_amount_cny(value: object) -> Decimal | None:
    """Convert Tushare daily turnover from thousand CNY to canonical CNY."""

    parsed = _safe_decimal(value)
    if parsed is None or parsed < 0:
        return None
    return parsed * TUSHARE_DAILY_AMOUNT_MULTIPLIER_TO_CNY


def _optional_nonnegative_float(value: object) -> float | None:
    """Return one finite nonnegative provider value when valid."""

    parsed = safe_float(value)
    if parsed is None or parsed < 0:
        return None
    return parsed


def tushare_market_cap_cny(value: object) -> float | None:
    """Convert Tushare ``total_mv``/``circ_mv`` from 万元 to canonical 元."""

    parsed = _optional_nonnegative_float(value)
    return parsed * TUSHARE_MARKET_CAP_MULTIPLIER_TO_CNY if parsed is not None else None


def matches_tushare_market_cap_unit(raw_value: object, canonical_value: object) -> bool:
    """Check that a normalized market cap matches the declared 万元→元 rule."""

    expected = tushare_market_cap_cny(raw_value)
    actual = _optional_nonnegative_float(canonical_value)
    if expected is None:
        return actual is None
    return actual is not None and math.isclose(expected, actual, rel_tol=1e-12, abs_tol=1e-6)


def _first_present(row: Mapping[str, object], *keys: str) -> object:
    """Return the first provider field whose key is present."""

    for key in keys:
        if key in row:
            return row[key]
    return None


def _safe_date(value: object) -> date | None:
    """Parse the date representations accepted by existing provider adapters."""

    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if hasattr(value, "date"):
        try:
            parsed = value.date()
            return parsed if isinstance(parsed, date) else None
        except (TypeError, ValueError):
            return None
    text = str(value)
    for candidate in (text[:10], text[:8]):
        for fmt in ("%Y-%m-%d", "%Y%m%d"):
            try:
                return datetime.strptime(candidate, fmt).date()
            except (TypeError, ValueError):
                continue
    return None


def _parse_compact_quote_date(value: object) -> date | None:
    """Parse the strict YYYYMMDD date used by the Tushare daily endpoint."""

    text = str(value or "").strip()
    if len(text) != 8 or not text.isascii() or not text.isdigit():
        return None
    try:
        return datetime.strptime(text, "%Y%m%d").date()
    except ValueError:
        return None


def parse_tushare_daily_quote_rows(
    rows: Sequence[Mapping[str, object]],
    *,
    requested_asset_code: str,
    source: str,
    fetched_at: datetime,
    target_date: date | None = None,
) -> QuoteSnapshot | None:
    """Map the latest daily row, optionally requiring an exact replay date.

    Production passes no target date and retains the gateway's latest-row
    semantics. Offline replay supplies the target date so an older row cannot
    satisfy a requested session. The latest row is selected before value
    validation, matching the existing fail-closed behavior for a bad latest row.
    """

    if not rows:
        return None
    latest = max(rows, key=lambda row: str(row.get("trade_date") or ""))
    trade_date = _parse_compact_quote_date(latest.get("trade_date"))
    if trade_date is None or (target_date is not None and trade_date != target_date):
        return None
    price = _safe_decimal(latest.get("close"))
    if price is None or price <= 0:
        return None
    pre_close = _safe_decimal(latest.get("pre_close"))
    change = price - pre_close if pre_close is not None and pre_close > 0 else None
    change_pct = (
        float(change / pre_close * 100)
        if change is not None and pre_close is not None and pre_close > 0
        else None
    )
    return QuoteSnapshot(
        stock_code=requested_asset_code,
        price=price,
        change=change,
        change_pct=change_pct,
        volume=_tushare_daily_volume_shares(latest.get("vol")),
        amount=_tushare_daily_amount_cny(latest.get("amount")),
        turnover_rate=safe_float(latest.get("turnover_rate")),
        high=_safe_decimal(latest.get("high")),
        low=_safe_decimal(latest.get("low")),
        open=_safe_decimal(latest.get("open")),
        pre_close=pre_close,
        source=source,
        observed_at=cn_market_session_close_utc(trade_date),
        fetched_at=fetched_at,
    )


def _tushare_valuation_extra(
    base: Mapping[str, object],
    *,
    response_completed_at: datetime,
    response_evidence: ResponseEvidenceLike | None = None,
) -> dict[str, Any]:
    """Publish canonical market-cap units and local response knowledge time."""

    result: dict[str, Any] = {
        **base,
        "market_cap_original_unit": "万元",
        "market_cap_canonical_unit": "元",
        "market_cap_multiplier_to_storage": TUSHARE_MARKET_CAP_MULTIPLIER_TO_CNY,
        "availability_basis": "response_completed_utc",
        "response_completed_at": response_completed_at.isoformat(),
    }
    if response_evidence is not None:
        result["raw_payload_scope"] = response_evidence.raw_payload_scope
    return result


def _tushare_valuation_source_record_id(
    *, asset_code: str, val_date: date, evidence: ResponseEvidenceLike
) -> str:
    """Bind a valuation row to its batch body digest, not to invented row bytes."""

    return (
        f"tushare:daily_basic:{val_date.strftime('%Y%m%d')}:"
        f"{asset_code}:{evidence.body_sha256[:16]}"
    )


def map_tushare_daily_basic_row(
    row: Mapping[str, object],
    *,
    asset_code: str,
    source: str,
    provider_extra: Mapping[str, object],
    response_completed_at: datetime,
    response_evidence: ResponseEvidenceLike | None = None,
) -> ValuationFact | None:
    """Map one captured daily_basic row through the production valuation rules."""

    val_date = _safe_date(_first_present(row, "trade_date", "val_date"))
    if val_date is None:
        return None
    canonical_asset_code = normalize_asset_code(asset_code, "tushare")
    if not canonical_asset_code:
        return None
    return ValuationFact(
        asset_code=canonical_asset_code,
        val_date=val_date,
        pe_ttm=safe_float(_first_present(row, "pe_ttm", "pe")),
        pb=safe_float(_first_present(row, "pb")),
        ps_ttm=safe_float(_first_present(row, "ps_ttm", "ps")),
        market_cap=tushare_market_cap_cny(_first_present(row, "total_mv")),
        float_market_cap=tushare_market_cap_cny(_first_present(row, "circ_mv")),
        dv_ratio=safe_float(_first_present(row, "dv_ttm", "dv_ratio")),
        source=source,
        observed_at=cn_market_session_close_utc(val_date),
        available_at=response_completed_at,
        fetched_at=response_completed_at,
        extra=_tushare_valuation_extra(
            provider_extra,
            response_completed_at=response_completed_at,
            response_evidence=response_evidence,
        ),
        source_record_id=(
            _tushare_valuation_source_record_id(
                asset_code=canonical_asset_code,
                val_date=val_date,
                evidence=response_evidence,
            )
            if response_evidence is not None
            else ""
        ),
        raw_payload_hash=response_evidence.body_sha256 if response_evidence is not None else "",
    )


__all__ = [
    "TUSHARE_MARKET_CAP_MULTIPLIER_TO_CNY",
    "map_tushare_daily_basic_row",
    "matches_tushare_market_cap_unit",
    "parse_tushare_daily_quote_rows",
    "tushare_market_cap_cny",
]
