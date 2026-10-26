"""Exact single-asset quote request and same-call capture contracts."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from threading import Barrier, local
from typing import cast

import pytest

from apps.data_center.domain.provider_response import (
    ProviderResponseCapture,
    ProviderResponseTransport,
    parse_provider_response_json,
)
from apps.data_center.infrastructure import tushare_client
from apps.data_center.infrastructure.gateways import tushare_gateway
from core.exceptions import TushareError


class _Frame:
    """Small pandas-like response retaining its own typed transport evidence."""

    def __init__(self, rows: list[dict[str, object]], evidence: object) -> None:
        self._rows = rows
        self.empty = not rows
        self.response_evidence = evidence

    def to_dict(self, orient: str) -> list[dict[str, object]]:
        assert orient == "records"
        return list(self._rows)


class _ProClient:
    """Record the exact daily call used by the narrow quote capability."""

    def __init__(self, frame: _Frame) -> None:
        self.frame = frame
        self.daily_calls: list[dict[str, str]] = []

    def daily(self, **params: str) -> _Frame:
        self.daily_calls.append(params)
        return self.frame


def _capture(asset_code: str, trade_date: date) -> ProviderResponseCapture:
    body = json.dumps(
        {
            "code": 0,
            "data": {
                "fields": ["ts_code", "trade_date", "close"],
                "items": [[asset_code, trade_date.strftime("%Y%m%d"), 10.5]],
            },
        },
        separators=(",", ":"),
    ).encode()
    return ProviderResponseCapture(
        body=body,
        payload=parse_provider_response_json(body),
        body_sha256=sha256(body).hexdigest(),
        body_size_bytes=len(body),
        response_completed_at=datetime(2026, 10, 26, 8, 0, tzinfo=UTC),
        status_code=200,
        content_type="application/json",
        transport=ProviderResponseTransport.EGRESS,
    )


def test_exact_quote_gateway_calls_daily_for_one_ts_code_with_session(monkeypatch) -> None:
    """The single-asset path must bound the provider request before parsing."""

    target = date(2026, 10, 26)
    capture = _capture("600000.SH", target)
    evidence = tushare_client.TushareResponseEvidence(
        body_sha256=capture.body_sha256,
        response_completed_at=capture.response_completed_at,
        response_capture=capture,
        sensitive_values=("provider-secret",),
    )
    row = {"ts_code": "600000.SH", "trade_date": "20261026", "close": 10.5}
    client = _ProClient(_Frame([row], evidence))
    factory_calls: list[dict[str, object]] = []

    def create_client(**kwargs: object) -> _ProClient:
        factory_calls.append(kwargs)
        return client

    monkeypatch.setattr(tushare_gateway, "create_tushare_pro_client", create_client)
    gateway = tushare_gateway.TushareGateway(
        token="provider-secret",
        source_name="market-primary",
        provider_id=19,
        dataset_key="equity.quote.snapshot",
    )

    quote, received_evidence = gateway.get_quote_snapshot_with_capture("600000.SH", target)

    assert client.daily_calls == [{"ts_code": "600000.SH", "trade_date": "20261026"}]
    assert factory_calls[0]["capture_provider_responses"] is True
    assert quote.stock_code == "600000.SH"
    assert quote.extra["raw_payload_hash"] == capture.body_sha256
    assert received_evidence.response_capture is capture
    assert received_evidence.sensitive_values == ("provider-secret",)


@pytest.mark.parametrize(
    "rows",
    [
        [{"ts_code": "000001.SZ", "trade_date": "20261026", "close": 10.5}],
        [
            {"ts_code": "600000.SH", "trade_date": "20261026", "close": 10.5},
            {"ts_code": "000001.SZ", "trade_date": "20261026", "close": 11.0},
        ],
        [{"ts_code": "600000.SH", "trade_date": "20261027", "close": 10.5}],
        [],
    ],
)
def test_exact_quote_gateway_rejects_rows_outside_requested_scope(
    monkeypatch, rows: list[dict[str, object]]
) -> None:
    """A provider response outside the requested asset/session cannot be narrowed locally."""

    target = date(2026, 10, 26)
    capture = _capture_rows(rows)
    evidence = tushare_client.TushareResponseEvidence(
        body_sha256=capture.body_sha256,
        response_completed_at=capture.response_completed_at,
        response_capture=capture,
    )
    client = _ProClient(_Frame(rows, evidence))
    monkeypatch.setattr(
        tushare_gateway,
        "create_tushare_pro_client",
        lambda **_kwargs: client,
    )
    gateway = tushare_gateway.TushareGateway(
        token="provider-secret",
        source_name="market-primary",
        provider_id=19,
        dataset_key="equity.quote.snapshot",
    )

    with pytest.raises(TushareError) as error:
        gateway.get_quote_snapshot_with_capture("600000.SH", target)

    assert error.value.code == "TUSHARE_EXACT_QUOTE_RESPONSE_MISMATCH"


def _capture_rows(rows: list[dict[str, object]]) -> ProviderResponseCapture:
    """Build an exact JSON response body for provider rows used by contract tests."""

    fields = ["ts_code", "trade_date", "close"]
    body = json.dumps(
        {
            "code": 0,
            "data": {
                "fields": fields,
                "items": [[row.get(field) for field in fields] for row in rows],
            },
        },
        separators=(",", ":"),
    ).encode()
    return ProviderResponseCapture(
        body=body,
        payload=parse_provider_response_json(body),
        body_sha256=sha256(body).hexdigest(),
        body_size_bytes=len(body),
        response_completed_at=datetime(2026, 10, 26, 8, 0, tzinfo=UTC),
        status_code=200,
        content_type="application/json",
        transport=ProviderResponseTransport.EGRESS,
    )


def test_capture_only_tushare_frame_keeps_capture_per_returned_response(monkeypatch) -> None:
    """Deferred retention carries frame-local captures without a global last value."""

    client = tushare_client._UnifiedRelayClient(
        token="provider-secret",
        http_url="https://market.example.com/pro",
        provider_id=19,
        dataset_key="equity.quote.snapshot",
        capture_provider_responses=True,
    )
    first = _capture("600000.SH", date(2026, 10, 26))
    second = _capture("000001.SZ", date(2026, 10, 27))
    captures = iter((first, second))
    monkeypatch.setattr(client, "_should_use_egress", lambda *_args, **_kwargs: True)

    def execute(*_args: object, **_kwargs: object) -> ProviderResponseCapture:
        return next(captures)

    from apps.data_center.application import egress_service

    monkeypatch.setattr(egress_service, "execute_provider_response_request", execute)
    first_frame = client.query("daily", ts_code="600000.SH", trade_date="20261026")
    second_frame = client.query("daily", ts_code="000001.SZ", trade_date="20261027")

    first_evidence = cast(tushare_client.TushareResponseEvidence, first_frame.response_evidence)
    second_evidence = cast(tushare_client.TushareResponseEvidence, second_frame.response_evidence)
    assert first_evidence.response_capture is first
    assert second_evidence.response_capture is second
    assert first_evidence.raw_payload_reference is None
    assert second_evidence.raw_payload_reference is None
    assert "provider-secret" in first_evidence.sensitive_values
    assert "response_capture" not in first_evidence.to_payload()
    assert "sensitive_values" not in first_evidence.to_payload()

    same_scope_capture_a = _capture("600000.SH", date(2026, 10, 26))
    same_scope_capture_b = replace(
        same_scope_capture_a,
        response_completed_at=same_scope_capture_a.response_completed_at + timedelta(seconds=1),
    )
    barrier = Barrier(2)
    thread_capture = local()

    def execute_same_scope(*_args: object, **_kwargs: object) -> ProviderResponseCapture:
        barrier.wait(timeout=5)
        return cast(ProviderResponseCapture, thread_capture.capture)

    monkeypatch.setattr(egress_service, "execute_provider_response_request", execute_same_scope)

    def query_same_scope(capture: ProviderResponseCapture) -> ProviderResponseCapture:
        thread_capture.capture = capture
        frame = client.query("daily", ts_code="600000.SH", trade_date="20261026")
        evidence = cast(tushare_client.TushareResponseEvidence, frame.response_evidence)
        return cast(ProviderResponseCapture, evidence.response_capture)

    with ThreadPoolExecutor(max_workers=2) as executor:
        concurrent_results = list(
            executor.map(query_same_scope, (same_scope_capture_a, same_scope_capture_b))
        )

    assert concurrent_results[0] is same_scope_capture_a
    assert concurrent_results[1] is same_scope_capture_b
