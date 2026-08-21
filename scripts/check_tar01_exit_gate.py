#!/usr/bin/env python
"""Check TAR-01's local safety gate and bounded runtime observation state."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from types import ModuleType
from typing import cast

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = REPO_ROOT / "governance" / "active_plan_registry.json"
DEFAULT_CONTRACT = REPO_ROOT / "governance" / "terminal_agent_runtime_contracts.json"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Keep direct script execution offline: the application package has a legacy
# eager Django-backed ``__init__`` while the evidence validator is pure.
if __package__ in (None, "") and "apps.agent_runtime.application" not in sys.modules:
    application_package = ModuleType("apps.agent_runtime.application")
    application_package.__path__ = [str(REPO_ROOT / "apps" / "agent_runtime" / "application")]
    sys.modules["apps.agent_runtime.application"] = application_package


@dataclass(frozen=True)
class GateCheck:
    """One machine-readable TAR-01 preflight check."""

    key: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class Tar01ExitGateReport:
    """The safe local decision for the TAR-01 execution boundary."""

    decision: str
    safety_ready: bool
    capacity_ready: bool
    checks: tuple[GateCheck, ...]
    reasons: tuple[str, ...]


def _read_json(path: Path) -> Mapping[str, object] | None:
    """Read a JSON object, returning ``None`` for malformed or missing input."""

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return cast(Mapping[str, object], value) if isinstance(value, Mapping) else None


def _mapping(value: object) -> Mapping[str, object] | None:
    """Narrow an arbitrary JSON value to an object."""

    return cast(Mapping[str, object], value) if isinstance(value, Mapping) else None


def _string_list(value: object) -> tuple[str, ...]:
    """Return a tuple only when every list member is a string."""

    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return (
        tuple(item for item in value if isinstance(item, str))
        if all(isinstance(item, str) for item in value)
        else ()
    )


def _check_registry(registry: Mapping[str, object]) -> tuple[GateCheck, ...]:
    """Check focus and dependency statuses in the active plan registry."""

    focus = _mapping(registry.get("execution_focus"))
    focus_ok = bool(
        focus
        and focus.get("unit_id") == "TAR-01"
        and set(_string_list(focus.get("allowed_parallel_execution_modes")))
        == {"production", "external", "governance"}
    )
    checks = [
        GateCheck(
            "registry_execution_focus",
            focus_ok,
            (
                "TAR-01 is the focused unit with read-only evidence modes"
                if focus_ok
                else "execution focus must remain TAR-01 with production/external/governance modes"
            ),
        )
    ]
    backlog = _mapping(registry.get("closure_backlog"))
    raw_units = backlog.get("units") if backlog else None
    units: dict[str, Mapping[str, object]] = {}
    if isinstance(raw_units, Sequence) and not isinstance(raw_units, (str, bytes)):
        for item in raw_units:
            unit = _mapping(item)
            unit_id = unit.get("id") if unit else None
            if unit is not None and isinstance(unit_id, str):
                units[unit_id] = unit
    expected = {"TAR-01": "active", "TAR-02": "waiting_dependency", "TAR-03": "waiting_dependency"}
    dependency_ok = all(
        units.get(unit_id, {}).get("status") == status for unit_id, status in expected.items()
    )
    checks.append(
        GateCheck(
            "tar_dependency_status",
            dependency_ok,
            (
                "TAR-01 active; TAR-02/TAR-03 waiting_dependency"
                if dependency_ok
                else "TAR-01/TAR-02/TAR-03 status does not preserve the execution dependency"
            ),
        )
    )
    return tuple(checks)


def _check_capacity_evidence(
    contract: Mapping[str, object],
    *,
    evidence_path: Path | None = None,
) -> GateCheck:
    """Validate the artifact named by the bounded runtime observation."""

    from apps.agent_runtime.application.terminal_runtime_capacity_evidence import (
        TerminalRuntimeCapacityEvidenceBinding,
        TerminalRuntimeCapacityEvidenceError,
        validate_terminal_runtime_capacity_evidence,
    )

    observation = _mapping(contract.get("runtime_observation"))
    if observation is None:
        return GateCheck(
            "capacity_evidence_integrity",
            False,
            "runtime_observation must be an object before evidence can be bound",
        )
    evidence_reference = observation.get("evidence")
    if type(evidence_reference) is not str or not evidence_reference:
        return GateCheck(
            "capacity_evidence_integrity",
            False,
            "runtime_observation.evidence must be a repository-relative path",
        )
    reference_path = Path(evidence_reference)
    if reference_path.is_absolute() or ".." in reference_path.parts:
        return GateCheck(
            "capacity_evidence_integrity",
            False,
            "runtime_observation.evidence must stay inside the repository",
        )
    identity = {
        "candidate_commit": observation.get("candidate_commit"),
        "release": observation.get("release"),
        "image": observation.get("image"),
    }
    if any(type(value) is not str for value in identity.values()):
        return GateCheck(
            "capacity_evidence_integrity",
            False,
            "runtime observation candidate identity is incomplete",
        )
    artifact_path = (
        evidence_path.resolve() if evidence_path is not None else REPO_ROOT / reference_path
    )
    payload = _read_json(artifact_path)
    if payload is None:
        return GateCheck(
            "capacity_evidence_integrity",
            False,
            f"capacity evidence is unreadable: {artifact_path}",
        )
    try:
        report = validate_terminal_runtime_capacity_evidence(
            payload,
            expected_candidate=TerminalRuntimeCapacityEvidenceBinding(
                candidate_commit=cast(str, identity["candidate_commit"]),
                release=cast(str, identity["release"]),
                image=cast(str, identity["image"]),
            ),
        )
    except TerminalRuntimeCapacityEvidenceError as exc:
        return GateCheck("capacity_evidence_integrity", False, str(exc))
    return GateCheck(
        "capacity_evidence_integrity",
        True,
        (
            "candidate-bound capacity evidence is internally consistent; "
            f"accepted={report.accepted_runs}, rejected={report.rejected_runs}, "
            "TAR-01 remains capacity-blocked"
        ),
    )


def _check_contract(
    contract: Mapping[str, object],
    *,
    capacity_evidence_path: Path | None = None,
) -> tuple[GateCheck, ...]:
    """Check that any runtime observation remains explicitly bounded."""

    checks: list[GateCheck] = []
    checks.append(
        GateCheck(
            "contract_decision_scope",
            contract.get("decision_status") == "runtime_observed_not_exit_ready",
            (
                "runtime observation is recorded without exit readiness"
                if contract.get("decision_status") == "runtime_observed_not_exit_ready"
                else "decision_status must remain runtime_observed_not_exit_ready"
            ),
        )
    )
    observation = _mapping(contract.get("runtime_observation"))
    observation_ok = bool(
        observation
        and observation.get("status") == "short_window_observed"
        and isinstance(observation.get("candidate_commit"), str)
        and len(cast(str, observation.get("candidate_commit"))) == 40
        and observation.get("queued_intake_enabled") is True
        and observation.get("queued_worker_enabled") is True
        and observation.get("capacity_ready") is False
        and observation.get("provider_execution") == "failed_not_claimed"
    )
    checks.append(
        GateCheck(
            "runtime_observation_bounded",
            observation_ok,
            (
                "queued/worker observation is candidate-bound and capacity remains incomplete"
                if observation_ok
                else "runtime observation must be candidate-bound, bounded, and not exit-ready"
            ),
        )
    )
    checks.append(_check_capacity_evidence(contract, evidence_path=capacity_evidence_path))
    baseline = _mapping(contract.get("baseline_evidence"))
    required_levels = baseline.get("required_concurrency_levels") if baseline else None
    baseline_shape_ok = bool(
        baseline
        and required_levels == [1, 5, 10, 20]
        and baseline.get("samples_must_share_exact_candidate_identity") is True
        and baseline.get("capacity_ready_requires_complete_observed_metrics") is True
        and baseline.get("capacity_ready_requires_all_hard_slos") is True
    )
    checks.append(
        GateCheck(
            "baseline_candidate_contract",
            baseline_shape_ok,
            (
                "1/5/10/20 and exact candidate/SLO binding are required"
                if baseline_shape_ok
                else "baseline candidate identity or capacity requirements drifted"
            ),
        )
    )
    closed = bool(
        baseline
        and baseline.get("runtime_enablement") == "not_authorized"
        and baseline.get("production_evidence_status") == "not_runtime"
        and observation is not None
        and observation.get("capacity_ready") is False
    )
    checks.append(
        GateCheck(
            "capacity_gate_not_exit_ready",
            closed,
            (
                "offline baseline remains separate; observed runtime is not exit-ready"
                if closed
                else "offline baseline or bounded runtime observation is inconsistent"
            ),
        )
    )
    matrix = _mapping(contract.get("test_matrix"))
    raw_scenarios = matrix.get("scenarios") if matrix else None
    scenarios: dict[str, Mapping[str, object]] = {}
    if isinstance(raw_scenarios, Sequence) and not isinstance(raw_scenarios, (str, bytes)):
        for item in raw_scenarios:
            scenario = _mapping(item)
            scenario_id = scenario.get("scenario_id") if scenario else None
            if scenario is not None and isinstance(scenario_id, str):
                scenarios[scenario_id] = scenario
    expected_statuses = {
        "repository-postgres-first-winner": "implemented",
        "celery-delivery-outcomes": "implemented",
        "api-wire-and-request-bounds": "implemented",
        "events-reconnect-and-owner-scope": "implemented",
        "load-1-5-10-20": "planned",
        "chaos-worker-stream-recovery": "planned",
    }
    planned_ok = bool(scenarios) and all(
        scenarios.get(scenario_id, {}).get("implementation_status") == status
        for scenario_id, status in expected_statuses.items()
    )
    checks.append(
        GateCheck(
            "runtime_scenarios_bounded",
            planned_ok,
            (
                "repository/Celery/API/events are observed; load/chaos remain planned"
                if planned_ok
                else "runtime scenario status does not match observed versus pending evidence"
            ),
        )
    )
    return tuple(checks)


def evaluate_tar01_exit_gate(
    *,
    registry_path: Path = DEFAULT_REGISTRY,
    contract_path: Path = DEFAULT_CONTRACT,
    capacity_evidence_path: Path | None = None,
) -> Tar01ExitGateReport:
    """Evaluate TAR-01 without turning a short observation into an exit decision."""

    registry = _read_json(registry_path)
    contract = _read_json(contract_path)
    if registry is None or contract is None:
        checks: tuple[GateCheck, ...] = (
            GateCheck(
                "inputs_readable", False, "registry and contract must be readable JSON objects"
            ),
        )
    else:
        checks = _check_registry(registry) + _check_contract(
            contract,
            capacity_evidence_path=capacity_evidence_path,
        )
    safety_ready = all(check.passed for check in checks)
    capacity_ready = False
    reasons = () if safety_ready else tuple(check.key for check in checks if not check.passed)
    decision = "BLOCKED" if safety_ready else "INVALID"
    return Tar01ExitGateReport(decision, safety_ready, capacity_ready, checks, reasons)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument(
        "--capacity-evidence",
        type=Path,
        help="override the artifact path while preserving contract candidate binding",
    )
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument(
        "--require-capacity",
        action="store_true",
        help="return non-zero while real capacity evidence is unavailable",
    )
    return parser


def main() -> int:
    """Run the TAR-01 safety preflight."""

    args = _build_parser().parse_args()
    result = evaluate_tar01_exit_gate(
        registry_path=args.registry.resolve(),
        contract_path=args.contract.resolve(),
        capacity_evidence_path=(
            args.capacity_evidence.resolve() if args.capacity_evidence is not None else None
        ),
    )
    if args.format == "json":
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(
            f"tar01-exit-gate decision={result.decision} "
            f"safety_ready={str(result.safety_ready).lower()} "
            f"capacity_ready={str(result.capacity_ready).lower()}"
        )
        for check in result.checks:
            print(f"[{'PASS' if check.passed else 'FAIL'}] {check.key}: {check.detail}")
    if args.require_capacity and not result.capacity_ready:
        return 1
    return 0 if result.safety_ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
