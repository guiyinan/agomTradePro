"""Contracts for the offline TAR-05 chaos evidence recorder."""

from __future__ import annotations

import ast
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from apps.agent_runtime.application.terminal_runtime_chaos_evidence import (
    TerminalRuntimeChaosCandidate,
    TerminalRuntimeChaosCounters,
    TerminalRuntimeChaosEvidenceReport,
    TerminalRuntimeChaosObservation,
    TerminalRuntimeChaosRecoveryStatus,
    TerminalRuntimeChaosRunStatus,
    TerminalRuntimeChaosState,
    TerminalRuntimeChaosStatus,
    TerminalRuntimeChaosStreamStatus,
    TerminalRuntimeChaosTimelineEvent,
    TerminalRuntimeChaosWorkerStatus,
    canonical_terminal_runtime_test_matrix_digest,
    serialize_terminal_runtime_chaos_evidence,
)
from scripts.record_terminal_runtime_chaos_evidence import (
    record_terminal_runtime_chaos_evidence,
)


def _candidate() -> TerminalRuntimeChaosCandidate:
    return TerminalRuntimeChaosCandidate(
        candidate_commit="a" * 40,
        candidate_release="20260824000100",
        oci_revision="sha256:" + "b" * 64,
        test_matrix_digest=canonical_terminal_runtime_test_matrix_digest(),
    )


def _payload() -> bytes:
    candidate = _candidate()
    started = datetime(2026, 8, 24, 0, 1, tzinfo=UTC)
    observation = TerminalRuntimeChaosObservation(
        scenario_id="worker-crash-recovery",
        fault="worker-crash",
        status=TerminalRuntimeChaosStatus.OBSERVED,
        environment="staging",
        candidate_identity=candidate,
        started_at=started,
        completed_at=started + timedelta(seconds=4),
        state=TerminalRuntimeChaosState(
            worker_status=TerminalRuntimeChaosWorkerStatus.RESTARTED,
            run_status=TerminalRuntimeChaosRunStatus.COMPLETED,
            stream_status=TerminalRuntimeChaosStreamStatus.TERMINAL_REPLAYED,
            recovery_status=TerminalRuntimeChaosRecoveryStatus.RECOVERED,
        ),
        counters=TerminalRuntimeChaosCounters(
            reconnect_attempts=1,
            reconnect_successes=1,
            terminal_overwrites=0,
            duplicate_non_idempotent_side_effects=0,
            cross_user_leaks=0,
        ),
        timeline=(
            TerminalRuntimeChaosTimelineEvent(
                sequence=1,
                occurred_at=started + timedelta(seconds=1),
                event="worker_stopped",
            ),
            TerminalRuntimeChaosTimelineEvent(
                sequence=2,
                occurred_at=started + timedelta(seconds=3),
                event="worker_restarted",
            ),
        ),
    )
    report = TerminalRuntimeChaosEvidenceReport(
        environment="staging",
        candidate_identity=candidate,
        collected_at=started + timedelta(seconds=5),
        observations=(observation,),
    )
    return serialize_terminal_runtime_chaos_evidence(report)


def _candidate_json(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "candidate_commit": "a" * 40,
                "candidate_release": "20260824000100",
                "oci_revision": "sha256:" + "b" * 64,
                "test_matrix_digest": canonical_terminal_runtime_test_matrix_digest(),
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def test_dry_run_is_canonical_and_does_not_write(tmp_path: Path) -> None:
    input_path = tmp_path / "chaos.json"
    input_path.write_bytes(_payload())

    result = record_terminal_runtime_chaos_evidence(input_path)

    assert result.ready_for_chaos_gate is True
    assert result.candidate_binding_verified is False
    assert result.written is False
    assert result.path is None
    assert not (tmp_path / "terminal-agent-chaos").exists()


def test_write_is_append_only_and_idempotent(tmp_path: Path) -> None:
    input_path = tmp_path / "chaos.json"
    input_path.write_bytes(_payload())
    output_root = tmp_path / "evidence"
    expected_path = tmp_path / "expected.json"
    _candidate_json(expected_path)

    first = record_terminal_runtime_chaos_evidence(
        input_path,
        expected_candidate_path=expected_path,
        output_root=output_root,
        write=True,
    )
    second = record_terminal_runtime_chaos_evidence(
        input_path,
        expected_candidate_path=expected_path,
        output_root=output_root,
        write=True,
    )

    assert first.candidate_binding_verified is True
    assert first.written is True
    assert second.written is False
    assert first.path == second.path
    assert first.path is not None
    assert first.path.read_bytes() == _payload()
    assert first.path.with_suffix(".sha256").read_text(encoding="ascii") == (
        f"{first.artifact_sha256}\n"
    )


def test_candidate_mismatch_fails_closed(tmp_path: Path) -> None:
    input_path = tmp_path / "chaos.json"
    input_path.write_bytes(_payload())
    expected_path = tmp_path / "expected.json"
    _candidate_json(expected_path)
    expected_path.write_text(
        expected_path.read_text(encoding="utf-8").replace("a" * 40, "c" * 40),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="evidence candidate does not match expected"):
        record_terminal_runtime_chaos_evidence(
            input_path,
            expected_candidate_path=expected_path,
        )


def test_unknown_runtime_enablement_is_rejected(tmp_path: Path) -> None:
    input_path = tmp_path / "chaos.json"
    payload = json.loads(_payload())
    payload["runtime_enablement"] = "enabled"
    input_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="chaos evidence cannot authorize runtime enablement"):
        record_terminal_runtime_chaos_evidence(input_path)


def test_recorder_has_no_network_or_runtime_side_effect_imports() -> None:
    tree = ast.parse(Path("scripts/record_terminal_runtime_chaos_evidence.py").read_text())
    imported = {
        alias.name.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert imported.isdisjoint({"django", "requests", "redis", "celery", "docker"})
