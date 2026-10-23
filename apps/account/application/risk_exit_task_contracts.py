"""Typed counts for observation-only Account exit tasks."""

from __future__ import annotations

from typing import TypedDict

from apps.account.application.stop_loss_use_cases import (
    StopLossCheckOutput,
    TakeProfitCheckOutput,
)


class RiskStageSnapshot(TypedDict):
    """Diagnostic counts for one completed or outcome-unknown risk stage."""

    completed: bool
    outcome: str
    requested: int | None
    succeeded: int | None
    failed: int | None
    triggered_count: int
    executed_count: int
    blocked_count: int
    check_unavailable_count: int
    execution_unknown_count: int
    stage_unknown_count: int
    stored: int | None
    counts_unavailable: bool


def summarize_risk_results(
    results: list[StopLossCheckOutput] | list[TakeProfitCheckOutput],
) -> RiskStageSnapshot:
    """Count checks separately from trigger intent and receipt-confirmed execution."""

    requested = len(results)
    succeeded = 0
    failed = 0
    triggered_count = 0
    blocked_count = 0
    check_unavailable_count = 0
    execution_unknown_count = 0
    counts_unavailable = False

    for result in results:
        if result.triggered:
            triggered_count += 1
        if result.check_status not in {"evaluated", "unavailable"}:
            failed += 1
            execution_unknown_count += 1
            counts_unavailable = True
            continue
        if result.check_status == "unavailable":
            if result.triggered or result.execution_status != "not_triggered":
                failed += 1
                execution_unknown_count += 1
                counts_unavailable = True
            else:
                check_unavailable_count += 1
                failed += 1
            continue
        if result.execution_status in {"confirmed", "unknown"}:
            failed += 1
            execution_unknown_count += 1
            counts_unavailable = True
            continue
        if result.triggered and result.execution_status == "blocked":
            failed += 1
            blocked_count += 1
            continue
        if result.triggered or result.execution_status == "blocked":
            failed += 1
            execution_unknown_count += 1
            counts_unavailable = True
            continue
        if result.execution_status == "not_triggered":
            succeeded += 1
            continue
        failed += 1
        execution_unknown_count += 1
        counts_unavailable = True

    stored: int | None = None if counts_unavailable else 0
    outcome = risk_outcome(
        requested=requested,
        succeeded=succeeded,
        failed=failed,
        blocked_count=blocked_count,
        check_unavailable_count=check_unavailable_count,
        execution_unknown_count=execution_unknown_count,
    )
    return {
        "completed": True,
        "outcome": outcome,
        "requested": requested,
        "succeeded": succeeded,
        "failed": failed,
        "triggered_count": triggered_count,
        "executed_count": 0,
        "blocked_count": blocked_count,
        "check_unavailable_count": check_unavailable_count,
        "execution_unknown_count": execution_unknown_count,
        "stage_unknown_count": 0,
        "stored": stored,
        "counts_unavailable": counts_unavailable,
    }


def unknown_stage_snapshot() -> RiskStageSnapshot:
    """Represent a stage exception without inventing completed counts."""

    return {
        "completed": True,
        "outcome": "failed",
        "requested": None,
        "succeeded": None,
        "failed": None,
        "triggered_count": 0,
        "executed_count": 0,
        "blocked_count": 0,
        "check_unavailable_count": 0,
        "execution_unknown_count": 0,
        "stage_unknown_count": 1,
        "stored": None,
        "counts_unavailable": True,
    }


def invalid_risk_input() -> RiskStageSnapshot:
    """Build deterministic task-input counts before constructing dependencies."""

    return {
        "completed": True,
        "outcome": "failed",
        "requested": 1,
        "succeeded": 0,
        "failed": 1,
        "triggered_count": 0,
        "executed_count": 0,
        "blocked_count": 0,
        "check_unavailable_count": 0,
        "execution_unknown_count": 0,
        "stage_unknown_count": 0,
        "stored": 0,
        "counts_unavailable": False,
    }


def risk_outcome(
    *,
    requested: int,
    succeeded: int,
    failed: int,
    blocked_count: int,
    check_unavailable_count: int,
    execution_unknown_count: int,
) -> str:
    """Choose a normalized task outcome from observed check counts."""

    if requested == 0:
        return "noop"
    if failed == 0:
        return "success"
    if succeeded > 0:
        return "partial"
    if blocked_count == requested:
        return "blocked"
    if check_unavailable_count or execution_unknown_count:
        return "failed"
    return "failed"


