"""Exercise the rehearsal observer against a real loopback HTTP server, not provider evidence."""

import gzip
import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from threading import Thread
from typing import Any
from zoneinfo import ZoneInfo

import pytest
import requests
from urllib3.response import HTTPResponse

from apps.data_center.domain.financial_response_evidence import (
    FinancialRequestScope,
    FinancialResponseScope,
)
from apps.data_center.domain.provider_response import ProviderResponseTransport
from apps.data_center.infrastructure.financial_response_capture import (
    FinancialResponseCaptureError,
    capture_financial_response,
)
from apps.data_center.infrastructure.provider_response_capture import (
    ProviderResponseCaptureError,
    capture_provider_response_body,
)
from apps.data_center.infrastructure.rehearsal_http_capture import RehearsalHttpCapture
from core.exceptions import DataFetchError

BODY = b'{"data":[12.5,30.2]}'


def _stream_response(
    body: bytes = BODY,
    *,
    content_encoding: str | None = None,
    declared_size: int | None = None,
) -> requests.Response:
    response = requests.Response()
    response.status_code = 200
    response.headers["Content-Type"] = "application/json"
    response.headers["Content-Length"] = str(len(body) if declared_size is None else declared_size)
    if content_encoding is not None:
        response.headers["Content-Encoding"] = content_encoding
    response.raw = HTTPResponse(
        body=BytesIO(body),
        headers=response.headers,
        status=200,
        preload_content=False,
        decode_content=False,
    )
    return response


def _observe_memory_response(
    monkeypatch: pytest.MonkeyPatch,
    response_factory: Callable[[], requests.Response] = _stream_response,
) -> requests.Response:
    def memory_send(
        session: requests.Session, request: requests.PreparedRequest, **kwargs: Any
    ) -> requests.Response:
        del session, kwargs
        response = response_factory()
        response.request = request
        return response

    monkeypatch.setattr(requests.Session, "send", memory_send)
    with RehearsalHttpCapture(max_dispatches=1, max_seconds=5.0) as capture:
        response = requests.get("https://provider.invalid/exact-body", timeout=1.0)
    assert capture.dispatches == 1
    assert capture.guard_failure_code is None
    assert capture.receipts[0].body_sha256 == hashlib.sha256(BODY).hexdigest()
    return response


@pytest.mark.parametrize("content_encoding", [None, "identity"])
def test_observed_identity_body_remains_readable_by_exact_provider_capture(
    monkeypatch: pytest.MonkeyPatch, content_encoding: str | None
) -> None:
    response = _observe_memory_response(
        monkeypatch, lambda: _stream_response(content_encoding=content_encoding)
    )
    captured = capture_provider_response_body(
        response, transport=ProviderResponseTransport.EGRESS, max_bytes=1024
    )
    assert captured.body == BODY
    assert captured.body_sha256 == hashlib.sha256(BODY).hexdigest()
    assert response.headers["Content-Length"] == str(len(BODY))
    assert response.json() == {"data": [12.5, 30.2]}


def test_observed_identity_body_keeps_financial_reader_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _observe_memory_response(monkeypatch)
    captured = capture_financial_response(
        response,
        request_scope=FinancialRequestScope(
            provider_name="AKShare",
            dataset_key="test.dataset",
            asset_code="000001.SZ",
            period_limit=1,
        ),
        response_scope=FinancialResponseScope(
            asset_codes=("000001.SZ",), period_ends=(), row_count=1
        ),
        decode=lambda body: body,
        clock=lambda: datetime(2026, 11, 18, tzinfo=UTC),
    )
    assert captured.raw_body == BODY
    assert captured.evidence.body_sha256 == hashlib.sha256(BODY).hexdigest()


def test_observed_gzip_still_fails_both_exact_capture_readers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _observe_memory_response(
        monkeypatch, lambda: _stream_response(gzip.compress(BODY), content_encoding="gzip")
    )
    with pytest.raises(ProviderResponseCaptureError) as provider_error:
        capture_provider_response_body(
            response, transport=ProviderResponseTransport.EGRESS, max_bytes=1024
        )
    assert provider_error.value.code == "PROVIDER_RESPONSE_ENCODING_UNSUPPORTED"
    with pytest.raises(FinancialResponseCaptureError) as financial_error:
        capture_financial_response(
            response,
            request_scope=FinancialRequestScope(
                provider_name="AKShare",
                dataset_key="test.dataset",
                asset_code="000001.SZ",
                period_limit=1,
            ),
            response_scope=FinancialResponseScope(
                asset_codes=("000001.SZ",), period_ends=(), row_count=1
            ),
            decode=lambda body: body,
        )
    assert financial_error.value.code == "FINANCIAL_RESPONSE_ENCODING_UNSUPPORTED"


