"""Exact single-security Tushare price response capture contracts."""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime
from decimal import Decimal, localcontext
from hashlib import sha256

import pytest

from apps.data_center.application.price_response_capture import (
    CapturedPriceBarResponse,
    ExactPriceBarRequestScope,
    ExactPriceBarValues,
    extract_exact_tushare_price_values,
    normalize_exact_tushare_price_bar,
    validate_exact_price_bar_capture,
)
from apps.data_center.domain.entities import PriceBar, ProviderConfig
from apps.data_center.domain.provider_response import (
    ProviderResponseCapture,
    ProviderResponseTransport,
    canonical_provider_response_json,
    parse_provider_response_json,
)
from apps.data_center.infrastructure import _provider_adapter_tushare as tushare_adapter_module
from apps.data_center.infrastructure import tushare_client, tushare_exact_price_capture
from apps.data_center.infrastructure._provider_adapter_tushare import (
    TushareUnifiedProviderAdapter,
)
from core.exceptions import DataFetchError, TushareError

_TARGET_DATE = date(2026, 9, 24)
_COMPLETED_AT = datetime(2026, 9, 24, 8, 10, tzinfo=UTC)
_FIELDS = ["ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount"]


def _row(
    asset_code: str = "600000.SH",
    *,
    trade_date: str = "20260924",
    open_price: object = 10.25,
    high_price: object = 12.75,
    low_price: object = 9.5,
    close_price: object = 12.5,
    volume: object = 250,
    amount: object = 123.45,
) -> dict[str, object]:
    """Build one raw Tushare daily row."""

    return {
        "ts_code": asset_code,
        "trade_date": trade_date,
        "open": open_price,
        "high": high_price,
        "low": low_price,
        "close": close_price,
        "vol": volume,
        "amount": amount,
    }


def _capture(
    rows: list[dict[str, object]], *, extra_data: dict[str, object] | None = None
) -> ProviderResponseCapture:
    """Build exact body bytes and payload from one Tushare response table."""

    data: dict[str, object] = {
        "fields": _FIELDS,
        "items": [[row.get(field) for field in _FIELDS] for row in rows],
    }
    if extra_data:
        data.update(extra_data)
    body = json.dumps({"code": 0, "data": data}, separators=(",", ":")).encode("utf-8")
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


def _exact_payload(
    rows: list[dict[str, object]], *, extra_data: dict[str, object] | None = None
) -> object:
    """Build strict parsed JSON while preserving exact Decimal number tokens."""

    data: dict[str, object] = {
        "fields": _FIELDS,
        "items": [[row.get(field) for field in _FIELDS] for row in rows],
    }
    if extra_data:
        data.update(extra_data)
    body = canonical_provider_response_json({"code": 0, "data": data}).encode("utf-8")
    return parse_provider_response_json(body)


def _scope() -> ExactPriceBarRequestScope:
    """Build one immutable exact request identity for direct extractor tests."""

    return ExactPriceBarRequestScope(
        provider_id=19,
        provider_name="provider-main",
        dataset_key="equity.price.bar",
        api_name="daily",
        asset_code="600000.SH",
        trade_date=_TARGET_DATE,
    )


class _Frame:
    """Minimal SDK frame carrying same-call capture metadata."""

    empty = False

    def __init__(
        self, rows: list[dict[str, object]], evidence: tushare_client.TushareResponseEvidence
    ) -> None:
        self._rows = rows
        self.response_evidence = evidence

    def to_dict(self, orient: str) -> list[dict[str, object]]:
        assert orient == "records"
        return self._rows


class _Pro:
    def __init__(self, frame: _Frame) -> None:
        self.frame = frame
        self.daily_calls: list[dict[str, str]] = []

    def daily(self, **params: str) -> _Frame:
        self.daily_calls.append(params)
        return self.frame


def _install_provider(
    monkeypatch: pytest.MonkeyPatch,
    rows: list[dict[str, object]],
    *,
    extra_data: dict[str, object] | None = None,
    frame_rows: list[dict[str, object]] | None = None,
) -> tuple[_Pro, list[dict[str, object]]]:
    """Install one fake configured client while recording factory arguments."""

    capture = _capture(rows, extra_data=extra_data)
    evidence = tushare_client.TushareResponseEvidence(
        body_sha256=capture.body_sha256,
        response_completed_at=capture.response_completed_at,
        response_capture=capture,
        sensitive_values=("provider-secret",),
    )
    pro = _Pro(_Frame(rows if frame_rows is None else frame_rows, evidence))
    factory_calls: list[dict[str, object]] = []

    def create_client(**kwargs: object) -> _Pro:
        factory_calls.append(kwargs)
        return pro

    monkeypatch.setattr(tushare_exact_price_capture, "create_tushare_pro_client", create_client)
    return pro, factory_calls


def _adapter() -> TushareUnifiedProviderAdapter:
    """Return a provider adapter bound to one explicit Tushare configuration."""

    config = ProviderConfig(
        id=19,
        name="provider-main",
        source_type="tushare",
        is_active=True,
        priority=1,
        api_key="provider-secret",
        api_secret="",
        http_url="https://relay.example.test/tushare/pro",
        api_endpoint="",
        extra_config={"tushare_request_mode": "unified_relay"},
        description="",
    )
    return TushareUnifiedProviderAdapter(config)


