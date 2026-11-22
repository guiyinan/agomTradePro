"""Isolated contracts for actual S6 graph-refresh dispatch budgeting."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests
from requests import Response

from apps.data_center.infrastructure.rehearsal_http_capture import RehearsalHttpCapture
from apps.data_center.infrastructure.rehearsal_response_store import (
    RehearsalResponseContext,
    RehearsalResponseStore,
)
from core.exceptions import DataFetchError
from scripts import prepare_s6_candidate_source_snapshot as _SNAPSHOT
from scripts import refresh_s6_isolated_market_graph as _REFRESH
from scripts import s6_isolated_market_graph_receipt as _RECEIPT

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _fake_send(counter: list[int], lock: threading.Lock):
    """Return a fake transport that responds without opening a socket."""

    def send(
        _session: requests.Session,
        request: requests.PreparedRequest,
        **_kwargs: object,
    ) -> Response:
        with lock:
            counter[0] += 1
        response = Response()
        response.status_code = 200
        response.url = str(request.url)
        response._content = b"{}"
        response._content_consumed = True
        return response

    return send


def _dispatch(session: requests.Session, *, delay_label: str | None = None) -> Response:
    headers = {"X-Test-Delay": delay_label} if delay_label is not None else None
    request = session.prepare_request(
        requests.Request(
            "GET",
            "https://provider.invalid/market?credential=private",
            headers=headers,
        )
    )
    return session.send(request, timeout=3)


def test_51st_attempt_is_blocked_before_transport_even_when_task_swallows_it(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A caught cap error still invalidates the capture and cannot yield a receipt."""
    sends = [0]
    lock = threading.Lock()
    monkeypatch.setattr(requests.Session, "send", _fake_send(sends, lock))
    capture = RehearsalHttpCapture(max_dispatches=50, max_seconds=30)

    def task() -> dict[str, object]:
        with requests.Session() as session:
            for _ in range(51):
                try:
                    _dispatch(session)
                except DataFetchError:
                    return {"outcome": "partial"}
        return {"outcome": "success"}

    result = _REFRESH._execute_captured_task(task, capture=capture)

    assert result == {"outcome": "partial"}
    assert sends[0] == capture.dispatches == 50
    assert len(capture.receipts) == 50
    assert capture.rejected_dispatches == 1
    assert capture.guard_failure_code == "REHEARSAL_HTTP_BUDGET_EXCEEDED"
    assert _REFRESH._capture_failure_code(capture) == "S6_GRAPH_REFRESH_HTTP_BUDGET_EXCEEDED"

    assert _REFRESH._blocked("S6_GRAPH_REFRESH_HTTP_BUDGET_EXCEEDED", capture=capture) == 2
    output = capsys.readouterr().err
    assert "dispatch_count=50" in output
    assert "rejected_dispatch_count=1" in output
    assert "credential=private" not in output
    assert "provider.invalid" not in output


def test_exact_dispatch_limit_completes_without_false_guard_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Using exactly the configured allowance is not treated as an overrun."""
    sends = [0]
    lock = threading.Lock()
    monkeypatch.setattr(requests.Session, "send", _fake_send(sends, lock))
    capture = RehearsalHttpCapture(max_dispatches=50, max_seconds=30)

    def task() -> int:
        with requests.Session() as session:
            for _ in range(50):
                _dispatch(session)
        return 50

    assert _REFRESH._execute_captured_task(task, capture=capture) == 50
    assert sends[0] == capture.dispatches == 50
    assert len(capture.receipts) == 50
    assert capture.rejected_dispatches == 0
    assert capture.guard_failure_code is None


def test_concurrent_send_reservation_never_exceeds_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Concurrent adapter lookup cannot let several calls reserve one final slot."""
    sends = [0]
    send_lock = threading.Lock()
    monkeypatch.setattr(requests.Session, "send", _fake_send(sends, send_lock))
    original_get_adapter = requests.Session.get_adapter

    def delayed_get_adapter(session: requests.Session, url: str):
        time.sleep(0.02)
        return original_get_adapter(session, url)

    monkeypatch.setattr(requests.Session, "get_adapter", delayed_get_adapter)
    capture = RehearsalHttpCapture(max_dispatches=1, max_seconds=30)
    start = threading.Barrier(24)

    def request_once(_index: int) -> bool:
        with requests.Session() as session:
            start.wait(timeout=5)
            try:
                _dispatch(session)
            except DataFetchError:
                return False
            return True

    def task() -> list[bool]:
        with ThreadPoolExecutor(max_workers=24) as pool:
            return list(pool.map(request_once, range(24)))

    outcomes = _REFRESH._execute_captured_task(task, capture=capture)

    assert isinstance(outcomes, list)
    assert sum(outcomes) == sends[0] == capture.dispatches == 1
    assert len(capture.receipts) == 1
    assert capture.rejected_dispatches == 23
    assert capture.guard_failure_code == "REHEARSAL_HTTP_BUDGET_EXCEEDED"


