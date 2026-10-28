"""Capture and scope checks for one exact Tushare ``stk_limit`` response."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256

import pytest

from apps.data_center.application.price_limit_response_capture import (
    CapturedPriceLimitResponse,
    ExactPriceLimitRequestScope,
    ExactPriceLimitValues,
    validate_exact_price_limit_capture,
)
from apps.data_center.domain.entities import ProviderConfig
from apps.data_center.domain.provider_response import (
    ProviderResponseCapture,
    ProviderResponseTransport,
    canonical_provider_response_json,
    parse_provider_response_json,
)
from apps.data_center.infrastructure import tushare_client, tushare_exact_price_limit_capture
from apps.data_center.infrastructure._provider_adapter_tushare import (
    TushareUnifiedProviderAdapter,
)
from core.exceptions import DataFetchError, TushareError

_TRADE_DATE = date(2026, 9, 24)
_COMPLETED_AT = datetime(2026, 9, 24, 8, 10, tzinfo=UTC)
_FIELDS = ["ts_code", "trade_date", "down_limit", "up_limit"]


def _scope() -> ExactPriceLimitRequestScope:
    """Build the exact provider request identity used by the test fixture."""

    return ExactPriceLimitRequestScope(
        provider_id=19,
        provider_name="provider-main",
        dataset_key="equity.price.limit",
        api_name="stk_limit",
        asset_code="600000.SH",
        trade_date=_TRADE_DATE,
    )


def _config() -> ProviderConfig:
    """Return one active configured Tushare source without reading secrets."""

    return ProviderConfig(
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


def _row(
    *,
    asset_code: str = "600000.SH",
    trade_date: str = "20260924",
    lower: object = Decimal("9.50"),
    upper: object = Decimal("12.50"),
) -> dict[str, object]:
    """Return one Tushare limit row with source-native decimal prices."""

    return {
        "ts_code": asset_code,
        "trade_date": trade_date,
        "down_limit": lower,
        "up_limit": upper,
    }


def _make_capture(
    rows: list[dict[str, object]],
    *,
    fields: list[str] | None = None,
    extra_data: dict[str, object] | None = None,
    code: object = 0,
) -> ProviderResponseCapture:
    """Encode one exact response body and its strict parsed values."""

    selected_fields = list(_FIELDS if fields is None else fields)
    data: dict[str, object] = {
        "fields": selected_fields,
        "items": [[row.get(field) for field in selected_fields] for row in rows],
    }
    if extra_data:
        data.update(extra_data)
    body = canonical_provider_response_json({"code": code, "data": data}).encode("utf-8")
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


class _Frame:
    """Small SDK frame stand-in carrying same-call response evidence."""

    def __init__(
        self,
        rows: list[dict[str, object]],
        evidence: tushare_client.TushareResponseEvidence | None,
    ) -> None:
        self.empty = not rows
        self._rows = rows
        self.response_evidence = evidence

    def to_dict(self, orient: str) -> list[dict[str, object]]:
        """Return the SDK-shaped records for the configured orientation."""

        assert orient == "records"
        return self._rows


class _Pro:
    """Fake dynamic Tushare client that records one ``stk_limit`` call."""

    def __init__(self, frame: _Frame) -> None:
        self.frame = frame
        self.stk_limit_calls: list[dict[str, object]] = []

    def stk_limit(self, **params: object) -> _Frame:
        """Return the captured frame without making a network request."""

        self.stk_limit_calls.append(params)
        return self.frame


def _install_provider(
    monkeypatch: pytest.MonkeyPatch,
    body_rows: list[dict[str, object]],
    *,
    frame_rows: list[dict[str, object]] | None = None,
    fields: list[str] | None = None,
    extra_data: dict[str, object] | None = None,
    evidence_available: bool = True,
) -> tuple[_Pro, list[dict[str, object]]]:
    """Install one fake client and capture configured factory arguments."""

    capture = _make_capture(body_rows, fields=fields, extra_data=extra_data)
    evidence = (
        tushare_client.TushareResponseEvidence(
            body_sha256=capture.body_sha256,
            response_completed_at=capture.response_completed_at,
            response_capture=capture,
            sensitive_values=("provider-secret",),
        )
        if evidence_available
        else None
    )
    pro = _Pro(_Frame(body_rows if frame_rows is None else frame_rows, evidence))
    factory_calls: list[dict[str, object]] = []

    def create_client(**kwargs: object) -> _Pro:
        """Record construction parameters and return the isolated fake client."""

        factory_calls.append(kwargs)
        return pro

    monkeypatch.setattr(
        tushare_exact_price_limit_capture,
        "create_tushare_pro_client",
        create_client,
    )
    return pro, factory_calls


def _fetch() -> CapturedPriceLimitResponse:
    """Call the exact capture entry with one explicit configured provider."""

    return tushare_exact_price_limit_capture.fetch_exact_tushare_price_limit(
        _config(),
        asset_code="600000.SH",
        target_trade_date=_TRADE_DATE,
        deployment_region="test-region",
        request_mode="unified_relay",
    )


def test_exact_capture_uses_one_scoped_call_and_returns_body_bound_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exact API parameters, provider route, values, and body share one capture."""

    pro, factory_calls = _install_provider(monkeypatch, [_row()])

    result = _fetch()

    assert result.request_scope == _scope()
    assert result.values == ExactPriceLimitValues(
        lower_limit_price=Decimal("9.50"),
        upper_limit_price=Decimal("12.50"),
    )
    assert result.capture.body_sha256 == sha256(result.capture.body).hexdigest()
    assert result.capture.response_completed_at == _COMPLETED_AT
    assert result.capture.transport is ProviderResponseTransport.EGRESS
    assert pro.stk_limit_calls == [
        {
            "ts_code": "600000.SH",
            "trade_date": "20260924",
            "fields": "ts_code,trade_date,down_limit,up_limit",
        }
    ]
    assert factory_calls == [
        {
            "token": "provider-secret",
            "http_url": "https://relay.example.test/tushare/pro",
            "request_mode": "unified_relay",
            "provider_id": 19,
            "deployment_region": "test-region",
            "dataset_key": "equity.price.limit",
            "capture_provider_responses": True,
        }
    ]


