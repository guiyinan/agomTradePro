"""Exact full-market session quote capture contracts for Tushare."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from hashlib import sha256

import pytest

from apps.data_center.domain.entities import ProviderConfig
from apps.data_center.domain.market_time import cn_market_session_close_utc
from apps.data_center.domain.provider_response import (
    ProviderResponseCapture,
    ProviderResponseTransport,
    parse_provider_response_json,
)
from apps.data_center.infrastructure import tushare_client
from apps.data_center.infrastructure._provider_adapter_tushare import (
    TushareUnifiedProviderAdapter,
)
from apps.data_center.infrastructure.gateways import tushare_gateway
from core.exceptions import TushareError

_TARGET_DATE = date(2026, 9, 24)
_COMPLETED_AT = datetime(2026, 9, 24, 8, 10, tzinfo=UTC)
_FIELDS = [
    "ts_code",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "pre_close",
    "vol",
    "amount",
]


def _row(
    asset_code: str, *, close: float = 12.0, trade_date: str = "20260924"
) -> dict[str, object]:
    """Return one complete provider daily row."""

    return {
        "ts_code": asset_code,
        "trade_date": trade_date,
        "open": close - 1,
        "high": close + 1,
        "low": close - 2,
        "close": close,
        "pre_close": close - 1,
        "vol": 100,
        "amount": 200,
    }


def _capture(
    rows: list[dict[str, object]],
    *,
    fields: list[str] | None = None,
) -> ProviderResponseCapture:
    """Build capture bytes from the table payload used as the raw-source truth."""

    columns = _FIELDS if fields is None else fields
    body = json.dumps(
        {
            "code": 0,
            "data": {
                "fields": columns,
                "items": [[row.get(column) for column in columns] for row in rows],
            },
        },
        separators=(",", ":"),
    ).encode("utf-8")
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
    """Expose capture metadata while making mutable rows unusable as evidence."""

    empty = False

    def __init__(self, evidence: tushare_client.TushareResponseEvidence) -> None:
        self.response_evidence = evidence

    def to_dict(self, orient: str) -> list[dict[str, object]]:
        raise AssertionError(f"captured-session rows must come from body bytes, not {orient}")


class _Pro:
    def __init__(self, frame: _Frame) -> None:
        self.frame = frame
        self.daily_calls: list[dict[str, str]] = []

    def daily(self, **params: str) -> _Frame:
        self.daily_calls.append(params)
        return self.frame


def _gateway_for_capture(
    monkeypatch: pytest.MonkeyPatch,
    capture: ProviderResponseCapture | None,
) -> tuple[tushare_gateway.TushareGateway, _Pro, list[dict[str, object]]]:
    """Create one configured gateway fake and record client factory arguments."""

    evidence = tushare_client.TushareResponseEvidence(
        body_sha256=(capture.body_sha256 if capture is not None else "a" * 64),
        response_completed_at=(
            capture.response_completed_at if capture is not None else _COMPLETED_AT
        ),
        response_capture=capture,
        sensitive_values=("provider-secret",),
    )
    pro = _Pro(_Frame(evidence))
    factory_calls: list[dict[str, object]] = []

    def create_client(**kwargs: object) -> _Pro:
        factory_calls.append(kwargs)
        return pro

    monkeypatch.setattr(tushare_gateway, "create_tushare_pro_client", create_client)
    gateway = tushare_gateway.TushareGateway(
        token="provider-secret",
        http_url="https://relay.example.test/tushare/pro",
        request_mode="unified_relay",
        source_name="market-primary",
        provider_id=19,
        deployment_region="cn-east",
        dataset_key="equity.quote.snapshot",
    )
    return gateway, pro, factory_calls


def test_full_session_capture_uses_one_unscoped_daily_request_and_body_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A same-call byte capture supplies all rows and retains session semantics."""

    capture = _capture(
        [
            _row("000001.SZ", close=12.5),
            _row("600000.SH", close=8.5),
            _row("600519.SH", close=1400),
            _row("600519.SH", close=1401),
        ]
    )
    gateway, pro, factory_calls = _gateway_for_capture(monkeypatch, capture)

    quotes, evidence = gateway.get_quote_snapshots_for_session_with_capture(
        ["000001.SZ", "600000.SH"],
        _TARGET_DATE,
    )

    assert pro.daily_calls == [{"trade_date": "20260924"}]
    assert factory_calls[0]["capture_provider_responses"] is True
    assert factory_calls[0]["provider_id"] == 19
    assert factory_calls[0]["http_url"] == "https://relay.example.test/tushare/pro"
    assert [quote.stock_code for quote in quotes] == ["000001.SZ", "600000.SH"]
    assert [quote.price for quote in quotes] == [12.5, 8.5]
    assert all(quote.fetched_at == _COMPLETED_AT for quote in quotes)
    assert all(quote.observed_at == cn_market_session_close_utc(_TARGET_DATE) for quote in quotes)
    assert all(quote.extra["raw_payload_hash"] == capture.body_sha256 for quote in quotes)
    assert evidence.response_capture is capture
    assert evidence.sensitive_values == ("provider-secret",)


