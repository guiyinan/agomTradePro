"""Contracts for the DATA-01 isolated restore evidence recorder."""

from __future__ import annotations

import ast
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from apps.data_center.application.data01_restore_evidence import (
    Data01RestoreEvidenceError,
    data01_restore_artifact_sha256,
    parse_data01_restore_snapshot,
    serialize_data01_restore_evidence,
)
from scripts.record_data01_restore_evidence import record_data01_restore_evidence

EVIDENCE_PATH = Path("docs/deployment/data01-latest-backup-restore-2026-08-23.json")


def _payload() -> bytes:
    """Read the real isolated restore artifact committed to the repository."""

    return EVIDENCE_PATH.read_bytes()


def test_committed_restore_snapshot_is_exact_and_non_production() -> None:
    report = parse_data01_restore_snapshot(
        _payload(),
        as_of=datetime(2026, 8, 24, tzinfo=UTC),
    )

    assert report.isolated_restore_verified is True
    assert report.dump_sha256 == "f028ec2fe986be3c0f56f529e3fc44332ece472000c6e43f917d42b9ac2ffc55"
    assert report.dump_size_bytes == 142_825_371
    assert len(report.source_snapshot.tables) == 539
    assert len(report.source_snapshot.sequences) == 460
    assert len(report.source_snapshot.data_center_migrations) == 72
    encoded = serialize_data01_restore_evidence(report)
    decoded = json.loads(encoded)
    assert decoded["production_claim"] is False
    assert decoded["production_ready"] is False
    assert decoded["runtime_enablement"] == "not_authorized"
    assert decoded["comparison"]["snapshots_equal"] is True


def test_serializer_and_recorder_are_deterministic_and_idempotent(tmp_path: Path) -> None:
    input_path = tmp_path / "restore.json"
    input_path.write_bytes(_payload())
    output_root = tmp_path / "evidence"

    first = record_data01_restore_evidence(input_path, output_root=output_root, write=True)
    second = record_data01_restore_evidence(input_path, output_root=output_root, write=True)

    assert first.isolated_restore_verified is True
    assert first.written is True
    assert second.written is False
    assert first.path == second.path
    assert first.path is not None
    expected_payload = serialize_data01_restore_evidence(parse_data01_restore_snapshot(_payload()))
    assert first.path.read_bytes() == expected_payload
    assert first.path.with_suffix(".sha256").read_text(encoding="ascii") == (
        f"{first.artifact_sha256}\n"
    )
    report = parse_data01_restore_snapshot(_payload())
    assert first.artifact_sha256 == data01_restore_artifact_sha256(
        serialize_data01_restore_evidence(report)
    )


def test_dump_hash_drift_fails_closed() -> None:
    payload = json.loads(_payload())
    payload["dump_sha256_after"] = "a" * 64

    with pytest.raises(Data01RestoreEvidenceError, match="dump SHA-256 changed"):
        parse_data01_restore_snapshot(json.dumps(payload).encode("utf-8"))


def test_table_drift_fails_closed() -> None:
    payload = json.loads(_payload())
    table = payload["restored_snapshot"]["tables"]["account_profile"]
    table["rows"] += 1

    with pytest.raises(Data01RestoreEvidenceError, match="source and restored snapshots differ"):
        parse_data01_restore_snapshot(json.dumps(payload).encode("utf-8"))


def test_future_snapshot_fails_closed() -> None:
    payload = json.loads(_payload())
    payload["finished_at"] = "2026-08-25T00:00:00+00:00"

    with pytest.raises(Data01RestoreEvidenceError, match="from the future"):
        parse_data01_restore_snapshot(
            json.dumps(payload).encode("utf-8"),
            as_of=datetime(2026, 8, 24, tzinfo=UTC),
        )


def test_unknown_top_level_key_fails_closed() -> None:
    payload = json.loads(_payload())
    payload["production_ready"] = True

    with pytest.raises(Data01RestoreEvidenceError, match="keys changed"):
        parse_data01_restore_snapshot(json.dumps(payload).encode("utf-8"))


def test_application_and_recorder_have_no_network_or_orm_imports() -> None:
    for path in (
        Path("apps/data_center/application/data01_restore_evidence.py"),
        Path("scripts/record_data01_restore_evidence.py"),
    ):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = {
            alias.name.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        assert imported.isdisjoint({"django", "psycopg", "paramiko", "requests", "redis"})
        source = path.read_text(encoding="utf-8")
        assert ".objects" not in source