def test_capture_request_params_bind_the_complete_sanitized_tushare_outer_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The replay scope includes API name, explicit fields, and exact query params."""

    _install_provider(monkeypatch, [_row()])

    result = _fetch()

    assert result.request_scope.request_params() == {
        "provider_id": 19,
        "provider_name": "provider-main",
        "api_name": "stk_limit",
        "fields": "ts_code,trade_date,down_limit,up_limit",
        "params": {"ts_code": "600000.SH", "trade_date": "20260924"},
    }


def test_capture_validator_rechecks_values_against_original_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A typed capture cannot replace the normalized values after the request."""

    _install_provider(monkeypatch, [_row()])
    result = _fetch()
    changed = CapturedPriceLimitResponse(
        request_scope=result.request_scope,
        values=ExactPriceLimitValues(
            lower_limit_price=Decimal("9.49"),
            upper_limit_price=Decimal("12.50"),
        ),
        capture=result.capture,
        sensitive_values=result.sensitive_values,
    )

    with pytest.raises(DataFetchError):
        validate_exact_price_limit_capture(changed, scope=_scope())


def test_exact_capture_preserves_long_decimal_values_and_rejects_sdk_float_rounding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Long decimals come from response bytes; an inexact SDK float cannot certify them."""

    lower = Decimal("9.123456789012345678901234567890123456789")
    upper = Decimal("12.987654321098765432109876543210987654321")
    _install_provider(
        monkeypatch,
        [_row(lower=lower, upper=upper)],
        frame_rows=[_row(lower=lower, upper=upper)],
    )

    result = _fetch()

    assert result.values.lower_limit_price.as_tuple() == lower.as_tuple()
    assert result.values.upper_limit_price.as_tuple() == upper.as_tuple()

    _install_provider(
        monkeypatch,
        [_row(lower=lower, upper=upper)],
        frame_rows=[_row(lower=float(lower), upper=float(upper))],
    )
    with pytest.raises((DataFetchError, TushareError)):
        _fetch()


@pytest.mark.parametrize(
    ("body_rows", "frame_rows", "extra_data"),
    [
        ([], [], None),
        ([_row(), _row()], [_row(), _row()], None),
        ([_row()], [_row(lower=Decimal("9.49"))], None),
        ([_row()], [_row()], {"has_more": True}),
        ([_row(asset_code="000001.SZ")], [_row(asset_code="000001.SZ")], None),
        ([_row(trade_date="20260925")], [_row(trade_date="20260925")], None),
    ],
)
def test_exact_capture_rejects_empty_nonunique_partial_or_wrong_scope_response(
    monkeypatch: pytest.MonkeyPatch,
    body_rows: list[dict[str, object]],
    frame_rows: list[dict[str, object]],
    extra_data: dict[str, object] | None,
) -> None:
    """Only a complete unique row matching the request can produce bounds."""

    _install_provider(
        monkeypatch,
        body_rows,
        frame_rows=frame_rows,
        extra_data=extra_data,
    )

    with pytest.raises((DataFetchError, TushareError)):
        _fetch()


@pytest.mark.parametrize(
    ("lower", "upper"),
    [
        (Decimal("0"), Decimal("12.50")),
        (Decimal("-0.01"), Decimal("12.50")),
        (Decimal("9.50"), Decimal("0")),
        (Decimal("9.50"), Decimal("-0.01")),
        (Decimal("13.00"), Decimal("12.50")),
        (None, Decimal("12.50")),
        (Decimal("9.50"), "Infinity"),
    ],
)
def test_exact_capture_rejects_unknown_nonpositive_or_reversed_bounds(
    monkeypatch: pytest.MonkeyPatch,
    lower: object,
    upper: object,
) -> None:
    """Missing or invalid limits never become an unbounded-price decision."""

    _install_provider(monkeypatch, [_row(lower=lower, upper=upper)])

    with pytest.raises((DataFetchError, TushareError)):
        _fetch()


def test_exact_capture_requires_same_call_body_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A normalized frame without verifiable original response bytes is rejected."""

    _install_provider(monkeypatch, [_row()], evidence_available=False)

    with pytest.raises((DataFetchError, TushareError)):
        _fetch()


