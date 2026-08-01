"""Scheduled decision-readiness fail-closed guard contracts."""

from datetime import UTC, datetime
from typing import Any

from django.conf import settings

from apps.config_center.application.decision_readiness_guard import (
    DecisionReadinessGuardDependencies,
)
from apps.config_center.application.decision_readiness_guard_tasks import (
    audit_decision_readiness_task,
)
from apps.config_center.domain.entities import DecisionRuntimeState, DecisionRuntimeStatus

NOW = datetime(2026, 8, 2, 4, 0, tzinfo=UTC)


def _runtime_state(
    status: DecisionRuntimeStatus = DecisionRuntimeStatus.ACTIVE,
) -> DecisionRuntimeState:
    reason = "" if status is DecisionRuntimeStatus.ACTIVE else "operator gate"
    return DecisionRuntimeState(
        status=status,
        reason=reason,
        changed_at=NOW,
        changed_by="operator",
        release_ref="release-sha",
    )


def _ready_payload() -> dict[str, Any]:
    return {"status": "ok", "must_not_use_for_decision": False}


def _dependencies(
    *,
    runtime_status: DecisionRuntimeStatus = DecisionRuntimeStatus.ACTIVE,
    probes: tuple[tuple[str, Any], ...] | None = None,
    transitions: list[tuple[str, str]] | None = None,
    alerts: list[tuple[str, str, dict[str, Any]]] | None = None,
) -> DecisionReadinessGuardDependencies:
    active_transitions = transitions if transitions is not None else []
    active_alerts = alerts if alerts is not None else []

    def block_runtime(reason: str, release_ref: str) -> DecisionRuntimeState:
        active_transitions.append((reason, release_ref))
        return DecisionRuntimeState(
            status=DecisionRuntimeStatus.BLOCKED,
            reason=reason,
            changed_at=NOW,
            changed_by="system:decision-readiness-audit",
            release_ref=release_ref,
        )

    def publish_alert(title: str, message: str, metadata: dict[str, Any]) -> None:
        active_alerts.append((title, message, metadata))

    return DecisionReadinessGuardDependencies(
        read_runtime_state=lambda: _runtime_state(runtime_status),
        block_runtime_state=block_runtime,
        probes=probes
        or (
            ("core_coverage", _ready_payload),
            ("provider_capabilities", _ready_payload),
            ("decision_data", _ready_payload),
        ),
        publish_alert=publish_alert,
    )


def test_decision_readiness_guard_keeps_active_when_all_checks_pass(
    monkeypatch,
) -> None:
    transitions: list[tuple[str, str]] = []
    dependencies = _dependencies(transitions=transitions)
    monkeypatch.setattr(
        "apps.config_center.application.decision_readiness_guard._default_dependencies",
        lambda: dependencies,
    )

    result = audit_decision_readiness_task.run()

    assert result["outcome"] == "success"
    assert result["success"] is True
    assert result["requested"] == 3
    assert result["succeeded"] == 3
    assert result["failed"] == 0
    assert result["stored"] == 0
    assert transitions == []


def test_decision_readiness_guard_blocks_active_runtime_on_unready_check(
    monkeypatch,
) -> None:
    transitions: list[tuple[str, str]] = []
    alerts: list[tuple[str, str, dict[str, Any]]] = []
    dependencies = _dependencies(
        transitions=transitions,
        alerts=alerts,
        probes=(
            (
                "core_coverage",
                lambda: {
                    "status": "incomplete",
                    "must_not_use_for_decision": True,
                },
            ),
            ("provider_capabilities", _ready_payload),
            ("decision_data", _ready_payload),
        ),
    )
    monkeypatch.setattr(
        "apps.config_center.application.decision_readiness_guard._default_dependencies",
        lambda: dependencies,
    )

    result = audit_decision_readiness_task.run()

    assert result["outcome"] == "blocked"
    assert result["success"] is False
    assert result["failed_checks"] == ["core_coverage"]
    assert result["stored"] == 1
    assert result["runtime_state"]["status"] == "blocked"
    assert transitions == [
        ("Automated decision readiness audit blocked: core_coverage", "release-sha")
    ]
    assert alerts[0][2]["failed_checks"] == ["core_coverage"]


def test_decision_readiness_guard_fails_closed_when_probe_raises(monkeypatch) -> None:
    transitions: list[tuple[str, str]] = []

    def broken_probe() -> dict[str, Any]:
        raise RuntimeError("database unavailable")

    dependencies = _dependencies(
        transitions=transitions,
        probes=(
            ("core_coverage", broken_probe),
            ("provider_capabilities", _ready_payload),
            ("decision_data", _ready_payload),
        ),
    )
    monkeypatch.setattr(
        "apps.config_center.application.decision_readiness_guard._default_dependencies",
        lambda: dependencies,
    )

    result = audit_decision_readiness_task.run()

    assert result["outcome"] == "failed"
    assert result["success"] is False
    assert result["failed_checks"] == ["core_coverage"]
    assert result["technical_failures"] == ["core_coverage"]
    assert result["stored"] == 1
    assert len(transitions) == 1


def test_decision_readiness_guard_preserves_operator_controlled_gate(
    monkeypatch,
) -> None:
    probe_calls: list[str] = []

    def probe() -> dict[str, Any]:
        probe_calls.append("called")
        return _ready_payload()

    dependencies = _dependencies(
        runtime_status=DecisionRuntimeStatus.MAINTENANCE,
        probes=(("core_coverage", probe),),
    )
    monkeypatch.setattr(
        "apps.config_center.application.decision_readiness_guard._default_dependencies",
        lambda: dependencies,
    )

    result = audit_decision_readiness_task.run()

    assert result["outcome"] == "blocked"
    assert result["stage"] == "runtime_state"
    assert result["runtime_status"] == "maintenance"
    assert probe_calls == []


def test_decision_readiness_guard_has_daily_fail_closed_schedule() -> None:
    schedule = settings.CELERY_BEAT_SCHEDULE["decision-readiness-fail-closed-audit"]

    assert schedule["task"] == (
        "apps.config_center.application.decision_readiness_guard_tasks."
        "audit_decision_readiness_task"
    )
    assert schedule["schedule"].hour == {18}
    assert schedule["schedule"].minute == {30}
