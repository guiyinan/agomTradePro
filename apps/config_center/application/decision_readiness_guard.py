"""Fail-closed orchestration for scheduled decision-readiness audits."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from apps.config_center.domain.entities import DecisionRuntimeState, DecisionRuntimeStatus
from shared.domain.task_outcomes import TaskBusinessOutcome

ReadinessPayload = dict[str, Any]
ReadinessProbe = Callable[[], ReadinessPayload]
RuntimeStateReader = Callable[[], DecisionRuntimeState]
RuntimeStateBlocker = Callable[[str, str], DecisionRuntimeState]
AlertPublisher = Callable[[str, str, dict[str, Any]], None]

AUDIT_TASK_NAME = (
    "apps.config_center.application.decision_readiness_guard_tasks." "audit_decision_readiness_task"
)
AUDIT_CHANGED_BY = "system:decision-readiness-audit"


@dataclass(frozen=True)
class DecisionReadinessGuardDependencies:
    """Injected application services used by the scheduled guard."""

    read_runtime_state: RuntimeStateReader
    block_runtime_state: RuntimeStateBlocker
    probes: tuple[tuple[str, ReadinessProbe], ...]
    publish_alert: AlertPublisher


def _is_ready(payload: ReadinessPayload) -> bool:
    """Return whether one probe explicitly proves decision readiness."""

    return bool(
        payload.get("status") == "ok" and payload.get("must_not_use_for_decision") is not True
    )


def _default_dependencies() -> DecisionReadinessGuardDependencies:
    """Compose the guard from public application services."""

    from apps.config_center.application.use_cases import (
        GetDecisionRuntimeStateUseCase,
        UpdateDecisionRuntimeStateUseCase,
    )
    from apps.data_center.application.interface_services import (
        get_decision_data_readiness_payload,
        get_decision_provider_capability_health_payload,
    )
    from apps.data_center.application.query_services import (
        get_active_stock_fact_coverage_payload,
    )
    from shared.infrastructure.operational_alert_registry import (
        record_operational_alert,
    )

    runtime_reader = GetDecisionRuntimeStateUseCase()
    runtime_updater = UpdateDecisionRuntimeStateUseCase()

    def block_runtime_state(reason: str, release_ref: str) -> DecisionRuntimeState:
        return runtime_updater.execute(
            status=DecisionRuntimeStatus.BLOCKED.value,
            reason=reason,
            changed_by=AUDIT_CHANGED_BY,
            release_ref=release_ref,
        )

    def publish_alert(title: str, message: str, metadata: dict[str, Any]) -> None:
        record_operational_alert(
            level="critical",
            task_name=AUDIT_TASK_NAME,
            title=title,
            message=message,
            metadata=metadata,
        )

    return DecisionReadinessGuardDependencies(
        read_runtime_state=runtime_reader.execute,
        block_runtime_state=block_runtime_state,
        probes=(
            ("core_coverage", get_active_stock_fact_coverage_payload),
            (
                "provider_capabilities",
                get_decision_provider_capability_health_payload,
            ),
            ("decision_data", get_decision_data_readiness_payload),
        ),
        publish_alert=publish_alert,
    )


def run_decision_readiness_guard(
    dependencies: DecisionReadinessGuardDependencies | None = None,
) -> dict[str, Any]:
    """Audit decision data and persist a global block when any check fails.

    The guard never promotes a runtime state back to ``active``. Maintenance,
    validation, and existing blocked states remain operator-controlled.
    """

    active_dependencies = dependencies or _default_dependencies()
    runtime_state = active_dependencies.read_runtime_state()
    if runtime_state.status is not DecisionRuntimeStatus.ACTIVE:
        return {
            "success": False,
            "outcome": TaskBusinessOutcome.BLOCKED.value,
            "stage": "runtime_state",
            "requested": 0,
            "succeeded": 0,
            "failed": 0,
            "stored": 0,
            "runtime_status": runtime_state.status.value,
            "block_reason_code": runtime_state.block_reason_code,
            "reason": "operator-controlled decision runtime gate is already active",
        }

    results: dict[str, ReadinessPayload] = {}
    failed_checks: list[str] = []
    technical_failures: list[str] = []
    for check_key, probe in active_dependencies.probes:
        try:
            payload = probe()
        except Exception:
            payload = {
                "status": "error",
                "must_not_use_for_decision": True,
                "block_reason_code": f"{check_key}_probe_failed",
            }
            technical_failures.append(check_key)
        results[check_key] = payload
        if not _is_ready(payload):
            failed_checks.append(check_key)

    requested = len(active_dependencies.probes)
    if not failed_checks:
        return {
            "success": True,
            "outcome": TaskBusinessOutcome.SUCCESS.value,
            "stage": "complete",
            "requested": requested,
            "succeeded": requested,
            "failed": 0,
            "stored": 0,
            "checks": results,
        }

    reason = "Automated decision readiness audit blocked: " + ", ".join(failed_checks)
    try:
        blocked_state = active_dependencies.block_runtime_state(
            reason,
            runtime_state.release_ref,
        )
    except Exception:
        return {
            "success": False,
            "outcome": TaskBusinessOutcome.FAILED.value,
            "stage": "runtime_transition",
            "requested": requested,
            "succeeded": requested - len(failed_checks),
            "failed": len(failed_checks),
            "stored": 0,
            "failed_checks": failed_checks,
            "technical_failures": technical_failures,
            "error": "failed to persist the decision runtime block",
            "checks": results,
        }

    alert_metadata = {
        "failed_checks": failed_checks,
        "technical_failures": technical_failures,
        "runtime_status": blocked_state.status.value,
        "release_ref": blocked_state.release_ref,
    }
    active_dependencies.publish_alert(
        "Decision readiness automatically blocked",
        reason,
        alert_metadata,
    )
    outcome = TaskBusinessOutcome.FAILED if technical_failures else TaskBusinessOutcome.BLOCKED
    return {
        "success": False,
        "outcome": outcome.value,
        "stage": "complete",
        "requested": requested,
        "succeeded": requested - len(failed_checks),
        "failed": len(failed_checks),
        "stored": 1,
        "failed_checks": failed_checks,
        "technical_failures": technical_failures,
        "runtime_state": blocked_state.to_dict(),
        "checks": results,
    }


__all__ = [
    "AUDIT_CHANGED_BY",
    "AUDIT_TASK_NAME",
    "DecisionReadinessGuardDependencies",
    "run_decision_readiness_guard",
]
