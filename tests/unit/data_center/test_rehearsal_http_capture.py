"""Exercise the rehearsal observer against a real loopback HTTP server, not provider evidence."""

import hashlib
import json
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from zoneinfo import ZoneInfo

import pytest
import requests

from apps.data_center.infrastructure.rehearsal_http_capture import RehearsalHttpCapture
from core.exceptions import DataFetchError

BODY = b'{"data":[12.5,30.2]}'


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
