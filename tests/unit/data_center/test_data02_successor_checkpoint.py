"""Contracts for the DATA-02 successor read-only checkpoint recorder."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from apps.data_center.application.data02_successor_checkpoint import (
    Data02SuccessorCheckpointError,
    data02_successor_checkpoint_artifact_sha256,
    parse_data02_successor_checkpoint,
    serialize_data02_successor_checkpoint,
)
from scripts.record_data02_successor_checkpoint import record_data02_successor_checkpoint

CHECKPOINT_PATH = Path(
    "docs/deployment/data02-successor-production-readonly-checkpoint-2026-09-02-aa7127ff.json"
)
AS_OF = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)


def _payload(*, publication_id_prefix: str | None = "test-pub") -> dict[str, object]:
    """Load the checked-in checkpoint and optionally add publication identities."""

    payload = json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8"))
    if publication_id_prefix is None:
        return payload
    publication = payload["publication_rebuild_dry_run"]
    assert isinstance(publication, dict)
    datasets = publication["datasets"]
    assert isinstance(datasets, dict)
    for index, dataset_key in enumerate(sorted(datasets)):
        dataset = datasets[dataset_key]
        assert isinstance(dataset, dict)
        dataset["publication_id"] = f"{publication_id_prefix}-{index}"
        dataset["publication_hash"] = f"{index + 1:064x}"
    return payload


def _bytes(payload: dict[str, object]) -> bytes:
    """Encode one deterministic JSON checkpoint envelope."""

    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def test_checked_in_checkpoint_fails_closed_without_publication_identities() -> None:
    """The current production snapshot cannot be accepted until four IDs are supplied."""

    with pytest.raises(Data02SuccessorCheckpointError, match="publication.datasets.*keys changed"):
        parse_data02_successor_checkpoint(CHECKPOINT_PATH.read_bytes(), as_of=AS_OF)


def test_valid_successor_checkpoint_is_candidate_bound_and_never_ready() -> None:
    """A complete synthetic shape retains all blockers and remains non-enabling."""

    report = parse_data02_successor_checkpoint(_bytes(_payload()), as_of=AS_OF)
    decoded = json.loads(serialize_data02_successor_checkpoint(report))

    assert decoded["schema_version"] == "data02-successor-checkpoint-readonly.v1"
    assert decoded["candidate"]["source_commit"] == "aa7127ff4d9f71555b0d0486314da5518bd2ac20"
    assert decoded["public_probe_window"]["decision_must_not_use_for_decision"] is True
    assert decoded["publication_rebuild_dry_run"]["dataset_count"] == 4
    assert all(
        "publication_id" in dataset and "publication_hash" in dataset
        for dataset in decoded["publication_rebuild_dry_run"]["datasets"].values()
    )
    assert decoded["gate"]["data02_execution_ready"] is False
    assert decoded["gate"]["data02_exit_gate_complete"] is False
    assert decoded["production_claim"] is False
    assert decoded["production_ready"] is False
    assert decoded["runtime_enablement"] == "not_authorized"


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda payload: payload["candidate"].__setitem__("candidate_drift", True), "drift"),
        (lambda payload: payload["fact_repair_dry_run"].__setitem__("exit_code", 1), "exit_code"),
        (
            lambda payload: payload["side_effects"].__setitem__("production_database_write", True),
            "side effects",
        ),
        (
            lambda payload: payload["connection_stability"].__setitem__("client_backend_growth", 1),
            "growth",
        ),
        (
            lambda payload: payload["public_probe_window"].__setitem__(
                "decision_ready_503_count", 2
            ),
            "decision probe",
        ),
    ],
)
def test_inconsistent_successor_checkpoint_fails_closed(mutate, message: str) -> None:
    """Candidate drift, writes, inconsistent samples and failed decision probes cannot pass."""

    payload = _payload()
    mutate(payload)
    with pytest.raises(Data02SuccessorCheckpointError, match=message):
        parse_data02_successor_checkpoint(_bytes(payload), as_of=AS_OF)


def test_publication_identity_collision_fails_closed() -> None:
    """Each core dataset must have a distinct immutable publication identity."""

    payload = _payload()
    datasets = payload["publication_rebuild_dry_run"]["datasets"]
    assert isinstance(datasets, dict)
    first_key, second_key = sorted(datasets)[:2]
    datasets[second_key]["publication_id"] = datasets[first_key]["publication_id"]
    with pytest.raises(Data02SuccessorCheckpointError, match="identities must be unique"):
        parse_data02_successor_checkpoint(_bytes(payload), as_of=AS_OF)


def test_recorder_is_deterministic_append_only_and_dry_run_by_default(tmp_path: Path) -> None:
    """The explicit writer is idempotent and never writes on a dry run."""

    input_path = tmp_path / "checkpoint.json"
    input_path.write_bytes(_bytes(_payload()))
    dry = record_data02_successor_checkpoint(input_path)
    assert dry.written is False
    assert dry.publication_identity_count == 4
    assert not (tmp_path / "data02-successor-checkpoint").exists()

    root = tmp_path / "evidence"
    first = record_data02_successor_checkpoint(input_path, output_root=root, write=True)
    second = record_data02_successor_checkpoint(input_path, output_root=root, write=True)
    assert first.written is True
    assert second.written is False
    assert first.path == second.path
    assert first.path is not None
    assert first.path.with_suffix(".sha256").read_text(encoding="ascii") == (
        f"{first.artifact_sha256}\n"
    )
    assert first.artifact_sha256 == data02_successor_checkpoint_artifact_sha256(
        first.path.read_bytes()
    )


def test_recorder_cli_runs_directly_from_repository_root() -> None:
    """The server-side recorder help is usable without installing a local package."""

    result = subprocess.run(
        [sys.executable, "scripts/record_data02_successor_checkpoint.py", "--help"],
        cwd=Path(__file__).resolve().parents[3],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "checkpoint JSON path" in result.stdout


def test_recorder_modules_have_no_network_or_orm_imports() -> None:
    """The parser and CLI cannot silently become a production client."""

    for path in (
        Path("apps/data_center/application/data02_successor_checkpoint.py"),
        Path("scripts/record_data02_successor_checkpoint.py"),
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
