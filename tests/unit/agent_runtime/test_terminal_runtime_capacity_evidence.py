"""Tests for the candidate-bound TAR-01 capacity evidence guard."""

from __future__ import annotations

import ast
import copy
import json
from pathlib import Path
from typing import cast

import pytest

from apps.agent_runtime.application.terminal_runtime_capacity_evidence import (
    TerminalRuntimeCapacityEvidenceBinding,
    TerminalRuntimeCapacityEvidenceError,
    validate_terminal_runtime_capacity_evidence,
)
from scripts.validate_terminal_runtime_capacity_evidence import main as validate_main

EVIDENCE_PATH = Path("docs/deployment/tar01-current-production-capacity-2026-08-22-71e62773.json")
CONTRACT_PATH = Path("governance/terminal_agent_runtime_contracts.json")


def _payload() -> dict[str, object]:
    """Load a fresh copy of the current candidate-bound observation."""

    return cast(dict[str, object], json.loads(EVIDENCE_PATH.read_text(encoding="utf-8")))


def _expected_candidate() -> TerminalRuntimeCapacityEvidenceBinding:
    """Load the candidate identity that the governance contract expects."""

    contract = cast(dict[str, object], json.loads(CONTRACT_PATH.read_text(encoding="utf-8")))
    observation = cast(dict[str, object], contract["runtime_observation"])
    return TerminalRuntimeCapacityEvidenceBinding(
        candidate_commit=cast(str, observation["candidate_commit"]),
        release=cast(str, observation["release"]),
        image=cast(str, observation["image"]),
    )


def _mapping(value: object) -> dict[str, object]:
    """Narrow a test payload object to a mutable JSON object."""

    return cast(dict[str, object], value)


def test_current_candidate_capacity_observation_is_valid() -> None:
    """The current artifact validates but remains explicitly capacity-blocked."""

    report = validate_terminal_runtime_capacity_evidence(
        _payload(),
        expected_candidate=_expected_candidate(),
    )

    assert report.candidate_commit == "71e62773ebc3032996f5f14801ac6a2a3ad28b65"
    assert report.candidate_release == "20260822012308"
    assert report.image_id.startswith("sha256:")
    assert report.accepted_runs == 4
    assert report.rejected_runs == 32
    assert report.level_count == 4
    assert report.idempotency_verified is True
    assert report.worker_recovery_verified is True
    assert report.sse_verified is True
    assert report.cleanup_verified is True
    assert report.decision == "BLOCKED"
    assert report.safety_ready is True
    assert report.capacity_ready is False


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("candidate", "source_commit"), "0" * 40),
        (("capacity", "accepted_runs"), 5),
        (("capacity", "levels", "5", "429"), 3),
        (("capacity", "queue_final", "global_queued"), 1),
        (("idempotency", "second_durable_row"), True),
        (("cleanup", "runtime_flags_after_observation", "TERMINAL_RUNTIME_AUTHORIZED"), True),
        (("worker_recovery", "chaos_runs_error_code"), "provider_success"),
        (("tar01_gate", "capacity_ready"), True),
    ],
)
def test_substituted_capacity_facts_fail_closed(
    path: tuple[str, ...],
    value: object,
) -> None:
    """Candidate, count, queue, idempotency, cleanup, provider, and gate substitutions fail."""

    payload = copy.deepcopy(_payload())
    cursor: dict[str, object] = payload
    for key in path[:-1]:
        cursor = _mapping(cursor[key])
    cursor[path[-1]] = value

    with pytest.raises(TerminalRuntimeCapacityEvidenceError):
        validate_terminal_runtime_capacity_evidence(
            payload,
            expected_candidate=_expected_candidate(),
        )


def test_contract_image_binding_accepts_legacy_worker_tag() -> None:
    """The binding supports the prior manifest image-tag representation safely."""

    binding = _expected_candidate()
    legacy_binding = TerminalRuntimeCapacityEvidenceBinding(
        candidate_commit=binding.candidate_commit,
        release=binding.release,
        image="agomtradepro-web:20260822012308",
    )
    report = validate_terminal_runtime_capacity_evidence(
        _payload(),
        expected_candidate=legacy_binding,
    )
    assert report.capacity_ready is False


def test_script_is_read_only_and_reports_stable_summary(monkeypatch, capsys) -> None:
    """The CLI validates a file and never enables the queued runtime."""

    monkeypatch.setattr(
        "sys.argv",
        [
            "validate_terminal_runtime_capacity_evidence.py",
            str(EVIDENCE_PATH),
            "--contract",
            str(CONTRACT_PATH),
        ],
    )

    assert validate_main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["accepted_runs"] == 4
    assert output["rejected_runs"] == 32
    assert output["decision"] == "BLOCKED"
    assert output["safety_ready"] is True
    assert output["capacity_ready"] is False


def test_guard_has_no_network_or_runtime_imports() -> None:
    """The evidence guard is an offline application contract."""

    source = Path("apps/agent_runtime/application/terminal_runtime_capacity_evidence.py").read_text(
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
        for forbidden in ("django", "requests", "celery", "socket", "subprocess")
    )
    assert ".objects" not in source
