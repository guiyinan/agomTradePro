"""Behavioral boundary tests for the R6 state-model Domain contracts."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from apps.research.domain.state_model_activation import (
    R6ActivationAction,
    R6ActivationScopeRef,
    create_r6_activation_event,
    derive_r6_activation_state,
    validate_r6_activation_approval,
    validate_r6_activation_authorization,
    validate_r6_activation_scope,
    validate_r6_monitoring_activation_evidence,
)
from apps.research.domain.state_model_monitoring import (
    R6MonitoringAssessment,
    R6MonitoringAssessmentStatus,
    R6MonitoringBlockerCode,
    R6MonitoringMetricKey,
    R6MonitoringMetricObservation,
    R6MonitoringObservation,
    R6MonitoringPeriodEntry,
    R6MonitoringPolicy,
    derive_r6_monitoring_period_id,
    evaluate_r6_monitoring,
)
from apps.research.domain.state_model_qualification_contracts import (
    advanced_state_pit_manifest_canonical_hash,
    advanced_state_threshold_hash,
    external_artifact_attestation_canonical_hash,
)
from tests.unit.research.state_model_monitoring_factories import NOW as MONITORING_NOW
from tests.unit.research.state_model_monitoring_factories import (
    QUALIFICATION_REF,
    active_qualification,
    observation,
    period_calendar,
    policy,
    thresholds,
)
from tests.unit.research.state_model_qualification_factories import (
    complete_derived_metric_bundle,
    complete_qualification_study,
    qualification_policy,
    study_preregistration,
)
from tests.unit.research.test_state_model_activation import HASH_C as ACTIVATION_HASH_C
from tests.unit.research.test_state_model_activation import NOW as ACTIVATION_NOW
from tests.unit.research.test_state_model_activation import (
    _approval,
    _authorization,
    _monitoring,
    _qualification_ref,
    _scope,
)


def test_activation_scope_and_shared_guards_reject_invalid_owner_payloads() -> None:
    """Scope and common owner guards reject malformed, unsafe, or stale payloads."""

    scope = _scope()

    with pytest.raises(ValueError, match="bounded non-blank token"):
        replace(scope, purpose="")
    with pytest.raises(ValueError, match="timezone-aware"):
        replace(
            _monitoring("naive", _qualification_ref("a")),
            evaluated_at=ACTIVATION_NOW.replace(tzinfo=None),
        )
    with pytest.raises(ValueError, match="unique reason codes"):
        replace(
            _authorization(
                suffix="duplicate-reasons",
                action=R6ActivationAction.ACTIVATE,
                subject=_approval("a"),
                sequence=1,
            ),
            reason_codes=("same", "same"),
        )
    with pytest.raises(ValueError, match="cannot authorize a production consumer"):
        replace(scope, research_only=False)

    tampered_scope = _scope()
    object.__setattr__(tampered_scope, "content_hash", ACTIVATION_HASH_C)
    with pytest.raises(ValueError, match="content hash mismatch"):
        validate_r6_activation_scope(tampered_scope)
    with pytest.raises(ValueError, match="invalid type"):
        validate_r6_activation_scope(object())

    tampered_approval = _approval("a")
    object.__setattr__(tampered_approval, "qualification_ref", object())
    with pytest.raises(ValueError, match="qualification_ref has an invalid type"):
        validate_r6_activation_approval(tampered_approval)


def test_activation_monitoring_and_approval_boundaries_remain_research_only() -> None:
    """Owner monitoring and approval projections preserve status, clocks, and seals."""

    monitoring = _monitoring("a", _qualification_ref("a"))
    with pytest.raises(ValueError, match="owner must be research"):
        replace(monitoring, owner="external")
    with pytest.raises(ValueError, match="status is invalid"):
        replace(monitoring, status="healthy")
    with pytest.raises(ValueError, match="clocks are invalid"):
        replace(monitoring, evaluated_at=monitoring.recorded_at + timedelta(seconds=1))
    with pytest.raises(ValueError, match="retirement-review status/flag differs"):
        replace(monitoring, retirement_review_required=True)
    with pytest.raises(ValueError, match="invalid type"):
        validate_r6_monitoring_activation_evidence(object())

    approval = _approval("a")
    with pytest.raises(ValueError, match="approval owner must be research"):
        replace(approval, owner="external")
    with pytest.raises(ValueError, match="label protocol differs"):
        replace(approval, required_label_protocol_version="labels.other")
    with pytest.raises(ValueError, match="maximum monitoring age"):
        replace(approval, maximum_monitoring_age_seconds=0)
    with pytest.raises(ValueError, match="clocks are invalid"):
        replace(approval, decided_at=approval.recorded_at + timedelta(seconds=1))

    invalid_ref = _approval("a")
    object.__setattr__(invalid_ref, "monitoring_ref", object())
    with pytest.raises(ValueError, match="monitoring_ref has an invalid type"):
        validate_r6_activation_approval(invalid_ref)

    invalid_outcome = _approval("a")
    object.__setattr__(invalid_outcome, "outcome", "approved")
    with pytest.raises(ValueError, match="approval outcome is invalid"):
        validate_r6_activation_approval(invalid_outcome)

    invalid_hash = _approval("a")
    object.__setattr__(invalid_hash, "content_hash", ACTIVATION_HASH_C)
    with pytest.raises(ValueError, match="content hash mismatch"):
        validate_r6_activation_approval(invalid_hash)
    with pytest.raises(ValueError, match="invalid type"):
        validate_r6_activation_approval(object())


def test_activation_authorization_and_event_nested_types_are_revalidated() -> None:
    """Manual commands and events reject substituted nested identities and clocks."""

    approval_a = _approval("a")
    approval_b = _approval("b")
    authorization = _authorization(
        suffix="nested",
        action=R6ActivationAction.ACTIVATE,
        subject=approval_a,
        sequence=1,
    )

    with pytest.raises(ValueError, match="authorization owner must be research"):
        replace(authorization, owner="external")
    invalid_scope_ref = _authorization(
        suffix="invalid-scope-ref",
        action=R6ActivationAction.ACTIVATE,
        subject=approval_a,
        sequence=1,
    )
    object.__setattr__(invalid_scope_ref, "scope_ref", object())
    with pytest.raises(ValueError, match="scope_ref has an invalid type"):
        validate_r6_activation_authorization(invalid_scope_ref)

    invalid_subject = _authorization(
        suffix="invalid-subject",
        action=R6ActivationAction.ACTIVATE,
        subject=approval_a,
        sequence=1,
    )
    object.__setattr__(invalid_subject, "subject", object())
    with pytest.raises(ValueError, match="subject has an invalid type"):
        validate_r6_activation_authorization(invalid_subject)

    invalid_target = _authorization(
        suffix="invalid-target",
        action=R6ActivationAction.ROLLBACK,
        subject=approval_b,
        rollback_target=approval_a,
        sequence=1,
    )
    object.__setattr__(invalid_target, "rollback_target", object())
    with pytest.raises(ValueError, match="rollback_target has an invalid type"):
        validate_r6_activation_authorization(invalid_target)
    with pytest.raises(ValueError, match="authorization action is invalid"):
        replace(authorization, action="activate")
    with pytest.raises(ValueError, match="rollback authorization has a target"):
        replace(authorization, rollback_target=approval_b.ref)
    with pytest.raises(ValueError, match="sequence is invalid"):
        replace(authorization, expected_sequence=0)
    with pytest.raises(ValueError, match="cannot claim a previous head"):
        replace(authorization, expected_previous_event_hash=ACTIVATION_HASH_C)
    with pytest.raises(ValueError, match="clocks are invalid"):
        replace(authorization, issued_at=authorization.recorded_at + timedelta(seconds=1))

    root = create_r6_activation_event(
        authorization=authorization,
        previous_events=(),
        applied_at=ACTIVATION_NOW,
    )
    event = root
    object.__setattr__(event, "action", "activate")
    with pytest.raises(ValueError, match="event action is invalid"):
        derive_r6_activation_state((event,), evaluated_at=ACTIVATION_NOW)

    event = create_r6_activation_event(
        authorization=authorization,
        previous_events=(),
        applied_at=ACTIVATION_NOW,
    )
    object.__setattr__(event, "scope_ref", object())
    with pytest.raises(ValueError, match="scope_ref has an invalid type"):
        derive_r6_activation_state((event,), evaluated_at=ACTIVATION_NOW)

    event = create_r6_activation_event(
        authorization=authorization,
        previous_events=(),
        applied_at=ACTIVATION_NOW,
    )
    object.__setattr__(event, "subject", object())
    with pytest.raises(ValueError, match="subject has an invalid type"):
        derive_r6_activation_state((event,), evaluated_at=ACTIVATION_NOW)

    invalid_event_target = create_r6_activation_event(
        authorization=authorization,
        previous_events=(),
        applied_at=ACTIVATION_NOW,
    )
    object.__setattr__(invalid_event_target, "rollback_target", object())
    with pytest.raises(ValueError, match="rollback_target has an invalid type"):
        derive_r6_activation_state((invalid_event_target,), evaluated_at=ACTIVATION_NOW)

    invalid_event_target = create_r6_activation_event(
        authorization=authorization,
        previous_events=(),
        applied_at=ACTIVATION_NOW,
    )
    object.__setattr__(invalid_event_target, "action", R6ActivationAction.ROLLBACK)
    with pytest.raises(ValueError, match="rollback event has a target"):
        derive_r6_activation_state((invalid_event_target,), evaluated_at=ACTIVATION_NOW)

    invalid_sequence = create_r6_activation_event(
        authorization=authorization,
        previous_events=(),
        applied_at=ACTIVATION_NOW,
    )
    object.__setattr__(invalid_sequence, "sequence", 0)
    with pytest.raises(ValueError, match="event sequence is invalid"):
        derive_r6_activation_state((invalid_sequence,), evaluated_at=ACTIVATION_NOW)

    invalid_clock = create_r6_activation_event(
        authorization=authorization,
        previous_events=(),
        applied_at=ACTIVATION_NOW,
    )
    object.__setattr__(
        invalid_clock, "recorded_at", invalid_clock.occurred_at - timedelta(seconds=1)
    )
    with pytest.raises(ValueError, match="precedes occurrence"):
        derive_r6_activation_state((invalid_clock,), evaluated_at=ACTIVATION_NOW)
    with pytest.raises(ValueError, match="invalid type"):
        validate_r6_activation_authorization(object())


def test_activation_create_rejects_inactive_stale_cross_scope_and_duplicate_transitions() -> None:
    """The append factory admits only a current authorization for the live stack head."""

    approval_a = _approval("a")
    approval_b = _approval("b")
    root_authorization = _authorization(
        suffix="root-for-errors",
        action=R6ActivationAction.ACTIVATE,
        subject=approval_a,
        sequence=1,
    )
    root = create_r6_activation_event(
        authorization=root_authorization,
        previous_events=(),
        applied_at=ACTIVATION_NOW,
    )

    inactive = _authorization(
        suffix="inactive",
        action=R6ActivationAction.ACTIVATE,
        subject=approval_b,
        sequence=1,
        recorded_at_override=ACTIVATION_NOW - timedelta(hours=2),
    )
    with pytest.raises(ValueError, match="inactive at application time"):
        create_r6_activation_event(
            authorization=inactive,
            previous_events=(),
            applied_at=ACTIVATION_NOW,
        )

    stale_sequence = _authorization(
        suffix="stale-sequence",
        action=R6ActivationAction.ACTIVATE,
        subject=approval_b,
        sequence=1,
        expected_previous_event_hash=None,
        issued_at_override=ACTIVATION_NOW + timedelta(minutes=1),
        recorded_at_override=ACTIVATION_NOW + timedelta(minutes=2),
    )
    with pytest.raises(ValueError, match="sequence is stale"):
        create_r6_activation_event(
            authorization=stale_sequence,
            previous_events=(root,),
            applied_at=ACTIVATION_NOW + timedelta(minutes=3),
        )

    cross_scope = _authorization(
        suffix="cross-scope",
        action=R6ActivationAction.ACTIVATE,
        subject=approval_b,
        sequence=2,
        expected_previous_event_hash=root.content_hash,
        issued_at_override=ACTIVATION_NOW + timedelta(minutes=1),
        recorded_at_override=ACTIVATION_NOW + timedelta(minutes=2),
    )
    object.__setattr__(
        cross_scope,
        "scope_ref",
        R6ActivationScopeRef("other-scope", "scope.v1", "d" * 64),
    )
    object.__setattr__(cross_scope, "content_hash", cross_scope.calculated_content_hash)
    with pytest.raises(ValueError, match="crosses scope streams"):
        create_r6_activation_event(
            authorization=cross_scope,
            previous_events=(root,),
            applied_at=ACTIVATION_NOW + timedelta(minutes=3),
        )

    duplicate = _authorization(
        suffix="duplicate-live",
        action=R6ActivationAction.ACTIVATE,
        subject=approval_a,
        sequence=2,
        expected_previous_event_hash=root.content_hash,
        issued_at_override=ACTIVATION_NOW + timedelta(minutes=1),
        recorded_at_override=ACTIVATION_NOW + timedelta(minutes=2),
    )
    with pytest.raises(ValueError, match="duplicate an approval"):
        create_r6_activation_event(
            authorization=duplicate,
            previous_events=(root,),
            applied_at=ACTIVATION_NOW + timedelta(minutes=3),
        )

    wrong_retire = _authorization(
        suffix="wrong-retire",
        action=R6ActivationAction.RETIRE,
        subject=approval_b,
        sequence=2,
        expected_previous_event_hash=root.content_hash,
        issued_at_override=ACTIVATION_NOW + timedelta(minutes=1),
        recorded_at_override=ACTIVATION_NOW + timedelta(minutes=2),
    )
    with pytest.raises(ValueError, match="target the active approval"):
        create_r6_activation_event(
            authorization=wrong_retire,
            previous_events=(root,),
            applied_at=ACTIVATION_NOW + timedelta(minutes=3),
        )

    rollback_without_stack = _authorization(
        suffix="rollback-without-stack",
        action=R6ActivationAction.ROLLBACK,
        subject=approval_a,
        rollback_target=approval_a,
        sequence=2,
        expected_previous_event_hash=root.content_hash,
        issued_at_override=ACTIVATION_NOW + timedelta(minutes=1),
        recorded_at_override=ACTIVATION_NOW + timedelta(minutes=2),
    )
    with pytest.raises(ValueError, match=r"stack\[-2\]"):
        create_r6_activation_event(
            authorization=rollback_without_stack,
            previous_events=(root,),
            applied_at=ACTIVATION_NOW + timedelta(minutes=3),
        )


def test_activation_replay_rejects_empty_forks_clock_reuse_and_illegal_stack_actions() -> None:
    """Replay rejects malformed prefixes before deriving a potentially unsafe active approval."""

    approval_a = _approval("a")
    approval_b = _approval("b")
    first = create_r6_activation_event(
        authorization=_authorization(
            suffix="replay-first",
            action=R6ActivationAction.ACTIVATE,
            subject=approval_a,
            sequence=1,
        ),
        previous_events=(),
        applied_at=ACTIVATION_NOW,
    )
    second = create_r6_activation_event(
        authorization=_authorization(
            suffix="replay-second",
            action=R6ActivationAction.ACTIVATE,
            subject=approval_b,
            sequence=2,
            expected_previous_event_hash=first.content_hash,
        ),
        previous_events=(first,),
        applied_at=ACTIVATION_NOW + timedelta(minutes=10),
    )

    with pytest.raises(ValueError, match="has no events"):
        derive_r6_activation_state((), evaluated_at=ACTIVATION_NOW)
    with pytest.raises(ValueError, match="event has an invalid type"):
        derive_r6_activation_state((first, object()), evaluated_at=ACTIVATION_NOW)

    other_scope = replace(first, scope_ref=R6ActivationScopeRef("other", "v1", "e" * 64))
    with pytest.raises(ValueError, match="cross scope streams"):
        derive_r6_activation_state((first, other_scope), evaluated_at=ACTIVATION_NOW)

    non_monotonic = replace(
        second,
        occurred_at=first.recorded_at,
        recorded_at=first.recorded_at + timedelta(minutes=1),
    )
    with pytest.raises(ValueError, match="not strictly monotonic"):
        derive_r6_activation_state(
            (first, non_monotonic), evaluated_at=ACTIVATION_NOW + timedelta(minutes=10)
        )

    broken_chain = replace(second, previous_event_hash=ACTIVATION_HASH_C)
    with pytest.raises(ValueError, match="hash chain is broken"):
        derive_r6_activation_state(
            (first, broken_chain), evaluated_at=ACTIVATION_NOW + timedelta(minutes=10)
        )

    reused_authorization = replace(
        second,
        authorization_id=first.authorization_id,
        authorization_version=first.authorization_version,
    )
    with pytest.raises(ValueError, match="reuses an authorization"):
        derive_r6_activation_state(
            (first, reused_authorization), evaluated_at=ACTIVATION_NOW + timedelta(minutes=10)
        )

    duplicate_approval = replace(
        second,
        subject=first.subject,
        action=R6ActivationAction.ACTIVATE,
        rollback_target=None,
    )
    with pytest.raises(ValueError, match="duplicates a live approval"):
        derive_r6_activation_state(
            (first, duplicate_approval), evaluated_at=ACTIVATION_NOW + timedelta(minutes=10)
        )

    illegal_retire = replace(
        second,
        action=R6ActivationAction.RETIRE,
        subject=approval_b.ref,
        rollback_target=None,
    )
    with pytest.raises(ValueError, match="does not target the active approval"):
        derive_r6_activation_state(
            (first, illegal_retire), evaluated_at=ACTIVATION_NOW + timedelta(minutes=10)
        )

    illegal_rollback = replace(
        first,
        action=R6ActivationAction.ROLLBACK,
        rollback_target=approval_a.ref,
        sequence=1,
        previous_event_hash=None,
        occurred_at=ACTIVATION_NOW + timedelta(minutes=1),
        recorded_at=ACTIVATION_NOW + timedelta(minutes=1),
    )
    with pytest.raises(ValueError, match=r"rollback does not target stack\[-2\]"):
        derive_r6_activation_state(
            (illegal_rollback,), evaluated_at=ACTIVATION_NOW + timedelta(minutes=2)
        )


def test_qualification_scalar_contracts_reject_invalid_domains_and_hash_inputs() -> None:
    """Qualification thresholds and regression evidence enforce their mathematical domains."""

    criterion = qualification_policy().metric_criteria[0]
    with pytest.raises(ValueError, match="metric direction is invalid"):
        replace(criterion, direction="higher")

    coefficient_criterion = qualification_policy().coefficient_criteria[0]
    with pytest.raises(ValueError, match="expected_sign is invalid"):
        replace(coefficient_criterion, expected_sign="positive")
    with pytest.raises(ValueError, match="between zero and one"):
        replace(coefficient_criterion, maximum_p_value=Decimal("1.1"))
    with pytest.raises(ValueError, match="cannot be negative"):
        replace(coefficient_criterion, minimum_absolute_estimate=Decimal("-0.1"))

    study = complete_qualification_study()
    evidence = study.policy_coefficients[0]
    with pytest.raises(ValueError, match="must be positive"):
        replace(evidence, standard_error=Decimal("0"))
    with pytest.raises(ValueError, match="confidence interval is reversed"):
        replace(evidence, confidence_interval_lower=Decimal("0.8"))
    with pytest.raises(ValueError, match="within its confidence interval"):
        replace(evidence, estimate=Decimal("0.9"))
    with pytest.raises(ValueError, match="p_value must be between zero and one"):
        replace(evidence, p_value=Decimal("1.1"))

    diagnostics = study.policy_diagnostics
    with pytest.raises(ValueError, match="adjusted_r_squared"):
        replace(diagnostics, adjusted_r_squared=Decimal("1.1"))
    with pytest.raises(ValueError, match="p-values must be between zero and one"):
        replace(diagnostics, residual_autocorrelation_p_value=Decimal("-0.1"))
    with pytest.raises(ValueError, match="condition_number must be positive"):
        replace(diagnostics, condition_number=Decimal("0"))

    with pytest.raises(TypeError, match="AdvancedStateModelAcceptanceThresholds"):
        advanced_state_threshold_hash(object())
    with pytest.raises(TypeError, match="StateModelPITManifestEvidence"):
        advanced_state_pit_manifest_canonical_hash(object())
    with pytest.raises(TypeError, match="ExternalArtifactAttestation"):
        external_artifact_attestation_canonical_hash(object())


def test_qualification_policy_and_preregistration_reject_invalid_windows_and_sets() -> None:
    """Versioned qualification policy and preregistration cannot be structurally substituted."""

    policy_value = qualification_policy()
    with pytest.raises(ValueError, match="valid_until must follow activated_at"):
        replace(policy_value, valid_until=policy_value.activated_at)
    with pytest.raises(ValueError, match="metric criteria must be non-empty"):
        replace(policy_value, metric_criteria=())
    with pytest.raises(ValueError, match="exactly seven comparative metrics"):
        replace(policy_value, metric_criteria=policy_value.metric_criteria[:-1])
    with pytest.raises(ValueError, match="coefficient criteria must be non-empty"):
        replace(policy_value, coefficient_criteria=())
    with pytest.raises(ValueError, match="coefficient criteria must be non-empty"):
        replace(
            policy_value,
            coefficient_criteria=(
                policy_value.coefficient_criteria[0],
                policy_value.coefficient_criteria[0],
            ),
        )
    with pytest.raises(ValueError, match="minimum_adjusted_r_squared"):
        replace(policy_value, minimum_adjusted_r_squared=Decimal("1.1"))
    with pytest.raises(ValueError, match="minimum diagnostic p-values"):
        replace(policy_value, minimum_residual_autocorrelation_p_value=Decimal("1.1"))
    with pytest.raises(ValueError, match="maximum_condition_number"):
        replace(policy_value, maximum_condition_number=Decimal("0"))
    with pytest.raises(ValueError, match="bounded non-blank string"):
        replace(policy_value, policy_version=" ")

    preregistration = study_preregistration()
    with pytest.raises(ValueError, match="methodology is invalid"):
        replace(preregistration, methodology=object())
    with pytest.raises(ValueError, match="window_end must follow window_start"):
        replace(preregistration, oos_window_end=preregistration.oos_window_start)
    with pytest.raises(ValueError, match="cannot contain whitespace"):
        replace(preregistration, candidate_version="candidate v2")
    with pytest.raises(ValueError, match="sha256 digest"):
        replace(preregistration, trial_family_hash="bad")


def test_qualification_derived_bundle_and_study_windows_remain_content_bound() -> None:
    """Derived metrics and comparative studies reject invalid values and duplicate dimensions."""

    bundle = complete_derived_metric_bundle()
    with pytest.raises(ValueError, match="label_stability_score"):
        replace(bundle, label_stability_score=Decimal("1.1"))
    with pytest.raises(ValueError, match="valid_until must follow evaluated_at"):
        replace(bundle, valid_until=bundle.evaluated_at)

    study = complete_qualification_study()
    with pytest.raises(ValueError, match="OOS window_end must follow window_start"):
        replace(study, oos_window_end=study.oos_window_start)
    with pytest.raises(ValueError, match="evaluated before its OOS window ends"):
        replace(study, evaluated_at=study.oos_window_end - timedelta(seconds=1))
    with pytest.raises(ValueError, match="valid_until must follow evaluated_at"):
        replace(study, valid_until=study.evaluated_at)
    with pytest.raises(ValueError, match="embargo_periods cannot be negative"):
        replace(study, embargo_periods=True)
    with pytest.raises(ValueError, match="metrics must be non-empty and unique"):
        replace(study, metrics=(study.metrics[0], study.metrics[0]))
    with pytest.raises(ValueError, match="policy coefficients must be non-empty and unique"):
        replace(
            study,
            policy_coefficients=(study.policy_coefficients[0], study.policy_coefficients[0]),
        )


def test_monitoring_period_identity_and_calendar_boundaries_are_canonical() -> None:
    """Monitoring calendars reject reversed, duplicate, noncanonical, and overlapping windows."""

    calendar = period_calendar()
    entry = calendar.entries[0]
    with pytest.raises(ValueError, match="window must be non-empty"):
        derive_r6_monitoring_period_id(
            period_calendar_id=calendar.calendar_id,
            period_calendar_version=calendar.calendar_version,
            period_start=entry.period_end,
            period_end=entry.period_start,
        )
    with pytest.raises(ValueError, match="calendar period must be non-empty"):
        R6MonitoringPeriodEntry(
            period_id=entry.period_id,
            period_start=entry.period_start,
            period_end=entry.period_start,
        )
    with pytest.raises(ValueError, match="calendar clocks are invalid"):
        replace(calendar, valid_until=calendar.valid_from)
    with pytest.raises(ValueError, match="entries are required"):
        replace(calendar, entries=())
    with pytest.raises(ValueError, match="IDs must be unique"):
        replace(calendar, entries=(entry, entry, *calendar.entries[2:]))
    with pytest.raises(ValueError, match="identity is not canonical"):
        replace(calendar, entries=(replace(entry, period_id="e" * 64), *calendar.entries[1:]))

    outside = R6MonitoringPeriodEntry(
        period_id=derive_r6_monitoring_period_id(
            period_calendar_id=calendar.calendar_id,
            period_calendar_version=calendar.calendar_version,
            period_start=calendar.valid_from - timedelta(days=1),
            period_end=calendar.valid_from,
        ),
        period_start=calendar.valid_from - timedelta(days=1),
        period_end=calendar.valid_from,
    )
    with pytest.raises(ValueError, match="lies outside validity"):
        replace(calendar, entries=(outside, *calendar.entries[1:]))

    overlap = R6MonitoringPeriodEntry(
        period_id=derive_r6_monitoring_period_id(
            period_calendar_id=calendar.calendar_id,
            period_calendar_version=calendar.calendar_version,
            period_start=entry.period_start,
            period_end=entry.period_end + timedelta(hours=1),
        ),
        period_start=entry.period_start,
        period_end=entry.period_end + timedelta(hours=1),
    )
    with pytest.raises(ValueError, match="entries cannot overlap"):
        replace(calendar, entries=(overlap, *calendar.entries[1:]))


def test_monitoring_threshold_policy_and_observation_contracts_reject_bad_inputs() -> None:
    """Injected monitoring thresholds and raw facts reject wrong types, clocks, and safety flags."""

    threshold = thresholds()[0]
    with pytest.raises(ValueError, match="threshold metric_key is invalid"):
        replace(threshold, metric_key="log_loss")
    with pytest.raises(ValueError, match="threshold direction is invalid"):
        replace(threshold, direction="at_least")
    with pytest.raises(ValueError, match="breach count must be positive"):
        replace(threshold, retirement_review_consecutive_breaches=0)

    monitoring_policy = policy()
    with pytest.raises(ValueError, match="thresholds must be unique"):
        replace(monitoring_policy, thresholds=(monitoring_policy.thresholds[0],) * 2)
    with pytest.raises(ValueError, match="minimum_observation_count must be positive"):
        replace(monitoring_policy, minimum_observation_count=0)
    with pytest.raises(ValueError, match="maximum_observation_age_seconds must be positive"):
        replace(monitoring_policy, maximum_observation_age_seconds=0)
    with pytest.raises(ValueError, match="knowledge/active clocks are invalid"):
        replace(monitoring_policy, active_from=monitoring_policy.recorded_at - timedelta(seconds=1))

    with pytest.raises(ValueError, match="observation metric_key is invalid"):
        R6MonitoringMetricObservation(metric_key="log_loss", unit="score", value=Decimal("0.2"))
    with pytest.raises(ValueError, match="observation unit is invalid"):
        R6MonitoringMetricObservation(
            metric_key=R6MonitoringMetricKey.LOG_LOSS,
            unit=object(),
            value=Decimal("0.2"),
        )

    fact = observation(sequence=1, monitoring_policy=policy(minimum_observation_count=1))
    with pytest.raises(ValueError, match="evidence clocks are invalid"):
        replace(fact, available_at=fact.observed_at - timedelta(seconds=1))
    with pytest.raises(ValueError, match="fall within its period window"):
        replace(
            fact,
            observed_at=fact.period_end,
            available_at=fact.period_end + timedelta(hours=1),
            recorded_at=fact.period_end + timedelta(hours=2),
        )
    with pytest.raises(ValueError, match="period identity is not canonical"):
        replace(fact, observation_period_id="e" * 64)
    with pytest.raises(ValueError, match="cannot authorize production behavior"):
        replace(fact, research_only=False)


def test_monitoring_assessment_shape_and_safety_invariants_are_revalidated() -> None:
    """Assessment status, blocker, review, and execution flags form one sealed shape."""

    monitoring_policy = policy()
    qualification = active_qualification()
    assessment = evaluate_r6_monitoring(
        qualification_ref=QUALIFICATION_REF,
        qualification_content_hash=QUALIFICATION_REF.assessment_hash,
        qualification_assessed_at=qualification.assessed_at,
        qualification_known_at=qualification.known_at,
        requested_policy_id=monitoring_policy.policy_id,
        requested_policy_version=monitoring_policy.policy_version,
        expected_policy_hash=monitoring_policy.content_hash,
        policy=monitoring_policy,
        period_calendar=period_calendar(),
        observations=(
            observation(sequence=1, monitoring_policy=monitoring_policy),
            observation(sequence=2, monitoring_policy=monitoring_policy),
        ),
        evaluated_at=MONITORING_NOW,
    )
    assert assessment.status is R6MonitoringAssessmentStatus.HEALTHY

    with pytest.raises(ValueError, match="blockers must be unique"):
        replace(
            assessment,
            blockers=(R6MonitoringBlockerCode.POLICY_MISSING,) * 2,
        )
    with pytest.raises(ValueError, match="observation hashes must be unique"):
        replace(
            assessment,
            observation_hashes=(assessment.observation_hashes[0],) * 2,
        )
    with pytest.raises(ValueError, match="blocked R6 monitoring assessment shape"):
        replace(
            assessment,
            status=R6MonitoringAssessmentStatus.BLOCKED,
            metric_results=(),
            blockers=(),
        )
    with pytest.raises(ValueError, match="non-blocked"):
        replace(
            assessment,
            blockers=(R6MonitoringBlockerCode.POLICY_MISSING,),
        )
    with pytest.raises(ValueError, match="requires the review flag"):
        replace(
            assessment,
            status=R6MonitoringAssessmentStatus.RETIREMENT_REVIEW_REQUIRED,
            retirement_review_required=False,
        )
    with pytest.raises(ValueError, match="only retirement-review status"):
        replace(assessment, retirement_review_required=True)
    with pytest.raises(ValueError, match="cannot automatically retire"):
        replace(assessment, automatic_retirement=True)
    with pytest.raises(ValueError, match="cannot authorize production behavior"):
        replace(assessment, research_only=False)


def test_monitoring_evaluation_rejects_missing_qualification_and_owner_context() -> None:
    """Evaluation blocks missing qualification clocks and substituted policy/calendar owners."""

    monitoring_policy = policy()
    qualification = active_qualification()
    calendar = period_calendar()

    def evaluate(**changes: object) -> R6MonitoringAssessment:
        values: dict[str, object] = {
            "qualification_ref": QUALIFICATION_REF,
            "qualification_content_hash": QUALIFICATION_REF.assessment_hash,
            "qualification_assessed_at": qualification.assessed_at,
            "qualification_known_at": qualification.known_at,
            "requested_policy_id": monitoring_policy.policy_id,
            "requested_policy_version": monitoring_policy.policy_version,
            "expected_policy_hash": monitoring_policy.content_hash,
            "policy": monitoring_policy,
            "period_calendar": calendar,
            "observations": (),
            "evaluated_at": MONITORING_NOW,
        }
        values.update(changes)
        return evaluate_r6_monitoring(**values)

    missing_clock = evaluate(qualification_assessed_at=None)
    assert missing_clock.status is R6MonitoringAssessmentStatus.BLOCKED
    assert R6MonitoringBlockerCode.ACTIVE_QUALIFICATION_INVALID in missing_clock.blockers

    reversed_clock = evaluate(
        qualification_assessed_at=qualification.known_at + timedelta(minutes=1),
    )
    assert reversed_clock.status is R6MonitoringAssessmentStatus.BLOCKED
    assert R6MonitoringBlockerCode.ACTIVE_QUALIFICATION_INVALID in reversed_clock.blockers

    binding = evaluate(requested_policy_id="substituted-policy")
    assert binding.status is R6MonitoringAssessmentStatus.BLOCKED
    assert R6MonitoringBlockerCode.POLICY_BINDING_MISMATCH in binding.blockers

    malformed_policy = policy()
    object.__setattr__(malformed_policy, "thresholds", (object(),))
    malformed_policy_result = evaluate(
        policy=malformed_policy,
        expected_policy_hash=malformed_policy.content_hash,
        requested_policy_id=malformed_policy.policy_id,
        requested_policy_version=malformed_policy.policy_version,
    )
    assert R6MonitoringBlockerCode.POLICY_HASH_MISMATCH in malformed_policy_result.blockers

    malformed_calendar = period_calendar()
    object.__setattr__(malformed_calendar, "entries", (object(),))
    malformed_calendar_result = evaluate(period_calendar=malformed_calendar)
    assert (
        R6MonitoringBlockerCode.PERIOD_CALENDAR_HASH_MISMATCH in malformed_calendar_result.blockers
    )

    substituted_calendar = period_calendar()
    object.__setattr__(substituted_calendar, "calendar_id", "substituted-calendar")
    substituted_result = evaluate(period_calendar=substituted_calendar)
    assert R6MonitoringBlockerCode.PERIOD_CALENDAR_BINDING_MISMATCH in substituted_result.blockers


def test_monitoring_evaluation_rejects_duplicate_and_substituted_observations() -> None:
    """Observation identity, period, canonical window, binding, and label substitutions fail closed."""

    monitoring_policy = policy()
    first = observation(sequence=1, monitoring_policy=monitoring_policy)
    second = observation(sequence=2, monitoring_policy=monitoring_policy)
    qualification = active_qualification()

    def evaluate(
        facts: tuple[R6MonitoringObservation, ...],
        *,
        selected_policy: R6MonitoringPolicy = monitoring_policy,
    ) -> R6MonitoringAssessment:
        return evaluate_r6_monitoring(
            qualification_ref=QUALIFICATION_REF,
            qualification_content_hash=QUALIFICATION_REF.assessment_hash,
            qualification_assessed_at=qualification.assessed_at,
            qualification_known_at=qualification.known_at,
            requested_policy_id=selected_policy.policy_id,
            requested_policy_version=selected_policy.policy_version,
            expected_policy_hash=selected_policy.content_hash,
            policy=selected_policy,
            period_calendar=period_calendar(),
            observations=facts,
            evaluated_at=MONITORING_NOW,
        )

    duplicate_identity = replace(
        second,
        observation_id=first.observation_id,
        observation_version=first.observation_version,
    )
    duplicate_identity_result = evaluate((first, duplicate_identity))
    assert (
        R6MonitoringBlockerCode.OBSERVATION_IDENTITY_DUPLICATE in duplicate_identity_result.blockers
    )

    duplicate_period = replace(
        first,
        observation_id="r6-monitoring-observation-duplicate-period",
        observed_at=first.observed_at + timedelta(seconds=1),
        available_at=first.available_at + timedelta(seconds=1),
        recorded_at=first.recorded_at + timedelta(seconds=1),
    )
    duplicate_period_result = evaluate((first, duplicate_period))
    assert R6MonitoringBlockerCode.OBSERVATION_PERIOD_DUPLICATE in duplicate_period_result.blockers

    insufficient_result = evaluate((first,))
    assert R6MonitoringBlockerCode.OBSERVATION_COUNT_INSUFFICIENT in insufficient_result.blockers

    period_id_tampered = observation(
        sequence=1,
        monitoring_policy=policy(minimum_observation_count=1),
    )
    object.__setattr__(period_id_tampered, "observation_period_id", "e" * 64)
    period_id_result = evaluate_r6_monitoring(
        qualification_ref=QUALIFICATION_REF,
        qualification_content_hash=QUALIFICATION_REF.assessment_hash,
        qualification_assessed_at=qualification.assessed_at,
        qualification_known_at=qualification.known_at,
        requested_policy_id=period_id_tampered.policy_id,
        requested_policy_version=period_id_tampered.policy_version,
        expected_policy_hash=period_id_tampered.policy_hash,
        policy=policy(minimum_observation_count=1),
        period_calendar=period_calendar(),
        observations=(period_id_tampered,),
        evaluated_at=MONITORING_NOW,
    )
    assert R6MonitoringBlockerCode.OBSERVATION_PERIOD_ID_MISMATCH in period_id_result.blockers

    window_tampered = observation(
        sequence=1,
        monitoring_policy=policy(minimum_observation_count=1),
    )
    object.__setattr__(window_tampered, "observed_at", window_tampered.period_end)
    window_result = evaluate_r6_monitoring(
        qualification_ref=QUALIFICATION_REF,
        qualification_content_hash=QUALIFICATION_REF.assessment_hash,
        qualification_assessed_at=qualification.assessed_at,
        qualification_known_at=qualification.known_at,
        requested_policy_id=window_tampered.policy_id,
        requested_policy_version=window_tampered.policy_version,
        expected_policy_hash=window_tampered.policy_hash,
        policy=policy(minimum_observation_count=1),
        period_calendar=period_calendar(),
        observations=(window_tampered,),
        evaluated_at=MONITORING_NOW,
    )
    assert R6MonitoringBlockerCode.OBSERVATION_PERIOD_WINDOW_INVALID in window_result.blockers

    binding_policy = policy(minimum_observation_count=1)
    binding_tampered = observation(sequence=1, monitoring_policy=binding_policy)
    object.__setattr__(binding_tampered, "policy_id", "substituted-policy")
    binding_result = evaluate_r6_monitoring(
        qualification_ref=QUALIFICATION_REF,
        qualification_content_hash=QUALIFICATION_REF.assessment_hash,
        qualification_assessed_at=qualification.assessed_at,
        qualification_known_at=qualification.known_at,
        requested_policy_id=binding_policy.policy_id,
        requested_policy_version=binding_policy.policy_version,
        expected_policy_hash=binding_policy.content_hash,
        policy=binding_policy,
        period_calendar=period_calendar(),
        observations=(binding_tampered,),
        evaluated_at=MONITORING_NOW,
    )
    assert R6MonitoringBlockerCode.OBSERVATION_BINDING_MISMATCH in binding_result.blockers

    label_policy = policy(minimum_observation_count=1)
    label_mismatch = replace(
        observation(sequence=1, monitoring_policy=label_policy),
        label_protocol_version="labels-substituted",
    )
    label_result = evaluate_r6_monitoring(
        qualification_ref=QUALIFICATION_REF,
        qualification_content_hash=QUALIFICATION_REF.assessment_hash,
        qualification_assessed_at=qualification.assessed_at,
        qualification_known_at=qualification.known_at,
        requested_policy_id=label_policy.policy_id,
        requested_policy_version=label_policy.policy_version,
        expected_policy_hash=label_policy.content_hash,
        policy=label_policy,
        period_calendar=period_calendar(),
        observations=(label_mismatch,),
        evaluated_at=MONITORING_NOW,
    )
    assert R6MonitoringBlockerCode.LABEL_PROTOCOL_MISMATCH in label_result.blockers
