"""Domain contracts for the R7 human-review reminder ledger."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest

from apps.research.domain.scenario_research_hashing import hash_components
from apps.research.domain.scenario_review_reminders import (
    ReminderEventType,
    ReminderLifecycleBlocked,
    ReminderLifecycleState,
    ScenarioReviewPeriodEvidenceBinding,
    ScenarioReviewReminder,
    ScenarioReviewReminderEvent,
    ScenarioReviewReminderSchedulePolicy,
    acknowledge_scenario_review_reminder,
    build_scenario_review_period_evidence_bindings,
    derive_scenario_review_reminder_state,
    is_scenario_review_reminder_due,
    reconcile_scenario_review_reminder,
)
from tests.unit.research.scenario_review_reminder_factories import (
    NOW,
    make_path_study,
    make_policy,
    make_review_intent,
)


def _schedule_policy() -> ScenarioReviewReminderSchedulePolicy:
    return ScenarioReviewReminderSchedulePolicy.from_probability_policy(
        probability_policy=make_policy(),
        schedule_version="scenario-review-schedule.v1",
        expiry_delay=timedelta(days=5),
        escalation_delay=timedelta(days=1),
        maximum_escalation_level=2,
        path_horizon_periods=2,
        owner_evidence_hash="b" * 64,
        escalation_policy_version="scenario-escalation.v1",
        escalation_policy_hash="c" * 64,
    )


def _reminder() -> ScenarioReviewReminder:
    return ScenarioReviewReminder.create(
        intent=make_review_intent(),
        schedule_policy=_schedule_policy(),
        path_evidence_hash="d" * 64,
        period_bindings=(
            ScenarioReviewPeriodEvidenceBinding.create(
                period_index=1,
                conditional_probability_identity_hashes=("e" * 64, "f" * 64),
                transition_probability_identity_hashes=("1" * 64, "2" * 64),
            ),
            ScenarioReviewPeriodEvidenceBinding.create(
                period_index=2,
                conditional_probability_identity_hashes=("3" * 64, "4" * 64),
                transition_probability_identity_hashes=("5" * 64, "6" * 64),
            ),
        ),
    )


def test_schedule_binds_exact_source_policy_owner_and_period_evidence() -> None:
    reminder = _reminder()

    assert reminder.intent.forecast_entry_id == "forecast-r7-1"
    assert reminder.schedule_policy.owner_evidence_hash == "b" * 64
    assert reminder.path_evidence_hash == "d" * 64
    assert tuple(item.period_index for item in reminder.period_bindings) == (1, 2)
    assert reminder.delivery_scope == "internal_review"
    assert reminder.must_not_execute is True
    assert reminder.external_dispatch_requested is False
    assert reminder.auto_approval_requested is False
    assert reminder.research_only is True
    assert reminder.expires_at == reminder.due_at + timedelta(days=5)


def test_typed_path_projection_binds_each_exact_period_and_rejects_substitution() -> None:
    intent = make_review_intent()
    policy = _schedule_policy()
    path = make_path_study()

    bindings = build_scenario_review_period_evidence_bindings(
        intent=intent,
        schedule_policy=policy,
        path_evidence=path,
    )

    assert tuple(item.period_index for item in bindings) == (1, 2)
    assert all(len(item.conditional_probability_identity_hashes) == 2 for item in bindings)
    assert all(len(item.transition_probability_identity_hashes) == 4 for item in bindings)
    with pytest.raises(ValueError, match="scenario-set revision"):
        build_scenario_review_period_evidence_bindings(
            intent=intent,
            schedule_policy=policy,
            path_evidence=make_path_study(
                scenario_set_revision_id=UUID("00000000-0000-0000-0000-000000000999"),
            ),
        )
    with pytest.raises(ValueError, match="cannot postdate"):
        build_scenario_review_period_evidence_bindings(
            intent=intent,
            schedule_policy=policy,
            path_evidence=make_path_study(generated_at=NOW),
        )
    with pytest.raises(ValueError, match="expired"):
        build_scenario_review_period_evidence_bindings(
            intent=intent,
            schedule_policy=policy,
            path_evidence=make_path_study(
                generated_at=NOW - timedelta(hours=3),
                valid_until=intent.created_at,
            ),
        )


def test_period_bindings_require_contiguous_exact_conditional_and_transition_ids() -> None:
    with pytest.raises(ValueError, match="conditional probability identities"):
        ScenarioReviewPeriodEvidenceBinding.create(
            period_index=1,
            conditional_probability_identity_hashes=(),
            transition_probability_identity_hashes=("1" * 64,),
        )
    with pytest.raises(ValueError, match="contiguous"):
        ScenarioReviewReminder.create(
            intent=make_review_intent(),
            schedule_policy=_schedule_policy(),
            path_evidence_hash="d" * 64,
            period_bindings=(
                ScenarioReviewPeriodEvidenceBinding.create(
                    period_index=2,
                    conditional_probability_identity_hashes=("e" * 64,),
                    transition_probability_identity_hashes=("1" * 64,),
                ),
            ),
        )


def test_reconcile_appends_deterministic_root_due_escalations_and_expiry() -> None:
    reminder = _reminder()
    after_expiry = reminder.expires_at + timedelta(hours=3)

    first = reconcile_scenario_review_reminder(
        reminder=reminder,
        events=(),
        as_of=after_expiry,
        recorded_at=after_expiry,
    )
    replay = reconcile_scenario_review_reminder(
        reminder=reminder,
        events=first,
        as_of=after_expiry + timedelta(days=1),
        recorded_at=after_expiry + timedelta(days=1),
    )

    assert tuple(item.event_type for item in first) == (
        ReminderEventType.SCHEDULED,
        ReminderEventType.DUE,
        ReminderEventType.ESCALATED,
        ReminderEventType.ESCALATED,
        ReminderEventType.EXPIRED,
    )
    assert tuple(item.escalation_level for item in first) == (0, 0, 1, 2, 2)
    assert first[0].previous_event_hash is None
    assert all(
        current.previous_event_hash == previous.content_hash
        for previous, current in zip(first, first[1:], strict=False)
    )
    assert replay == first
    assert derive_scenario_review_reminder_state(reminder, first) is ReminderLifecycleState.EXPIRED
    assert is_scenario_review_reminder_due(reminder, first, reminder.expires_at) is False


def test_exact_due_escalation_and_expiry_boundaries_are_half_open() -> None:
    reminder = _reminder()
    first_escalation = reminder.due_at + timedelta(days=1)
    second_escalation = reminder.due_at + timedelta(days=2)
    cases = (
        (reminder.due_at - timedelta(microseconds=1), (ReminderEventType.SCHEDULED,)),
        (
            reminder.due_at,
            (ReminderEventType.SCHEDULED, ReminderEventType.DUE),
        ),
        (
            first_escalation - timedelta(microseconds=1),
            (ReminderEventType.SCHEDULED, ReminderEventType.DUE),
        ),
        (
            first_escalation,
            (
                ReminderEventType.SCHEDULED,
                ReminderEventType.DUE,
                ReminderEventType.ESCALATED,
            ),
        ),
        (
            second_escalation - timedelta(microseconds=1),
            (
                ReminderEventType.SCHEDULED,
                ReminderEventType.DUE,
                ReminderEventType.ESCALATED,
            ),
        ),
        (
            second_escalation,
            (
                ReminderEventType.SCHEDULED,
                ReminderEventType.DUE,
                ReminderEventType.ESCALATED,
                ReminderEventType.ESCALATED,
            ),
        ),
        (
            reminder.expires_at - timedelta(microseconds=1),
            (
                ReminderEventType.SCHEDULED,
                ReminderEventType.DUE,
                ReminderEventType.ESCALATED,
                ReminderEventType.ESCALATED,
            ),
        ),
        (
            reminder.expires_at,
            (
                ReminderEventType.SCHEDULED,
                ReminderEventType.DUE,
                ReminderEventType.ESCALATED,
                ReminderEventType.ESCALATED,
                ReminderEventType.EXPIRED,
            ),
        ),
    )
    for as_of, expected in cases:
        events = reconcile_scenario_review_reminder(
            reminder=reminder,
            events=(),
            as_of=as_of,
            recorded_at=as_of,
        )
        assert tuple(item.event_type for item in events) == expected


def _forge_event(
    source: ScenarioReviewReminderEvent,
    *,
    escalation_level: int | None = None,
    actor_evidence_hash: str | None = None,
    reason_code: str | None = None,
    previous_event_hash: str | None = None,
) -> ScenarioReviewReminderEvent:
    level = source.escalation_level if escalation_level is None else escalation_level
    actor = actor_evidence_hash or source.actor_evidence_hash
    reason = reason_code or source.reason_code
    previous = source.previous_event_hash if previous_event_hash is None else previous_event_hash
    occurred = source.occurred_at.astimezone(UTC).isoformat()
    event_id = hash_components(
        source.event_version,
        source.reminder_id,
        source.event_type.value,
        str(level),
        occurred,
        source.idempotency_key,
    )
    content_hash = hash_components(
        source.event_version,
        event_id,
        source.reminder_id,
        source.event_type.value,
        str(source.sequence),
        str(level),
        occurred,
        actor,
        reason,
        source.idempotency_key,
        previous or "",
        "internal_review",
        "True",
        "False",
        "False",
        "True",
        "True",
    )
    return ScenarioReviewReminderEvent(
        event_version=source.event_version,
        event_id=event_id,
        reminder_id=source.reminder_id,
        event_type=source.event_type,
        sequence=source.sequence,
        escalation_level=level,
        occurred_at=source.occurred_at,
        recorded_at=source.recorded_at,
        actor_evidence_hash=actor,
        reason_code=reason,
        idempotency_key=source.idempotency_key,
        previous_event_hash=previous,
        delivery_scope="internal_review",
        must_not_execute=True,
        external_dispatch_requested=False,
        auto_approval_requested=False,
        research_only=True,
        must_not_use_for_decision=True,
        content_hash=content_hash,
        record_hash=hash_components(
            content_hash,
            source.recorded_at.astimezone(UTC).isoformat(),
        ),
    )


def test_self_consistent_forged_system_events_and_missing_root_are_rejected() -> None:
    reminder = _reminder()
    root, due = reconcile_scenario_review_reminder(
        reminder=reminder,
        events=(),
        as_of=reminder.due_at,
        recorded_at=reminder.due_at,
    )
    forged = (
        _forge_event(due, escalation_level=1),
        _forge_event(due, actor_evidence_hash="0" * 64),
        _forge_event(due, reason_code="forged.reason"),
        _forge_event(due, previous_event_hash="0" * 64),
    )
    for event in forged:
        with pytest.raises(ValueError):
            derive_scenario_review_reminder_state(reminder, (root, event))
    with pytest.raises(ValueError, match="event root"):
        derive_scenario_review_reminder_state(reminder, (due,))


def test_acknowledgement_is_human_evidence_only_and_closes_lifecycle() -> None:
    reminder = _reminder()
    due_events = reconcile_scenario_review_reminder(
        reminder=reminder,
        events=(),
        as_of=reminder.due_at,
        recorded_at=reminder.due_at,
    )
    acknowledged = acknowledge_scenario_review_reminder(
        reminder=reminder,
        events=due_events,
        acknowledged_at=reminder.due_at + timedelta(hours=1),
        recorded_at=reminder.due_at + timedelta(hours=1),
        actor_evidence_hash="9" * 64,
        reason_code="human_review.acknowledged",
        idempotency_key="ack-request-1",
    )

    assert acknowledged.event_type is ReminderEventType.ACKNOWLEDGED
    assert acknowledged.actor_evidence_hash == "9" * 64
    assert acknowledged.external_dispatch_requested is False
    assert acknowledged.auto_approval_requested is False
    history = (*due_events, acknowledged)
    assert (
        derive_scenario_review_reminder_state(reminder, history)
        is ReminderLifecycleState.ACKNOWLEDGED
    )
    assert (
        is_scenario_review_reminder_due(
            reminder,
            history,
            reminder.due_at + timedelta(days=1),
        )
        is False
    )
    with pytest.raises(ReminderLifecycleBlocked) as exc_info:
        acknowledge_scenario_review_reminder(
            reminder=reminder,
            events=history,
            acknowledged_at=reminder.due_at + timedelta(hours=2),
            recorded_at=reminder.due_at + timedelta(hours=2),
            actor_evidence_hash="9" * 64,
            reason_code="human_review.acknowledged",
            idempotency_key="ack-request-2",
        )
    assert exc_info.value.reason_code == "scenario_review_reminder.lifecycle.terminal"


def test_acknowledge_before_due_and_at_expiry_fails_closed() -> None:
    reminder = _reminder()
    root = reconcile_scenario_review_reminder(
        reminder=reminder,
        events=(),
        as_of=reminder.created_at,
        recorded_at=reminder.created_at,
    )
    for at, expected in (
        (reminder.due_at - timedelta(microseconds=1), "not_due"),
        (reminder.expires_at, "expired"),
    ):
        with pytest.raises(ReminderLifecycleBlocked) as exc_info:
            acknowledge_scenario_review_reminder(
                reminder=reminder,
                events=root,
                acknowledged_at=at,
                recorded_at=at,
                actor_evidence_hash="9" * 64,
                reason_code="human_review.acknowledged",
                idempotency_key=f"ack-{expected}",
            )
        assert exc_info.value.reason_code.endswith(expected)


def test_schedule_rejects_tampered_policy_and_noncanonical_period_ids() -> None:
    intent = make_review_intent()
    with pytest.raises(ValueError, match="policy hash"):
        ScenarioReviewReminder.create(
            intent=intent,
            schedule_policy=ScenarioReviewReminderSchedulePolicy.create(
                schedule_version="scenario-review-schedule.v1",
                probability_policy_version="scenario-calibration-policy.v1",
                probability_policy_hash="0" * 64,
                expiry_delay=timedelta(days=5),
                escalation_delay=timedelta(days=1),
                maximum_escalation_level=2,
                path_horizon_periods=2,
                owner_evidence_hash="b" * 64,
                escalation_policy_version="scenario-escalation.v1",
                escalation_policy_hash="c" * 64,
            ),
            path_evidence_hash="d" * 64,
            period_bindings=(
                ScenarioReviewPeriodEvidenceBinding.create(
                    period_index=1,
                    conditional_probability_identity_hashes=("e" * 64,),
                    transition_probability_identity_hashes=("1" * 64,),
                ),
            ),
        )

    with pytest.raises(ValueError, match="canonical"):
        ScenarioReviewPeriodEvidenceBinding(
            period_index=1,
            conditional_probability_identity_hashes=("f" * 64, "e" * 64),
            transition_probability_identity_hashes=("1" * 64,),
            content_hash="0" * 64,
        )


def test_reconcile_is_timezone_invariant_and_recorded_at_does_not_shift_schedule() -> None:
    reminder = _reminder()
    as_of_utc = reminder.due_at + timedelta(days=1)
    as_of_plus_eight = as_of_utc.astimezone(timezone(timedelta(hours=8)))

    utc_events = reconcile_scenario_review_reminder(
        reminder=reminder,
        events=(),
        as_of=as_of_utc,
        recorded_at=as_of_utc,
    )
    plus_eight_events = reconcile_scenario_review_reminder(
        reminder=reminder,
        events=(),
        as_of=as_of_plus_eight,
        recorded_at=as_of_utc + timedelta(hours=2),
    )

    assert tuple(item.event_id for item in utc_events) == tuple(
        item.event_id for item in plus_eight_events
    )
    assert tuple(item.occurred_at for item in utc_events) == tuple(
        item.occurred_at for item in plus_eight_events
    )
    assert utc_events[-1].recorded_at != plus_eight_events[-1].recorded_at
    assert datetime(2026, 8, 5, tzinfo=UTC).utcoffset() == timedelta(0)
