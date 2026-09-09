"""Focused transport safety and response-shape contracts."""

from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from django.test import override_settings

from apps.data_center.domain.egress_routing import EgressRequestContext
from apps.data_center.infrastructure import egress_transport as transport_module


def _context() -> EgressRequestContext:
    return EgressRequestContext(
        provider_id=3,
        dataset_key="equity.price.bar",
        target_url="https://data.example.com/history",
        deployment_region="overseas",
    )


def test_decode_eastmoney_kline_ignores_optional_trailing_field() -> None:
    """The optional f116 field must not break the stable eleven-field schema."""

    payload = {
        "data": {
            "klines": [
                "2026-09-08,10,11,12,9,100,1000,30,1,0.1,2,999999",
            ]
        }
    }

    frame = transport_module._decode_eastmoney_payload(payload, "600000")

    assert list(frame.columns) == [
        "日期",
        "股票代码",
        "开盘",
        "收盘",
        "最高",
        "最低",
        "成交量",
        "成交额",
        "振幅",
        "涨跌幅",
        "涨跌额",
        "换手率",
    ]
    assert frame.iloc[0]["换手率"] == 2


def test_transport_rejects_non_2xx_without_reading_unbounded_body(monkeypatch) -> None:
    """HTTP errors are never treated as successful JSON provider responses."""

    class Response:
        status_code = 404
        is_redirect = False
        is_permanent_redirect = False
        headers: dict[str, str] = {}
        encoding = "utf-8"

        def close(self) -> None:
            return None

        def iter_content(self, *, chunk_size: int):
            raise AssertionError("error response body should not be read")

    class Session:
        trust_env = True
        proxies: dict[str, str] = {}

        def mount(self, *_args):
            return None

        def get(self, *_args, **_kwargs):
            return Response()

        def close(self) -> None:
            return None

    session = Session()
    monkeypatch.setattr(transport_module.requests, "Session", lambda: session)
    monkeypatch.setattr(
        transport_module,
        "_validate_public_target",
        lambda _url: SimpleNamespace(
            url="https://93.184.216.34/history",
            scheme="https",
            host_header="data.example.com",
            adapter=None,
        ),
    )
    monkeypatch.setattr(transport_module._shared_state, "circuit_open", lambda _key: False)
    monkeypatch.setattr(transport_module._shared_state, "acquire", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(transport_module._shared_state, "release", lambda _key: None)

    result, payload = transport_module.EgressHttpTransport(max_attempts=1).request_payload(
        _context(),
        egress_id=None,
        request_id=uuid4(),
        attempt=1,
        method="GET",
        params=None,
        json_body=None,
        headers=None,
        expect_json=True,
    )

    assert result.outcome == "failed"
    assert result.error_code == "EGRESS_HTTP_404"
    assert payload is None


def test_bounded_json_reader_rejects_oversized_body() -> None:
    """Provider responses have a hard byte ceiling before JSON decoding."""

    response = SimpleNamespace(
        headers={},
        encoding="utf-8",
        iter_content=lambda *, chunk_size: [b"{}"],
    )

    with pytest.raises(ValueError, match="response_body_too_large"):
        transport_module._read_bounded_json(response, max_bytes=1)


@override_settings(DEBUG=False, REDIS_URL="")
def test_production_limiter_fails_closed_without_redis() -> None:
    """A production worker never falls back to an independent local counter."""

    state = transport_module._SharedEgressState()

    assert state.acquire("egress:test", 1) is False
    assert state.backend_unavailable() is True


@override_settings(DEBUG=False)
def test_shared_state_recovers_on_next_request_after_redis_returns(monkeypatch):
    """A transient Redis outage must not permanently block the worker."""
    state = transport_module._SharedEgressState()
    redis_client = Mock()
    redis_client.eval.side_effect = [ConnectionError("offline"), 1]
    monkeypatch.setattr(state, "_redis_client", lambda: redis_client)
    monkeypatch.setattr(transport_module.cache, "get", lambda _key: None)
    assert state.acquire("egress:test", 1) is False
    assert state.shared_state_unavailable() is True
    assert state.circuit_open("egress:test") is False
    assert state.shared_state_unavailable() is False
    assert state.acquire("egress:test", 1) is True
