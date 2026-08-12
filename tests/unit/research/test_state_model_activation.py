"""Pure Domain contracts for the separate R6 activation/rollback stack."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from apps.research.domain.state_model_activation import (
    R6ActivationAction,
    R6ActivationApproval,
    R6ActivationApprovalOutcome,
    R6ActivationAuthorization,
    R6ActivationScope,
    R6ActivationScopeRef,
    R6MonitoringActivationEvidence,
    R6MonitoringActivationStatus,
    create_r6_activation_event,
    derive_r6_activation_state,
)
from apps.research.domain.state_model_qualification_lifecycle import R6QualificationRef

NOW = datetime(2026, 8, 9, 12, tzinfo=UTC)
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64


def _scope() -> R6ActivationScope:
    return R6ActivationScope(
        scope_id="r6-state-model-advisory",
        scope_version="scope.v1",
        purpose="state-model-advisory",
        label_protocol_version="labels.v1",
    )


def _qualification_ref(suffix: str) -> R6QualificationRef:
    return R6QualificationRef(
        assessment_id=f"qualification-{suffix}",
        assessment_hash=HASH_A if suffix == "a" else HASH_B,
    )


def _monitoring(
    suffix: str,
    qualification_ref: R6QualificationRef,
) -> R6MonitoringActivationEvidence:
    return R6MonitoringActivationEvidence(
        assessment_id=f"monitoring-{suffix}",
        assessment_hash=HASH_C if suffix == "a" else HASH_A,
        qualification_ref=qualification_ref,
        policy_id="monitor-policy",
        policy_version="policy.v1",
        policy_hash=HASH_B,
        label_protocol_version="labels.v1",
        label_set_hash=HASH_C,
        status=R6MonitoringActivationStatus.HEALTHY,
        evaluated_at=NOW - timedelta(hours=2),
        recorded_at=NOW - timedelta(hours=1),
        valid_until=NOW + timedelta(days=7),
        owner="research",
        evidence_ref=f"research:r6-monitoring:{suffix}",
    )


def _approval(suffix: str) -> R6ActivationApproval:
    qualification_ref = _qualification_ref(suffix)
    monitoring = _monitoring(suffix, qualification_ref)
    return R6ActivationApproval(
        approval_id=f"activation-{suffix}",
        approval_version="approval.v1",
        scope=_scope(),
        qualification_ref=qualification_ref,
        active_qualification_hash=HASH_C,
        candidate_id=f"candidate-{suffix}",
        candidate_version="candidate.v1",
        monitoring_ref=monitoring.ref,
        monitoring_evidence_hash=monitoring.content_hash,
        required_monitoring_policy_id=monitoring.policy_id,
        required_monitoring_policy_version=monitoring.policy_version,
        required_monitoring_policy_hash=monitoring.policy_hash,
        required_label_protocol_version=monitoring.label_protocol_version,
        required_label_set_hash=monitoring.label_set_hash,
        maximum_monitoring_age_seconds=86_400,
        outcome=R6ActivationApprovalOutcome.APPROVED,
        owner="research",
        decided_at=NOW - timedelta(minutes=30),
        recorded_at=NOW - timedelta(minutes=20),
        valid_until=NOW + timedelta(days=2),
        reason_codes=("qualified_and_healthy",),
        evidence_ref=f"research:r6-activation:{suffix}",
    )


def _authorization(
    *,
    suffix: str,
    action: R6ActivationAction,
    subject: R6ActivationApproval,
    sequence: int,
    rollback_target: R6ActivationApproval | None = None,
    expected_previous_event_hash: str | None = None,
    issued_at_override: datetime | None = None,
    recorded_at_override: datetime | None = None,
) -> R6ActivationAuthorization:
    recorded_at = recorded_at_override or (
        NOW - timedelta(minutes=4) + timedelta(minutes=(sequence - 1) * 10)
    )
    return R6ActivationAuthorization(
        authorization_id=f"authorization-{suffix}",
        authorization_version="authorization.v1",
        event_id=f"activation-event-{suffix}",
        event_version="event.v1",
        scope_ref=R6ActivationScopeRef.from_scope(subject.scope),
        action=action,
        subject=subject.ref,
        rollback_target=None if rollback_target is None else rollback_target.ref,
        expected_sequence=sequence,
        expected_previous_event_hash=expected_previous_event_hash,
        owner="research",
        issued_at=issued_at_override or recorded_at - timedelta(minutes=1),
        recorded_at=recorded_at,
        valid_until=recorded_at + timedelta(hours=1),
        reason_codes=(f"manual_{action.value}",),
        evidence_ref=f"research:r6-activation-authorization:{suffix}",
    )


def test_activation_stack_rolls_back_only_to_exact_previous_approval() -> None:
    """A→B may roll back only from B to the exact stack[-2] identity A."""

    approval_a = _approval("a")
    approval_b = _approval("b")
    event_a = create_r6_activation_event(
        authorization=_authorization(
            suffix="a",
            action=R6ActivationAction.ACTIVATE,
            subject=approval_a,
            sequence=1,
        ),
        previous_events=(),
        applied_at=NOW,
    )
    event_b = create_r6_activation_event(
        authorization=_authorization(
            suffix="b",
            action=R6ActivationAction.ACTIVATE,
            subject=approval_b,
            sequence=2,
            expected_previous_event_hash=event_a.content_hash,
        ),
        previous_events=(event_a,),
        applied_at=NOW + timedelta(minutes=10),
    )
    rollback = create_r6_activation_event(
        authorization=_authorization(
            suffix="rollback-b-to-a",
            action=R6ActivationAction.ROLLBACK,
            subject=approval_b,
            sequence=3,
            rollback_target=approval_a,
            expected_previous_event_hash=event_b.content_hash,
        ),
        previous_events=(event_a, event_b),
        applied_at=NOW + timedelta(minutes=20),
    )

    state = derive_r6_activation_state(
        (event_a, event_b, rollback),
        evaluated_at=NOW + timedelta(minutes=20),
    )

    assert state.active_approval == approval_a.ref
    assert state.activation_stack == (approval_a.ref,)
    assert state.sequence == 3


def test_rollback_rejects_alias_target_and_reordered_prefix() -> None:
    """Caller-selected aliases and reordered stream prefixes cannot steer rollback."""

    approval_a = _approval("a")
    approval_b = _approval("b")
    event_a = create_r6_activation_event(
        authorization=_authorization(
            suffix="a",
            action=R6ActivationAction.ACTIVATE,
            subject=approval_a,
            sequence=1,
        ),
        previous_events=(),
        applied_at=NOW,
    )
    event_b = create_r6_activation_event(
        authorization=_authorization(
            suffix="b",
            action=R6ActivationAction.ACTIVATE,
            subject=approval_b,
            sequence=2,
            expected_previous_event_hash=event_a.content_hash,
        ),
        previous_events=(event_a,),
        applied_at=NOW + timedelta(minutes=10),
    )
    alias = _approval("a")
    object.__setattr__(alias, "content_hash", HASH_C)

    with pytest.raises(ValueError, match=r"stack\[-2\]"):
        create_r6_activation_event(
            authorization=_authorization(
                suffix="bad-rollback",
                action=R6ActivationAction.ROLLBACK,
                subject=approval_b,
                sequence=3,
                rollback_target=alias,
                expected_previous_event_hash=event_b.content_hash,
            ),
            previous_events=(event_a, event_b),
            applied_at=NOW + timedelta(minutes=20),
        )
    with pytest.raises(ValueError, match="sequence"):
        derive_r6_activation_state(
            (event_b, event_a),
            evaluated_at=NOW + timedelta(minutes=20),
        )


def test_event_tamper_and_future_evidence_fail_closed() -> None:
    """Event seals and PIT recording clocks are replayed, not trusted structurally."""

    approval = _approval("a")
    event = create_r6_activation_event(
        authorization=_authorization(
            suffix="a",
            action=R6ActivationAction.ACTIVATE,
            subject=approval,
            sequence=1,
        ),
        previous_events=(),
        applied_at=NOW,
    )
    object.__setattr__(event, "content_hash", HASH_A)
    with pytest.raises(ValueError, match="content hash"):
        derive_r6_activation_state((event,), evaluated_at=NOW)

    fresh = create_r6_activation_event(
        authorization=_authorization(
            suffix="fresh",
            action=R6ActivationAction.ACTIVATE,
            subject=approval,
            sequence=1,
        ),
        previous_events=(),
        applied_at=NOW,
    )
    with pytest.raises(ValueError, match="future"):
        derive_r6_activation_state((fresh,), evaluated_at=NOW - timedelta(microseconds=1))


def test_transition_authorization_cannot_be_prerecorded_before_stream_head() -> None:
    """A manual next action must be recorded after the state it authorizes exists."""

    approval_a = _approval("a")
    approval_b = _approval("b")
    root = create_r6_activation_event(
        authorization=_authorization(
            suffix="root",
            action=R6ActivationAction.ACTIVATE,
            subject=approval_a,
            sequence=1,
        ),
        previous_events=(),
        applied_at=NOW,
    )
    prerecord = _authorization(
        suffix="prerecorded-next",
        action=R6ActivationAction.ACTIVATE,
        subject=approval_b,
        sequence=2,
        expected_previous_event_hash=root.content_hash,
        recorded_at_override=NOW - timedelta(minutes=1),
    )

    with pytest.raises(ValueError, match="strictly follow the stream head"):
        create_r6_activation_event(
            authorization=prerecord,
            previous_events=(root,),
            applied_at=NOW + timedelta(minutes=1),
        )


def test_authorization_requires_exact_head_and_strict_issue_record_chronology() -> None:
    """An equal-clock or alternate-head authorization cannot consume the next sequence."""

    approval_a = _approval("a")
    approval_b = _approval("b")
    root = create_r6_activation_event(
        authorization=_authorization(
            suffix="root-strict",
            action=R6ActivationAction.ACTIVATE,
            subject=approval_a,
            sequence=1,
        ),
        previous_events=(),
        applied_at=NOW,
    )
    equal_clock = _authorization(
        suffix="equal-clock",
        action=R6ActivationAction.ACTIVATE,
        subject=approval_b,
        sequence=2,
        expected_previous_event_hash=root.content_hash,
        issued_at_override=NOW,
        recorded_at_override=NOW,
    )
    with pytest.raises(ValueError, match="strictly follow the stream head"):
        create_r6_activation_event(
            authorization=equal_clock,
            previous_events=(root,),
            applied_at=NOW + timedelta(minutes=1),
        )

    alternate_head = _authorization(
        suffix="alternate-head",
        action=R6ActivationAction.ACTIVATE,
        subject=approval_b,
        sequence=2,
        expected_previous_event_hash=HASH_C,
        issued_at_override=NOW + timedelta(minutes=1),
        recorded_at_override=NOW + timedelta(minutes=2),
    )
    with pytest.raises(ValueError, match="previous head hash differs"):
        create_r6_activation_event(
            authorization=alternate_head,
            previous_events=(root,),
            applied_at=NOW + timedelta(minutes=3),
        )


def test_retire_clears_activation_without_publishing_or_execution_authority() -> None:
    """Manual retirement closes the stack and every event remains non-consuming."""

    approval = _approval("a")
    activated = create_r6_activation_event(
        authorization=_authorization(
            suffix="activate",
            action=R6ActivationAction.ACTIVATE,
            subject=approval,
            sequence=1,
        ),
        previous_events=(),
        applied_at=NOW,
    )
    retired = create_r6_activation_event(
        authorization=_authorization(
            suffix="retire",
            action=R6ActivationAction.RETIRE,
            subject=approval,
            sequence=2,
            expected_previous_event_hash=activated.content_hash,
        ),
        previous_events=(activated,),
        applied_at=NOW + timedelta(minutes=10),
    )
    state = derive_r6_activation_state(
        (activated, retired),
        evaluated_at=NOW + timedelta(minutes=10),
    )

    assert state.active_approval is None
    assert state.activation_stack == ()
    assert retired.must_not_replace_regime is True
    assert retired.must_not_publish_current is True
    assert retired.must_not_use_for_decision is True
    assert retired.must_not_execute is True