def test_exact_price_capture_binds_one_daily_call_and_canonical_units(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Capture bytes, source date, and normalized values from the exact same call."""

    pro, factory_calls = _install_provider(monkeypatch, [_row()])
    monkeypatch.setattr(tushare_adapter_module, "_deployment_region", lambda: "test-region")

    result = _adapter().fetch_price_bar_with_capture("600000.SH", _TARGET_DATE)

    assert isinstance(result, CapturedPriceBarResponse)
    assert result.request_scope == ExactPriceBarRequestScope(
        provider_id=19,
        provider_name="provider-main",
        dataset_key="equity.price.bar",
        api_name="daily",
        asset_code="600000.SH",
        trade_date=_TARGET_DATE,
    )
    assert isinstance(result.bar, PriceBar)
    assert result.bar.asset_code == "600000.SH"
    assert result.bar.bar_date == _TARGET_DATE
    assert (result.bar.open, result.bar.high, result.bar.low, result.bar.close) == (
        10.25,
        12.75,
        9.5,
        12.5,
    )
    assert result.bar.volume == 25_000.0
    assert result.bar.amount == 123_450.0
    assert result.bar.fetched_at == _COMPLETED_AT
    assert result.bar.source == "tushare"
    assert result.capture.body_sha256 == sha256(result.capture.body).hexdigest()
    assert result.sensitive_values == ("provider-secret",)
    assert pro.daily_calls == [{"ts_code": "600000.SH", "trade_date": "20260924"}]
    assert factory_calls == [
        {
            "token": "provider-secret",
            "http_url": "https://relay.example.test/tushare/pro",
            "request_mode": "unified_relay",
            "provider_id": 19,
            "deployment_region": "test-region",
            "dataset_key": "equity.price.bar",
            "capture_provider_responses": True,
        }
    ]


def test_exact_price_values_preserve_high_precision_decimal_source_values() -> None:
    """Direct extraction must never round legal source numbers through binary float."""

    open_value = Decimal("10.123456789012345678901234567890123456")
    high_value = Decimal("12.345678901234567890123456789012345678")
    low_value = Decimal("9.123456789012345678901234567890123456")
    close_value = Decimal("11.234567890123456789012345678901234567")
    amount_value = Decimal("1.234567890123456789012345678901")
    payload = _exact_payload(
        [
            _row(
                open_price=open_value,
                high_price=high_value,
                low_price=low_value,
                close_price=close_value,
                volume=Decimal("250.000000000000000000000000000000"),
                amount=amount_value,
            )
        ]
    )

    values = extract_exact_tushare_price_values(payload, request_scope=_scope())

    assert type(values) is ExactPriceBarValues
    assert values.open == open_value
    assert values.high == high_value
    assert values.low == low_value
    assert values.close == close_value
    assert values.volume == Decimal("25000")
    assert values.amount == Decimal("1234.567890123456789012345678901")
    assert all(
        type(value) is Decimal
        for value in (
            values.open,
            values.high,
            values.low,
            values.close,
            values.volume,
            values.amount,
        )
    )
    with pytest.raises(FrozenInstanceError):
        values.close = Decimal("11")


def test_exact_price_unit_conversion_ignores_low_ambient_decimal_context() -> None:
    """Lot and thousand-CNY multipliers must preserve every exact digit."""

    payload = _exact_payload(
        [
            _row(
                volume=Decimal("12345.67"),
                amount=Decimal("12345.6789"),
            )
        ]
    )

    with localcontext() as context:
        context.prec = 2
        values = extract_exact_tushare_price_values(payload, request_scope=_scope())

    assert values.volume == Decimal("1234567")
    assert values.amount == Decimal("12345678.9000")


@pytest.mark.parametrize(
    ("rows", "extra_data", "expected_code"),
    (
        (
            [_row(), _row()],
            None,
            "PRICE_EXACT_DAILY_CAPTURE_BODY_INVALID",
        ),
        (
            [_row()],
            {"has_more": True},
            "PRICE_EXACT_DAILY_CAPTURE_BODY_INVALID",
        ),
        (
            [_row()],
            {"unexpected": "extra response data"},
            "PRICE_EXACT_DAILY_CAPTURE_BODY_INVALID",
        ),
    ),
)
def test_exact_price_values_reject_repeated_truncated_or_extra_body_data(
    rows: list[dict[str, object]],
    extra_data: dict[str, object] | None,
    expected_code: str,
) -> None:
    """Direct exact extraction retains the single-complete-row body contract."""

    with pytest.raises(DataFetchError) as error:
        extract_exact_tushare_price_values(
            _exact_payload(rows, extra_data=extra_data),
            request_scope=_scope(),
        )

    assert error.value.code == expected_code


@pytest.mark.parametrize(
    "row",
    (
        _row("000001.SZ"),
        _row(trade_date="20260925"),
    ),
    ids=("wrong-security", "wrong-session"),
)
def test_exact_price_values_reject_body_outside_request_scope(
    row: dict[str, object],
) -> None:
    """Exact extraction cannot reuse another security or trading-session row."""

    with pytest.raises(DataFetchError) as error:
        extract_exact_tushare_price_values(_exact_payload([row]), request_scope=_scope())

    assert error.value.code == "PRICE_EXACT_DAILY_CAPTURE_BODY_SCOPE_MISMATCH"


@pytest.mark.parametrize(
    "row",
    (
        _row(open_price=None),
        _row(open_price=True),
        _row(close_price="NaN"),
        _row(high_price=9.0),
        _row(volume=-1),
        _row(volume=Decimal("0.001")),
        _row(amount=-1),
    ),
)
def test_exact_price_values_retain_numeric_and_whole_share_rejections(
    row: dict[str, object],
) -> None:
    """Missing, boolean, non-finite, inconsistent, and fractional-share rows fail."""

    with pytest.raises(TushareError) as error:
        extract_exact_tushare_price_values(_exact_payload([row]), request_scope=_scope())

    assert error.value.code == "TUSHARE_EXACT_PRICE_RESPONSE_MISMATCH"


def test_legacy_price_bar_normalizer_still_returns_float_ohlc_and_units() -> None:
    """The existing provider-facing PriceBar conversion remains float compatible."""

    bar = normalize_exact_tushare_price_bar(
        _row(),
        scope=_scope(),
        source="tushare",
        fetched_at=_COMPLETED_AT,
    )

    assert all(type(value) is float for value in (bar.open, bar.high, bar.low, bar.close))
    assert type(bar.volume) is float
    assert type(bar.amount) is float
    assert bar.volume == 25_000.0
    assert bar.amount == 123_450.0


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("open", True),
        ("high", None),
        ("low", float("inf")),
        ("volume", True),
        ("amount", float("nan")),
    ],
)
def test_exact_capture_rejects_invalid_normalized_bar_numbers(
    field_name: str, invalid_value: object
) -> None:
    """Invalid normalized values fail even when Python equality would match raw 1.0."""

    raw_row = _row(
        open_price=1,
        high_price=1,
        low_price=1,
        close_price=1,
        volume=0.01,
        amount=0.001,
    )
    scope = ExactPriceBarRequestScope(
        provider_id=19,
        provider_name="provider-main",
        dataset_key="equity.price.bar",
        api_name="daily",
        asset_code="600000.SH",
        trade_date=_TARGET_DATE,
    )
    normalized_bar = PriceBar(
        asset_code="600000.SH",
        bar_date=_TARGET_DATE,
        open=1.0,
        high=1.0,
        low=1.0,
        close=1.0,
        volume=1.0,
        amount=1.0,
        source="tushare",
        fetched_at=_COMPLETED_AT,
    )
    malformed_bar = replace(normalized_bar, **{field_name: invalid_value})
    captured = CapturedPriceBarResponse(
        request_scope=scope,
        bar=malformed_bar,
        capture=_capture([raw_row]),
    )

    with pytest.raises(DataFetchError):
        validate_exact_price_bar_capture(
            captured,
            request_scope=scope,
            source_type="tushare",
        )


@pytest.mark.parametrize(
    "rows",
    [
        [_row("000001.SZ")],
        [_row(trade_date="20260925")],
        [_row(), _row()],
        [_row(open_price=None)],
        [_row(high_price=10.0)],
        [_row(low_price=10.5)],
        [_row(close_price=True)],
        [_row(volume=-1)],
        [_row(amount="NaN")],
    ],
)
def test_exact_price_capture_rejects_out_of_scope_or_incomplete_rows(
    monkeypatch: pytest.MonkeyPatch,
    rows: list[dict[str, object]],
) -> None:
    """No fallback or partial row can satisfy the requested exact bar."""

    _install_provider(monkeypatch, rows)

    with pytest.raises(TushareError):
        _adapter().fetch_price_bar_with_capture("600000.SH", _TARGET_DATE)


def test_exact_price_capture_rejects_truncated_provider_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider table truncation cannot be accepted as a complete single row."""

    _install_provider(monkeypatch, [_row()], extra_data={"has_more": True})

    with pytest.raises(TushareError):
        _adapter().fetch_price_bar_with_capture("600000.SH", _TARGET_DATE)


@pytest.mark.parametrize(
    ("raw_row", "frame_changes"),
    [
        (_row(), {"close": 12.6}),
        (
            _row(
                open_price=1,
                high_price=2,
                low_price=0.5,
                close_price=1,
                volume=1,
                amount=1,
            ),
            {"open": True},
        ),
    ],
)
def test_exact_price_capture_rejects_frame_values_detached_from_raw_body(
    monkeypatch: pytest.MonkeyPatch,
    raw_row: dict[str, object],
    frame_changes: dict[str, object],
) -> None:
    """The same call's parsed frame cannot contradict its captured bytes."""

    frame_row = {**raw_row, **frame_changes}
    _install_provider(monkeypatch, [raw_row], frame_rows=[frame_row])

    with pytest.raises(TushareError):
        _adapter().fetch_price_bar_with_capture("600000.SH", _TARGET_DATE)
