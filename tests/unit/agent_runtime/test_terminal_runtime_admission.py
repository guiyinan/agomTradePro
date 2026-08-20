"""Pure tests for the bounded TAR-02 admission decision contract."""

from __future__ import annotations

import ast
from dataclasses import MISSING, fields
from pathlib import Path

import pytest

from apps.agent_runtime.application.terminal_runtime_admission import (
    TerminalAdmissionDecision,
    TerminalAdmissionDecisionReason,
    TerminalAdmissionSnapshot,
    TerminalRuntimeAdmissionError,
    evaluate_terminal_admission,
    evaluate_terminal_runtime_admission,
)
from apps.agent_runtime.application.terminal_runtime_queue_policy import (
    TERMINAL_AGENT_QUEUE_NAME,
    TERMINAL_AGENT_STREAM_NAMESPACE,
    TerminalAdmissionLimits,
    TerminalFallbackMode,
    TerminalRunDeadlines,
    TerminalRuntimeFeatureFlags,
    TerminalRuntimeQueuePolicy,
    TerminalWorkerQueueLimits,
)


def _policy(
    *,
    per_user_active: int = 2,
    per_user_queued: int = 3,
    global_active: int = 4,
    global_queued: int = 8,
    queued_intake_enabled: bool = True,
    queued_worker_enabled: bool = True,
    legacy_inline_enabled: bool = True,
    emergency_stop: bool = False,
    fallback_mode: TerminalFallbackMode = TerminalFallbackMode.PAUSE,
) -> TerminalRuntimeQueuePolicy:
    """Build explicit policy values for pure decision tests."""

    return TerminalRuntimeQueuePolicy(
        worker_limits=TerminalWorkerQueueLimits(
            queue_name=TERMINAL_AGENT_QUEUE_NAME,
            stream_namespace=TERMINAL_AGENT_STREAM_NAMESPACE,
            worker_concurrency=global_active,
            broker_prefetch_count=1,
            queue_max_depth=global_queued,
            stream_max_length=100,
            stream_ttl_seconds=3600,
            max_tasks_per_child=100,
        ),
        admission_limits=TerminalAdmissionLimits(
            per_user_active=per_user_active,
            per_user_queued=per_user_queued,
            global_active=global_active,
            global_queued=global_queued,
        ),
        deadlines=TerminalRunDeadlines(
            max_queue_wait_seconds=300,
            soft_timeout_seconds=45,
            hard_timeout_seconds=60,
            cancel_grace_seconds=10,
            heartbeat_interval_seconds=5,
            orphan_after_seconds=30,
        ),
        feature_flags=TerminalRuntimeFeatureFlags(
            queued_intake_enabled=queued_intake_enabled,
            queued_worker_enabled=queued_worker_enabled,
            legacy_inline_enabled=legacy_inline_enabled,
            fallback_mode=fallback_mode,
            emergency_stop=emergency_stop,
            legacy_inline_concurrency=1,
            legacy_inline_timeout_seconds=60,
        ),
    )


def _snapshot(**overrides: object) -> TerminalAdmissionSnapshot:
    """Build one explicit, internally coherent counter snapshot."""

    values: dict[str, object] = {
        "actor_user_id": 41,
        "user_active": 0,
        "user_queued": 0,
        "global_active": 0,
        "global_queued": 0,
        "worker_ready": True,
    }
    values.update(overrides)
    return TerminalAdmissionSnapshot(**values)  # type: ignore[arg-type]


def test_admission_accepts_under_all_caps_and_preserves_actor_scope() -> None:
    """An explicit under-cap snapshot is accepted for exactly its actor."""

    decision = evaluate_terminal_admission(_policy(), _snapshot())

    assert decision.accepted is True
    assert decision.reason is TerminalAdmissionDecisionReason.ACCEPTED
    assert decision.actor_user_id == 41


