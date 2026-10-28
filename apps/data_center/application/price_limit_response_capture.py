"""Typed exact response capture and replay contracts for provider price limits."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Protocol, cast, runtime_checkable

from apps.data_center.application.price_response_capture import (
    _ASSET_CODE,
    _bounded_decimal_parts,
)
from apps.data_center.application.provider_response_payload import (
    ProviderResponsePayloadReference,
)
from apps.data_center.domain.provider_response import (
    ProviderResponseCapture,
    parse_provider_response_json,
)
from apps.data_center.domain.raw_landing import RawPayload
from core.exceptions import DataFetchError

_DATASET_KEY = "equity.price.limit"
_API_NAME = "stk_limit"
_FIELDS = "ts_code,trade_date,down_limit,up_limit"
_REQUIRED_FIELDS = frozenset({"ts_code", "trade_date", "down_limit", "up_limit"})
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def _invalid(code: str, message: str) -> DataFetchError:
    """Build one stable error for malformed or mismatched price-limit evidence."""

    return DataFetchError(message, code=code)


def _strict_json_decimal(value: object, field_name: str) -> Decimal | None:
    """Accept only exact Decimal or integer tokens from the strict JSON parser."""

    if type(value) is Decimal:
        parsed = value
    elif type(value) is int:
        parsed = Decimal(value)
    else:
        return None
    try:
        _bounded_decimal_parts(parsed, field_name)
    except ValueError:
        return None
    return parsed


@dataclass(frozen=True, slots=True)
class ExactPriceLimitRequestScope:
    """Bind one configured ``stk_limit`` call to one provider, asset, and date."""

    provider_id: int
    provider_name: str
    dataset_key: str
    api_name: str
    asset_code: str
    trade_date: date

    def __post_init__(self) -> None:
        """Reject any request that does not identify one canonical Tushare row."""

        if type(self.provider_id) is not int or self.provider_id < 1:
            raise ValueError("provider_id must be a positive integer")
        if (
            type(self.provider_name) is not str
            or not self.provider_name.strip()
            or len(self.provider_name) > 100
        ):
            raise ValueError("provider_name must be bounded non-empty text")
        if self.dataset_key != _DATASET_KEY or self.api_name != _API_NAME:
            raise ValueError("price-limit request scope is unsupported")
        if type(self.asset_code) is not str or _ASSET_CODE.fullmatch(self.asset_code) is None:
            raise ValueError("asset_code must be one canonical Tushare security code")
        if type(self.trade_date) is not date:
            raise ValueError("trade_date must be a date")

    def request_params(self) -> dict[str, object]:
        """Return the exact credential-free Tushare call dimensions."""

        return {
            "provider_id": self.provider_id,
            "provider_name": self.provider_name,
            "api_name": _API_NAME,
            "fields": _FIELDS,
            "params": {
                "ts_code": self.asset_code,
                "trade_date": self.trade_date.strftime("%Y%m%d"),
            },
        }

    def to_payload(self) -> dict[str, object]:
        """Return this safe request identity for immutable evidence binding."""

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
class ExactPriceLimitValues:
    """Two exact positive provider-native limit prices, with no currency claim."""

    lower_limit_price: Decimal
    upper_limit_price: Decimal

    def __post_init__(self) -> None:
        """Reject inexact, nonfinite, nonpositive, or reversed price boundaries."""

        _bounded_decimal_parts(self.lower_limit_price, "lower_limit_price")
        _bounded_decimal_parts(self.upper_limit_price, "upper_limit_price")
        if self.lower_limit_price <= 0 or self.upper_limit_price <= 0:
            raise ValueError("price-limit values must be positive")
        if self.lower_limit_price > self.upper_limit_price:
            raise ValueError("lower price limit cannot exceed upper price limit")


@dataclass(frozen=True, slots=True)
class CapturedPriceLimitResponse:
    """Carry validated limits and the exact bytes from the same provider call."""

    request_scope: ExactPriceLimitRequestScope
    values: ExactPriceLimitValues
    capture: ProviderResponseCapture = field(repr=False)
    sensitive_values: tuple[str, ...] = field(default=(), repr=False)

    def __post_init__(self) -> None:
        """Require typed scope, values, capture, and credential-redaction hints."""

        if type(self.request_scope) is not ExactPriceLimitRequestScope:
            raise TypeError("request_scope must be ExactPriceLimitRequestScope")
        if type(self.values) is not ExactPriceLimitValues:
            raise TypeError("values must be ExactPriceLimitValues")
        if type(self.capture) is not ProviderResponseCapture:
            raise TypeError("capture must be ProviderResponseCapture")
        if not isinstance(self.sensitive_values, tuple) or any(
            type(value) is not str or not value for value in self.sensitive_values
        ):
            raise ValueError("sensitive_values must contain non-empty text")


@runtime_checkable
class ExactPriceLimitResponseProviderProtocol(Protocol):
    """Capability for one exact Tushare limit row with same-call response bytes."""

    def fetch_price_limit_with_capture(
        self,
        asset_code: str,
        target_trade_date: date,
    ) -> CapturedPriceLimitResponse:
        """Fetch one security/date limit row and return its original body capture."""
        ...


def _exact_price_limit_row(
    payload: object,
    *,
    scope: ExactPriceLimitRequestScope,
) -> dict[str, object]:
    """Validate one complete successful table envelope and return its scoped row."""

    if type(payload) is not dict or type(payload.get("code")) is not int:
        raise _invalid(
            "PRICE_EXACT_LIMIT_RESPONSE_INVALID",
            "Exact Tushare price-limit body has an invalid provider envelope",
        )
    response = cast(dict[str, object], payload)
    data_value = response.get("data")
    if response.get("code") != 0 or type(data_value) is not dict:
        raise _invalid(
            "PRICE_EXACT_LIMIT_RESPONSE_INVALID",
            "Exact Tushare price-limit body is not a successful table response",
        )
    data = cast(dict[str, object], data_value)
    fields_value = data.get("fields")
    items_value = data.get("items")
    has_more = data.get("has_more", False)
    if (
        set(data) - {"fields", "items", "has_more"}
        or type(fields_value) is not list
        or not all(type(name) is str and name.strip() for name in fields_value)
        or len(set(fields_value)) != len(fields_value)
        or set(fields_value) != _REQUIRED_FIELDS
        or type(has_more) is not bool
        or has_more
        or type(items_value) is not list
        or len(items_value) != 1
        or type(items_value[0]) is not list
        or len(items_value[0]) != len(fields_value)
    ):
        raise _invalid(
            "PRICE_EXACT_LIMIT_RESPONSE_INVALID",
            "Exact Tushare price-limit body is incomplete or non-unique",
        )
    fields = cast(list[str], fields_value)
    row_values = cast(list[object], items_value[0])
    row = dict(zip(fields, row_values, strict=True))
    if row.get("ts_code") != scope.asset_code or row.get("trade_date") != scope.trade_date.strftime(
        "%Y%m%d"
    ):
        raise _invalid(
            "PRICE_EXACT_LIMIT_SCOPE_MISMATCH",
            "Exact Tushare price-limit row differs from its request scope",
        )
    return row


def _same_decimal(left: Decimal, right: Decimal) -> bool:
    """Compare Decimal representations without treating scale changes as identical."""

    return left.as_tuple() == right.as_tuple()


def extract_exact_tushare_price_limit_values(
    payload: object,
    *,
    scope: ExactPriceLimitRequestScope,
) -> ExactPriceLimitValues:
    """Extract exact provider-native bounds from one strict parsed Tushare body.

    The caller must parse retained or captured response bytes with
    ``parse_provider_response_json`` before using this function. It returns
    numbers only and does not infer whether a security is tradable or has no
    price limit.
    """

    if type(scope) is not ExactPriceLimitRequestScope:
        raise TypeError("scope must be ExactPriceLimitRequestScope")
    row = _exact_price_limit_row(payload, scope=scope)
    lower = _strict_json_decimal(row.get("down_limit"), "down_limit")
    upper = _strict_json_decimal(row.get("up_limit"), "up_limit")
    if lower is None or upper is None or lower <= 0 or upper <= 0 or lower > upper:
        raise _invalid(
            "PRICE_EXACT_LIMIT_VALUES_INVALID",
            "Exact Tushare price-limit values are missing or invalid",
        )
    try:
        return ExactPriceLimitValues(
            lower_limit_price=lower,
            upper_limit_price=upper,
        )
    except (TypeError, ValueError) as error:
        raise _invalid(
            "PRICE_EXACT_LIMIT_VALUES_INVALID",
            "Exact Tushare price-limit values exceed the bounded representation",
        ) from error


def validate_exact_price_limit_capture(
    captured: object,
    *,
    scope: ExactPriceLimitRequestScope,
) -> CapturedPriceLimitResponse:
    """Revalidate exact scope, values, and body binding on one capture object."""

    if type(captured) is not CapturedPriceLimitResponse:
        raise _invalid(
            "PRICE_EXACT_LIMIT_CAPTURE_INVALID",
            "Exact price-limit provider returned no typed response capture",
        )
    response = captured
    if (
        response.request_scope != scope
        or not response.capture.payload_matches_body()
        or not response.capture.body
    ):
        raise _invalid(
            "PRICE_EXACT_LIMIT_CAPTURE_SCOPE_MISMATCH",
            "Exact price-limit capture does not match its configured request",
        )
    values = extract_exact_tushare_price_limit_values(
        response.capture.payload_from_body(), scope=scope
    )
    if not (
        _same_decimal(response.values.lower_limit_price, values.lower_limit_price)
        and _same_decimal(response.values.upper_limit_price, values.upper_limit_price)
    ):
        raise _invalid(
            "PRICE_EXACT_LIMIT_CAPTURE_VALUE_MISMATCH",
            "Normalized price limits differ from their captured response body",
        )
    return response


def validate_exact_price_limit_payload_reference(
    reference: ProviderResponsePayloadReference,
    *,
    scope: ExactPriceLimitRequestScope,
) -> None:
    """Require a RawPayload reference to identify an unredacted original limit body."""

    if type(reference) is not ProviderResponsePayloadReference:
        raise _invalid(
            "PRICE_EXACT_LIMIT_REFERENCE_INVALID",
            "Exact price-limit RawPayload reference is invalid",
        )
    if (
        reference.provider_name != scope.provider_name
        or reference.dataset_key != scope.dataset_key
        or reference.original_body_retained is not True
        or reference.retained_content_encoding != "exact_original_utf8_json"
        or reference.body_sha256 != reference.retained_content_sha256
        or reference.body_size_bytes < 1
        or _DIGEST.fullmatch(reference.body_sha256) is None
        or reference.response_completed_at.tzinfo is None
        or reference.response_completed_at.utcoffset() is None
    ):
        raise _invalid(
            "PRICE_EXACT_LIMIT_REFERENCE_SCOPE_MISMATCH",
            "Price-limit reference is not bound to this exact original response scope",
        )


def replay_exact_tushare_price_limit_values(
    raw_payload: RawPayload,
    reference: ProviderResponsePayloadReference,
    *,
    scope: ExactPriceLimitRequestScope,
) -> ExactPriceLimitValues:
    """Verify one retained original RawPayload and reconstruct its exact limits."""

    validate_exact_price_limit_payload_reference(reference, scope=scope)
    if type(raw_payload) is not RawPayload or not reference.verifies(raw_payload):
        raise _invalid(
            "PRICE_EXACT_LIMIT_REPLAY_REFERENCE_MISMATCH",
            "Retained price-limit RawPayload does not match its response reference",
        )
    if (
        raw_payload.provider_name != scope.provider_name
        or raw_payload.dataset_key != scope.dataset_key
        or raw_payload.fetched_at != reference.response_completed_at
        or raw_payload.request_params != scope.request_params()
    ):
        raise _invalid(
            "PRICE_EXACT_LIMIT_REPLAY_SCOPE_MISMATCH",
            "Retained price-limit request does not match its exact scope",
        )
    envelope = raw_payload.payload
    if (
        envelope.get("api_name") != scope.api_name
        or envelope.get("provider_name") != scope.provider_name
        or envelope.get("dataset_key") != scope.dataset_key
        or envelope.get("response_completed_at") != reference.response_completed_at.isoformat()
        or envelope.get("response_body_sha256") != reference.body_sha256
        or envelope.get("original_body_retained") is not True
        or envelope.get("retained_content_encoding") != "exact_original_utf8_json"
    ):
        raise _invalid(
            "PRICE_EXACT_LIMIT_REPLAY_SCOPE_MISMATCH",
            "Retained price-limit response metadata does not match its scope",
        )
    retained_text = envelope.get("retained_response_json")
    if type(retained_text) is not str:
        raise _invalid(
            "PRICE_EXACT_LIMIT_REPLAY_BODY_MISSING",
            "Retained original price-limit response body is missing",
        )
    retained_body = retained_text.encode("utf-8")
    if (
        len(retained_body) != reference.body_size_bytes
        or hashlib.sha256(retained_body).hexdigest() != reference.body_sha256
    ):
        raise _invalid(
            "PRICE_EXACT_LIMIT_REPLAY_BODY_HASH_MISMATCH",
            "Retained original price-limit response bytes differ from their reference",
        )
    try:
        payload = parse_provider_response_json(retained_body)
    except ValueError as error:
        raise _invalid(
            "PRICE_EXACT_LIMIT_REPLAY_JSON_INVALID",
            "Retained original price-limit response is not strict JSON",
        ) from error
    return extract_exact_tushare_price_limit_values(payload, scope=scope)


__all__ = [
    "CapturedPriceLimitResponse",
    "ExactPriceLimitRequestScope",
    "ExactPriceLimitResponseProviderProtocol",
    "ExactPriceLimitValues",
    "extract_exact_tushare_price_limit_values",
    "replay_exact_tushare_price_limit_values",
    "validate_exact_price_limit_capture",
    "validate_exact_price_limit_payload_reference",
]
