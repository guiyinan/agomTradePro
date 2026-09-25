"""Offline tests for the output-only response-retention proposal."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import requests

PROPOSAL_ROOT = Path(__file__).resolve().parents[3]
PROPOSAL_INFRA = PROPOSAL_ROOT / "apps" / "data_center" / "infrastructure"
PROPOSAL_PACKAGE = "_s6_response_replay_proposal"
PROPOSAL_INFRA_PACKAGE = f"{PROPOSAL_PACKAGE}.infrastructure"


def _load_python_module(name: str, path: Path) -> ModuleType:
    """Load one draft module under an isolated package name for offline tests."""
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("proposal module cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _install_proposal_package() -> tuple[ModuleType, ModuleType]:
    """Load only the copied proposal modules, never the live shared implementation."""
    root_package = ModuleType(PROPOSAL_PACKAGE)
    root_package.__dict__["__path__"] = []
    infra_package = ModuleType(PROPOSAL_INFRA_PACKAGE)
    infra_package.__dict__["__path__"] = [str(PROPOSAL_INFRA)]
    sys.modules[PROPOSAL_PACKAGE] = root_package
    sys.modules[PROPOSAL_INFRA_PACKAGE] = infra_package
    store_module = _load_python_module(
        f"{PROPOSAL_INFRA_PACKAGE}.rehearsal_response_store",
        PROPOSAL_INFRA / "rehearsal_response_store.py",
    )
    capture_module = _load_python_module(
        f"{PROPOSAL_INFRA_PACKAGE}.rehearsal_http_capture",
        PROPOSAL_INFRA / "rehearsal_http_capture.py",
    )
    return store_module, capture_module


@pytest.fixture(scope="module")
def proposal_modules() -> Any:
    """Load and then remove the independent proposal package from sys.modules."""
    modules = _install_proposal_package()
    try:
        yield modules
    finally:
        for name in tuple(sys.modules):
            if name == PROPOSAL_PACKAGE or name.startswith(f"{PROPOSAL_PACKAGE}."):
                del sys.modules[name]


def _context(
    modules: Any,
    *,
    dataset: str = "equity.quote.snapshot",
    sample_codes: tuple[str, ...] = ("000001.SZ", "600000.SH"),
) -> Any:
    """Build the frozen Tushare association context used only by these local fixtures."""
    return modules[0].RehearsalResponseContext(
        candidate_sha="c" * 40,
        target_trade_date="2026-09-24",
        universe_sha256="a" * 64,
        provider_identities_sha256="b" * 64,
        provider_id=7,
        provider_source="tushare",
        endpoint_id="primary",
        dataset=dataset,
        sample_codes=sample_codes,
    )


def _body(
    *,
    dataset: str = "equity.quote.snapshot",
    rows: list[list[object]] | None = None,
    fields: list[str] | None = None,
    message: object = "",
    code: object = 0,
    has_more: object = False,
    extra: dict[str, object] | None = None,
) -> bytes:
    """Create an explicitly synthetic successful daily or daily_basic response."""
    if dataset == "equity.quote.snapshot":
        fields = fields or ["ts_code", "trade_date", "close", "vol"]
        rows = rows or [
            ["000001.SZ", "20260924", 10.25, 100],
            ["600000.SH", "20260924", 9.75, 200],
        ]
    else:
        fields = fields or ["ts_code", "trade_date", "total_mv", "circ_mv", "pe_ttm"]
        rows = rows or [
            ["000001.SZ", "20260924", 120.0, 90.0, 10.5],
            ["600000.SH", "20260924", 220.0, 180.0, None],
        ]
    envelope: dict[str, object] = {
        "request_id": "req-12345",
        "code": code,
        "msg": message,
        "data": {"fields": fields, "items": rows, "has_more": has_more},
    }
    if extra:
        envelope.update(extra)
    return json.dumps(envelope, separators=(",", ":"), allow_nan=True).encode("utf-8")


def _store(
    modules: Any,
    root: Path,
    *,
    max_responses: int = 3,
    max_response_bytes: int = 1_000_000,
    max_total_bytes: int = 2_000_000,
) -> Any:
    """Construct a store rooted in an already-created task-private test directory."""
    return modules[0].RehearsalResponseStore(
        root,
        max_responses=max_responses,
        max_response_bytes=max_response_bytes,
        max_total_bytes=max_total_bytes,
    )


def _persist(
    store: Any,
    context: Any,
    body: bytes,
    *,
    receipt_index: int = 3,
) -> Any:
    """Persist one synthetic response with safe, fixed transport metadata."""
    return store.persist_response(
        context,
        receipt_index=receipt_index,
        host="api.tushare.pro",
        path_sha256="d" * 64,
        method="POST",
        started_at="2026-09-25T02:00:00+00:00",
        finished_at="2026-09-25T02:00:01+00:00",
        status_code=200,
        response_body=body,
    )


class _FakeResponse(requests.Response):
    """A response whose chunks come only from an in-memory fixture."""

    def __init__(self, payload: bytes, *, status_code: int = 200) -> None:
        super().__init__()
        self.status_code = status_code
        self._payload = payload

    def iter_content(self, chunk_size: int = 1, decode_unicode: bool = False) -> Any:
        del decode_unicode
        for offset in range(0, len(self._payload), chunk_size):
            yield self._payload[offset : offset + chunk_size]


class _FakeTransport:
    """Return only a mutable in-memory response fixture from the requests transport seam."""

    def __init__(self) -> None:
        self.response = _FakeResponse(b"")

    def send(
        self, session: requests.Session, request: requests.PreparedRequest, **kwargs: object
    ) -> requests.Response:
        del session, request, kwargs
        return self.response


def _install_fake_transport(monkeypatch: pytest.MonkeyPatch) -> _FakeTransport:
    """Install a local fake before capture wraps the requests transport method."""
    transport = _FakeTransport()
    monkeypatch.setattr(requests.Session, "send", transport.send)
    return transport


def _send_fake_request(
    transport: _FakeTransport,
    payload: bytes,
    *,
    status_code: int = 200,
    url: str = "https://api.tushare.pro/v1/daily?token=DO_NOT_RETAIN",
) -> requests.Response:
    """Dispatch an in-memory response through the already-wrapped fake transport."""
    transport.response = _FakeResponse(payload, status_code=status_code)
    request = requests.Request(
        "POST",
        url,
        data="REQUEST_BODY_SECRET",
        headers={"Authorization": "Bearer REQUEST_HEADER_SECRET"},
    ).prepare()
    session = requests.Session()
    return session.send(request, timeout=5)


def test_strict_parser_accepts_success_and_full_market_superset(proposal_modules: Any) -> None:
    """Allow a full daily_basic table even when replay later selects a smaller sample."""
    store_module = proposal_modules[0]
    context = _context(
        proposal_modules,
        dataset="equity.valuation.fact",
        sample_codes=("000001.SZ",),
    )
    parsed = store_module.parse_validate_tushare_response(
        _body(dataset="equity.valuation.fact", message=None), context
    )
    assert [row["ts_code"] for row in parsed] == ["000001.SZ", "600000.SH"]
    assert parsed[0]["trade_date"] == "20260924"
    assert parsed[1]["pe_ttm"] is None


@pytest.mark.parametrize(
    "body",
    [
        _body(message="provider failure echoed: secret"),
        _body(code=True),
        _body(has_more=True),
        _body(extra={"access_token": "secret"}),
        _body(fields=["ts_code", "trade_date", "token"]),
        _body(rows=[["000001.SZ", "20260924", "not numeric", 100]]),
        _body(rows=[["000001.SZ", "20260925", 10.0, 100]]),
        _body(rows=[["000001.SZ", "20260924", float("nan"), 100]]),
        b'{"code":0,"code":0,"data":{"fields":["ts_code","trade_date"],"items":[]}}',
    ],
)
def test_invalid_responses_are_never_retained(
    proposal_modules: Any, tmp_path: Path, body: bytes
) -> None:
    """Reject failed, incomplete, ambiguous, future-dated or unsafe table payloads."""
    root = tmp_path / "evidence"
    root.mkdir()
    context = _context(proposal_modules)
    store = _store(proposal_modules, root)
    with pytest.raises(proposal_modules[0].DataFetchError):
        _persist(store, context, body)
    assert list(root.rglob("*.body")) == []


def test_store_writes_exact_bytes_and_safe_context_reference(
    proposal_modules: Any, tmp_path: Path
) -> None:
    """Retain the original response bytes and attach only bounded association metadata."""
    root = tmp_path / "evidence"
    root.mkdir()
    context = _context(proposal_modules)
    body = _body()
    ref = _persist(_store(proposal_modules, root), context, body)
    artifact = root / ref.path
    assert ref.schema == "release.provider-response-artifact-ref.v1"
    assert ref.path.startswith("provider-responses/0003-")
    assert ref.body_sha256 == hashlib.sha256(body).hexdigest()
    assert ref.body_bytes == len(body)
    assert artifact.read_bytes() == body
    metadata = json.dumps(ref.__dict__, sort_keys=True)
    assert "DO_NOT_RETAIN" not in metadata
    assert "REQUEST_HEADER_SECRET" not in metadata
    assert "REQUEST_BODY_SECRET" not in metadata


def test_response_count_budget_and_collision_do_not_overwrite(
    proposal_modules: Any, tmp_path: Path
) -> None:
    """Enforce the count budget and exclusive path creation without replacing old bytes."""
    root = tmp_path / "evidence"
    root.mkdir()
    context = _context(proposal_modules)
    body = _body()
    store = _store(proposal_modules, root, max_responses=2)
    first_ref = _persist(store, context, body, receipt_index=4)
    artifact = root / first_ref.path
    with pytest.raises(proposal_modules[0].DataFetchError) as collision:
        _persist(store, context, body, receipt_index=4)
    assert collision.value.code == "REHEARSAL_RESPONSE_ARTIFACT_EXISTS"
    assert artifact.read_bytes() == body
    second_body = _body(message=None)
    _persist(store, context, second_body, receipt_index=5)
    with pytest.raises(proposal_modules[0].DataFetchError) as exhausted:
        _persist(store, context, body, receipt_index=6)
    assert exhausted.value.code == "REHEARSAL_RESPONSE_COUNT_LIMIT"
    assert len(list(root.rglob("*.body"))) == 2


def test_byte_budgets_reject_without_partial_success(proposal_modules: Any, tmp_path: Path) -> None:
    """Reject bodies beyond either byte cap before creating an artifact."""
    context = _context(proposal_modules)
    body = _body()
    response_root = tmp_path / "response-limit"
    response_root.mkdir()
    too_small = _store(
        proposal_modules,
        response_root,
        max_response_bytes=len(body) - 1,
    )
    with pytest.raises(proposal_modules[0].DataFetchError) as response_limit:
        _persist(too_small, context, body)
    assert response_limit.value.code == "REHEARSAL_RESPONSE_BODY_LIMIT"
    assert list(response_root.rglob("*.body")) == []

    total_root = tmp_path / "total-limit"
    total_root.mkdir()
    total_limited = _store(
        proposal_modules,
        total_root,
        max_total_bytes=len(body),
    )
    _persist(total_limited, context, body, receipt_index=1)
    with pytest.raises(proposal_modules[0].DataFetchError) as total_limit:
        _persist(total_limited, context, _body(message=None), receipt_index=2)
    assert total_limit.value.code == "REHEARSAL_RESPONSE_TOTAL_LIMIT"
    assert len(list(total_root.rglob("*.body"))) == 1


def test_write_failure_removes_partial_body(
    proposal_modules: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A failed durability boundary must leave no body file or reference."""
    store_module = proposal_modules[0]
    root = tmp_path / "evidence"
    root.mkdir()
    store = _store(proposal_modules, root)

    def fail_fsync(descriptor: int) -> None:
        del descriptor
        raise OSError("synthetic fsync failure")

    monkeypatch.setattr(store_module.os, "fsync", fail_fsync)
    with pytest.raises(store_module.DataFetchError) as failure:
        _persist(store, _context(proposal_modules), _body())
    assert failure.value.code == "REHEARSAL_RESPONSE_WRITE_FAILED"
    assert list(root.rglob("*.body")) == []


