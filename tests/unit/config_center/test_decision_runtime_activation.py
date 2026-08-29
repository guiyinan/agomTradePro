"""Fail-closed contracts for decision-runtime activation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from apps.config_center.application.decision_runtime_activation import (
    ActivateDecisionRuntimeUseCase,
    DecisionRuntimeActivationDependencies,
    DecisionRuntimeActivationError,
)
from apps.config_center.domain.entities import DecisionRuntimeState, DecisionRuntimeStatus

NOW = datetime(2026, 8, 30, 2, 0, tzinfo=UTC)
RELEASE_REF = "a" * 40


def _blocked_state() -> DecisionRuntimeState:
    return DecisionRuntimeState(
        status=DecisionRuntimeStatus.BLOCKED,
        reason="data repair pending",
        changed_at=NOW - timedelta(hours=1),
        changed_by="operator-old",
        release_ref="old-release",
    )


def _ready() -> dict[str, object]:
    return {"status": "ok", "must_not_use_for_decision": False}


def _use_case(
    *,
    probe_results: dict[str, list[dict[str, object]]] | None = None,
    cas_succeeds: bool = True,
):
    state = [_blocked_state()]
    transitions: list[DecisionRuntimeState] = []
    results = probe_results or {
        "core_coverage": [_ready(), _ready()],
        "provider_capabilities": [_ready(), _ready()],
        "decision_data": [_ready(), _ready()],
    }

    def read_state() -> DecisionRuntimeState:
        return state[0]

    def compare_and_set(
        expected: DecisionRuntimeState,
        requested: DecisionRuntimeState,
    ) -> DecisionRuntimeState | None:
        if not cas_succeeds or state[0] != expected:
            return None
        state[0] = requested
        transitions.append(requested)
        return requested

    def block(requested: DecisionRuntimeState) -> DecisionRuntimeState:
        state[0] = requested
        transitions.append(requested)
        return requested

    def probe(name: str):
        def _execute() -> dict[str, object]:
            values = results[name]
            return values.pop(0) if len(values) > 1 else values[0]

        return _execute

    use_case = ActivateDecisionRuntimeUseCase(
        DecisionRuntimeActivationDependencies(
            read_runtime_state=read_state,
            compare_and_set_runtime_state=compare_and_set,
            block_runtime_state=block,
            probes=(
                ("core_coverage", probe("core_coverage")),
                ("provider_capabilities", probe("provider_capabilities")),
                ("decision_data", probe("decision_data")),
            ),
            clock=lambda: NOW,
        )
    )
    return use_case, state, transitions


def test_activation_preview_runs_three_checks_without_mutation() -> None:
    use_case, state, transitions = _use_case()

    preview = use_case.preview(release_ref=RELEASE_REF)

    assert preview.ready is True
    assert preview.failed_checks == ()
    assert state[0].status is DecisionRuntimeStatus.BLOCKED
    assert transitions == []


def test_activation_compare_and_set_revalidates_before_success() -> None:
    use_case, state, transitions = _use_case()

    result = use_case.execute(
        release_ref=RELEASE_REF,
        changed_by="release-owner",
    )

    assert result.activated is True
    assert result.reblocked is False
    assert result.failed_checks == ()
    assert state[0].status is DecisionRuntimeStatus.ACTIVE
    assert state[0].release_ref == RELEASE_REF
    assert len(transitions) == 1


def test_activation_preflight_failure_never_writes_active() -> None:
    blocked = {"status": "incomplete", "must_not_use_for_decision": True}
    use_case, state, transitions = _use_case(
        probe_results={
            "core_coverage": [blocked],
            "provider_capabilities": [_ready()],
            "decision_data": [_ready()],
        }
    )

    with pytest.raises(DecisionRuntimeActivationError, match="core_coverage"):
        use_case.execute(release_ref=RELEASE_REF, changed_by="release-owner")

    assert state[0].status is DecisionRuntimeStatus.BLOCKED
    assert transitions == []


def test_activation_rejects_compare_and_set_drift() -> None:
    use_case, state, transitions = _use_case(cas_succeeds=False)

    with pytest.raises(DecisionRuntimeActivationError, match="drifted"):
        use_case.execute(release_ref=RELEASE_REF, changed_by="release-owner")

    assert state[0].status is DecisionRuntimeStatus.BLOCKED
    assert transitions == []


def test_activation_final_probe_failure_automatically_reblocks() -> None:
    blocked = {"status": "blocked", "must_not_use_for_decision": True}
    use_case, state, transitions = _use_case(
        probe_results={
            "core_coverage": [_ready(), blocked],
            "provider_capabilities": [_ready(), _ready()],
            "decision_data": [_ready(), _ready()],
        }
    )

    result = use_case.execute(
        release_ref=RELEASE_REF,
        changed_by="release-owner",
    )

    assert result.activated is False
    assert result.reblocked is True
    assert result.failed_checks == ("core_coverage",)
    assert state[0].status is DecisionRuntimeStatus.BLOCKED
    assert state[0].changed_by == "system:decision-runtime-activation"
    assert [item.status for item in transitions] == [
        DecisionRuntimeStatus.ACTIVE,
        DecisionRuntimeStatus.BLOCKED,
    ]