def test_elapsed_time_limit_is_checked_after_adapter_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A slow local adapter lookup cannot let an expired request reach transport."""
    sends = [0]
    lock = threading.Lock()
    monkeypatch.setattr(requests.Session, "send", _fake_send(sends, lock))
    original_get_adapter = requests.Session.get_adapter

    def delayed_get_adapter(session: requests.Session, url: str):
        time.sleep(0.02)
        return original_get_adapter(session, url)

    monkeypatch.setattr(requests.Session, "get_adapter", delayed_get_adapter)
    capture = RehearsalHttpCapture(max_dispatches=50, max_seconds=0.001)

    def task() -> str:
        with requests.Session() as session:
            try:
                _dispatch(session)
            except DataFetchError:
                return "partial"
        return "success"

    result = _REFRESH._execute_captured_task(task, capture=capture)

    assert result == "partial"
    assert sends[0] == capture.dispatches == 0
    assert capture.rejected_dispatches == 1
    assert capture.guard_failure_code == "REHEARSAL_HTTP_BUDGET_EXCEEDED"


def test_parallel_response_retention_keeps_artifact_index_aligned_with_receipt_order(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Three reverse completions still leave each ref at its dispatch list index."""
    body = json.dumps(
        {
            "request_id": "req-1",
            "code": 0,
            "msg": "",
            "data": {
                "fields": ["ts_code", "trade_date", "close", "vol"],
                "items": [["600000.SH", "20261116", 10.25, 100]],
                "has_more": False,
            },
        },
        separators=(",", ":"),
    ).encode("utf-8")
    context = RehearsalResponseContext(
        candidate_sha="c" * 40,
        target_trade_date="2026-11-16",
        universe_sha256="a" * 64,
        provider_identities_sha256="b" * 64,
        provider_id=7,
        provider_source="tushare",
        endpoint_id="primary",
        dataset="equity.quote.snapshot",
        sample_codes=("600000.SH",),
    )
    response_root = tmp_path / "responses"
    response_root.mkdir()
    store = RehearsalResponseStore(
        response_root,
        max_responses=3,
        max_response_bytes=100_000,
        max_total_bytes=200_000,
    )
    original_persist = store.persist_response
    completion_gates = {index: threading.Event() for index in range(3)}
    completion_order: list[int] = []
    completion_lock = threading.Lock()

    def delayed_persist(response_context, **kwargs):
        receipt_index = kwargs["receipt_index"]
        if receipt_index < 2 and not completion_gates[receipt_index + 1].wait(timeout=5):
            raise AssertionError("higher dispatch did not complete response retention")
        artifact = original_persist(response_context, **kwargs)
        with completion_lock:
            completion_order.append(receipt_index)
        completion_gates[receipt_index].set()
        return artifact

    monkeypatch.setattr(store, "persist_response", delayed_persist)
    sends = [0]
    send_lock = threading.Lock()

    def fake_send(
        _session: requests.Session,
        request: requests.PreparedRequest,
        **_kwargs: object,
    ) -> Response:
        with send_lock:
            sends[0] += 1
        response = Response()
        response.status_code = 200
        response.url = str(request.url)
        response._content = body
        response._content_consumed = True
        return response

    monkeypatch.setattr(requests.Session, "send", fake_send)
    capture = RehearsalHttpCapture(max_dispatches=3, max_seconds=30, response_store=store)
    start = threading.Barrier(3)

    def retain_once(label: str) -> None:
        with requests.Session() as session:
            start.wait(timeout=5)
            with capture.provider_probe(context):
                _dispatch(session, delay_label=label)

    def task() -> None:
        with ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(retain_once, ("first", "second", "third")))

    _REFRESH._execute_captured_task(task, capture=capture)

    artifact_refs = [receipt.response_artifact for receipt in capture.receipts]
    assert sends[0] == capture.dispatches == 3
    assert completion_order == [2, 1, 0]
    assert len(artifact_refs) == 3
    for index, artifact in enumerate(artifact_refs):
        assert artifact is not None
        assert artifact.receipt_index == index
        assert (response_root / artifact.path).is_file()
    assert len(list(response_root.rglob("*.body"))) == 3