def merge_risk_snapshots(snapshots: list[RiskStageSnapshot]) -> RiskStageSnapshot:
    """Merge diagnostic stage snapshots while preserving unknown denominators."""

    counts_unavailable = any(snapshot["counts_unavailable"] for snapshot in snapshots)
    stage_unknown_count = sum(snapshot["stage_unknown_count"] for snapshot in snapshots)
    execution_unknown_count = sum(snapshot["execution_unknown_count"] for snapshot in snapshots)
    triggered_count = sum(snapshot["triggered_count"] for snapshot in snapshots)
    executed_count = sum(snapshot["executed_count"] for snapshot in snapshots)
    blocked_count = sum(snapshot["blocked_count"] for snapshot in snapshots)
    check_unavailable_count = sum(snapshot["check_unavailable_count"] for snapshot in snapshots)
    requested_values = [snapshot["requested"] for snapshot in snapshots]
    succeeded_values = [snapshot["succeeded"] for snapshot in snapshots]
    failed_values = [snapshot["failed"] for snapshot in snapshots]
    stored_values = [snapshot["stored"] for snapshot in snapshots]
    requested = (
        sum(value for value in requested_values if value is not None)
        if all(value is not None for value in requested_values)
        else None
    )
    succeeded = (
        sum(value for value in succeeded_values if value is not None)
        if all(value is not None for value in succeeded_values)
        else None
    )
    failed = (
        sum(value for value in failed_values if value is not None)
        if all(value is not None for value in failed_values)
        else None
    )
    stored = (
        sum(value for value in stored_values if value is not None)
        if all(value is not None for value in stored_values)
        else None
    )
    if requested is None or succeeded is None or failed is None:
        known_success = any(
            snapshot["succeeded"] is not None and snapshot["succeeded"] > 0
            for snapshot in snapshots
        )
        outcome = "partial" if known_success else "failed"
    else:
        outcome = risk_outcome(
            requested=requested,
            succeeded=succeeded,
            failed=failed,
            blocked_count=blocked_count,
            check_unavailable_count=check_unavailable_count,
            execution_unknown_count=execution_unknown_count + stage_unknown_count,
        )
    return {
        "completed": True,
        "outcome": outcome,
        "requested": requested,
        "succeeded": succeeded,
        "failed": failed,
        "triggered_count": triggered_count,
        "executed_count": executed_count,
        "blocked_count": blocked_count,
        "check_unavailable_count": check_unavailable_count,
        "execution_unknown_count": execution_unknown_count,
        "stage_unknown_count": stage_unknown_count,
        "stored": stored,
        "counts_unavailable": counts_unavailable or requested is None,
    }


def risk_task_result(
    snapshot: RiskStageSnapshot,
    *,
    status: str | None = None,
    reason_code: str | None = None,
    count_unit: str = "position_check",
) -> dict[str, object]:
    """Project one stage snapshot using explicit units and stable diagnostics."""

    outcome = snapshot["outcome"]
    result: dict[str, object] = {
        "status": status or outcome,
        "success": outcome in {"success", "partial", "noop"},
        "outcome": outcome,
        "requested": snapshot["requested"],
        "succeeded": snapshot["succeeded"],
        "failed": snapshot["failed"],
        "stored": snapshot["stored"],
        "checked_count": snapshot["requested"] if count_unit == "position_check" else None,
        "triggered_count": snapshot["triggered_count"],
        "executed_count": snapshot["executed_count"],
        "blocked_count": snapshot["blocked_count"],
        "check_unavailable_count": snapshot["check_unavailable_count"],
        "execution_unknown_count": snapshot["execution_unknown_count"],
        "stage_unknown_count": snapshot["stage_unknown_count"],
        "counts_unavailable": snapshot["counts_unavailable"],
        "count_unit": count_unit,
        "stored_count_unit": "confirmed_simulated_trade_receipt",
    }
    if reason_code is not None:
        result["reason_code"] = reason_code
    elif snapshot["blocked_count"]:
        result["reason_code"] = "legacy_automatic_exit_not_qualified"
    elif snapshot["check_unavailable_count"]:
        result["reason_code"] = "automatic_exit_check_unavailable"
    elif snapshot["stage_unknown_count"] or snapshot["execution_unknown_count"]:
        result["reason_code"] = "automatic_exit_stage_outcome_unknown"
    return result
