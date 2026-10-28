"""Typed request and response carrier for exact Tushare daily price bars."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Protocol, cast, runtime_checkable

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
_MAX_DECIMAL_TEXT_LENGTH = 512
_MAX_DECIMAL_DIGITS = 256
_MAX_DECIMAL_EXPONENT = 512


def _safe_decimal(value: object) -> Decimal | None:
    """Parse one finite decimal Tushare value, rejecting booleans and missing data."""

    if value is None or isinstance(value, bool):
        return None
    try:
        text = str(value)
        if len(text) > _MAX_DECIMAL_TEXT_LENGTH:
            return None
        parsed = Decimal(text)
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not parsed.is_finite():
        return None
    parts = parsed.as_tuple()
    if (
        not isinstance(parts.exponent, int)
        or len(parts.digits) > _MAX_DECIMAL_DIGITS
        or abs(parts.exponent) > _MAX_DECIMAL_EXPONENT
    ):
        return None
    return parsed


def _bounded_decimal_parts(value: Decimal, field_name: str) -> tuple[int, int, int]:
    """Return sign, coefficient, and exponent for a bounded finite Decimal."""

    if type(value) is not Decimal or not value.is_finite():
        raise ValueError(f"{field_name} must be a finite Decimal")
    parts = value.as_tuple()
    if (
        not isinstance(parts.exponent, int)
        or len(parts.digits) > _MAX_DECIMAL_DIGITS
        or abs(parts.exponent) > _MAX_DECIMAL_EXPONENT
    ):
        raise ValueError(f"{field_name} exceeds the bounded Decimal representation")
    return parts.sign, int("".join(str(digit) for digit in parts.digits)), parts.exponent


def _decimal_times_integer(value: Decimal, multiplier: int, field_name: str) -> Decimal:
    """Multiply a bounded Decimal by an integer without Decimal context rounding."""

    sign, coefficient, exponent = _bounded_decimal_parts(value, field_name)
    scaled_coefficient = coefficient * multiplier
    digits = tuple(int(character) for character in str(scaled_coefficient))
    return Decimal((sign, digits, exponent))


def _integer_after_decimal_scale(value: Decimal, multiplier: int) -> int | None:
    """Return ``value * multiplier`` as an integer only when exactly integral."""

    sign, coefficient, exponent = _bounded_decimal_parts(value, "daily_volume")
    scaled_coefficient = coefficient * multiplier
    if exponent >= 0:
        integer_value = scaled_coefficient * int(10**exponent)
    else:
        divisor = int(10 ** (-exponent))
        integer_value, remainder = divmod(scaled_coefficient, divisor)
        if remainder:
            return None
    return -integer_value if sign else integer_value


def _tushare_daily_volume_shares(value: object) -> int | None:
    """Convert Tushare daily volume from lots (手) to canonical shares."""

    parsed = _safe_decimal(value)
    if parsed is None or parsed < 0:
        return None
    shares = _integer_after_decimal_scale(parsed, int(TUSHARE_DAILY_VOLUME_MULTIPLIER_TO_SHARES))
    if shares is None or len(str(abs(shares))) > _MAX_DECIMAL_DIGITS:
        return None
    return shares


def _tushare_daily_amount_cny(value: object) -> Decimal | None:
    """Convert Tushare daily turnover from thousand CNY to canonical CNY."""

    parsed = _safe_decimal(value)
    if parsed is None or parsed < 0:
        return None
    amount = _decimal_times_integer(
        parsed,
        int(TUSHARE_DAILY_AMOUNT_MULTIPLIER_TO_CNY),
        "daily_amount",
    )
    try:
        _bounded_decimal_parts(amount, "daily_amount_cny")
    except ValueError:
        return None
    return amount


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
class ExactPriceBarValues:
    """Canonical exact OHLC prices, whole shares, and CNY turnover from one row."""

    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    amount: Decimal

    def __post_init__(self) -> None:
        """Reject inexact types, unbounded numbers, invalid OHLC, or fractional shares."""

        for field_name, value in (
            ("open", self.open),
            ("high", self.high),
            ("low", self.low),
            ("close", self.close),
            ("volume", self.volume),
            ("amount", self.amount),
        ):
            _bounded_decimal_parts(value, field_name)
        if any(value <= 0 for value in (self.open, self.high, self.low, self.close)):
            raise ValueError("exact price OHLC values must be positive")
        if self.high < max(self.open, self.low, self.close) or self.low > min(
            self.open, self.high, self.close
        ):
            raise ValueError("exact price OHLC range is inconsistent")
        if self.volume < 0 or _integer_after_decimal_scale(self.volume, 1) is None:
            raise ValueError("exact price volume must be nonnegative whole shares")
        if self.amount < 0:
            raise ValueError("exact price amount must be nonnegative CNY")


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


def _exact_price_values_from_row(row: Mapping[str, object]) -> ExactPriceBarValues:
    """Validate one source row and convert its values to exact canonical units."""

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
    try:
        return ExactPriceBarValues(
            open=open_value,
            high=high_value,
            low=low_value,
            close=close_value,
            volume=Decimal(volume_shares),
            amount=amount_cny,
        )
    except ValueError as error:
        raise TushareError(
            "Exact Tushare daily values exceed the bounded numeric representation",
            code="TUSHARE_EXACT_PRICE_RESPONSE_MISMATCH",
        ) from error


def _price_bar_from_values(
    values: ExactPriceBarValues,
    *,
    scope: ExactPriceBarRequestScope,
    source: str,
    fetched_at: datetime,
) -> PriceBar:
    """Convert exact canonical values to the legacy float-based PriceBar."""

    prices = tuple(
        safe_float(value) for value in (values.open, values.high, values.low, values.close)
    )
    amount_value = safe_float(values.amount)
    volume_value = safe_float(values.volume)
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


def _exact_price_row_from_payload(
    payload: object,
    *,
    request_scope: ExactPriceBarRequestScope,
) -> dict[str, object]:
    """Validate one complete response envelope and return its exact scoped row."""

    if not isinstance(payload, dict) or type(payload.get("code")) is not int:
        raise DataFetchError(
            "Exact daily price body has an invalid provider envelope",
            code="PRICE_EXACT_DAILY_CAPTURE_BODY_INVALID",
        )
    payload_object = cast(dict[str, object], payload)
    data_value = payload_object.get("data")
    if payload_object.get("code") != 0 or not isinstance(data_value, dict):
        raise DataFetchError(
            "Exact daily price body is not a successful provider response",
            code="PRICE_EXACT_DAILY_CAPTURE_BODY_INVALID",
        )
    data = cast(dict[str, object], data_value)
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
    field_names = cast(list[str], fields)
    row_values = cast(list[object], rows[0])
    row = dict(zip(field_names, row_values, strict=True))
    if row.get("ts_code") != request_scope.asset_code or row.get(
        "trade_date"
    ) != request_scope.trade_date.strftime("%Y%m%d"):
        raise DataFetchError(
            "Exact daily price body identity differs from the request",
            code="PRICE_EXACT_DAILY_CAPTURE_BODY_SCOPE_MISMATCH",
        )
    return row


def extract_exact_tushare_price_values(
    payload: object,
    *,
    request_scope: ExactPriceBarRequestScope,
) -> ExactPriceBarValues:
    """Extract exact canonical values from a strict parsed Tushare daily body.

    The caller must parse retained bytes with ``parse_provider_response_json``
    before calling this function. This value contains normalized numbers only;
    it does not prove source eligibility, freshness, or execution suitability.
    """

    if not isinstance(request_scope, ExactPriceBarRequestScope):
        raise TypeError("request_scope must be ExactPriceBarRequestScope")
    row = _exact_price_row_from_payload(payload, request_scope=request_scope)
    return _exact_price_values_from_row(row)


def normalize_exact_tushare_price_bar(
    row: Mapping[str, object],
    *,
    scope: ExactPriceBarRequestScope,
    source: str,
    fetched_at: datetime,
) -> PriceBar:
    """Validate and normalize one captured Tushare row into canonical price units."""

    values = _exact_price_values_from_row(row)
    return _price_bar_from_values(
        values,
        scope=scope,
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
    values = extract_exact_tushare_price_values(payload, request_scope=request_scope)
    normalized_bar = _price_bar_from_values(
        values,
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
    "ExactPriceBarValues",
    "ExactPriceBarRequestScope",
    "ExactPriceBarResponseProviderProtocol",
    "extract_exact_tushare_price_values",
    "normalize_exact_tushare_price_bar",
    "validate_exact_price_bar_capture",
    "validate_exact_price_bar_payload_reference",
]
