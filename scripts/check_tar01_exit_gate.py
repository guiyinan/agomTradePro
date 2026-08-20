#!/usr/bin/env python
"""Check TAR-01's local safety gate without claiming runtime capacity."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import cast

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = REPO_ROOT / "governance" / "active_plan_registry.json"
DEFAULT_CONTRACT = REPO_ROOT / "governance" / "terminal_agent_runtime_contracts.json"


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


def _check_contract(contract: Mapping[str, object]) -> tuple[GateCheck, ...]:
    """Check that the runtime remains a closed, contract-only implementation."""

    checks: list[GateCheck] = []
    checks.append(
        GateCheck(
            "contract_decision_scope",
            contract.get("decision_status") == "repository_contract_only",
            (
                "contract remains repository_contract_only"
                if contract.get("decision_status") == "repository_contract_only"
                else "decision_status must remain repository_contract_only"
            ),
        )
    )
    feature_flags = _mapping(contract.get("feature_flags"))
    flags = _mapping(feature_flags.get("fields")) if feature_flags is not None else None
    expected_flags = {
        "TERMINAL_QUEUED_INTAKE_ENABLED": False,
        "TERMINAL_QUEUED_WORKER_ENABLED": False,
        "TERMINAL_LEGACY_INLINE_ENABLED": True,
        "TERMINAL_LEGACY_INLINE_CONCURRENCY": 1,
        "TERMINAL_LEGACY_INLINE_TIMEOUT_SECONDS": 60,
    }
    flags_ok = flags is not None and all(
        flags.get(key) == value for key, value in expected_flags.items()
    )
    checks.append(
        GateCheck(
            "runtime_flags_closed",
            flags_ok,
            (
                "queued intake/worker disabled and inline remains one-slot <=60s"
                if flags_ok
                else "queued flags or inline guard differ from the fail-closed contract"
            ),
        )
    )
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
    )
    checks.append(
        GateCheck(
            "capacity_gate_closed",
            closed,
            (
                "runtime enablement remains not_authorized/not_runtime"
                if closed
                else "runtime enablement must remain not_authorized with no runtime evidence"
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
    planned = {
        "repository-postgres-first-winner",
        "celery-delivery-outcomes",
        "events-reconnect-and-owner-scope",
        "load-1-5-10-20",
        "chaos-worker-stream-recovery",
    }
    planned_ok = bool(scenarios) and all(
        scenarios.get(scenario_id, {}).get("implementation_status") == "planned"
        for scenario_id in planned
    )
    checks.append(
        GateCheck(
            "future_runtime_scenarios_waiting",
            planned_ok,
            (
                "repository/Celery/events/load/chaos scenarios remain planned"
                if planned_ok
                else "a future runtime scenario was marked implemented before its gate"
            ),
        )
    )
    return tuple(checks)


def evaluate_tar01_exit_gate(
    *,
    registry_path: Path = DEFAULT_REGISTRY,
    contract_path: Path = DEFAULT_CONTRACT,
) -> Tar01ExitGateReport:
    """Evaluate the local TAR-01 safety boundary without enabling runtime."""

    registry = _read_json(registry_path)
    contract = _read_json(contract_path)
    if registry is None or contract is None:
        checks: tuple[GateCheck, ...] = (
            GateCheck(
                "inputs_readable", False, "registry and contract must be readable JSON objects"
            ),
        )
    else:
        checks = _check_registry(registry) + _check_contract(contract)
    safety_ready = all(check.passed for check in checks)
    capacity_ready = False
    reasons = () if safety_ready else tuple(check.key for check in checks if not check.passed)
    decision = "BLOCKED" if safety_ready else "INVALID"
    return Tar01ExitGateReport(decision, safety_ready, capacity_ready, checks, reasons)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
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
