"""Unit contracts for the offline EVID-02 PostgreSQL evidence recorder."""

from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from apps.research.application.evid_02_postgres_evidence import (
    EVID_02_HARNESS_SUITE,
    EVID_02_INPUT_FORMAT,
    Evid02EvidenceError,
    evid_02_artifact_sha256,
    parse_evid_02_run_payload,
    serialize_evid_02_report,
)
from scripts.record_evid_02_postgres_evidence import (
    _write_append_only,
)
from scripts.record_evid_02_postgres_evidence import main as record_main

_STARTED_AT = "2026-08-19T08:00:00.000000Z"
_FINISHED_AT = "2026-08-19T08:00:03.000000Z"


def _raw_payload() -> dict[str, object]:
    """Build a complete raw result emitted by the fixed local harness."""

    return {
        "format": EVID_02_INPUT_FORMAT,
        "database": {
            "vendor": "postgresql",
            "host": "127.0.0.1",
            "database_name": "evidence_scope_test_20260819",
            "disposable": True,
            "empty_before": True,
        },
        "run": {
            "run_id": "local-pg-run-20260819",
            "suite": EVID_02_HARNESS_SUITE,
            "started_at": _STARTED_AT,
            "finished_at": _FINISHED_AT,
            "pytest_exit_code": 0,
        },
        "cases": [
            {
                "case_id": "empty_root_first_winner",
                "status": "passed",
                "winner_count": 1,
                "conflict_count": 1,
                "row_count": 1,
                "duration_seconds": 1.0,
            },
            {
                "case_id": "same_predecessor_successor_first_winner",
                "status": "passed",
                "winner_count": 1,
                "conflict_count": 1,
                "row_count": 2,
                "duration_seconds": 1.0,
            },
            {
                "case_id": "outer_transaction_rollback",
                "status": "passed",
                "winner_count": 0,
                "conflict_count": 0,
                "row_count": 0,
                "duration_seconds": 1.0,
            },
        ],
        "head_audit": {
            "status": "not_collected",
            "reason": "local_harness_does_not_query_existing_ledgers",
        },
        "human_approval": {
            "status": "not_collected",
            "reason": "automation_must_not_invent_human_approval",
        },
    }


def _payload_bytes(payload: dict[str, object] | None = None) -> bytes:
    """Encode a raw fixture with stable compact JSON bytes."""

    return json.dumps(payload or _raw_payload(), separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )


def test_valid_harness_payload_is_non_production_and_content_addressed() -> None:
    """All fixed local cases serialize deterministically without a gate claim."""

    raw = _payload_bytes()
    report = parse_evid_02_run_payload(raw, source_kind="local_postgresql_harness")
    canonical = serialize_evid_02_report(report)
    decoded = json.loads(canonical)

    assert report.collection_status.value == "passed"
    assert report.production_ready is False
    assert decoded["production_claim"] is False
    assert decoded["runtime_enablement"] == "not_authorized"
    assert decoded["head_audit"]["status"] == "not_collected"
    assert decoded["human_approval"]["status"] == "not_collected"
    assert canonical == serialize_evid_02_report(report)
    assert evid_02_artifact_sha256(canonical) == hashlib.sha256(canonical).hexdigest()


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload["cases"].pop(),
        lambda payload: payload["cases"].append(payload["cases"][0]),
        lambda payload: payload["cases"].__setitem__(
            0, {**payload["cases"][0], "case_id": "unknown"}
        ),
    ],
)
def test_case_set_must_be_complete_unique_and_known(mutation) -> None:
    """Missing, duplicate, and unknown case IDs cannot hide absent evidence."""

    payload = _raw_payload()
    mutation(payload)
    with pytest.raises(Evid02EvidenceError, match="case"):
        parse_evid_02_run_payload(_payload_bytes(payload), source_kind="local_postgresql_harness")


def test_case_status_and_facts_are_derived_not_caller_passed() -> None:
    """A skipped case remains incomplete and impossible to promote."""

    payload = _raw_payload()
    payload["cases"][1]["status"] = "skipped"
    parsed = parse_evid_02_run_payload(
        _payload_bytes(payload), source_kind="local_postgresql_harness"
    )
    assert parsed.collection_status.value == "incomplete"
    assert parsed.production_ready is False

    payload = _raw_payload()
    payload["cases"][0]["winner_count"] = 2
    with pytest.raises(Evid02EvidenceError, match="facts"):
        parse_evid_02_run_payload(_payload_bytes(payload), source_kind="local_postgresql_harness")


@pytest.mark.parametrize("host", ["production-db", "vps", "10.0.0.2"])
def test_database_binding_rejects_production_or_remote_hosts(host: str) -> None:
    """The recorder cannot be redirected to a VPS or production database."""

    payload = _raw_payload()
    payload["database"]["host"] = host
    with pytest.raises(Evid02EvidenceError, match="host"):
        parse_evid_02_run_payload(_payload_bytes(payload), source_kind="local_postgresql_harness")