@pytest.mark.parametrize("asset_code", ["600000", "600000.sh", ""])
def test_exact_capture_rejects_noncanonical_request_before_provider_call(
    monkeypatch: pytest.MonkeyPatch,
    asset_code: str,
) -> None:
    """Malformed request identity is blocked before creating the provider client."""

    calls: list[dict[str, object]] = []

    def unexpected_client(**kwargs: object) -> _Pro:
        """Record any request that wrongly reaches the provider boundary."""

        calls.append(kwargs)
        return _Pro(_Frame([], None))

    monkeypatch.setattr(
        tushare_exact_price_limit_capture,
        "create_tushare_pro_client",
        unexpected_client,
    )

    with pytest.raises((DataFetchError, TushareError)):
        tushare_exact_price_limit_capture.fetch_exact_tushare_price_limit(
            _config(),
            asset_code=asset_code,
            target_trade_date=_TRADE_DATE,
            deployment_region="test-region",
            request_mode="unified_relay",
        )
    assert calls == []


def test_capture_validator_rejects_wrong_request_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A valid body cannot be rebound to a different target trading day."""

    _install_provider(monkeypatch, [_row()])
    result = _fetch()
    wrong_scope = ExactPriceLimitRequestScope(
        provider_id=19,
        provider_name="provider-main",
        dataset_key="equity.price.limit",
        api_name="stk_limit",
        asset_code="600000.SH",
        trade_date=date(2026, 9, 25),
    )

    with pytest.raises(DataFetchError):
        validate_exact_price_limit_capture(result, scope=wrong_scope)


def test_inactive_config_blocks_exact_capture_before_client_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An inactive provider or malformed active flag cannot reach the client."""

    client_calls: list[dict[str, object]] = []

    def unexpected_client(**kwargs: object) -> _Pro:
        """Record any provider client created for an inactive configuration."""

        client_calls.append(kwargs)
        return _Pro(_Frame([], None))

    monkeypatch.setattr(
        tushare_exact_price_limit_capture,
        "create_tushare_pro_client",
        unexpected_client,
    )

    for active_value in (False, "true"):
        config = replace(_config(), is_active=active_value)  # type: ignore[arg-type]
        with pytest.raises(TushareError):
            tushare_exact_price_limit_capture.fetch_exact_tushare_price_limit(
                config,
                asset_code="600000.SH",
                target_trade_date=_TRADE_DATE,
                deployment_region="test-region",
                request_mode="unified_relay",
            )

    assert client_calls == []


def test_direct_adapter_call_for_inactive_config_never_creates_provider_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exposed provider method blocks before any network-capable client is made."""

    client_calls: list[dict[str, object]] = []

    def unexpected_client(**kwargs: object) -> _Pro:
        """Record any provider client created for an inactive configuration."""

        client_calls.append(kwargs)
        return _Pro(_Frame([], None))

    monkeypatch.setattr(
        tushare_exact_price_limit_capture,
        "create_tushare_pro_client",
        unexpected_client,
    )
    adapter = TushareUnifiedProviderAdapter(replace(_config(), is_active=False))

    with pytest.raises(TushareError):
        adapter.fetch_price_limit_with_capture("600000.SH", _TRADE_DATE)

    assert client_calls == []
