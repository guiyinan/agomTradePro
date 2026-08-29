"""Contracts for the AUD-03 read-only operational observation recorder."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from apps.audit.application.aud03_operational_observation_evidence import (
    Aud03OperationalObservationError,
    aud03_operational_observation_artifact_sha256,
    parse_aud03_operational_observation,
    serialize_aud03_operational_observation,
)
from scripts.record_aud03_operational_observation_evidence import (
    record_aud03_operational_observation,
)


def _candidate() -> dict[str, str]:
    """Return a complete candidate identity."""

    return {
        "commit": "a" * 40,
        "matrix_sha256": "b" * 64,
        "oci_revision": "sha256:" + "c" * 64,
        "version": "20260824.01",
    }


def _available_observation(
    observed_at: str, *, candidate: dict[str, str] | None = None
) -> dict[str, object]:
    """Build one complete operational observation."""

    return {
        "archive": {
            "availability": "available",
            "manifest_sha256": "d" * 64,
            "member_count": 7204,
            "reason_code": None,
            "restored_sha256": "e" * 64,
            "source_sha256": "e" * 64,
        },
        "alerts": {
            "active_codes": [],
            "availability": "available",
            "critical_codes": [],
            "reason_code": None,
        },
        "candidate": candidate or _candidate(),
        "metrics": {
            "availability": "available",
            "reason_code": None,
            "values": {"audit.events.count": 3, "audit.outbox.age_seconds": 0.0},
        },
        "migration": {
            "applied_count": 72,
            "availability": "available",
            "failed_count": 0,
            "graph_sha256": "f" * 64,
            "pending_count": 0,
            "reason_code": None,
            "status": "ok",
        },
        "observed_at": observed_at,
        "outbox": {
            "availability": "available",
            "claimed_count": 0,
            "delivered_count": 0,
            "due_pending_count": 0,
            "expired_claimed_count": 0,
            "failed_count": 0,
            "oldest_backlog_at": None,
            "oldest_claimed_at": None,
            "pending_count": 0,
            "reason_code": None,
        },
        "recovery": {
            "availability": "available",
            "completed_at": "2026-08-23T08:00:00.000000Z",
            "duplicate_count": 0,
            "loss_count": 0,
            "reason_code": None,
            "started_at": "2026-08-23T07:59:00.000000Z",
            "status": "ok",
        },
        "tui": {"availability": "available", "reason_code": None, "status": "ok"},
    }


def _payload() -> dict[str, object]:
    """Build a complete two-sample select-only envelope."""

    return {
        "candidate": _candidate(),
        "observations": [
            _available_observation("2026-08-23T08:00:00.000000Z"),
            _available_observation("2026-08-23T08:05:00.000000Z"),
        ],
        "read_mode": "select_only",
    }


def _payload_bytes(payload: dict[str, object] | None = None) -> bytes:
    """Encode a deterministic envelope."""

    return json.dumps(payload or _payload(), separators=(",", ":"), sort_keys=True).encode("utf-8")


def test_valid_observations_derive_operational_facts_without_acceptance() -> None:
    """Available source facts are preserved and never become a production gate."""

    report = parse_aud03_operational_observation(
        _payload_bytes(),
        as_of=datetime(2026, 8, 24, tzinfo=UTC),
    )
    decoded = json.loads(serialize_aud03_operational_observation(report))

    assert decoded["schema_version"] == "aud03-operational-observation-readonly.v1"
    assert decoded["candidate"]["commit"] == "a" * 40
    assert decoded["observation"] == {
        "first_observed_at": "2026-08-23T08:00:00.000000Z",
        "last_observed_at": "2026-08-23T08:05:00.000000Z",
        "observation_duration_seconds": 300.0,
        "sample_count": 2,
    }
    assert decoded["operational"]["backlog_max_count"] == 0
    assert decoded["operational"]["recovery_duration_max_seconds"] == 60.0
    assert decoded["operational"]["duplicate_count"] == 0
    assert decoded["operational"]["loss_count"] == 0
    assert decoded["checks"]["missing_section_count"] == 0
    assert decoded["checks"]["archive_integrity_mismatch_count"] == 0
    assert decoded["production_claim"] is False
    assert decoded["production_ready"] is False
    assert decoded["runtime_enablement"] == "not_authorized"


def test_unavailable_sections_remain_unknown_and_not_zero(tmp_path: Path) -> None:
    """An unavailable metric/outbox source is explicit, never silently zeroed."""

    payload = _payload()
    metrics = payload["observations"][0]["metrics"]
    metrics["availability"] = "unavailable"
    metrics["reason_code"] = "metrics_not_collected"
    metrics["values"] = {}
    outbox = payload["observations"][1]["outbox"]
    outbox["availability"] = "unavailable"
    outbox["reason_code"] = "outbox_not_collected"
    for key in (
        "pending_count",
        "due_pending_count",
        "claimed_count",
        "expired_claimed_count",
        "failed_count",
        "delivered_count",
        "oldest_backlog_at",
        "oldest_claimed_at",
    ):
        outbox[key] = None

    decoded = json.loads(
        serialize_aud03_operational_observation(
            parse_aud03_operational_observation(_payload_bytes(payload))
        )
    )
    assert decoded["checks"]["missing_section_count"] == 2
    assert decoded["operational"]["metrics_available_samples"] == 1
    assert decoded["operational"]["outbox_available_samples"] == 1
    assert decoded["operational"]["backlog_max_count"] == 0

    input_path = tmp_path / "observation.json"
    input_path.write_bytes(_payload_bytes(payload))
    result = record_aud03_operational_observation(input_path)
    assert result.missing_section_count == 2


@pytest.mark.parametrize(
    "mutation, message",
    [
        (lambda payload: payload.__setitem__("read_mode", "write"), "read_mode"),
        (
            lambda payload: payload["observations"][1]["candidate"].__setitem__("commit", "d" * 40),
            "candidate drift",
        ),
        (
            lambda payload: payload["observations"][1].__setitem__(
                "observed_at", "2026-08-22T08:05:00.000000Z"
            ),
            "chronological",
        ),
        (
            lambda payload: payload["observations"][0]["migration"].__setitem__(
                "pending_count", -1
            ),
            "non-negative",
        ),
        (
            lambda payload: payload["observations"][0]["recovery"].__setitem__(
                "completed_at", "2026-08-24T00:00:00Z"
            ),
            "after observed_at",
        ),
    ],
)
def test_invalid_observation_contract_fails_closed(mutation, message: str) -> None:
    """Mutation mode, drift, time and invalid counts cannot pass."""

    payload = _payload()
    mutation(payload)
    with pytest.raises(Aud03OperationalObservationError, match=message):
        parse_aud03_operational_observation(
            _payload_bytes(payload),
            as_of=datetime(2026, 8, 24, tzinfo=UTC),
        )


def test_unknown_and_sensitive_fields_fail_closed() -> None:
    """Schema drift and secret/raw-log-shaped fields are rejected."""

    payload = _payload()
    payload["observations"][0]["tui"]["unexpected"] = "x"
    with pytest.raises(Aud03OperationalObservationError, match="keys changed"):
        parse_aud03_operational_observation(_payload_bytes(payload))

    payload = _payload()
    payload["observations"][0]["metrics"]["values"]["api_token"] = 1
    with pytest.raises(Aud03OperationalObservationError, match="forbidden field"):
        parse_aud03_operational_observation(_payload_bytes(payload))


def test_archive_mismatch_and_recovery_counts_are_derived() -> None:
    """Archive and recovery facts are derived from hashes/counters, not labels."""

    payload = _payload()
    payload["observations"][0]["archive"]["restored_sha256"] = "1" * 64
    payload["observations"][0]["recovery"]["duplicate_count"] = 2
    payload["observations"][0]["recovery"]["loss_count"] = 1
    decoded = json.loads(
        serialize_aud03_operational_observation(
            parse_aud03_operational_observation(_payload_bytes(payload))
        )
    )
    assert decoded["checks"]["archive_integrity_mismatch_count"] == 1
    assert decoded["operational"]["duplicate_count"] == 2
    assert decoded["operational"]["loss_count"] == 1


def test_recorder_is_deterministic_append_only_and_dry_run(tmp_path: Path) -> None:
    """The explicit writer is idempotent and the default is read-only."""

    input_path = tmp_path / "observation.json"
    input_path.write_bytes(_payload_bytes())
    assert record_aud03_operational_observation(input_path).written is False
    output_root = tmp_path / "evidence"
    first = record_aud03_operational_observation(input_path, output_root=output_root, write=True)
    second = record_aud03_operational_observation(input_path, output_root=output_root, write=True)
    assert first.written is True
    assert second.written is False
    assert first.path == second.path
    assert first.path is not None
    canonical = serialize_aud03_operational_observation(
        parse_aud03_operational_observation(_payload_bytes())
    )
    assert first.path.read_bytes() == canonical
    assert first.artifact_sha256 == aud03_operational_observation_artifact_sha256(canonical)
    assert first.path.with_suffix(".sha256").read_text(encoding="ascii") == (
        f"{first.artifact_sha256}\n"
    )


def test_recorder_script_runs_directly_from_repository_root() -> None:
    """The server-side recorder is usable without PYTHONPATH setup."""

    result = subprocess.run(
        [sys.executable, "scripts/record_aud03_operational_observation_evidence.py", "--help"],
        cwd=Path(__file__).resolve().parents[3],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "AUD-03 observation envelope JSON" in result.stdout


def test_recorder_modules_have_no_network_or_orm_imports() -> None:
    """The offline collector cannot silently become a production client."""

    for path in (
        Path("apps/audit/application/aud03_operational_observation_evidence.py"),
        Path("scripts/record_aud03_operational_observation_evidence.py"),
    ):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = {
            alias.name.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        assert imported.isdisjoint({"django", "psycopg", "paramiko", "requests", "redis"})
        assert ".objects" not in path.read_text(encoding="utf-8")