def test_database_binding_rejects_sqlite_and_non_disposable_input() -> None:
    """SQLite and non-empty/non-disposable sources are never EVID-02 evidence."""

    payload = _raw_payload()
    payload["database"]["vendor"] = "sqlite"
    with pytest.raises(Evid02EvidenceError, match="vendor"):
        parse_evid_02_run_payload(_payload_bytes(payload), source_kind="local_postgresql_harness")

    payload = _raw_payload()
    payload["database"]["empty_before"] = False
    with pytest.raises(Evid02EvidenceError, match="empty"):
        parse_evid_02_run_payload(_payload_bytes(payload), source_kind="local_postgresql_harness")


def test_human_approval_and_head_audit_cannot_be_fabricated() -> None:
    """The offline contract records missing external facts explicitly."""

    payload = _raw_payload()
    payload["human_approval"]["status"] = "approved"
    with pytest.raises(Evid02EvidenceError, match="human approval"):
        parse_evid_02_run_payload(_payload_bytes(payload), source_kind="local_postgresql_harness")

    payload = _raw_payload()
    payload["head_audit"]["status"] = "collected"
    with pytest.raises(Evid02EvidenceError, match="current-head"):
        parse_evid_02_run_payload(_payload_bytes(payload), source_kind="local_postgresql_harness")


def test_secret_fields_are_rejected_without_echoing_values() -> None:
    """Secret-shaped fields fail closed without exposing the supplied value."""

    secret = "never-print-this-secret"
    payload = _raw_payload()
    payload["run"]["api_key"] = secret
    with pytest.raises(Evid02EvidenceError) as caught:
        parse_evid_02_run_payload(_payload_bytes(payload), source_kind="local_postgresql_harness")
    assert secret not in str(caught.value)


def test_timestamp_and_payload_shape_are_strict() -> None:
    """Canonical UTC-Z timestamps and exact JSON keys are required."""

    payload = _raw_payload()
    payload["run"]["started_at"] = "2026-08-19T08:00:00+00:00"
    with pytest.raises(Evid02EvidenceError, match="UTC-Z"):
        parse_evid_02_run_payload(_payload_bytes(payload), source_kind="local_postgresql_harness")

    payload = _raw_payload()
    payload["unexpected"] = "field"
    with pytest.raises(Evid02EvidenceError, match="key set"):
        parse_evid_02_run_payload(_payload_bytes(payload), source_kind="local_postgresql_harness")


def test_recorder_module_has_no_database_or_network_imports() -> None:
    """Offline collector code cannot silently become a production client."""

    source = Path("apps/research/application/evid_02_postgres_evidence.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    imported = {
        alias.name
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not any(
        forbidden in name
        for name in imported
        for forbidden in ("django", "psycopg", "postgres", "requests", "socket", "subprocess")
    )


def test_content_addressed_writer_is_idempotent_and_rejects_collision(tmp_path: Path) -> None:
    """The recorder never overwrites bytes at an existing digest path."""

    payload = b"canonical-evid-02-evidence"
    digest = hashlib.sha256(payload).hexdigest()
    path, created = _write_append_only(tmp_path, digest, payload)
    assert created is True
    assert path.read_bytes() == payload
    same_path, created_again = _write_append_only(tmp_path, digest, payload)
    assert same_path == path
    assert created_again is False
    with pytest.raises(Evid02EvidenceError, match="collision"):
        _write_append_only(tmp_path, digest, b"different-bytes")


def test_recorder_cli_defaults_to_dry_run_and_supports_explicit_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The CLI is read-only by default and writes only with explicit --write."""

    input_path = tmp_path / "harness.json"
    input_path.write_bytes(_payload_bytes())
    monkeypatch.setattr(
        "sys.argv",
        ["record_evid_02_postgres_evidence.py", "--input", str(input_path)],
    )
    assert record_main() == 0
    assert not (tmp_path / "evid-02-postgres").exists()

    output_root = tmp_path / "evidence"
    monkeypatch.setattr(
        "sys.argv",
        [
            "record_evid_02_postgres_evidence.py",
            "--input",
            str(input_path),
            "--output-root",
            str(output_root),
            "--write",
        ],
    )
    assert record_main() == 0
    assert list((output_root / "evid-02-postgres").rglob("*.json"))


def test_recorder_script_runs_directly_from_repository_root() -> None:
    """The server-side recorder must be executable without PYTHONPATH setup."""

    result = subprocess.run(
        [sys.executable, "scripts/record_evid_02_postgres_evidence.py", "--help"],
        cwd=Path(__file__).resolve().parents[2],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "raw harness result JSON path" in result.stdout