@pytest.mark.parametrize(
    ("field_name", "reason"),
    [
        ("user_active", TerminalAdmissionDecisionReason.PER_USER_ACTIVE_LIMIT),
        ("user_queued", TerminalAdmissionDecisionReason.PER_USER_QUEUED_LIMIT),
        ("global_active", TerminalAdmissionDecisionReason.GLOBAL_ACTIVE_LIMIT),
        ("global_queued", TerminalAdmissionDecisionReason.GLOBAL_QUEUED_LIMIT),
    ],
)
def test_admission_rejects_at_each_configured_cap(
    field_name: str,
    reason: TerminalAdmissionDecisionReason,
) -> None:
    """Equality with any per-user or global cap is fail-closed."""

    limits = {
        "user_active": 2,
        "user_queued": 3,
        "global_active": 4,
        "global_queued": 8,
    }
    snapshot_values: dict[str, object] = {
        "user_active": 0,
        "user_queued": 0,
        "global_active": 0,
        "global_queued": 0,
        "worker_ready": True,
    }
    snapshot_values[field_name] = limits[field_name]
    if field_name == "user_active":
        snapshot_values["global_active"] = limits[field_name]
    if field_name == "user_queued":
        snapshot_values["global_queued"] = limits[field_name]
    decision = evaluate_terminal_admission(_policy(), _snapshot(**snapshot_values))

    assert decision.accepted is False
    assert decision.reason is reason


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"worker_ready": False}, TerminalAdmissionDecisionReason.QUEUED_UNAVAILABLE),
        (
            {"queued_intake_enabled": False},
            TerminalAdmissionDecisionReason.QUEUED_UNAVAILABLE,
        ),
        (
            {"queued_intake_enabled": False, "queued_worker_enabled": False},
            TerminalAdmissionDecisionReason.QUEUED_UNAVAILABLE,
        ),
        (
            {
                "queued_intake_enabled": False,
                "queued_worker_enabled": False,
                "legacy_inline_enabled": False,
                "emergency_stop": True,
            },
            TerminalAdmissionDecisionReason.SUBMISSIONS_PAUSED,
        ),
    ],
)
def test_admission_flags_and_worker_readiness_fail_closed(
    overrides: dict[str, object],
    reason: TerminalAdmissionDecisionReason,
) -> None:
    """Unavailable or paused queued mode never becomes an inline acceptance."""

    policy_overrides = {key: value for key, value in overrides.items() if key != "worker_ready"}
    snapshot_overrides = {key: value for key, value in overrides.items() if key == "worker_ready"}
    decision = evaluate_terminal_admission(
        _policy(**policy_overrides),  # type: ignore[arg-type]
        _snapshot(**snapshot_overrides),
    )

    assert decision.accepted is False
    assert decision.reason is reason


def test_restricted_inline_fallback_is_not_queued_acceptance() -> None:
    """A migration fallback cannot make a disabled queued path look admitted."""

    decision = evaluate_terminal_admission(
        _policy(
            queued_intake_enabled=False,
            queued_worker_enabled=False,
            fallback_mode=TerminalFallbackMode.RESTRICTED_INLINE,
        ),
        _snapshot(),
    )

    assert decision.accepted is False
    assert decision.reason is TerminalAdmissionDecisionReason.QUEUED_UNAVAILABLE


@pytest.mark.parametrize(
    "overrides",
    [
        {"actor_user_id": 0},
        {"actor_user_id": True},
        {"user_active": -1},
        {"user_queued": True},
        {"global_active": -1},
        {"global_queued": False},
        {"user_active": 2, "global_active": 1},
        {"user_queued": 2, "global_queued": 1},
        {"worker_ready": 1},
    ],
)
def test_snapshot_rejects_invalid_or_impossible_counts(overrides: dict[str, object]) -> None:
    """The snapshot has no coercion path for booleans, negatives, or impossible totals."""

    with pytest.raises(TerminalRuntimeAdmissionError):
        _snapshot(**overrides)


def test_contract_has_no_implicit_snapshot_or_decision_defaults() -> None:
    """Every admission fact must be supplied by a future trusted composition root."""

    assert all(field.default is MISSING for field in fields(TerminalAdmissionSnapshot))
    assert all(field.default is MISSING for field in fields(TerminalAdmissionDecision))


@pytest.mark.parametrize(
    "accepted,reason",
    [
        (True, TerminalAdmissionDecisionReason.GLOBAL_ACTIVE_LIMIT),
        (False, TerminalAdmissionDecisionReason.ACCEPTED),
    ],
)
def test_decision_rejects_accepted_reason_contradictions(
    accepted: bool,
    reason: TerminalAdmissionDecisionReason,
) -> None:
    """Callers cannot forge a successful decision by changing one field."""

    with pytest.raises(TerminalRuntimeAdmissionError, match="contradicts"):
        TerminalAdmissionDecision(actor_user_id=41, accepted=accepted, reason=reason)


def test_runtime_alias_is_the_same_pure_function() -> None:
    """The descriptive alias cannot introduce a second admission implementation."""

    assert evaluate_terminal_runtime_admission is evaluate_terminal_admission


def test_admission_module_has_no_runtime_or_infrastructure_dependency() -> None:
    """The decision contract cannot silently enable queue or worker execution."""

    path = Path("apps/agent_runtime/application/terminal_runtime_admission.py")
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        alias.name
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert all(not name.startswith("django") for name in imported)
    assert all("infrastructure" not in name for name in imported)
    assert all("celery" not in name.casefold() for name in imported)
    assert ".objects" not in source
    assert "OpenAIAgentsTerminalService" not in source
    assert ".publish(" not in source
    assert ".dispatch(" not in source
