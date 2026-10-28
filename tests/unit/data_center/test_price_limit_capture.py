"""Actual adapter-to-raw-retention contracts for explicit daily price bounds."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal, localcontext
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from apps.data_center.application import egress_service
from apps.data_center.application.price_limit_capture import (
    CaptureExactPriceLimitUseCase,
    ReadRetainedPriceLimitUseCase,
)
from apps.data_center.domain.egress_routing import (
    EgressRequestContext,
    EgressRouteDecision,
    EgressStrategy,
)
from apps.data_center.domain.entities import ProviderConfig
from apps.data_center.domain.provider_response import ProviderResponseTransport
from apps.data_center.domain.raw_landing import RawPayload
from apps.data_center.infrastructure import egress_transport, tushare_client
from apps.data_center.infrastructure.provider_adapters import TushareUnifiedProviderAdapter
from core.exceptions import DataFetchError
from tests.unit.data_center.test_tushare_provider_response_capture import _Response, _Session

TRADE_DATE = date(2026, 10, 28)
BODY = (
    b'{"code":0,"data":{"fields":["ts_code","trade_date","down_limit","up_limit"],'
    b'"items":[["600000.SH","20261028",9.1234567890123456789,11.1234567890123456789]]}}'
)


def configured_provider() -> ProviderConfig:
    """Build an explicit fixture route with no production credential."""
    return ProviderConfig(
        id=19,
        name="limit-fixture",
        source_type="tushare",
        is_active=True,
        priority=1,
        api_key="fixture-limit-token",
        api_secret="",
        http_url="https://limits.example.test/pro",
        api_endpoint="",
        extra_config={"tushare_request_mode": "unified_relay"},
        description="",
    )


class ConfigReader:
    """Allow tests to revoke or replace configuration during a capture."""

    def __init__(self, config: ProviderConfig | None = None) -> None:
        self.config = config if config is not None else configured_provider()
        self.calls: list[int] = []

    def get_by_id(self, provider_id: int) -> ProviderConfig | None:
        self.calls.append(provider_id)
        return self.config


class RawStore:
    """Keep immutable rows under the existing RawPayload repository contract."""

    def __init__(self) -> None:
        self.rows: dict[str, RawPayload] = {}

    def save(self, payload: RawPayload) -> RawPayload:
        previous = self.rows.get(payload.payload_hash)
        if previous is not None and previous != payload:
            raise ValueError("raw_payload_immutable_conflict")
        self.rows[payload.payload_hash] = payload
        return payload

    def get_by_hash(self, payload_hash: str) -> RawPayload | None:
        return self.rows.get(payload_hash)


def install_transport(monkeypatch: pytest.MonkeyPatch, body: bytes = BODY) -> _Session:
    """Use real request, capture, and parsing code with an offline HTTP stream."""
    session = _Session(_Response(body))
    monkeypatch.setattr(tushare_client, "_create_requests_session", lambda: session)
    monkeypatch.setattr(
        tushare_client._UnifiedRelayClient, "_should_use_egress", lambda *_a, **_kw: False
    )
    return session


def test_real_adapter_retains_and_replays_original_decimal_body(monkeypatch) -> None:
    session = install_transport(monkeypatch)
    store = RawStore()
    configs = ConfigReader()
    capture = CaptureExactPriceLimitUseCase(configs, TushareUnifiedProviderAdapter, store)
    with localcontext() as context:
        context.prec = 3
        result = capture.execute(
            provider_id=19, asset_code="600000.SH", target_trade_date=TRADE_DATE
        )
        replay = ReadRetainedPriceLimitUseCase(store).execute(
            result.reference, scope=result.request_scope
        )
    assert result == replay
    assert result.values.lower_limit_price == Decimal("9.1234567890123456789")
    assert result.values.upper_limit_price == Decimal("11.1234567890123456789")
    assert result.known_at == result.reference.response_completed_at
    assert result.price_unit == "provider_native_price"
    assert result.currency is None and result.source_published_at is None
    assert result.observed_at is None
    assert result.must_not_use_for_decision is True and result.must_not_execute is True
    row = store.rows[result.reference.payload_hash]
    assert row.payload["retained_response_json"].encode() == BODY
    assert result.reference.verifies(row)
    assert configs.calls == [19, 19]
    assert len(session.calls) == 1
    assert session.calls[0]["json"]["api_name"] == "stk_limit"
    assert session.calls[0]["json"]["params"] == {"ts_code": "600000.SH", "trade_date": "20261028"}
    assert session.response.raw.calls == 1 and session.response.closed
    ReadRetainedPriceLimitUseCase(store).execute(result.reference, scope=result.request_scope)
    assert len(session.calls) == 1


@pytest.mark.parametrize("provider_id", [True, 0, -1, "19"])
def test_invalid_provider_is_rejected_before_configuration_or_network(
    monkeypatch, provider_id
) -> None:
    session = install_transport(monkeypatch)
    configs = ConfigReader()
    store = RawStore()
    with pytest.raises(DataFetchError, match="PRICE_LIMIT_CAPTURE_REQUEST_INVALID"):
        CaptureExactPriceLimitUseCase(configs, TushareUnifiedProviderAdapter, store).execute(
            provider_id=provider_id, asset_code="600000.SH", target_trade_date=TRADE_DATE
        )
    assert configs.calls == [] and session.calls == [] and store.rows == {}


@pytest.mark.parametrize(
    "asset_code,target",
    [("bad", TRADE_DATE), (" 600000.SH", TRADE_DATE), ("600000.SH", datetime(2026, 10, 28))],
)
def test_invalid_scope_never_calls_transport(monkeypatch, asset_code, target) -> None:
    session = install_transport(monkeypatch)
    store = RawStore()
    with pytest.raises(DataFetchError, match="PRICE_LIMIT_CAPTURE_REQUEST_INVALID"):
        CaptureExactPriceLimitUseCase(ConfigReader(), TushareUnifiedProviderAdapter, store).execute(
            provider_id=19, asset_code=asset_code, target_trade_date=target
        )
    assert session.calls == [] and store.rows == {}


@pytest.mark.parametrize("changes", [{"is_active": False}, {"source_type": "akshare"}, {"id": 20}])
def test_inactive_or_wrong_provider_blocks_before_transport(monkeypatch, changes) -> None:
    session = install_transport(monkeypatch)
    store = RawStore()
    configs = ConfigReader(replace(configured_provider(), **changes))
    with pytest.raises(DataFetchError, match="PRICE_LIMIT_CAPTURE_PROVIDER_UNAVAILABLE"):
        CaptureExactPriceLimitUseCase(configs, TushareUnifiedProviderAdapter, store).execute(
            provider_id=19, asset_code="600000.SH", target_trade_date=TRADE_DATE
        )
    assert session.calls == [] and store.rows == {}


def test_provider_revoked_while_response_arrives_is_not_retained(monkeypatch) -> None:
    install_transport(monkeypatch)
    configs = ConfigReader()
    store = RawStore()

    def build(config: ProviderConfig):
        adapter = TushareUnifiedProviderAdapter(config)
        original = adapter.fetch_price_limit_with_capture

        def fetch(asset_code: str, target_trade_date: date):
            result = original(asset_code, target_trade_date)
            configs.config = replace(config, is_active=False)
            return result

        monkeypatch.setattr(adapter, "fetch_price_limit_with_capture", fetch)
        return adapter

    with pytest.raises(DataFetchError, match="PRICE_LIMIT_CAPTURE_PROVIDER_CHANGED"):
        CaptureExactPriceLimitUseCase(configs, build, store).execute(
            provider_id=19, asset_code="600000.SH", target_trade_date=TRADE_DATE
        )
    assert store.rows == {}


def test_corrupted_persisted_payload_is_rejected_by_fresh_reader(monkeypatch) -> None:
    install_transport(monkeypatch)
    store = RawStore()
    result = CaptureExactPriceLimitUseCase(
        ConfigReader(), TushareUnifiedProviderAdapter, store
    ).execute(provider_id=19, asset_code="600000.SH", target_trade_date=TRADE_DATE)
    row = store.rows[result.reference.payload_hash]
    store.rows[row.payload_hash] = replace(
        row, payload={**row.payload, "retained_response_json": "{}"}
    )
    with pytest.raises(DataFetchError):
        ReadRetainedPriceLimitUseCase(store).execute(result.reference, scope=result.request_scope)


def test_missing_persisted_payload_is_not_recreated(monkeypatch) -> None:
    session = install_transport(monkeypatch)
    store = RawStore()
    result = CaptureExactPriceLimitUseCase(
        ConfigReader(), TushareUnifiedProviderAdapter, store
    ).execute(provider_id=19, asset_code="600000.SH", target_trade_date=TRADE_DATE)
    store.rows.clear()
    with pytest.raises(DataFetchError, match="PRICE_LIMIT_CAPTURE_PAYLOAD_MISSING"):
        ReadRetainedPriceLimitUseCase(store).execute(result.reference, scope=result.request_scope)
    assert len(session.calls) == 1 and store.rows == {}


def test_redacted_body_is_retained_safely_but_not_returned_as_exact_evidence(monkeypatch) -> None:
    body = BODY.replace(b'"code":0', b'"code":0,"message":"fixture-limit-token"')
    install_transport(monkeypatch, body)
    store = RawStore()
    with pytest.raises(DataFetchError):
        CaptureExactPriceLimitUseCase(ConfigReader(), TushareUnifiedProviderAdapter, store).execute(
            provider_id=19, asset_code="600000.SH", target_trade_date=TRADE_DATE
        )
    assert len(store.rows) == 1
    row = next(iter(store.rows.values()))
    assert "fixture-limit-token" not in json.dumps(row.payload)
    assert row.payload["original_body_retained"] is False


@pytest.mark.parametrize("mode", ["sdk_path", "rest_path", "unified_relay"])
def test_configured_egress_captures_stk_limit_bytes_and_exact_wire_scope(monkeypatch, mode) -> None:
    """Exercise each real client through EgressHttpTransport using an offline stream."""
    session = _Session(_Response(BODY))
    monkeypatch.setattr(tushare_client, "_create_requests_session", lambda: session)
    monkeypatch.setattr(egress_transport.requests, "Session", lambda: session)
    sdk = Mock()
    sdk._DataApi__http_url = "https://limits.example.test/pro"
    original_import = tushare_client.import_module
    monkeypatch.setattr(
        tushare_client,
        "import_module",
        lambda name: (
            SimpleNamespace(pro_api=lambda _token: sdk)
            if name == "tushare"
            else original_import(name)
        ),
    )
    monkeypatch.setattr(
        egress_service,
        "preview_route",
        lambda _context: EgressRouteDecision(
            rule_id=7, strategy=EgressStrategy.FIXED, candidates=(9,), reason="fixture"
        ),
    )
    monkeypatch.setattr(
        egress_transport,
        "_validate_public_target",
        lambda url: SimpleNamespace(
            scheme="https", host_header="limits.example.test", adapter=object(), url=url
        ),
    )
    monkeypatch.setattr(egress_transport._shared_state, "circuit_open", lambda _key: False)
    monkeypatch.setattr(egress_transport._shared_state, "shared_state_unavailable", lambda: False)
    monkeypatch.setattr(egress_transport._shared_state, "acquire", lambda *_a, **_kw: True)
    monkeypatch.setattr(egress_transport._shared_state, "release", lambda _key: None)
    monkeypatch.setattr(egress_transport._shared_state, "success", lambda _key: None)
    contexts: list[EgressRequestContext] = []

    def execute(context, *, method, params, json_body, headers, max_attempts):
        contexts.append(context)
        outcome, capture = egress_transport.EgressHttpTransport(
            max_attempts=max_attempts
        ).request_provider_response(
            context,
            egress_id=None,
            request_id=uuid4(),
            attempt=1,
            method=method,
            params=params,
            json_body=json_body,
            headers=headers,
        )
        assert outcome.outcome == "success" and capture is not None
        return capture

    monkeypatch.setattr(egress_service, "execute_provider_response_request", execute)
    store = RawStore()
    configs = ConfigReader(
        replace(configured_provider(), extra_config={"tushare_request_mode": mode})
    )
    result = CaptureExactPriceLimitUseCase(configs, TushareUnifiedProviderAdapter, store).execute(
        provider_id=19, asset_code="600000.SH", target_trade_date=TRADE_DATE
    )
    assert result.reference.transport is ProviderResponseTransport.EGRESS
    assert result.reference.original_body_retained is True
    assert (
        ReadRetainedPriceLimitUseCase(store).execute(result.reference, scope=result.request_scope)
        == result
    )
    assert len(contexts) == len(session.calls) == 1
    assert contexts[0].provider_id == 19 and contexts[0].dataset_key == "equity.price.limit"
    expected_suffix = "/stk-limit" if mode == "rest_path" else ""
    assert contexts[0].target_url == "https://limits.example.test/pro" + expected_suffix
    call = session.calls[0]
    if mode == "rest_path":
        assert call["params"]["ts_code"] == "600000.SH"
        assert call["params"]["trade_date"] == "20261028"
        assert call["params"]["fields"] == "ts_code,trade_date,down_limit,up_limit"
    else:
        assert call["json"]["api_name"] == "stk_limit"
        assert call["json"]["params"] == {"ts_code": "600000.SH", "trade_date": "20261028"}
        assert call["json"]["fields"] == "ts_code,trade_date,down_limit,up_limit"
    sdk.query.assert_not_called()
