"""Tests for Tushare client transport selection."""

from __future__ import annotations

from typing import Any
from unittest.mock import Mock

import pytest

from shared.infrastructure.tushare_client import (
    TUSHARE_REQUEST_MODE_UNIFIED_RELAY,
    TushareRelayAuthorizationError,
    create_tushare_pro_client,
    resolve_tushare_runtime_settings,
)


class _RelayResponse:
    """Minimal successful requests response used by relay tests."""

    status_code = 200

    def raise_for_status(self) -> None:
        """Model one successful HTTP status."""

    def json(self) -> dict[str, object]:
        """Return a standard Tushare response body."""

        return {
            "code": 0,
            "msg": "ok",
            "data": {
                "fields": ["exchange", "cal_date", "is_open"],
                "items": [["SSE", "20240102", 1]],
            },
        }


class _RelaySession:
    """Capture relay request details without making network calls."""

    def __init__(self) -> None:
        self.headers: dict[str, str] = {}
        self.trust_env = True
        self.proxies: dict[str, str] = {}
        self.calls: list[dict[str, object]] = []

    def post(
        self,
        url: str,
        *,
        json: dict[str, object],
        timeout: int,
    ) -> _RelayResponse:
        """Capture one POST call and return a deterministic response."""

        self.calls.append({"url": url, "json": json, "timeout": timeout})
        return _RelayResponse()


class _RejectedRelayResponse(_RelayResponse):
    """Minimal relay response for an invalid API credential."""

    status_code = 403


def test_unified_relay_rejects_invalid_api_key_without_payload_fallback(
    monkeypatch: Any,
) -> None:
    """A relay authorization failure must remain distinguishable from source outage."""

    session = _RelaySession()
    monkeypatch.setattr(session, "post", lambda *_args, **_kwargs: _RejectedRelayResponse())
    monkeypatch.setattr(
        "shared.infrastructure.tushare_client.requests.Session",
        lambda: session,
    )
    client = create_tushare_pro_client(
        token="rejected-secret",
        http_url="https://relay.example.test/tushare/pro",
        request_mode=TUSHARE_REQUEST_MODE_UNIFIED_RELAY,
    )

    with pytest.raises(TushareRelayAuthorizationError, match="HTTP 403"):
        client.daily(ts_code="000001.SZ")


def test_unified_relay_posts_to_exact_url_with_api_key_header(monkeypatch: Any) -> None:
    """Relay mode must not append the API name to the configured endpoint."""

    session = _RelaySession()
    monkeypatch.setattr(
        "shared.infrastructure.tushare_client.requests.Session",
        lambda: session,
    )

    client = create_tushare_pro_client(
        token="relay-secret",
        http_url="https://relay.example.test/tushare/pro",
        request_mode=TUSHARE_REQUEST_MODE_UNIFIED_RELAY,
    )
    result = client.trade_cal(
        exchange="SSE",
        start_date="20240102",
        end_date="20240102",
        fields="exchange,cal_date,is_open",
    )

    assert result.to_dict(orient="records") == [
        {"exchange": "SSE", "cal_date": "20240102", "is_open": 1}
    ]
    assert session.headers == {"X-API-Key": "relay-secret"}
    assert session.trust_env is False
    assert session.proxies == {"http": "", "https": ""}
    assert session.calls == [
        {
            "url": "https://relay.example.test/tushare/pro",
            "json": {
                "api_name": "trade_cal",
                "token": "relay-secret",
                "params": {
                    "exchange": "SSE",
                    "start_date": "20240102",
                    "end_date": "20240102",
                },
                "fields": "exchange,cal_date,is_open",
            },
            "timeout": 30,
        }
    ]


def test_sdk_path_mode_remains_the_default(monkeypatch: Any) -> None:
    """Existing Tushare clients must keep the SDK path transport by default."""

    pro = Mock()
    monkeypatch.setattr("tushare.pro_api", Mock(return_value=pro))

    result = create_tushare_pro_client(
        token="standard-token",
        http_url="https://proxy.example.test",
        request_mode="sdk_path",
    )

    assert result is pro
    assert pro._DataApi__http_url == "https://proxy.example.test"


def test_request_mode_rejects_unknown_values() -> None:
    """Unknown transport modes must fail closed."""

    with pytest.raises(ValueError, match="request mode is unsupported"):
        resolve_tushare_runtime_settings(
            token="token",
            http_url="https://proxy.example.test",
            request_mode="unknown",
        )


def test_unified_relay_requires_endpoint() -> None:
    """Relay mode cannot silently fall back to the official endpoint."""

    with pytest.raises(ValueError, match="relay URL"):
        create_tushare_pro_client(
            token="token",
            http_url="",
            request_mode=TUSHARE_REQUEST_MODE_UNIFIED_RELAY,
        )
