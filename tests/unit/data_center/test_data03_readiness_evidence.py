"""Contracts for the DATA-03 read-only readiness evidence recorder."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from apps.data_center.application.data03_readiness_evidence import (
    Data03ReadinessEvidenceError,
    data03_readiness_artifact_sha256,
    parse_data03_readiness_snapshot,
    serialize_data03_readiness_evidence,
)
from scripts.record_data03_readiness_evidence import record_data03_readiness_evidence


def _candidate() -> dict[str, str]:
    """Return a complete immutable candidate identity."""

    return {
        "commit": "a" * 40,
        "matrix_sha256": "b" * 64,
        "oci_revision": "sha256:" + "c" * 64,
        "version": "20260824.01",
    }


def _observation(captured_at: str, *, candidate: dict[str, str] | None = None) -> dict[str, object]:
    """Build one service/decision probe with canonical smoke inputs."""

    return {
        "captured_at": captured_at,
        "candidate": candidate or _candidate(),
        "service": {
            "checks": {
                "database": {"status": "ok"},
                "redis": {"status": "skipped"},
            },
            "endpoint": "/api/ready/",
            "http_status": 200,
            "status": "ok",
            "timestamp": captured_at,
        },
        "decision": {
            "checks": {
                "core_coverage": {
                    "block_reason_code": "core_data_coverage_incomplete",
                    "must_not_use_for_decision": True,
                    "status": "incomplete",
                },
                "runtime_state": {"status": "blocked"},
            },
            "endpoint": "/api/decision-ready/",
            "http_status": 503,
            "must_not_use_for_decision": True,
            "status": "blocked",
            "timestamp": captured_at,
        },
        "smoke_checks": [
            {
                "detail": {"rows": 0},
                "key": "canonical.data-center",
                "observed_at": captured_at,
                "status": "blocked",
            },
            {
                "detail": {"route": "/api/health/"},
                "key": "service.health",
                "observed_at": captured_at,
                "status": "ok",
            },
        ],
    }


def _payload() -> dict[str, object]:
    """Build a complete externally captured DATA-03 envelope."""

    return {
        "candidate": _candidate(),
        "observations": [
            _observation("2026-08-23T08:00:00.000000Z"),
            _observation("2026-08-23T08:05:00.000000Z"),
        ],
        "read_mode": "http_get_read_only",
    }


def _payload_bytes(payload: dict[str, object] | None = None) -> bytes:
    """Encode an envelope with stable JSON bytes."""

    return json.dumps(payload or _payload(), separators=(",", ":"), sort_keys=True).encode("utf-8")


def test_valid_snapshot_derives_observation_and_fail_closed_flags() -> None:
    """Readiness facts are derived from raw probes but never unlock a gate."""

    report = parse_data03_readiness_snapshot(
        _payload_bytes(),
        as_of=datetime(2026, 8, 24, tzinfo=UTC),
    )
    decoded = json.loads(serialize_data03_readiness_evidence(report))

    assert decoded["candidate"]["commit"] == "a" * 40
    assert decoded["observation"]["sample_count"] == 2
    assert decoded["observation"]["observation_duration_seconds"] == 300.0
    assert decoded["observation"]["max_source_age_seconds"] == 0.0
    assert decoded["checks"] == {
        "check_defect_count": 4,
        "decision_blocker_count": 2,
        "service_failure_count": 0,
        "smoke_failure_count": 2,
    }
    assert decoded["samples"][0]["decision"]["timestamp"] == "2026-08-23T08:00:00.000000Z"
    assert decoded["samples"][0]["smoke_checks"][0]["observed_at"].endswith("Z")
    assert decoded["schema_version"] == "data03-readiness-readonly.v1"
    assert decoded["production_claim"] is False
    assert decoded["production_ready"] is False
    assert decoded["runtime_enablement"] == "not_authorized"


def test_serializer_and_recorder_are_deterministic_and_append_only(tmp_path: Path) -> None:
    """Explicit writing is idempotent and content-addressed."""

    input_path = tmp_path / "readiness.json"
    input_path.write_bytes(_payload_bytes())
    output_root = tmp_path / "evidence"

    first = record_data03_readiness_evidence(input_path, output_root=output_root, write=True)
    second = record_data03_readiness_evidence(input_path, output_root=output_root, write=True)

    assert first.written is True
    assert second.written is False
    assert first.path == second.path
    assert first.path is not None
    expected = serialize_data03_readiness_evidence(
        parse_data03_readiness_snapshot(_payload_bytes())
    )
    assert first.path.read_bytes() == expected
    assert first.artifact_sha256 == data03_readiness_artifact_sha256(expected)
    assert first.path.with_suffix(".sha256").read_text(encoding="ascii") == (
        f"{first.artifact_sha256}\n"
    )
    assert first.decision_blocker_count == 2
    assert first.service_failure_count == 0
    assert first.smoke_failure_count == 2


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
                "captured_at", "2026-08-22T08:05:00.000000Z"
            ),
            "chronological",
        ),
        (
            lambda payload: payload["observations"][0]["decision"].__setitem__("http_status", 200),
            "disagree",
        ),
        (
            lambda payload: payload["observations"][0]["service"].__setitem__(
                "timestamp", "2026-08-25T00:00:00Z"
            ),
            "future",
        ),
    ],
)
def test_invalid_readiness_contract_fails_closed(mutation, message: str) -> None:
    """Mutation mode, candidate drift, time drift and status spoofing cannot pass."""

    payload = _payload()
    mutation(payload)
    with pytest.raises(Data03ReadinessEvidenceError, match=message):
        parse_data03_readiness_snapshot(
            _payload_bytes(payload),
            as_of=datetime(2026, 8, 24, tzinfo=UTC),
        )


def test_unknown_keys_nonfinite_values_and_unsorted_smoke_fail_closed() -> None:
    """The parser does not silently accept schema drift or invalid JSON."""

    payload = _payload()
    payload["observations"][0]["service"]["unexpected"] = True
    with pytest.raises(Data03ReadinessEvidenceError, match="keys changed"):
        parse_data03_readiness_snapshot(_payload_bytes(payload))

    payload = _payload()
    payload["observations"][0]["decision"]["checks"]["x"] = float("nan")
    with pytest.raises(Data03ReadinessEvidenceError, match="finite JSON"):
        parse_data03_readiness_snapshot(_payload_bytes(payload))

    payload = _payload()
    payload["observations"][0]["smoke_checks"].reverse()
    with pytest.raises(Data03ReadinessEvidenceError, match="sorted"):
        parse_data03_readiness_snapshot(_payload_bytes(payload))


def test_recorder_cli_defaults_to_dry_run_and_supports_explicit_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The server-side recorder never writes unless --write is explicit."""

    input_path = tmp_path / "readiness.json"
    input_path.write_bytes(_payload_bytes())
    monkeypatch.setattr(
        "sys.argv",
        ["record_data03_readiness_evidence.py", "--input", str(input_path)],
    )
    from scripts.record_data03_readiness_evidence import main as record_main

    assert record_main() == 0
    assert not (tmp_path / "data03-readiness").exists()

    output_root = tmp_path / "evidence"
    monkeypatch.setattr(
        "sys.argv",
        [
            "record_data03_readiness_evidence.py",
            "--input",
            str(input_path),
            "--output-root",
            str(output_root),
            "--write",
        ],
    )
    assert record_main() == 0
    assert list((output_root / "data03-readiness").rglob("*.json"))


def test_recorder_script_runs_directly_from_repository_root() -> None:
    """The server-side CLI is usable without a PYTHONPATH adjustment."""

    result = subprocess.run(
        [sys.executable, "scripts/record_data03_readiness_evidence.py", "--help"],
        cwd=Path(__file__).resolve().parents[3],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "readiness envelope JSON path" in result.stdout


def test_recorder_modules_have_no_network_or_orm_imports() -> None:
    """The offline collector cannot silently become a production client."""

    for path in (
        Path("apps/data_center/application/data03_readiness_evidence.py"),
        Path("scripts/record_data03_readiness_evidence.py"),
    ):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = {
            alias.name.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        assert imported.isdisjoint({"django", "psycopg", "paramiko", "requests", "redis"})
        assert ".objects" not in path.read_text(encoding="utf-8")
