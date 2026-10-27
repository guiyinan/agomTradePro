"""Typed request and response carrier for exact Tushare daily price bars."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Protocol, runtime_checkable

from apps.data_center.application.provider_response_payload import (
    ProviderResponsePayloadReference,
)
from apps.data_center.domain.entities import PriceBar
from apps.data_center.domain.enums import PriceAdjustment
from apps.data_center.domain.provider_response import ProviderResponseCapture
from core.exceptions import DataFetchError, TushareError
from shared.numeric import safe_float

_ASSET_CODE = re.compile(r"[0-9]{6}\.(?:SH|SZ|BJ)\Z")
TUSHARE_DAILY_VOLUME_MULTIPLIER_TO_SHARES = Decimal("100")
TUSHARE_DAILY_AMOUNT_MULTIPLIER_TO_CNY = Decimal("1000")


def _safe_decimal(value: object) -> Decimal | None:
    """Parse one finite decimal Tushare value, rejecting booleans and missing data."""

    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() else None


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


def _is_finite_exact_price_value(value: object) -> bool:
    """Accept only non-boolean finite numeric values on a captured PriceBar."""

    if value is None or isinstance(value, bool):
        return False
    parsed = safe_float(value)
    return parsed is not None and math.isfinite(parsed)


@dataclass(frozen=True, slots=True)
class ExactPriceBarRequestScope:
    """Bind one configured provider request to one canonical asset and day."""

    provider_id: int
    provider_name: str
    dataset_key: str
    api_name: str
    asset_code: str
    trade_date: date

    def __post_init__(self) -> None:
        """Reject request scopes that cannot identify one exact daily bar."""

        if isinstance(self.provider_id, bool) or not isinstance(self.provider_id, int):
            raise ValueError("provider_id must be an integer")
        if self.provider_id < 1:
            raise ValueError("provider_id must be positive")
        if (
            not isinstance(self.provider_name, str)
            or not self.provider_name.strip()
            or len(self.provider_name) > 100
        ):
            raise ValueError("provider_name must be bounded non-empty text")
        if self.dataset_key != "equity.price.bar" or self.api_name != "daily":
            raise ValueError("price-bar request scope is unsupported")
        if not isinstance(self.asset_code, str) or _ASSET_CODE.fullmatch(self.asset_code) is None:
            raise ValueError("asset_code must be one canonical A-share code")
        if type(self.trade_date) is not date:
            raise ValueError("trade_date must be a date")

    def request_params(self) -> dict[str, object]:
        """Return the exact safe API parameters, excluding transport credentials."""

        return {
            "provider_id": self.provider_id,
            "provider_name": self.provider_name,
            "api_name": self.api_name,
            "fields": "",
            "params": {
                "ts_code": self.asset_code,
                "trade_date": self.trade_date.strftime("%Y%m%d"),
            },
        }

    def to_payload(self) -> dict[str, object]:
        """Return safe request identity without response data or credentials."""

        return {
            "provider_id": self.provider_id,
            "provider_name": self.provider_name,
            "dataset_key": self.dataset_key,
            "api_name": self.api_name,
            "asset_code": self.asset_code,
            "trade_date": self.trade_date.isoformat(),
            "request_params": self.request_params(),
        }


@dataclass(frozen=True, slots=True)
class CapturedPriceBarResponse:
    """Carry one normalized daily bar with the exact bytes from that call."""

    request_scope: ExactPriceBarRequestScope
    bar: PriceBar
    capture: ProviderResponseCapture = field(repr=False)
    sensitive_values: tuple[str, ...] = field(default=(), repr=False)

    def __post_init__(self) -> None:
        """Require the bar identity and response capture to match the request."""

        if not isinstance(self.request_scope, ExactPriceBarRequestScope):
            raise TypeError("request_scope must be ExactPriceBarRequestScope")
        if not isinstance(self.bar, PriceBar):
            raise TypeError("bar must be PriceBar")
        if self.bar.asset_code != self.request_scope.asset_code:
            raise ValueError("price bar asset does not match request scope")
        if self.bar.bar_date != self.request_scope.trade_date:
            raise ValueError("price bar date does not match request scope")
        if not isinstance(self.capture, ProviderResponseCapture):
            raise TypeError("capture must be ProviderResponseCapture")
        if not self.capture.payload_matches_body():
            raise ValueError("captured response bytes do not match parsed payload")
        if any(not isinstance(value, str) or not value for value in self.sensitive_values):
            raise ValueError("sensitive_values must contain non-empty text")


def normalize_exact_tushare_price_bar(
    row: Mapping[str, object],
    *,
    scope: ExactPriceBarRequestScope,
    source: str,
    fetched_at: datetime,
) -> PriceBar:
    """Validate and normalize one captured Tushare row into canonical price units."""

    raw_prices = {key: _safe_decimal(row.get(key)) for key in ("open", "high", "low", "close")}
    if any(value is None or value <= 0 for value in raw_prices.values()):
        raise TushareError(
            "Exact Tushare daily OHLC values are missing or invalid",
            code="TUSHARE_EXACT_PRICE_RESPONSE_MISMATCH",
        )
    open_value = raw_prices["open"]
    high_value = raw_prices["high"]
    low_value = raw_prices["low"]
    close_value = raw_prices["close"]
    if open_value is None or high_value is None or low_value is None or close_value is None:
        raise TushareError(
            "Exact Tushare daily OHLC values are missing or invalid",
            code="TUSHARE_EXACT_PRICE_RESPONSE_MISMATCH",
        )
    if high_value < max(open_value, low_value, close_value) or low_value > min(
        open_value, high_value, close_value
    ):
        raise TushareError(
            "Exact Tushare daily OHLC range is inconsistent",
            code="TUSHARE_EXACT_PRICE_RESPONSE_MISMATCH",
        )

    volume_shares = _tushare_daily_volume_shares(row.get("vol"))
    amount_cny = _tushare_daily_amount_cny(row.get("amount"))
    if volume_shares is None or amount_cny is None:
        raise TushareError(
            "Exact Tushare daily volume or amount is missing or invalid",
            code="TUSHARE_EXACT_PRICE_RESPONSE_MISMATCH",
        )

    prices = tuple(safe_float(raw_prices[field]) for field in ("open", "high", "low", "close"))
    amount_value = safe_float(amount_cny)
    volume_value = safe_float(volume_shares)
    if (
        any(value is None for value in prices)
        or amount_value is None
        or volume_value is None
        or not math.isfinite(amount_value)
        or not math.isfinite(volume_value)
    ):
        raise TushareError(
            "Exact Tushare daily price values cannot be represented",
            code="TUSHARE_EXACT_PRICE_RESPONSE_MISMATCH",
        )
    open_float, high_float, low_float, close_float = prices
    if open_float is None or high_float is None or low_float is None or close_float is None:
        raise DataFetchError(
            "Exact Tushare daily price values cannot be represented",
            code="TUSHARE_EXACT_PRICE_RESPONSE_MISMATCH",
        )
    return PriceBar(
        asset_code=scope.asset_code,
        bar_date=scope.trade_date,
        open=open_float,
        high=high_float,
        low=low_float,
        close=close_float,
        volume=volume_value,
        amount=amount_value,
        source=source,
        fetched_at=fetched_at,
    )


def validate_exact_price_bar_capture(
    response: object,
    *,
    request_scope: ExactPriceBarRequestScope,
    source_type: str,
) -> CapturedPriceBarResponse:
    """Validate one normalized price bar against its exact request and body."""

    if not isinstance(response, CapturedPriceBarResponse):
        raise DataFetchError(
            "Exact daily price provider returned no typed capture",
            code="PRICE_EXACT_DAILY_CAPTURE_INVALID",
        )
    scope = response.request_scope
    capture = response.capture
    bar = response.bar
    expected_source = str(source_type or request_scope.provider_name).strip()
    if (
        scope != request_scope
        or bar.asset_code != request_scope.asset_code
        or bar.bar_date != request_scope.trade_date
        or bar.fetched_at != capture.response_completed_at
        or bar.source != expected_source
        or bar.freq != "1d"
        or bar.adjustment is not PriceAdjustment.NONE
        or bar.volume is None
        or bar.amount is None
        or not capture.payload_matches_body()
    ):
        raise DataFetchError(
            "Exact daily price capture does not match its configured request",
            code="PRICE_EXACT_DAILY_CAPTURE_SCOPE_MISMATCH",
        )
    if not all(
        _is_finite_exact_price_value(value)
        for value in (bar.open, bar.high, bar.low, bar.close, bar.volume, bar.amount)
    ):
        raise DataFetchError(
            "Exact daily normalized price bar contains an invalid numeric value",
            code="PRICE_EXACT_DAILY_CAPTURE_VALUE_MISMATCH",
        )

    payload = capture.payload_from_body()
    if not isinstance(payload, dict) or type(payload.get("code")) is not int:
        raise DataFetchError(
            "Exact daily price body has an invalid provider envelope",
            code="PRICE_EXACT_DAILY_CAPTURE_BODY_INVALID",
        )
    data = payload.get("data")
    if payload.get("code") != 0 or not isinstance(data, dict):
        raise DataFetchError(
            "Exact daily price body is not a successful provider response",
            code="PRICE_EXACT_DAILY_CAPTURE_BODY_INVALID",
        )
    fields = data.get("fields")
    rows = data.get("items")
    has_more = data.get("has_more", False)
    required_fields = {
        "ts_code",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "vol",
        "amount",
    }
    if (
        set(data) - {"fields", "items", "has_more"}
        or not isinstance(fields, list)
        or not all(isinstance(field_name, str) and field_name.strip() for field_name in fields)
        or len(set(fields)) != len(fields)
        or not required_fields.issubset(fields)
        or type(has_more) is not bool
        or has_more
        or not isinstance(rows, list)
        or len(rows) != 1
        or not isinstance(rows[0], list)
        or len(rows[0]) != len(fields)
    ):
        raise DataFetchError(
            "Exact daily price body is incomplete or outside the request shape",
            code="PRICE_EXACT_DAILY_CAPTURE_BODY_INVALID",
        )
    row = dict(zip(fields, rows[0], strict=True))
    if row.get("ts_code") != request_scope.asset_code or row.get(
        "trade_date"
    ) != request_scope.trade_date.strftime("%Y%m%d"):
        raise DataFetchError(
            "Exact daily price body identity differs from the request",
            code="PRICE_EXACT_DAILY_CAPTURE_BODY_SCOPE_MISMATCH",
        )
    normalized_bar = normalize_exact_tushare_price_bar(
        row,
        scope=request_scope,
        source=expected_source,
        fetched_at=capture.response_completed_at,
    )
    if bar != normalized_bar:
        raise DataFetchError(
            "Exact daily normalized price bar does not match its captured body",
            code="PRICE_EXACT_DAILY_CAPTURE_VALUE_MISMATCH",
        )
    return response


def validate_exact_price_bar_payload_reference(
    reference: ProviderResponsePayloadReference,
    *,
    captured_response: CapturedPriceBarResponse,
    run_id: str,
) -> None:
    """Require the retained body reference to match this response and sync run."""

    scope = captured_response.request_scope
    capture = captured_response.capture
    if not isinstance(reference, ProviderResponsePayloadReference) or (
        reference.provider_name != scope.provider_name
        or reference.dataset_key != scope.dataset_key
        or reference.body_sha256 != capture.body_sha256
        or reference.body_size_bytes != capture.body_size_bytes
        or reference.response_completed_at != capture.response_completed_at
        or reference.transport is not capture.transport
        or reference.run_id != run_id
    ):
        raise DataFetchError(
            "Exact daily RawPayload reference differs from its response or sync identity",
            code="PRICE_EXACT_DAILY_CAPTURE_REFERENCE_MISMATCH",
        )


@runtime_checkable
class ExactPriceBarResponseProviderProtocol(Protocol):
    """Optional provider capability for one exact daily price bar with bytes."""

    def fetch_price_bar_with_capture(
        self,
        asset_code: str,
        target_trade_date: date,
    ) -> CapturedPriceBarResponse:
        """Fetch one asset/session and return its exact response capture."""
        ...


__all__ = [
    "CapturedPriceBarResponse",
    "ExactPriceBarRequestScope",
    "ExactPriceBarResponseProviderProtocol",
    "normalize_exact_tushare_price_bar",
    "validate_exact_price_bar_capture",
    "validate_exact_price_bar_payload_reference",
]