@pytest.mark.parametrize(
    ("rows", "fields", "expected_code"),
    [
        (
            [_row("000001.SZ", trade_date="20260925")],
            None,
            "TUSHARE_SESSION_QUOTE_RESPONSE_MISMATCH",
        ),
        ([], None, "TUSHARE_DATA_NOT_YET_AVAILABLE"),
        ([_row("000001.SZ")], ["trade_date", "close"], "TUSHARE_INVALID_PAYLOAD"),
        (
            [_row("000001.SZ"), _row("000001.SZ")],
            None,
            "TUSHARE_DUPLICATE_QUOTE_ROW",
        ),
        (
            [_row("000001.SZ", close=0), _row("000001.SZ")],
            None,
            "TUSHARE_DUPLICATE_QUOTE_ROW",
        ),
    ],
)
def test_full_session_capture_rejects_wrong_day_malformed_or_duplicate_requested_rows(
    monkeypatch: pytest.MonkeyPatch,
    rows: list[dict[str, object]],
    fields: list[str] | None,
    expected_code: str,
) -> None:
    """A malformed or duplicate in-scope body cannot be silently narrowed."""

    gateway, _pro, _factory_calls = _gateway_for_capture(
        monkeypatch,
        _capture(rows, fields=fields),
    )

    with pytest.raises(TushareError) as caught:
        gateway.get_quote_snapshots_for_session_with_capture(["000001.SZ"], _TARGET_DATE)

    assert caught.value.code == expected_code