def test_capture_retains_only_inside_explicit_provider_scope(
    proposal_modules: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Keep calendar/out-of-scope responses in memory only and retain provider bytes once."""
    root = tmp_path / "evidence"
    root.mkdir()
    store = _store(proposal_modules, root)
    capture_module = proposal_modules[1]
    context = _context(proposal_modules)
    body = _body()
    capture = capture_module.RehearsalHttpCapture(
        max_dispatches=3,
        max_seconds=10.0,
        response_store=store,
    )
    transport = _install_fake_transport(monkeypatch)
    with capture:
        _send_fake_request(transport, body)
        assert capture.receipts[-1].response_artifact is None
        assert list(root.rglob("*.body")) == []
        with capture.provider_probe(context):
            _send_fake_request(transport, body)
        receipt = capture.receipts[-1]
        assert receipt.response_artifact is not None
        assert receipt.response_artifact.body_sha256 == hashlib.sha256(body).hexdigest()
        assert (root / receipt.response_artifact.path).read_bytes() == body
        serialized = json.dumps(capture.to_dict(), sort_keys=True)
        assert "DO_NOT_RETAIN" not in serialized
        assert "REQUEST_HEADER_SECRET" not in serialized
        assert "REQUEST_BODY_SECRET" not in serialized
        _send_fake_request(transport, body)
        assert capture.receipts[-1].response_artifact is None
    assert len(list(root.rglob("*.body"))) == 1


def test_capture_rejects_unsupported_response_without_success_reference(
    proposal_modules: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A non-success Tushare body fails closed and cannot leave a retained body file."""
    root = tmp_path / "evidence"
    root.mkdir()
    capture = proposal_modules[1].RehearsalHttpCapture(
        max_dispatches=1,
        max_seconds=10.0,
        response_store=_store(proposal_modules, root),
    )
    transport = _install_fake_transport(monkeypatch)
    with capture:
        with capture.provider_probe(_context(proposal_modules)):
            with pytest.raises(proposal_modules[0].DataFetchError):
                _send_fake_request(transport, _body(code=500))
    receipt = capture.receipts[-1]
    assert receipt.response_artifact is None
    assert receipt.error_code == "REHEARSAL_RESPONSE_NOT_RETAINABLE"
    assert list(root.rglob("*.body")) == []


def test_capture_without_store_keeps_default_observation_only_behavior(
    proposal_modules: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Keep the existing no-store default as observation-only even for HTTP 200 bodies."""
    root = tmp_path / "evidence"
    root.mkdir()
    capture = proposal_modules[1].RehearsalHttpCapture(max_dispatches=1, max_seconds=10.0)
    transport = _install_fake_transport(monkeypatch)
    with capture:
        _send_fake_request(transport, _body())
    assert capture.receipts[0].status_code == 200
    assert capture.receipts[0].response_artifact is None
    assert list(root.rglob("*.body")) == []


def test_provider_scope_requires_an_explicit_store(proposal_modules: Any) -> None:
    """Do not silently imply that response bytes were retained when no store was configured."""
    capture = proposal_modules[1].RehearsalHttpCapture(max_dispatches=1, max_seconds=1.0)
    with pytest.raises(proposal_modules[0].DataFetchError) as failure:
        with capture.provider_probe(_context(proposal_modules)):
            pass
    assert failure.value.code == "REHEARSAL_RESPONSE_STORE_UNAVAILABLE"


def test_context_rejects_noncanonical_identity_and_sample(proposal_modules: Any) -> None:
    """Require canonical hashes, dates and sorted unique provider sample identities."""
    context_type = proposal_modules[0].RehearsalResponseContext
    base: dict[str, object] = {
        "candidate_sha": "c" * 40,
        "target_trade_date": "2026-09-24",
        "universe_sha256": "a" * 64,
        "provider_identities_sha256": "b" * 64,
        "provider_id": 7,
        "provider_source": "tushare",
        "endpoint_id": "primary",
        "dataset": "equity.quote.snapshot",
        "sample_codes": ("000001.SZ", "600000.SH"),
    }
    invalid_values: list[dict[str, object]] = [
        {**base, "target_trade_date": "2026-02-30"},
        {**base, "provider_id": True},
        {**base, "provider_source": "other"},
        {**base, "sample_codes": ("600000.SH", "000001.SZ")},
        {**base, "sample_codes": ("000001.SZ", "000001.SZ")},
        {**base, "universe_sha256": "A" * 64},
    ]
    for fields in invalid_values:
        with pytest.raises(ValueError):
            context_type(**fields)
