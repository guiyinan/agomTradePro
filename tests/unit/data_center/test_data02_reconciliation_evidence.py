"""Contracts for the DATA-02 read-only reconciliation evidence recorder."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from apps.data_center.application.data02_reconciliation_evidence import (
    Data02ReconciliationEvidenceError,
    data02_reconciliation_artifact_sha256,
    parse_data02_reconciliation_snapshot,
    serialize_data02_reconciliation_evidence,
)
from scripts.record_data02_reconciliation_evidence import (
    record_data02_reconciliation_evidence,
)


def _payload() -> dict[str, object]:
    """Build a complete externally captured select-only snapshot envelope."""

    return {
        "candidate": {
            "commit": "a" * 40,
            "matrix_sha256": "b" * 64,
            "oci_revision": "sha256:" + "c" * 64,
            "version": "20260824.01",
        },
        "code_defect_keys": [],
        "dataset_key": "equity.price.bar",
        "expected_difference_keys": ["000002.SZ|2026-08-01"],
        "legacy": {
            "observed_at": "2026-08-23T08:00:00.000000Z",
            "records": {
                "000001.SZ|2026-08-01": {"close": 10.0},
                "000002.SZ|2026-08-01": {"close": 9.9},
            },
            "source": "legacy-read-model",
        },
        "canonical": {
            "observed_at": "2026-08-23T08:00:01.000000Z",
            "records": {
                "000001.SZ|2026-08-01": {"close": 10.0},
                "000002.SZ|2026-08-01": {"close": 10.0},
            },
            "source": "canonical-read-model",
        },
        "read_mode": "select_only",
    }


def _payload_bytes(payload: dict[str, object] | None = None) -> bytes:
    """Encode a snapshot envelope with stable JSON bytes."""

    return json.dumps(payload or _payload(), separators=(",", ":"), sort_keys=True).encode("utf-8")


def test_valid_snapshot_pair_preserves_candidate_times_and_classifications() -> None:
    """A valid pair is machine-readable but never a production gate."""

    report = parse_data02_reconciliation_snapshot(
        _payload_bytes(),
        as_of=datetime(2026, 8, 24, tzinfo=UTC),
    )
    decoded = json.loads(serialize_data02_reconciliation_evidence(report))

    assert report.export.report.counts == {
        "same": 1,
        "expected_difference": 1,
        "data_missing": 0,
        "semantic_conflict": 0,
        "code_defect": 0,
    }
    assert decoded["candidate"]["commit"] == "a" * 40
    assert decoded["legacy"]["observed_at"] == "2026-08-23T08:00:00.000000Z"
    assert decoded["canonical"]["observed_at"] == "2026-08-23T08:00:01.000000Z"
    assert decoded["read_mode"] == "select_only"
    assert decoded["schema_version"] == "data02-reconciliation-readonly.v1"
    assert decoded["production_claim"] is False
    assert decoded["production_ready"] is False
    assert decoded["runtime_enablement"] == "not_authorized"


def test_serializer_and_recorder_are_deterministic_and_append_only(tmp_path: Path) -> None:
    """The explicit writer is idempotent and cannot overwrite an artifact."""

    input_path = tmp_path / "snapshot.json"
    input_path.write_bytes(_payload_bytes())
    output_root = tmp_path / "evidence"

    first = record_data02_reconciliation_evidence(input_path, output_root=output_root, write=True)
    second = record_data02_reconciliation_evidence(input_path, output_root=output_root, write=True)

    assert first.reconciliation_clean is True
    assert first.written is True
    assert second.written is False
    assert first.path == second.path
    assert first.path is not None
    expected = serialize_data02_reconciliation_evidence(
        parse_data02_reconciliation_snapshot(_payload_bytes())
    )
    assert first.path.read_bytes() == expected
    assert first.artifact_sha256 == data02_reconciliation_artifact_sha256(expected)
    assert first.path.with_suffix(".sha256").read_text(encoding="ascii") == (
        f"{first.artifact_sha256}\n"
    )


@pytest.mark.parametrize(
    "mutation, message",
    [
        (lambda payload: payload.__setitem__("read_mode", "write"), "read_mode"),
        (
            lambda payload: payload["candidate"].__setitem__("commit", "not-a-sha"),
            "candidate.commit",
        ),
        (
            lambda payload: payload["legacy"].__setitem__("observed_at", "2026-08-25T00:00:00Z"),
            "future",
        ),
        (
            lambda payload: payload["canonical"].__setitem__("source", "legacy-read-model"),
            "sources must differ",
        ),
    ],
)
def test_invalid_snapshot_contract_fails_closed(mutation, message: str) -> None:
    """Write mode, future times, identity drift, and source reuse cannot pass."""

    payload = _payload()
    mutation(payload)
    with pytest.raises(Data02ReconciliationEvidenceError, match=message):
        parse_data02_reconciliation_snapshot(
            _payload_bytes(payload),
            as_of=datetime(2026, 8, 24, tzinfo=UTC),
        )


def test_nonfinite_record_value_and_unknown_classification_key_fail_closed() -> None:
    """Evidence never stringifies invalid values or silently drops labels."""

    payload = _payload()
    payload["legacy"]["records"]["000001.SZ|2026-08-01"]["close"] = float("nan")
    with pytest.raises(Data02ReconciliationEvidenceError, match="finite JSON"):
        parse_data02_reconciliation_snapshot(_payload_bytes(payload))

    payload = _payload()
    payload["expected_difference_keys"] = ["999999.SZ|2026-08-01"]
    with pytest.raises(Data02ReconciliationEvidenceError, match="not present"):
        parse_data02_reconciliation_snapshot(_payload_bytes(payload))


def test_recorder_cli_defaults_to_dry_run_and_supports_explicit_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The server-side CLI never writes unless --write is explicitly supplied."""

    input_path = tmp_path / "snapshot.json"
    input_path.write_bytes(_payload_bytes())
    monkeypatch.setattr(
        "sys.argv",
        ["record_data02_reconciliation_evidence.py", "--input", str(input_path)],
    )
    from scripts.record_data02_reconciliation_evidence import main as record_main

    assert record_main() == 0
    assert not (tmp_path / "data02-reconciliation").exists()

    output_root = tmp_path / "evidence"
    monkeypatch.setattr(
        "sys.argv",
        [
            "record_data02_reconciliation_evidence.py",
            "--input",
            str(input_path),
            "--output-root",
            str(output_root),
            "--write",
        ],
    )
    assert record_main() == 0
    assert list((output_root / "data02-reconciliation").rglob("*.json"))


def test_recorder_script_runs_directly_from_repository_root() -> None:
    """The server-side recorder is usable without a PYTHONPATH adjustment."""

    result = subprocess.run(
        [sys.executable, "scripts/record_data02_reconciliation_evidence.py", "--help"],
        cwd=Path(__file__).resolve().parents[3],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "snapshot envelope JSON path" in result.stdout


def test_recorder_modules_have_no_network_or_orm_imports() -> None:
    """The offline collector cannot silently become a production client."""

    for path in (
        Path("apps/data_center/application/data02_reconciliation_evidence.py"),
        Path("scripts/record_data02_reconciliation_evidence.py"),
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