@pytest.mark.parametrize(
    ("failure_kind", "expected_code"),
    (
        ("hidden_retry", "REHEARSAL_HIDDEN_RETRIES"),
        ("unknown_adapter", "REHEARSAL_TRANSPORT_UNOBSERVABLE"),
        ("redirect", "REHEARSAL_REDIRECT_BLOCKED"),
        ("oversized_body", "REHEARSAL_BODY_LIMIT"),
    ),
)
def test_swallowed_unobservable_transport_failures_invalidate_capture(
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
    expected_code: str,
) -> None:
    """A partial task result cannot hide retry, redirect, adapter, or body guard failures."""
    sends = [0]
    lock = threading.Lock()

    def fake_send(
        session: requests.Session,
        request: requests.PreparedRequest,
        **kwargs: object,
    ) -> Response:
        response = _fake_send(sends, lock)(session, request, **kwargs)
        if failure_kind == "redirect":
            response.status_code = 302
            response.headers["Location"] = "https://provider.invalid/next"
        elif failure_kind == "oversized_body":
            response._content = b"larger-than-limit"
        return response

    monkeypatch.setattr(requests.Session, "send", fake_send)
    capture_kwargs: dict[str, object] = {
        "max_dispatches": 2,
        "max_seconds": 30,
    }
    if failure_kind == "oversized_body":
        capture_kwargs["max_body_bytes"] = 1
    capture = RehearsalHttpCapture(**capture_kwargs)

    def task() -> dict[str, object]:
        with requests.Session() as session:
            if failure_kind == "hidden_retry":
                session.mount("https://", requests.adapters.HTTPAdapter(max_retries=1))
            if failure_kind == "unknown_adapter":
                monkeypatch.setattr(session, "get_adapter", lambda _url: object())
            try:
                _dispatch(session)
            except DataFetchError:
                return {"outcome": "partial"}
        return {"outcome": "success"}

    result = _REFRESH._execute_captured_task(task, capture=capture)

    assert result == {"outcome": "partial"}
    assert capture.guard_failure_code == expected_code
    assert _REFRESH._capture_failure_code(capture) == "S6_GRAPH_REFRESH_HTTP_OBSERVATION_FAILED"
    assert capture.dispatches <= 1
    if failure_kind in {"hidden_retry", "unknown_adapter"}:
        assert sends[0] == 0
        assert capture.rejected_dispatches == 1
    else:
        assert sends[0] == 1


def test_success_receipt_budget_summary_is_strict_and_secret_free() -> None:
    """Receipt and prepare validators reject forged counters or widened limits."""
    evidence: dict[str, object] = {
        "count_unit": "requests_session_dispatch",
        "dispatch_count": 50,
        "rejected_dispatch_count": 0,
        "guard_failure_code": None,
        "max_dispatches": 50,
        "max_seconds": 3600.0,
        "elapsed_seconds": 17.5,
    }
    assert _RECEIPT._validated_http_capture(evidence) == evidence

    identity = {
        "candidate_sha": "a" * 40,
        "attempt_id": "b" * 32,
        "attempt_plan_sha256": "c" * 64,
        "database": "agom_release_rehearsal_" + "d" * 32,
        "task_id": "s6-market-refresh-" + "b" * 32,
    }
    report = {
        "schema": "release.s6-isolated-market-graph-refresh.v2",
        "outcome": "success",
        **identity,
        "http_capture": evidence,
    }
    _SNAPSHOT._validate_market_graph_refresh_report(report, **identity)

    for changed in (
        {**evidence, "dispatch_count": 51},
        {**evidence, "max_dispatches": 51},
        {**evidence, "max_seconds": 3601.0},
        {**evidence, "rejected_dispatch_count": 1},
        {**evidence, "guard_failure_code": "REHEARSAL_HTTP_BUDGET_EXCEEDED"},
    ):
        with pytest.raises(ValueError):
            _RECEIPT._validated_http_capture(changed)
        with pytest.raises(ValueError):
            _SNAPSHOT._validate_market_graph_refresh_report(
                {**report, "http_capture": changed}, **identity
            )


def test_prepare_shell_passes_exact_reviewed_dispatch_bounds() -> None:
    """The only normal prepare path supplies the same limits the argv verifier pins."""
    shell = (_REPO_ROOT / "scripts/prepare_release_rehearsal_attempt.sh").read_text(
        encoding="utf-8"
    )
    assert "--max-dispatches 50" in shell
    assert "--max-seconds 3600" in shell


