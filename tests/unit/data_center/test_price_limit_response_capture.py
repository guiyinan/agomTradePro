"""Exact Decimal extraction and replay checks for Tushare price-limit evidence."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal, localcontext
from hashlib import sha256

import pytest

from apps.data_center.application.price_limit_response_capture import (
    ExactPriceLimitRequestScope,
    ExactPriceLimitValues,
    extract_exact_tushare_price_limit_values,
    replay_exact_tushare_price_limit_values,
    validate_exact_price_limit_payload_reference,
)
from apps.data_center.application.provider_response_payload import (
    ProviderResponsePayloadReference,
    RetainProviderResponsePayloadUseCase,
)
from apps.data_center.domain.provider_response import (
    ProviderResponseCapture,
    ProviderResponseTransport,
    canonical_provider_response_json,
    parse_provider_response_json,
)
from apps.data_center.domain.raw_landing import RawPayload
from core.exceptions import DataFetchError

_TRADE_DATE = date(2026, 9, 24)
_COMPLETED_AT = datetime(2026, 9, 24, 8, 10, tzinfo=UTC)
_FIELDS = ["ts_code", "trade_date", "down_limit", "up_limit"]


def _scope(
    *, asset_code: str = "600000.SH", trade_date: date = _TRADE_DATE
) -> ExactPriceLimitRequestScope:
    """Return one explicit provider, endpoint, security, and date scope."""

    return ExactPriceLimitRequestScope(
        provider_id=19,
        provider_name="provider-main",
        dataset_key="equity.price.limit",
        api_name="stk_limit",
        asset_code=asset_code,
        trade_date=trade_date,
    )


def _payload(
    *,
    asset_code: str = "600000.SH",
    trade_date: str = "20260924",
    lower: object = Decimal("9.50"),
    upper: object = Decimal("12.50"),
    fields: list[str] | None = None,
    rows: list[list[object]] | None = None,
    has_more: bool | None = False,
    extra_data: Mapping[str, object] | None = None,
    code: object = 0,
) -> object:
    """Build one strict parsed Tushare table payload without binary floats."""

    selected_fields = list(_FIELDS if fields is None else fields)
    selected_rows = [[asset_code, trade_date, lower, upper]] if rows is None else rows
    data: dict[str, object] = {"fields": selected_fields, "items": selected_rows}
    if has_more is not None:
        data["has_more"] = has_more
    if extra_data is not None:
        data.update(extra_data)
    body = canonical_provider_response_json({"code": code, "data": data}).encode("utf-8")
    return parse_provider_response_json(body)


def _body(payload: object | None = None) -> bytes:
    """Return exact UTF-8 response bytes for one parsed payload."""

    selected = _payload() if payload is None else payload
    return canonical_provider_response_json(selected).encode("utf-8")


class _RawRepository:
    """In-memory RawPayload store with immutable hash-addressed rows."""

    def __init__(self) -> None:
        self.rows: dict[str, RawPayload] = {}

    def save(self, payload: RawPayload) -> RawPayload:
        """Save an identical row or reject conflicting content at one hash."""

        existing = self.rows.get(payload.payload_hash)
        if existing is not None and existing != payload:
            raise ValueError("raw_payload_immutable_conflict")
        self.rows[payload.payload_hash] = payload
        return payload

    def get_by_hash(self, payload_hash: str) -> RawPayload | None:
        """Return one exact row by its retained content hash."""

        return self.rows.get(payload_hash)


def _capture(body: bytes) -> ProviderResponseCapture:
    """Bind exact bytes, strict parsed JSON, and a local completion clock."""

    return ProviderResponseCapture(
        body=body,
        payload=parse_provider_response_json(body),
        body_sha256=sha256(body).hexdigest(),
        body_size_bytes=len(body),
        response_completed_at=_COMPLETED_AT,
        status_code=200,
        content_type="application/json",
        transport=ProviderResponseTransport.EGRESS,
    )


def _retain(
    scope: ExactPriceLimitRequestScope,
    *,
    payload: object | None = None,
    api_name: str | None = None,
    request_params: Mapping[str, object] | None = None,
    sensitive_values: tuple[str, ...] = (),
) -> tuple[ProviderResponsePayloadReference, RawPayload]:
    """Retain one exact response through the existing RawPayload use case."""

    selected_payload = _payload() if payload is None else payload
    body = _body(selected_payload)
    repository = _RawRepository()
    reference = RetainProviderResponsePayloadUseCase(repository).execute(
        _capture(body),
        provider_name=scope.provider_name,
        dataset_key=scope.dataset_key,
        api_name=scope.api_name if api_name is None else api_name,
        request_params=scope.request_params() if request_params is None else request_params,
        sensitive_values=sensitive_values,
    )
    row = repository.get_by_hash(reference.payload_hash)
    assert row is not None
    return reference, row


def test_request_scope_uses_explicit_endpoint_and_exact_outer_request_shape() -> None:
    """The stored safe request identity matches the actual Tushare call inputs."""

    scope = _scope()

    assert scope.dataset_key == "equity.price.limit"
    assert scope.api_name == "stk_limit"
    assert scope.request_params() == {
        "provider_id": 19,
        "provider_name": "provider-main",
        "api_name": "stk_limit",
        "fields": "ts_code,trade_date,down_limit,up_limit",
        "params": {"ts_code": "600000.SH", "trade_date": "20260924"},
    }


@pytest.mark.parametrize(
    "updates",
    [
        {"provider_id": True},
        {"provider_id": 0},
        {"provider_name": ""},
        {"dataset_key": "equity.price.bar"},
        {"api_name": "daily"},
        {"asset_code": "600000"},
        {"trade_date": datetime(2026, 9, 24, tzinfo=UTC)},
    ],
)
def test_request_scope_rejects_invalid_or_noncanonical_identity(
    updates: dict[str, object],
) -> None:
    """A limit response can only be attached to one canonical request."""

    args: dict[str, object] = {
        "provider_id": 19,
        "provider_name": "provider-main",
        "dataset_key": "equity.price.limit",
        "api_name": "stk_limit",
        "asset_code": "600000.SH",
        "trade_date": _TRADE_DATE,
    }
    args.update(updates)

    with pytest.raises((TypeError, ValueError)):
        ExactPriceLimitRequestScope(**args)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("lower", "upper"),
    [
        (Decimal("0"), Decimal("1")),
        (Decimal("-0.01"), Decimal("1")),
        (Decimal("1"), Decimal("0")),
        (Decimal("1"), Decimal("-0.01")),
        (Decimal("NaN"), Decimal("2")),
        (Decimal("1"), Decimal("Infinity")),
        (1.0, Decimal("2")),
        (Decimal("1"), 2),
    ],
)
def test_exact_limit_values_reject_unknown_nonpositive_or_inexact_bounds(
    lower: object, upper: object
) -> None:
    """Only finite positive Decimal bounds in nondecreasing order are accepted."""

    with pytest.raises((TypeError, ValueError)):
        ExactPriceLimitValues(
            lower_limit_price=lower,  # type: ignore[arg-type]
            upper_limit_price=upper,  # type: ignore[arg-type]
        )


def test_exact_limit_values_preserve_high_precision_in_low_decimal_context() -> None:
    """DTO validation and comparison do not round bounds using ambient context."""

    lower = Decimal("9.123456789012345678901234567890123456789")
    upper = Decimal("12.987654321098765432109876543210987654321")

    with localcontext() as context:
        context.prec = 2
        values = ExactPriceLimitValues(lower_limit_price=lower, upper_limit_price=upper)

    assert values.lower_limit_price.as_tuple() == lower.as_tuple()
    assert values.upper_limit_price.as_tuple() == upper.as_tuple()


def test_extract_exact_price_limits_uses_scoped_body_decimals_without_rounding() -> None:
    """Strict parsed source values remain exact and preserve the requested identity."""

    lower = Decimal("9.123456789012345678901234567890123456789")
    upper = Decimal("12.987654321098765432109876543210987654321")
    payload = _payload(lower=lower, upper=upper)

    with localcontext() as context:
        context.prec = 2
        values = extract_exact_tushare_price_limit_values(payload, scope=_scope())

    assert type(values) is ExactPriceLimitValues
    assert values.lower_limit_price.as_tuple() == lower.as_tuple()
    assert values.upper_limit_price.as_tuple() == upper.as_tuple()


@pytest.mark.parametrize(
    ("lower", "upper"),
    [
        (None, Decimal("12.50")),
        ("", Decimal("12.50")),
        ("NaN", Decimal("12.50")),
        (Decimal("0"), Decimal("12.50")),
        (Decimal("-1"), Decimal("12.50")),
        (Decimal("9.50"), None),
        (Decimal("9.50"), "Infinity"),
        (Decimal("9.50"), Decimal("0")),
        (Decimal("13.00"), Decimal("12.50")),
        (True, Decimal("12.50")),
    ],
)
def test_extractor_blocks_missing_invalid_or_reversed_bounds(lower: object, upper: object) -> None:
    """Missing, empty, malformed, zero, negative, and reversed bounds never mean unbounded."""

    with pytest.raises(DataFetchError):
        extract_exact_tushare_price_limit_values(_payload(lower=lower, upper=upper), scope=_scope())


@pytest.mark.parametrize(
    "payload",
    [
        _payload(code=1),
        _payload(code=True),
        _payload(has_more=True),
        _payload(rows=[]),
        _payload(
            rows=[
                ["600000.SH", "20260924", Decimal("9.50"), Decimal("12.50")],
                ["600000.SH", "20260924", Decimal("9.50"), Decimal("12.50")],
            ]
        ),
        _payload(fields=["ts_code", "ts_code", "down_limit", "up_limit"]),
        _payload(extra_data={"unexpected": "value"}),
    ],
)
def test_extractor_rejects_bad_envelopes_duplicate_fields_and_nonunique_rows(
    payload: object,
) -> None:
    """Only one complete successful response row can provide exact boundaries."""

    with pytest.raises(DataFetchError):
        extract_exact_tushare_price_limit_values(payload, scope=_scope())


def test_extractor_and_replay_reject_fields_outside_the_requested_four() -> None:
    """Capture and replay enforce the same exact four-field source contract."""

    fields = [*_FIELDS, "pre_close"]
    payload = _payload(
        fields=fields,
        rows=[
            [
                "600000.SH",
                "20260924",
                Decimal("9.50"),
                Decimal("12.50"),
                Decimal("10.00"),
            ]
        ],
    )

    with pytest.raises(DataFetchError):
        extract_exact_tushare_price_limit_values(payload, scope=_scope())

    reference, row = _retain(_scope(), payload=payload)
    with pytest.raises(DataFetchError):
        replay_exact_tushare_price_limit_values(row, reference, scope=_scope())


@pytest.mark.parametrize("untrusted_number", [9.5, "9.50"])
def test_public_extractor_rejects_float_or_text_as_exact_json_numbers(
    untrusted_number: object,
) -> None:
    """Only strict-JSON Decimal and integer tokens can supply exact price values."""

    payload = {
        "code": 0,
        "data": {
            "fields": list(_FIELDS),
            "items": [["600000.SH", "20260924", untrusted_number, Decimal("12.50")]],
        },
    }

    with pytest.raises(DataFetchError):
        extract_exact_tushare_price_limit_values(payload, scope=_scope())


@pytest.mark.parametrize(
    ("asset_code", "trade_date"),
    [("000001.SZ", "20260924"), ("600000.SH", "20260925")],
)
def test_extractor_rejects_response_identity_outside_request_scope(
    asset_code: str, trade_date: str
) -> None:
    """A valid pair of prices cannot be rebound to a different security or day."""

    with pytest.raises(DataFetchError):
        extract_exact_tushare_price_limit_values(
            _payload(asset_code=asset_code, trade_date=trade_date), scope=_scope()
        )


def test_strict_json_rejects_duplicate_object_keys_and_nonstandard_numbers() -> None:
    """The original JSON parser rejects ambiguous keys and NaN/Infinity constants."""

    with pytest.raises(ValueError):
        parse_provider_response_json(b'{"code":0,"data":{"fields":[],"fields":[],"items":[]}}')
    for token in (b"NaN", b"Infinity", b"-Infinity"):
        with pytest.raises(ValueError):
            parse_provider_response_json(
                b'{"code":0,"data":{"fields":["ts_code","trade_date","down_limit","up_limit"],'
                b'"items":[["600000.SH","20260924",' + token + b",12.5]]}}"
            )


def test_payload_reference_and_replay_rebuild_values_from_original_raw_body() -> None:
    """A retained RawPayload reference replays exact scoped values after restart."""

    scope = _scope()
    reference, row = _retain(scope)

    validate_exact_price_limit_payload_reference(reference, scope=scope)
    values = replay_exact_tushare_price_limit_values(row, reference, scope=scope)

    assert reference.original_body_retained is True
    assert reference.retained_content_encoding == "exact_original_utf8_json"
    assert reference.body_sha256 == reference.retained_content_sha256
    assert reference.verifies(row)
    assert values == ExactPriceLimitValues(
        lower_limit_price=Decimal("9.50"), upper_limit_price=Decimal("12.50")
    )


def test_replay_rejects_redacted_original_even_when_generic_reference_verifies() -> None:
    """A redacted body cannot stand in for the exact original source response."""

    scope = _scope()
    payload = {
        "code": 0,
        "message": "secret-token-value",
        "data": {
            "fields": _FIELDS,
            "items": [["600000.SH", "20260924", Decimal("9.50"), Decimal("12.50")]],
        },
    }
    reference, row = _retain(
        scope,
        payload=payload,
        sensitive_values=("secret-token-value",),
    )

    assert reference.original_body_retained is False
    assert reference.verifies(row)
    with pytest.raises(DataFetchError):
        replay_exact_tushare_price_limit_values(row, reference, scope=scope)


@pytest.mark.parametrize("corruption", ["reference_hash", "row_hash", "request", "api"])
def test_replay_rejects_wrong_reference_hash_or_request_identity(corruption: str) -> None:
    """Generic reference validity does not replace endpoint and scope validation."""

    scope = _scope()
    reference, row = _retain(scope)
    changed_reference = reference
    changed_row = row
    if corruption == "reference_hash":
        changed_reference = replace(reference, body_sha256="f" * 64)
    elif corruption == "row_hash":
        changed_row = replace(
            row,
            payload={**row.payload, "response_body_sha256": "f" * 64},
        )
    elif corruption == "request":
        other_scope = _scope(asset_code="000001.SZ")
        changed_reference, changed_row = _retain(
            other_scope,
            request_params=other_scope.request_params(),
        )
    else:
        changed_reference, changed_row = _retain(scope, api_name="daily")

    with pytest.raises(DataFetchError):
        replay_exact_tushare_price_limit_values(changed_row, changed_reference, scope=scope)


def test_reference_scope_rejects_wrong_provider_or_dataset() -> None:
    """A response reference cannot cross the configured source identity."""

    scope = _scope()
    reference, _row = _retain(scope)
    wrong_scope = replace(scope, provider_name="other-provider")

    with pytest.raises(DataFetchError):
        validate_exact_price_limit_payload_reference(reference, scope=wrong_scope)