def test_observer_rejects_a_real_short_body_before_replaying_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def memory_send(
        session: requests.Session, request: requests.PreparedRequest, **kwargs: Any
    ) -> requests.Response:
        del session, kwargs
        response = _stream_response(BODY[:-3], declared_size=len(BODY))
        response.request = request
        return response

    monkeypatch.setattr(requests.Session, "send", memory_send)
    with RehearsalHttpCapture(max_dispatches=1, max_seconds=5.0) as capture:
        with pytest.raises(requests.exceptions.ChunkedEncodingError):
            requests.get("https://provider.invalid/short-body", timeout=1.0)
    assert capture.dispatches == 1
    assert capture.receipts[0].error_code == "REHEARSAL_HTTP_FAILED"
    assert capture.receipts[0].body_sha256 == ""


@pytest.fixture
def local_http():
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append(self.path)
            self.send_response(200)
            self.send_header("Content-Length", str(len(BODY)))
            self.end_headers()
            self.wfile.write(BODY)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/feed?token=test-credential", calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_real_transport_receipt_preserves_body_and_restores_session(local_http) -> None:
    url, calls = local_http
    original = requests.Session.send
    with RehearsalHttpCapture(max_dispatches=1, max_seconds=10) as capture:
        response = requests.get(url, stream=True, timeout=5)
        assert response.json() == {"data": [12.5, 30.2]}
        assert response.content == BODY
    assert requests.Session.send is original
    assert len(calls) == 1
    assert capture.receipts[0].body_sha256 == hashlib.sha256(BODY).hexdigest()
    assert "test-credential" not in json.dumps(capture.to_dict())


def test_budget_stops_next_dispatch_before_sending(local_http) -> None:
    url, calls = local_http
    with RehearsalHttpCapture(max_dispatches=1, max_seconds=10) as capture:
        requests.get(url, timeout=5)
        with pytest.raises(DataFetchError, match="budget exhausted"):
            requests.get(url, timeout=5)
    assert len(calls) == capture.dispatches == 1


def test_body_limit_failure_records_safe_code_and_restores_transport(local_http) -> None:
    url, _ = local_http
    original = requests.Session.send
    with pytest.raises(DataFetchError, match="too large"):
        with RehearsalHttpCapture(max_dispatches=1, max_seconds=10, max_body_bytes=3) as capture:
            requests.get(url, stream=True, timeout=5)
    assert requests.Session.send is original
    assert capture.receipts[0].error_code == "REHEARSAL_BODY_LIMIT"
    assert capture.receipts[0].body_sha256 == ""


def test_unobservable_adapter_retries_are_rejected_before_network(local_http) -> None:
    url, calls = local_http
    with requests.Session() as session:
        session.mount("http://", requests.adapters.HTTPAdapter(max_retries=2))
        with RehearsalHttpCapture(max_dispatches=1, max_seconds=10):
            with pytest.raises(DataFetchError, match="Unobservable"):
                session.get(url, timeout=5)
    assert calls == []


def test_normalized_valuation_hash_must_match_observed_response(local_http) -> None:
    from apps.data_center.domain.entities import ValuationFact
    from apps.data_center.infrastructure.market_rehearsal_runner import _probe

    url, _ = local_http
    target = datetime.now(UTC).astimezone(ZoneInfo("Asia/Shanghai")).date()

    def fetch():
        requests.get(url, timeout=5)
        now = datetime.now(UTC)
        return [
            ValuationFact(
                "600000.SH",
                target,
                pe_ttm=12.5,
                source="loopback-test-only",
                available_at=now,
                fetched_at=now,
                observed_at=now,
                source_record_id="test-row",
                raw_payload_hash="b" * 64,
            )
        ]

    with RehearsalHttpCapture(max_dispatches=1, max_seconds=10) as capture:
        report = _probe(
            dataset="equity.valuation.fact",
            fetch=fetch,
            sample=("600000.SH",),
            target_date=target,
            capture=capture,
        )
    assert report["outcome"] == "blocked"
    assert report["transport_error_code"] == "REHEARSAL_SOURCE_RESPONSE_MISMATCH"


@pytest.mark.parametrize("seconds", [True, float("nan"), float("inf"), 0, -1])
def test_nonfinite_or_invalid_budget_cannot_disable_bounds(seconds) -> None:
    with pytest.raises(ValueError):
        RehearsalHttpCapture(max_dispatches=1, max_seconds=seconds)
