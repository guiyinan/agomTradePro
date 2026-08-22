"""Tests for the TAR-01 safety preflight."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.check_tar01_exit_gate import evaluate_tar01_exit_gate

ROOT = Path(__file__).resolve().parents[2]


def test_tar01_preflight_completes_contract_without_runtime_capacity() -> None:
    """Contract completion does not misrepresent downstream capacity readiness."""

    report = evaluate_tar01_exit_gate(
        registry_path=ROOT / "governance/active_plan_registry.json",
        contract_path=ROOT / "governance/terminal_agent_runtime_contracts.json",
    )

    assert report.decision == "CONTRACT_COMPLETE"
    assert report.safety_ready is True
    assert report.capacity_ready is False
    assert report.reasons == ()


def test_tar01_preflight_rejects_queued_flag_drift(tmp_path: Path) -> None:
    """A malformed runtime observation is an invalid safety state."""

    contract_path = ROOT / "governance/terminal_agent_runtime_contracts.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract["runtime_observation"]["queued_worker_enabled"] = False
    altered = tmp_path / "contract.json"
    altered.write_text(json.dumps(contract), encoding="utf-8")

    report = evaluate_tar01_exit_gate(
        registry_path=ROOT / "governance/active_plan_registry.json",
        contract_path=altered,
    )

    assert report.decision == "INVALID"
    assert report.safety_ready is False
    assert "runtime_observation_bounded" in report.reasons


def test_tar01_preflight_rejects_dependency_status_drift(tmp_path: Path) -> None:
    """The scheduling preflight rejects a regression to the old dependency state."""

    registry_path = ROOT / "governance/active_plan_registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    for unit in registry["closure_backlog"]["units"]:
        if unit["id"] == "TAR-01":
            unit["status"] = "active"
    altered = tmp_path / "registry.json"
    altered.write_text(json.dumps(registry), encoding="utf-8")

    report = evaluate_tar01_exit_gate(
        registry_path=altered,
        contract_path=ROOT / "governance/terminal_agent_runtime_contracts.json",
    )

    assert report.decision == "INVALID"
    assert "tar_dependency_status" in report.reasons


def test_tar01_preflight_rejects_capacity_evidence_mutation(tmp_path: Path) -> None:
    """A candidate-bound artifact mutation invalidates the safety preflight."""

    evidence_path = (
        ROOT / "docs/deployment/tar01-current-production-capacity-2026-08-22-71e62773.json"
    )
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence["cleanup"]["runtime_flags_after_observation"]["TERMINAL_RUNTIME_AUTHORIZED"] = True
    altered = tmp_path / "capacity.json"
    altered.write_text(json.dumps(evidence), encoding="utf-8")

    report = evaluate_tar01_exit_gate(
        registry_path=ROOT / "governance/active_plan_registry.json",
        contract_path=ROOT / "governance/terminal_agent_runtime_contracts.json",
        capacity_evidence_path=altered,
    )

    assert report.decision == "INVALID"
    assert report.safety_ready is False
    assert "capacity_evidence_integrity" in report.reasons
