"""Reachable fail-closed boundary coverage for R7 reminders and R2 promotion."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from apps.data_center.domain.market_structure import (
    MarketStructureGovernanceArtifactKind,
    aggregate_market_structure,
    build_market_structure_evidence,
)
from apps.research.domain.r2_market_structure_promotion import (
    R2MarketStructureDecisionAuthorization,
    R2MarketStructureEvidenceSeal,
    R2MarketStructureLifecycleAction,
    R2MarketStructureLifecycleEventType,
    R2MarketStructurePromotionDecisionOutcome,
    R2MarketStructurePromotionPolicy,
    R2MarketStructurePromotionScope,
    create_r2_market_structure_lifecycle_event,
    create_r2_market_structure_promotion_decision,
    derive_r2_market_structure_active_stack,
)
from apps.research.domain.scenario_probability_contracts import (
    ForecastLedgerOutcomeObservation,
    ScenarioInvalidationEvidence,
)
from apps.research.domain.scenario_research_hashing import hash_components
from apps.research.domain.scenario_review_intent import build_review_reminder_intent
from apps.research.domain.scenario_review_reminders import (
    ReminderEventType,
    ScenarioReviewPeriodEvidenceBinding,
    ScenarioReviewReminderEvent,
    ScenarioReviewReminderSchedulePolicy,
    acknowledge_scenario_review_reminder,
    build_scenario_review_period_evidence_bindings,
    derive_scenario_review_reminder_state,
    reconcile_scenario_review_reminder,
)
from apps.signal.domain.forecast_scenario_evidence import ScenarioForecastBinding
from tests.unit.data_center.test_market_structure import (
    AS_OF,
    _actor,
    _calendar,
    _complete_observations,
    _coverage_for,
    _publication_attestation,
    _request,
    _series,
)
from tests.unit.research.r2_market_structure_promotion_factories import HASH as R2_HASH
from tests.unit.research.r2_market_structure_promotion_factories import (
    make_r2_decision,
    make_r2_evidence,
    make_r2_lifecycle_authorization,
    make_r2_policy,
)
from tests.unit.research.scenario_review_reminder_factories import (
    NOW,
    make_observation,
    make_path_study,
    make_policy,
    make_review_intent,
)
from tests.unit.research.test_scenario_review_reminders import _reminder


def _other_schedule_policy() -> ScenarioReviewReminderSchedulePolicy:
    """Build a valid schedule whose policy identity differs from the intent."""

    return ScenarioReviewReminderSchedulePolicy.create(
        schedule_version="scenario-review-schedule.other.v1",
        probability_policy_version="other-probability-policy.v1",
        probability_policy_hash="a" * 64,
        expiry_delay=timedelta(days=5),
        escalation_delay=timedelta(days=1),
        maximum_escalation_level=2,
        path_horizon_periods=2,
        owner_evidence_hash="b" * 64,
        escalation_policy_version="scenario-escalation.other.v1",
        escalation_policy_hash="c" * 64,
    )


def _variant_event(
    source: ScenarioReviewReminderEvent,
    *,
    sequence: int | None = None,
    event_type: ReminderEventType | None = None,
    escalation_level: int | None = None,
    occurred_at: datetime | None = None,
    recorded_at: datetime | None = None,
    previous_event_hash: str | None | object = ...,
    actor_evidence_hash: str | None = None,
    reason_code: str | None = None,
    idempotency_key: str | None = None,
    event_id: str | None = None,
) -> ScenarioReviewReminderEvent:
    """Rebuild one valid event header after changing its tested chain field."""

    event_version = source.event_version
    reminder_id = source.reminder_id
    chosen_type = source.event_type if event_type is None else event_type
    chosen_level = source.escalation_level if escalation_level is None else escalation_level
    chosen_occurred_at = source.occurred_at if occurred_at is None else occurred_at
    chosen_recorded_at = source.recorded_at if recorded_at is None else recorded_at
    chosen_actor = (
        source.actor_evidence_hash if actor_evidence_hash is None else actor_evidence_hash
    )
    chosen_reason = source.reason_code if reason_code is None else reason_code
    chosen_idempotency = source.idempotency_key if idempotency_key is None else idempotency_key
    chosen_previous = (
        source.previous_event_hash if previous_event_hash is ... else previous_event_hash
    )
    chosen_sequence = source.sequence if sequence is None else sequence
    chosen_event_id = (
        hash_components(
            event_version,
            reminder_id,
            chosen_type.value,
            str(chosen_level),
            chosen_occurred_at.astimezone(UTC).isoformat(),
            chosen_idempotency,
        )
        if event_id is None
        else event_id
    )
    content_hash = hash_components(
        event_version,
        chosen_event_id,
        reminder_id,
        chosen_type.value,
        str(chosen_sequence),
        str(chosen_level),
        chosen_occurred_at.astimezone(UTC).isoformat(),
        chosen_actor,
        chosen_reason,
        chosen_idempotency,
        chosen_previous or "",
        "internal_review",
        "True",
        "False",
        "False",
        "True",
        "True",
    )
    return ScenarioReviewReminderEvent(
        event_version=event_version,
        event_id=chosen_event_id,
        reminder_id=reminder_id,
        event_type=chosen_type,
        sequence=chosen_sequence,
        escalation_level=chosen_level,
        occurred_at=chosen_occurred_at,
        recorded_at=chosen_recorded_at,
        actor_evidence_hash=chosen_actor,
        reason_code=chosen_reason,
        idempotency_key=chosen_idempotency,
        previous_event_hash=chosen_previous,
        delivery_scope=source.delivery_scope,
        must_not_execute=source.must_not_execute,
        external_dispatch_requested=source.external_dispatch_requested,
        auto_approval_requested=source.auto_approval_requested,
        research_only=source.research_only,
        must_not_use_for_decision=source.must_not_use_for_decision,
        content_hash=content_hash,
        record_hash=hash_components(
            content_hash,
            chosen_recorded_at.astimezone(UTC).isoformat(),
        ),
    )


def _foreign_revision_intent() -> object:
    """Build a valid intent whose revision is outside the path-study scope."""

    foreign_revision = UUID("00000000-0000-0000-0000-000000000003")
    original = make_observation()
    assert original.invalidation is not None
    invalidation = ScenarioInvalidationEvidence.create(
        evidence_version=original.invalidation.evidence_version,
        scenario_revision_id=foreign_revision,
        scenario_set_revision_id=original.invalidation.scenario_set_revision_id,
        invalidated_at=original.invalidation.invalidated_at,
        invalidation_rule_version=original.invalidation.invalidation_rule_version,
        pit_manifest_id=original.invalidation.pit_manifest_id,
        evidence_refs=original.invalidation.evidence_refs,
    )
    binding = ScenarioForecastBinding.from_values(
        scenario_revision_id=foreign_revision,
        scenario_set_revision_id=original.binding.scenario_set_revision_id,
        subjective_probability=original.binding.subjective_probability,
        subjective_probability_source_version=(
            original.binding.subjective_probability_source_version
        ),
    )
    foreign_observation = ForecastLedgerOutcomeObservation.create(
        observation_version=original.observation_version,
        entry_id=original.entry_id,
        forecast_group_id=original.forecast_group_id,
        binding=binding,
        pit_manifest_id=original.pit_manifest_id,
        pit_manifest_version=original.pit_manifest_version,
        pit_manifest_hash=original.pit_manifest_hash,
        censoring_rule_version=original.censoring_rule_version,
        published_at=original.published_at,
        horizon_end=original.horizon_end,
        scenario_realized=original.scenario_realized,
        outcome_recorded_at=original.outcome_recorded_at,
        outcome_evidence_valid_until=original.outcome_evidence_valid_until,
        invalidation=invalidation,
    )
    return build_review_reminder_intent(
        observation=foreign_observation,
        policy=make_policy(),
        evaluated_at=NOW,
    )


def test_schedule_policy_rejects_mismatched_horizon_and_unsafe_controls() -> None:
    with pytest.raises(ValueError, match="path horizon"):
        ScenarioReviewReminderSchedulePolicy.from_probability_policy(
            probability_policy=make_policy(),
            schedule_version="scenario-review-schedule.v1",
            expiry_delay=timedelta(days=5),
            escalation_delay=timedelta(days=1),
            maximum_escalation_level=2,
            path_horizon_periods=3,
            owner_evidence_hash="b" * 64,
            escalation_policy_version="scenario-escalation.v1",
            escalation_policy_hash="c" * 64,
        )

    cases = (
        ("expiry_delay", timedelta(0), "expiry_delay"),
        ("escalation_delay", timedelta(0), "escalation_delay"),
        ("maximum_escalation_level", 0, "maximum_escalation_level"),
        ("path_horizon_periods", 0, "path_horizon_periods"),
    )
    for field_name, value, message in cases:
        kwargs = {
            "schedule_version": "scenario-review-schedule.v1",
            "probability_policy_version": "scenario-calibration-policy.v1",
            "probability_policy_hash": "a" * 64,
            "expiry_delay": timedelta(days=5),
            "escalation_delay": timedelta(days=1),
            "maximum_escalation_level": 2,
            "path_horizon_periods": 2,
            "owner_evidence_hash": "b" * 64,
            "escalation_policy_version": "scenario-escalation.v1",
            "escalation_policy_hash": "c" * 64,
        }
        kwargs[field_name] = value
        with pytest.raises(ValueError, match=message):
            ScenarioReviewReminderSchedulePolicy.create(**kwargs)


def test_schedule_and_period_binding_hashes_are_fail_closed() -> None:
    with pytest.raises(ValueError, match="content_hash mismatch"):
        replace(_other_schedule_policy(), content_hash="0" * 64)

    binding = ScenarioReviewPeriodEvidenceBinding.create(
        period_index=1,
        conditional_probability_identity_hashes=("a" * 64,),
        transition_probability_identity_hashes=("b" * 64,),
    )
    with pytest.raises(ValueError, match="period_index"):
        ScenarioReviewPeriodEvidenceBinding.create(
            period_index=0,
            conditional_probability_identity_hashes=("a" * 64,),
            transition_probability_identity_hashes=("b" * 64,),
        )
    with pytest.raises(ValueError, match="transition probability identities"):
        ScenarioReviewPeriodEvidenceBinding.create(
            period_index=1,
            conditional_probability_identity_hashes=("a" * 64,),
            transition_probability_identity_hashes=(),
        )
    with pytest.raises(ValueError, match="content_hash mismatch"):
        replace(binding, content_hash="0" * 64)


def test_reminder_exact_fields_and_safety_flags_cannot_be_substituted() -> None:
    reminder = _reminder()
    cases = (
        ("created_at", reminder.created_at + timedelta(microseconds=1), "exact review intent"),
        ("expires_at", reminder.expires_at + timedelta(microseconds=1), "expiry"),
        ("delivery_scope", "external", "delivery_scope"),
        ("must_not_execute", False, "safety boundary"),
        ("reminder_id", "0" * 64, "reminder_id"),
        ("content_hash", "0" * 64, "content_hash"),
    )
    for field_name, value, message in cases:
        with pytest.raises(ValueError, match=message):
            replace(reminder, **{field_name: value})
    with pytest.raises(ValueError, match="policy version"):
        replace(reminder, schedule_policy=_other_schedule_policy())


def test_path_binding_rejects_foreign_revision_and_schedule_horizon() -> None:
    with pytest.raises(ValueError, match="scenario revision"):
        build_scenario_review_period_evidence_bindings(
            intent=_foreign_revision_intent(),
            schedule_policy=ScenarioReviewReminderSchedulePolicy.create(
                schedule_version="scenario-review-schedule.v1",
                probability_policy_version="scenario-calibration-policy.v1",
                probability_policy_hash="a" * 64,
                expiry_delay=timedelta(days=5),
                escalation_delay=timedelta(days=1),
                maximum_escalation_level=2,
                path_horizon_periods=2,
                owner_evidence_hash="b" * 64,
                escalation_policy_version="scenario-escalation.v1",
                escalation_policy_hash="c" * 64,
            ),
            path_evidence=make_path_study(),
        )

    path_policy = ScenarioReviewReminderSchedulePolicy.create(
        schedule_version="scenario-review-schedule.v1",
        probability_policy_version="scenario-calibration-policy.v1",
        probability_policy_hash="a" * 64,
        expiry_delay=timedelta(days=5),
        escalation_delay=timedelta(days=1),
        maximum_escalation_level=2,
        path_horizon_periods=3,
        owner_evidence_hash="b" * 64,
        escalation_policy_version="scenario-escalation.v1",
        escalation_policy_hash="c" * 64,
    )
    with pytest.raises(ValueError, match="horizon"):
        build_scenario_review_period_evidence_bindings(
            intent=make_review_intent(),
            schedule_policy=path_policy,
            path_evidence=make_path_study(),
        )


def test_reconcile_rejects_naive_or_pre_creation_clock_and_continues_open_history() -> None:
    reminder = _reminder()
    with pytest.raises(ValueError, match="timezone-aware"):
        reconcile_scenario_review_reminder(
            reminder=reminder,
            events=(),
            as_of=reminder.created_at.replace(tzinfo=None),
            recorded_at=reminder.created_at,
        )
    with pytest.raises(ValueError, match="precede"):
        reconcile_scenario_review_reminder(
            reminder=reminder,
            events=(),
            as_of=reminder.created_at - timedelta(microseconds=1),
            recorded_at=reminder.created_at,
        )
    scheduled = reconcile_scenario_review_reminder(
        reminder=reminder,
        events=(),
        as_of=reminder.created_at,
        recorded_at=reminder.created_at,
    )
    continued = reconcile_scenario_review_reminder(
        reminder=reminder,
        events=scheduled,
        as_of=reminder.due_at,
        recorded_at=reminder.due_at,
    )
    assert tuple(event.event_type for event in continued) == (
        ReminderEventType.SCHEDULED,
        ReminderEventType.DUE,
    )


def test_reminder_event_headers_and_chain_fail_closed() -> None:
    reminder = _reminder()
    root, due = reconcile_scenario_review_reminder(
        reminder=reminder,
        events=(),
        as_of=reminder.due_at,
        recorded_at=reminder.due_at,
    )
    cases = (
        (lambda: replace(due, sequence=0), "sequence"),
        (lambda: replace(due, escalation_level=-1), "negative"),
        (
            lambda: replace(
                due,
                recorded_at=due.occurred_at - timedelta(microseconds=1),
            ),
            "precede",
        ),
        (lambda: replace(due, delivery_scope="external"), "delivery_scope"),
        (lambda: replace(due, must_not_execute=False), "safety boundary"),
        (lambda: replace(due, content_hash="0" * 64), "content_hash"),
        (lambda: replace(due, record_hash="0" * 64), "record_hash"),
        (lambda: _variant_event(due, sequence=3), "identity or sequence"),
        (lambda: _variant_event(due, event_id="0" * 64), "event_id"),
        (
            lambda: _variant_event(
                due,
                event_type=ReminderEventType.SCHEDULED,
                sequence=1,
                previous_event_hash=None,
                occurred_at=due.occurred_at,
            ),
            "root event",
        ),
        (
            lambda: _variant_event(
                due,
                occurred_at=reminder.created_at - timedelta(microseconds=1),
                recorded_at=reminder.created_at - timedelta(microseconds=1),
                previous_event_hash=root.content_hash,
            ),
            "chronological",
        ),
    )
    for make_event, message in cases:
        with pytest.raises(ValueError, match=message):
            event = make_event()
            history = (event,) if message == "root event" else (root, event)
            derive_scenario_review_reminder_state(reminder, history)


def test_reminder_chain_rejects_terminal_transition_and_wrong_event_order() -> None:
    reminder = _reminder()
    root, due = reconcile_scenario_review_reminder(
        reminder=reminder,
        events=(),
        as_of=reminder.due_at,
        recorded_at=reminder.due_at,
    )
    acknowledged = acknowledge_scenario_review_reminder(
        reminder=reminder,
        events=(root, due),
        acknowledged_at=reminder.due_at + timedelta(hours=1),
        recorded_at=reminder.due_at + timedelta(hours=1),
        actor_evidence_hash="9" * 64,
        reason_code="human_review.acknowledged",
        idempotency_key="ack-boundary",
    )
    with pytest.raises(ValueError, match="terminal state"):
        derive_scenario_review_reminder_state(
            reminder,
            (
                root,
                due,
                acknowledged,
                _variant_event(
                    acknowledged,
                    sequence=4,
                    occurred_at=acknowledged.occurred_at + timedelta(microseconds=1),
                    recorded_at=acknowledged.recorded_at + timedelta(microseconds=1),
                    previous_event_hash=acknowledged.content_hash,
                ),
            ),
        )

    with pytest.raises(ValueError, match="scheduled event"):
        derive_scenario_review_reminder_state(
            reminder,
            (
                _variant_event(
                    root,
                    sequence=1,
                    event_type=ReminderEventType.SCHEDULED,
                    previous_event_hash=None,
                ),
                _variant_event(
                    root,
                    sequence=2,
                    event_type=ReminderEventType.SCHEDULED,
                    occurred_at=root.occurred_at + timedelta(microseconds=1),
                    recorded_at=root.recorded_at + timedelta(microseconds=1),
                    previous_event_hash=root.content_hash,
                ),
            ),
        )


def test_reminder_chain_rejects_invalid_due_escalation_ack_and_expiry_transitions() -> None:
    reminder = _reminder()
    root, due = reconcile_scenario_review_reminder(
        reminder=reminder,
        events=(),
        as_of=reminder.due_at,
        recorded_at=reminder.due_at,
    )
    escalation_hash = reminder.schedule_policy.escalation_policy_hash
    bad_escalation_without_due = _variant_event(
        root,
        sequence=2,
        event_type=ReminderEventType.ESCALATED,
        escalation_level=1,
        occurred_at=reminder.due_at + reminder.schedule_policy.escalation_delay,
        recorded_at=reminder.due_at + reminder.schedule_policy.escalation_delay,
        actor_evidence_hash=escalation_hash,
        reason_code="scenario_review_reminder.escalated",
        idempotency_key=(
            f"{reminder.reminder_id}:escalated:1:"
            f"{(reminder.due_at + reminder.schedule_policy.escalation_delay).isoformat()}"
        ),
        previous_event_hash=root.content_hash,
    )
    with pytest.raises(ValueError, match="escalation requires"):
        derive_scenario_review_reminder_state(reminder, (root, bad_escalation_without_due))

    bad_level = _variant_event(
        due,
        sequence=3,
        event_type=ReminderEventType.ESCALATED,
        escalation_level=2,
        occurred_at=reminder.due_at + 2 * reminder.schedule_policy.escalation_delay,
        recorded_at=reminder.due_at + 2 * reminder.schedule_policy.escalation_delay,
        actor_evidence_hash=escalation_hash,
        reason_code="scenario_review_reminder.escalated",
        idempotency_key=(
            f"{reminder.reminder_id}:escalated:2:"
            f"{(reminder.due_at + 2 * reminder.schedule_policy.escalation_delay).isoformat()}"
        ),
        previous_event_hash=due.content_hash,
    )
    with pytest.raises(ValueError, match="contiguous"):
        derive_scenario_review_reminder_state(reminder, (root, due, bad_level))

    bad_time = _variant_event(
        due,
        sequence=3,
        event_type=ReminderEventType.ESCALATED,
        escalation_level=1,
        occurred_at=reminder.due_at
        + reminder.schedule_policy.escalation_delay
        + timedelta(microseconds=1),
        recorded_at=reminder.due_at
        + reminder.schedule_policy.escalation_delay
        + timedelta(microseconds=1),
        actor_evidence_hash=escalation_hash,
        reason_code="scenario_review_reminder.escalated",
        idempotency_key="bad-escalation-time",
        previous_event_hash=due.content_hash,
    )
    with pytest.raises(ValueError, match="occurrence"):
        derive_scenario_review_reminder_state(reminder, (root, due, bad_time))

    bad_ack_without_due = _variant_event(
        root,
        sequence=2,
        event_type=ReminderEventType.ACKNOWLEDGED,
        occurred_at=reminder.due_at,
        recorded_at=reminder.due_at,
        actor_evidence_hash="9" * 64,
        reason_code="human_review.acknowledged",
        idempotency_key="ack-without-due",
        previous_event_hash=root.content_hash,
    )
    with pytest.raises(ValueError, match="acknowledgement requires"):
        derive_scenario_review_reminder_state(reminder, (root, bad_ack_without_due))

    bad_ack_time = _variant_event(
        due,
        sequence=3,
        event_type=ReminderEventType.ACKNOWLEDGED,
        occurred_at=reminder.expires_at,
        recorded_at=reminder.expires_at,
        actor_evidence_hash="9" * 64,
        reason_code="human_review.acknowledged",
        idempotency_key="ack-at-expiry",
        previous_event_hash=due.content_hash,
    )
    with pytest.raises(ValueError, match="outside"):
        derive_scenario_review_reminder_state(reminder, (root, due, bad_ack_time))

    bad_expiry_without_due = _variant_event(
        root,
        sequence=2,
        event_type=ReminderEventType.EXPIRED,
        occurred_at=reminder.expires_at,
        recorded_at=reminder.expires_at,
        actor_evidence_hash=escalation_hash,
        reason_code="scenario_review_reminder.expired",
        idempotency_key=f"{reminder.reminder_id}:expired:{reminder.expires_at.isoformat()}",
        previous_event_hash=root.content_hash,
    )
    with pytest.raises(ValueError, match="expiry requires"):
        derive_scenario_review_reminder_state(reminder, (root, bad_expiry_without_due))

    bad_expiry_time = _variant_event(
        due,
        sequence=3,
        event_type=ReminderEventType.EXPIRED,
        occurred_at=reminder.expires_at - timedelta(microseconds=1),
        recorded_at=reminder.expires_at,
        actor_evidence_hash=escalation_hash,
        reason_code="scenario_review_reminder.expired",
        idempotency_key="bad-expiry-time",
        previous_event_hash=due.content_hash,
    )
    with pytest.raises(ValueError, match="exact expires_at"):
        derive_scenario_review_reminder_state(reminder, (root, due, bad_expiry_time))


def test_r2_scope_seal_and_policy_boundaries_are_fail_closed() -> None:
    evidence = make_r2_evidence()
    policy = make_r2_policy(evidence)
    seal = R2MarketStructureEvidenceSeal.from_evidence(evidence)
    with pytest.raises(ValueError, match="versions"):
        replace(policy.scope, group_revision=0)
    with pytest.raises(ValueError, match="identity or hash"):
        replace(policy.scope, scope_id="r2-ms-scope-" + "0" * 64)
    with pytest.raises(ValueError, match="version"):
        replace(seal, evidence_version=0)
    with pytest.raises(ValueError, match="Publication identities"):
        replace(seal, publication_ids=())
    with pytest.raises(ValueError, match="Publication datasets"):
        replace(seal, publication_datasets=tuple(reversed(seal.publication_datasets)))
    with pytest.raises(ValueError, match="clocks"):
        R2MarketStructurePromotionPolicy.create(
            policy_version="r2-promotion-policy.invalid.v1",
            scope=policy.scope,
            owner_approval_ref="research-owner://invalid",
            owner_approval_hash=R2_HASH,
            registered_at=NOW + timedelta(hours=2),
            active_from=NOW + timedelta(hours=1),
            valid_until=NOW + timedelta(days=1),
        )
    with pytest.raises(ValueError, match="Publication"):
        replace(policy, required_publication_datasets=("wrong-dataset",))
    with pytest.raises(ValueError, match="safety flags"):
        replace(policy, research_only=False)
    with pytest.raises(ValueError, match="identity or hash"):
        replace(policy, content_hash="0" * 64)


def test_r2_decision_authorization_and_decision_boundaries_are_fail_closed() -> None:
    evidence = make_r2_evidence()
    policy = make_r2_policy(evidence)
    decision, authorization = make_r2_decision(evidence, policy)
    seal = R2MarketStructureEvidenceSeal.from_evidence(evidence)
    with pytest.raises(ValueError, match="clocks"):
        R2MarketStructureDecisionAuthorization.create(
            authorization_version="r2-invalid-auth.v1",
            policy=policy,
            evidence=seal,
            issued_at=NOW + timedelta(hours=2),
            decided_at=NOW + timedelta(hours=1),
            decision_recorded_at=NOW + timedelta(hours=1),
            valid_until=NOW + timedelta(days=1),
            owner_receipt_hash=R2_HASH,
        )
    other_scope = R2MarketStructurePromotionScope.create(
        group_code="OTHER_GROUP",
        group_revision=1,
        method_version=evidence.method_version,
        policy_code=evidence.policy_code,
        policy_version=evidence.policy_version,
    )
    with pytest.raises(ValueError, match="semantic scopes"):
        replace(decision, evidence=replace(seal, scope=other_scope))
    with pytest.raises(ValueError, match="authorization was substituted"):
        replace(
            decision,
            authorization=replace(authorization, policy_content_hash="0" * 64),
        )
    with pytest.raises(ValueError, match="clocks were substituted"):
        replace(decision, decided_at=decision.decided_at + timedelta(minutes=1))
    with pytest.raises(ValueError, match="outcome was not derived"):
        replace(
            decision,
            outcome=R2MarketStructurePromotionDecisionOutcome.REJECTED,
        )
    with pytest.raises(ValueError, match="reasons were not derived"):
        replace(decision, reason_codes=("forged.reason",))
    with pytest.raises(ValueError, match="safety flags"):
        replace(decision, research_only=False)


def _r2_decision_pair() -> tuple[object, object, object, object]:
    """Build two real evidence seals and decisions sharing one valid policy."""

    first_evidence = make_r2_evidence()
    policy = make_r2_policy(first_evidence)
    first_seal = R2MarketStructureEvidenceSeal.from_evidence(first_evidence)
    second_evidence = _evidence_for_key("SECOND_EVIDENCE")
    second_seal = R2MarketStructureEvidenceSeal.from_evidence(second_evidence)
    decisions = []
    for seal in (first_seal, second_seal):
        decided_at = AS_OF + timedelta(hours=2)
        authorization = R2MarketStructureDecisionAuthorization.create(
            authorization_version=f"r2-decision-{seal.evidence_key}.v1",
            policy=policy,
            evidence=seal,
            issued_at=decided_at - timedelta(minutes=5),
            decided_at=decided_at,
            decision_recorded_at=decided_at + timedelta(minutes=5),
            valid_until=AS_OF + timedelta(days=20),
            owner_receipt_hash=R2_HASH,
        )
        decisions.append(
            create_r2_market_structure_promotion_decision(
                policy=policy,
                evidence=seal,
                authorization=authorization,
            )
        )
    return decisions[0], decisions[1], policy, first_seal


def _evidence_for_key(key: str) -> object:
    """Build the same complete market-structure evidence under another key."""

    first = _series("A")
    second = _series("B")
    observations = _complete_observations(first, second)
    request = replace(_request(), evidence_key=key)
    snapshot = aggregate_market_structure(
        request=request,
        period_calendar=_calendar(),
        definitions=(first, second),
        observations=observations,
        coverage=_coverage_for(observations),
    )
    actors = (_actor("A"), _actor("B"))
    return build_market_structure_evidence(
        request=request,
        snapshot=snapshot,
        period_calendar=_calendar(),
        actor_definitions=actors,
        series_definitions=(first, second),
        source_evidence=tuple(item.evidence for item in observations),
        governance_publications=(
            _publication_attestation(
                kind=MarketStructureGovernanceArtifactKind.PERIOD_CALENDAR,
                natural_key="calendar:TEST_MONTHLY_CALENDAR:v1",
                artifact_hash=_calendar().calendar_hash,
                observed_at=AS_OF,
                member_id="calendar-member",
            ),
            *(
                _publication_attestation(
                    kind=MarketStructureGovernanceArtifactKind.ACTOR,
                    natural_key=f"actor:TEST_TAXONOMY:v1:{actor.actor_code}",
                    artifact_hash=actor.definition_hash,
                    observed_at=actor.available_at,
                    member_id=f"actor-{actor.actor_code}",
                )
                for actor in actors
            ),
            *(
                _publication_attestation(
                    kind=MarketStructureGovernanceArtifactKind.SERIES,
                    natural_key=f"series:{series.series_code}:v1",
                    artifact_hash=series.definition_hash,
                    observed_at=series.available_at,
                    member_id=f"series-{series.actor_code}",
                )
                for series in (first, second)
            ),
        ),
    )


def test_r2_lifecycle_authorization_and_event_headers_reject_invalid_states() -> None:
    first, second, _policy, _seal = _r2_decision_pair()
    promote = create_r2_market_structure_lifecycle_event(
        history=(),
        decision=first,
        authorization=make_r2_lifecycle_authorization(first),
        rollback_target=None,
    )
    auth = make_r2_lifecycle_authorization(first)
    with pytest.raises(ValueError, match="target hash"):
        replace(auth, rollback_target_content_hash=R2_HASH)
    with pytest.raises(ValueError, match="target/action"):
        replace(auth, action=R2MarketStructureLifecycleAction.ROLLBACK)
    with pytest.raises(ValueError, match="clocks"):
        replace(auth, occurred_at=auth.issued_at - timedelta(minutes=1))
    with pytest.raises(ValueError, match="reasons"):
        replace(auth, reason_codes=())

    with pytest.raises(ValueError, match="sequence"):
        replace(promote, sequence=0)
    with pytest.raises(ValueError, match="root cannot"):
        replace(promote, previous_event_hash=R2_HASH)
    with pytest.raises(ValueError, match="non-root requires"):
        replace(promote, sequence=2, previous_event_hash="")
    with pytest.raises(ValueError, match="rollback target mismatch"):
        replace(
            promote,
            rollback_target_ref=first.reference,
            rollback_target_content_hash=first.content_hash,
        )
    with pytest.raises(ValueError, match="target hash"):
        replace(promote, rollback_target_content_hash=R2_HASH)
    with pytest.raises(ValueError, match="occurred_at exceeds"):
        replace(promote, occurred_at=promote.recorded_at + timedelta(minutes=1))
    with pytest.raises(ValueError, match="authorization/event mismatch"):
        replace(
            promote,
            authorization=replace(
                promote.authorization,
                action=R2MarketStructureLifecycleAction.RETIRE,
            ),
        )

    bad_scope = replace(
        make_r2_lifecycle_authorization(first),
        scope_id="r2-ms-other-scope",
        scope_content_hash=R2_HASH,
    )
    with pytest.raises(ValueError, match="authorization scope"):
        create_r2_market_structure_lifecycle_event(
            history=(),
            decision=first,
            authorization=bad_scope,
            rollback_target=None,
        )
    bad_ref = replace(
        make_r2_lifecycle_authorization(first),
        decision_ref=first.reference.__class__("other-decision", "v1"),
    )
    with pytest.raises(ValueError, match="another decision"):
        create_r2_market_structure_lifecycle_event(
            history=(),
            decision=first,
            authorization=bad_ref,
            rollback_target=None,
        )
    bad_hash = replace(
        make_r2_lifecycle_authorization(first),
        decision_content_hash=R2_HASH,
    )
    with pytest.raises(ValueError, match="decision hash"):
        create_r2_market_structure_lifecycle_event(
            history=(),
            decision=first,
            authorization=bad_hash,
            rollback_target=None,
        )
    rollback_auth = make_r2_lifecycle_authorization(
        second,
        action=R2MarketStructureLifecycleAction.ROLLBACK,
        rollback_target=first,
    )
    with pytest.raises(ValueError, match="target hash"):
        create_r2_market_structure_lifecycle_event(
            history=(promote,),
            decision=second,
            authorization=replace(rollback_auth, rollback_target_content_hash=R2_HASH),
            rollback_target=first,
        )


def test_r2_lifecycle_stack_rejects_duplicates_wrong_retire_and_bad_rollback() -> None:
    first, second, _policy, _seal = _r2_decision_pair()
    promote_first = create_r2_market_structure_lifecycle_event(
        history=(),
        decision=first,
        authorization=make_r2_lifecycle_authorization(first),
        rollback_target=None,
    )
    with pytest.raises(ValueError, match="already active"):
        create_r2_market_structure_lifecycle_event(
            history=(promote_first,),
            decision=first,
            authorization=make_r2_lifecycle_authorization(
                first,
                offset_hours=4,
            ),
            rollback_target=None,
        )

    with pytest.raises(ValueError, match="active top"):
        create_r2_market_structure_lifecycle_event(
            history=(promote_first,),
            decision=second,
            authorization=make_r2_lifecycle_authorization(
                second,
                action=R2MarketStructureLifecycleAction.RETIRE,
                offset_hours=4,
            ),
            rollback_target=None,
        )

    with pytest.raises(ValueError, match="stack"):
        create_r2_market_structure_lifecycle_event(
            history=(promote_first,),
            decision=first,
            authorization=make_r2_lifecycle_authorization(
                first,
                action=R2MarketStructureLifecycleAction.ROLLBACK,
                rollback_target=second,
                offset_hours=4,
            ),
            rollback_target=second,
        )

    promote_second = create_r2_market_structure_lifecycle_event(
        history=(promote_first,),
        decision=second,
        authorization=make_r2_lifecycle_authorization(second, offset_hours=4),
        rollback_target=None,
    )
    rollback = create_r2_market_structure_lifecycle_event(
        history=(promote_first, promote_second),
        decision=second,
        authorization=make_r2_lifecycle_authorization(
            second,
            action=R2MarketStructureLifecycleAction.ROLLBACK,
            rollback_target=first,
            offset_hours=5,
        ),
        rollback_target=first,
    )
    assert rollback.event_type is R2MarketStructureLifecycleEventType.ROLLED_BACK
    assert derive_r2_market_structure_active_stack((promote_first, promote_second, rollback)) == (
        first.reference,
    )