def test_full_session_capture_requires_same_call_response_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The opt-in transport cannot fall back when the returned frame lacks capture."""

    gateway, _pro, _factory_calls = _gateway_for_capture(monkeypatch, None)

    with pytest.raises(TushareError) as caught:
        gateway.get_quote_snapshots_for_session_with_capture(["000001.SZ"], _TARGET_DATE)

    assert caught.value.code == "TUSHARE_PROVIDER_RESPONSE_CAPTURE_UNAVAILABLE"


@pytest.mark.parametrize(
    ("asset_codes", "target_trade_date", "provider_id", "dataset_key"),
    [
        (["000001.SZ", "000001.SZ"], _TARGET_DATE, 19, "equity.quote.snapshot"),
        (["000001.sz"], _TARGET_DATE, 19, "equity.quote.snapshot"),
        (["000001"], _TARGET_DATE, 19, "equity.quote.snapshot"),
        (["000001.SZ"], datetime(2026, 9, 24, tzinfo=UTC), 19, "equity.quote.snapshot"),
        (["000001.SZ"], _TARGET_DATE, None, "equity.quote.snapshot"),
        (["000001.SZ"], _TARGET_DATE, 19, "equity.price.bar"),
    ],
)
def test_invalid_session_request_is_rejected_before_client_creation(
    monkeypatch: pytest.MonkeyPatch,
    asset_codes: list[str],
    target_trade_date: date,
    provider_id: int | None,
    dataset_key: str,
) -> None:
    """Invalid session identity and universe inputs make no configured client call."""

    capture = _capture([_row("000001.SZ")])
    evidence = tushare_client.TushareResponseEvidence(
        body_sha256=capture.body_sha256,
        response_completed_at=capture.response_completed_at,
        response_capture=capture,
    )
    pro = _Pro(_Frame(evidence))
    factory_calls: list[dict[str, object]] = []

    def create_client(**kwargs: object) -> _Pro:
        factory_calls.append(kwargs)
        return pro

    monkeypatch.setattr(tushare_gateway, "create_tushare_pro_client", create_client)
    gateway = tushare_gateway.TushareGateway(
        token="provider-secret",
        http_url="https://relay.example.test/tushare/pro",
        request_mode="unified_relay",
        source_name="market-primary",
        provider_id=provider_id,
        dataset_key=dataset_key,
    )

    with pytest.raises(TushareError) as caught:
        gateway.get_quote_snapshots_for_session_with_capture(asset_codes, target_trade_date)

    assert caught.value.code == "TUSHARE_SESSION_QUOTE_REQUEST_INVALID"
    assert factory_calls == []
    assert pro.daily_calls == []


def test_full_session_capture_preserves_missing_assets_for_application_verifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing row remains missing so the existing suspension verifier decides."""

    capture = _capture([_row("000001.SZ")])
    gateway, _pro, _factory_calls = _gateway_for_capture(monkeypatch, capture)

    quotes, _evidence = gateway.get_quote_snapshots_for_session_with_capture(
        ["000001.SZ", "600000.SH"],
        _TARGET_DATE,
    )

    assert [quote.stock_code for quote in quotes] == ["000001.SZ"]


def test_tushare_adapter_returns_typed_session_capture_from_configured_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The public provider capability preserves provider identity and source time."""

    capture = _capture([_row("000001.SZ", close=12.5), _row("600000.SH", close=8.5)])
    evidence = tushare_client.TushareResponseEvidence(
        body_sha256=capture.body_sha256,
        response_completed_at=capture.response_completed_at,
        response_capture=capture,
        sensitive_values=("provider-secret",),
    )
    pro = _Pro(_Frame(evidence))
    factory_calls: list[dict[str, object]] = []

    def create_client(**kwargs: object) -> _Pro:
        factory_calls.append(kwargs)
        return pro

    monkeypatch.setattr(tushare_gateway, "create_tushare_pro_client", create_client)
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
    adapter = TushareUnifiedProviderAdapter(config)

    response = adapter.fetch_quote_session_with_capture(
        ["000001.SZ", "600000.SH"],
        _TARGET_DATE,
    )

    assert response.request_scope.provider_id == 19
    assert response.request_scope.provider_name == "provider-main"
    assert response.request_scope.dataset_key == "equity.quote.snapshot"
    assert response.request_scope.api_name == "daily"
    assert response.request_scope.asset_codes == ("000001.SZ", "600000.SH")
    assert response.request_scope.request_params()["params"] == {"trade_date": "20260924"}
    assert response.capture is capture
    assert response.sensitive_values == ("provider-secret",)
    assert [quote.asset_code for quote in response.quotes] == ["000001.SZ", "600000.SH"]
    assert [quote.current_price for quote in response.quotes] == [12.5, 8.5]
    assert all(quote.source == "tushare" for quote in response.quotes)
    assert all(quote.fetched_at == _COMPLETED_AT for quote in response.quotes)
    assert all(
        quote.snapshot_at == cn_market_session_close_utc(_TARGET_DATE) for quote in response.quotes
    )
    assert all(quote.extra["raw_payload_hash"] == capture.body_sha256 for quote in response.quotes)
    assert pro.daily_calls == [{"trade_date": "20260924"}]
    assert factory_calls[0]["capture_provider_responses"] is True
    assert factory_calls[0]["token"] == "provider-secret"
    assert factory_calls[0]["http_url"] == "https://relay.example.test/tushare/pro"
    assert factory_calls[0]["request_mode"] == "unified_relay"
    assert factory_calls[0]["provider_id"] == 19
    assert factory_calls[0]["dataset_key"] == "equity.quote.snapshot"