@pytest.mark.parametrize("calendar_available", [True, False])
def test_calendar_discovery_and_task_share_one_transport_budget(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    calendar_available: bool,
) -> None:
    """The real launcher counts calendar requests even when no target is found."""
    from datetime import date

    import django
    import django.db

    from apps.data_center.application import market_calendar, tasks

    sends = [0]
    lock = threading.Lock()
    monkeypatch.setattr(requests.Session, "send", _fake_send(sends, lock))
    monkeypatch.setattr(_REFRESH, "_validate_runtime_identity", lambda *_args: None)
    monkeypatch.setattr(_REFRESH, "_prepare_candidate_imports", lambda: None)
    monkeypatch.setattr(_REFRESH, "_is_within", lambda *_args: True)
    monkeypatch.setattr(django, "setup", lambda: None)

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, _query):
            return None

        def fetchone(self):
            return ("isolated", "off", "off")

    monkeypatch.setattr(
        django.db,
        "connection",
        SimpleNamespace(settings_dict={"NAME": "isolated", "HOST": "isolated"}, cursor=Cursor),
    )

    def resolve(_now, *, ready_after):
        with requests.Session() as session:
            _dispatch(session)
        return date(2026, 11, 17) if calendar_available else None

    monkeypatch.setattr(_REFRESH, "_check_restored_graph_scope", lambda *_: date(2026, 11, 17))

    task_calls = []

    def apply(**_kwargs):
        task_calls.append(True)
        with requests.Session() as session:
            for _ in range(50):
                try:
                    _dispatch(session)
                except DataFetchError:
                    break
        return SimpleNamespace(state="FAILURE")

    monkeypatch.setattr(market_calendar, "latest_cn_market_session_ready_after", resolve)
    monkeypatch.setattr(tasks.refresh_full_market_publications_task, "apply", apply)
    args = SimpleNamespace(
        database="isolated",
        postgres_container="isolated",
        max_dispatches=50,
        max_seconds=30,
        task_id="test-isolated",
    )
    assert _REFRESH._run(args, {}) == 2
    output = capsys.readouterr().err
    if calendar_available:
        assert task_calls == [True]
        assert sends[0] == 50
        assert "S6_GRAPH_REFRESH_HTTP_BUDGET_EXCEEDED" in output
        assert "dispatch_count=50" in output
        assert "rejected_dispatch_count=1" in output
    else:
        assert not task_calls
        assert sends[0] == 1
        assert "S6_GRAPH_REFRESH_TARGET_SESSION_UNAVAILABLE" in output
        assert "dispatch_count=1" in output
    assert "provider.invalid" not in output
    assert "credential=private" not in output


def test_failed_graph_reports_guard_code_without_transport_secrets(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A post-dispatch redirect is identifiable without publishing its URL or query."""
    sends = [0]
    fake = _fake_send(sends, threading.Lock())

    def redirect(session, request, **kwargs):
        response = fake(session, request, **kwargs)
        response.status_code = 302
        response.headers["Location"] = "https://provider.invalid/private?token=private"
        return response

    monkeypatch.setattr(requests.Session, "send", redirect)
    capture = RehearsalHttpCapture(max_dispatches=2, max_seconds=30)
    with pytest.raises(DataFetchError):
        _REFRESH._execute_captured_task(lambda: _dispatch(requests.Session()), capture=capture)
    assert _REFRESH._blocked("S6_GRAPH_REFRESH_HTTP_OBSERVATION_FAILED", capture=capture) == 2
    output = capsys.readouterr().err
    assert "dispatch_count=1" in output
    assert "rejected_dispatch_count=0" in output
    assert "guard_failure_code=REHEARSAL_REDIRECT_BLOCKED" in output
    assert "provider.invalid" not in output and "private" not in output
    diagnostics = next(
        (
            line
            for line in output.splitlines()
            if line.startswith("S6_GRAPH_REFRESH_HTTP_FAILURES ")
        ),
        None,
    )
    assert diagnostics is not None
    failures = json.loads(diagnostics.split(" ", 1)[1])
    assert len(failures) == 1
    assert failures[0]["host_sha256"] == hashlib.sha256(b"provider.invalid").hexdigest()
    assert failures[0]["path_sha256"] == capture.receipts[0].path_sha256
    assert failures[0]["status_code"] == 302
    assert failures[0]["error_code"] == "REHEARSAL_REDIRECT_BLOCKED"
