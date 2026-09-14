"""Boundary tests for the research-only state-model qualification lifecycle."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from apps.research.domain.state_model_qualification import (
    StateModelQualificationAssessment,
    StateModelQualificationBlockerCode,
    StateModelQualificationStatus,
    evaluate_state_model_qualification,
)
from apps.research.domain.state_model_qualification_lifecycle import (
    R6QualificationLifecycleAction,
    R6QualificationLifecycleEvent,
    R6QualificationPromotionAuthorization,
    R6QualificationRef,
    create_r6_qualification_lifecycle_event,
    derive_r6_qualification_lifecycle_state,
)
from tests.unit.research.advanced_state_model_factories import (
    NOW,
    complete_candidate,
    proven_shortfall_report,
)
from tests.unit.research.state_model_qualification_factories import (
    accepted_advanced_assessment,
    complete_derived_metric_bundle,
    complete_qualification_study,
    qualification_policy,
    study_preregistration,
)


def _evaluate(**changes: object) -> StateModelQualificationAssessment:
    values: dict[str, object] = {
        "candidate": complete_candidate(),
        "advanced_assessment": accepted_advanced_assessment(),
        "derived_metric_bundle": complete_derived_metric_bundle(),
        "baseline_shortfall": proven_shortfall_report(),
        "preregistration": study_preregistration(),
        "study": complete_qualification_study(),
        "policy": qualification_policy(),
        "assessed_at": NOW,
    }
    values.update(changes)
    return evaluate_state_model_qualification(**values)  # type: ignore[arg-type]


def _reseal(value: object, **changes: object) -> object:
    """Mutate only a test copy, then restore its canonical content seal."""

    for field_name, field_value in changes.items():
        object.__setattr__(value, field_name, field_value)
    object.__setattr__(value, "content_hash", value.calculated_content_hash)  # type: ignore[attr-defined]
    value.__post_init__()  # type: ignore[attr-defined]
    return value


def _ref(name: str = "r6-qualification") -> R6QualificationRef:
    return R6QualificationRef(assessment_id=name, assessment_hash="a" * 64)


def _authorization(
    ref: R6QualificationRef,
    *,
    action: R6QualificationLifecycleAction,
    sequence: int,
    recorded_at: datetime,
    valid_until: datetime | None = None,
) -> R6QualificationPromotionAuthorization:
    """Build one owner authorization with a closed, content-bound time window."""

    return R6QualificationPromotionAuthorization(
        authorization_id=f"r6-authorization-{sequence}-{action.value}",
        authorization_version="v1",
        qualification_ref=ref,
        event_id=f"r6-event-{sequence}-{action.value}",
        event_version="v1",
        action=action,
        expected_sequence=sequence,
        owner="research",
        issued_at=recorded_at - timedelta(minutes=1),
        recorded_at=recorded_at,
        valid_until=valid_until or recorded_at + timedelta(hours=1),
        reason_codes=(f"manual-{action.value}",),
        evidence_ref=f"research://r6/lifecycle/{sequence}/{action.value}",
    )


def _event(
    ref: R6QualificationRef,
    *,
    action: R6QualificationLifecycleAction,
    sequence: int,
    recorded_at: datetime,
    previous_event_hash: str | None = None,
    valid_until: datetime | None = None,
) -> R6QualificationLifecycleEvent:
    authorization = _authorization(
        ref,
        action=action,
        sequence=sequence,
        recorded_at=recorded_at,
        valid_until=valid_until,
    )
    return create_r6_qualification_lifecycle_event(
        authorization=authorization,
        sequence=sequence,
        occurred_at=recorded_at,
        recorded_at=recorded_at,
        previous_event_hash=previous_event_hash,
    )


def test_complete_evaluation_is_sealed_and_remains_research_only() -> None:
    assessment = _evaluate()

    assert assessment.status is StateModelQualificationStatus.EVIDENCE_COMPLETE
    assert len(assessment.metric_results) == 7
    assert assessment.blockers == ()
    assert assessment.content_hash == assessment.calculated_content_hash
    assert assessment.may_request_promotion_review is True
    assert assessment.promotion_decision_present is False
    assert assessment.research_only is True
    assert assessment.must_not_use_for_decision is True
    assert assessment.must_not_replace_regime is True


def test_missing_qualification_dependencies_never_fall_back_to_caller_values() -> None:
    assessment = _evaluate(
        candidate=None,
        advanced_assessment=None,
        derived_metric_bundle=None,
        baseline_shortfall=None,
        preregistration=None,
        policy=None,
    )

    assert assessment.status is StateModelQualificationStatus.BLOCKED
    assert {
        StateModelQualificationBlockerCode.CANDIDATE_MISSING,
        StateModelQualificationBlockerCode.ADVANCED_ASSESSMENT_MISSING,
        StateModelQualificationBlockerCode.DERIVED_METRIC_BUNDLE_MISSING,
        StateModelQualificationBlockerCode.BASELINE_SHORTFALL_MISSING,
        StateModelQualificationBlockerCode.PREREGISTRATION_MISSING,
        StateModelQualificationBlockerCode.POLICY_MISSING,
    }.issubset(set(assessment.blockers))
    assert assessment.metric_results == ()
    assert assessment.may_request_promotion_review is False
    assert assessment.research_only is True
    assert assessment.must_not_use_for_decision is True
    assert assessment.must_not_replace_regime is True


@pytest.mark.parametrize(
    ("dependency", "expected_blocker"),
    (
        ("future_study", StateModelQualificationBlockerCode.STUDY_FROM_FUTURE),
        ("expired_study", StateModelQualificationBlockerCode.STUDY_STALE),
        ("expired_candidate", StateModelQualificationBlockerCode.CANDIDATE_EVIDENCE_STALE),
        (
            "future_derived_metrics",
            StateModelQualificationBlockerCode.DERIVED_METRIC_BUNDLE_FROM_FUTURE,
        ),
        ("expired_derived_metrics", StateModelQualificationBlockerCode.DERIVED_METRIC_BUNDLE_STALE),
        ("future_baseline", StateModelQualificationBlockerCode.BASELINE_EVIDENCE_FROM_FUTURE),
        ("expired_baseline", StateModelQualificationBlockerCode.BASELINE_EVIDENCE_STALE),
    ),
)
def test_future_and_expired_evidence_is_blocked(
    dependency: str,
    expected_blocker: StateModelQualificationBlockerCode,
) -> None:
    study = complete_qualification_study()
    if dependency == "future_study":
        changed: object = replace(
            study,
            evaluated_at=NOW + timedelta(hours=1),
            valid_until=NOW + timedelta(days=2),
        )
    elif dependency == "expired_study":
        changed = replace(study, valid_until=NOW)
    elif dependency == "expired_candidate":
        changed = replace(complete_candidate(), valid_until=NOW)
    elif dependency == "future_derived_metrics":
        bundle = complete_derived_metric_bundle()
        changed = replace(
            bundle,
            evaluated_at=NOW + timedelta(hours=1),
            valid_until=NOW + timedelta(hours=2),
        )
    elif dependency == "expired_derived_metrics":
        changed = replace(complete_derived_metric_bundle(), valid_until=NOW)
    elif dependency == "future_baseline":
        changed = _reseal(
            proven_shortfall_report(),
            evidence_evaluated_at=NOW + timedelta(hours=1),
            evidence_valid_until=NOW + timedelta(hours=2),
        )
    else:
        changed = _reseal(proven_shortfall_report(), evidence_valid_until=NOW)

    keyword = {
        "future_study": "study",
        "expired_study": "study",
        "expired_candidate": "candidate",
        "future_derived_metrics": "derived_metric_bundle",
        "expired_derived_metrics": "derived_metric_bundle",
        "future_baseline": "baseline_shortfall",
        "expired_baseline": "baseline_shortfall",
    }[dependency]
    assessment = _evaluate(**{keyword: changed})

    assert assessment.status is StateModelQualificationStatus.BLOCKED
    assert expected_blocker in assessment.blockers
    assert assessment.may_request_promotion_review is False


def test_hash_and_identity_substitution_blocks_the_qualification_gate() -> None:
    tampered_study = complete_qualification_study()
    object.__setattr__(tampered_study, "content_hash", "f" * 64)
    substituted_candidate = replace(
        complete_candidate(),
        candidate_version="substituted-candidate-v1",
        evidence_hash="0" * 64,
    )
    tampered_preregistration = study_preregistration()
    object.__setattr__(tampered_preregistration, "content_hash", "e" * 64)
    tampered_bundle = complete_derived_metric_bundle()
    object.__setattr__(tampered_bundle, "content_hash", "d" * 64)

    study_result = _evaluate(study=tampered_study)
    candidate_result = _evaluate(candidate=substituted_candidate)
    preregistration_result = _evaluate(preregistration=tampered_preregistration)
    bundle_result = _evaluate(derived_metric_bundle=tampered_bundle)
    raw_bundle_result = _evaluate(derived_metric_bundle=object())

    assert StateModelQualificationBlockerCode.STUDY_HASH_MISMATCH in study_result.blockers
    assert (
        StateModelQualificationBlockerCode.CANDIDATE_BINDING_MISMATCH in candidate_result.blockers
    )
    assert (
        StateModelQualificationBlockerCode.PREREGISTRATION_HASH_MISMATCH
        in preregistration_result.blockers
    )
    assert (
        StateModelQualificationBlockerCode.DERIVED_METRIC_BUNDLE_HASH_MISMATCH
        in bundle_result.blockers
    )
    assert (
        StateModelQualificationBlockerCode.DERIVED_METRIC_BUNDLE_BINDING_MISMATCH
        in raw_bundle_result.blockers
    )


def test_qualification_lifecycle_promote_then_retire_preserves_safety_flags() -> None:
    ref = _ref()
    promotion = _event(
        ref,
        action=R6QualificationLifecycleAction.PROMOTE,
        sequence=1,
        recorded_at=NOW,
    )
    retirement = _event(
        ref,
        action=R6QualificationLifecycleAction.RETIRE,
        sequence=2,
        recorded_at=NOW + timedelta(minutes=10),
        previous_event_hash=promotion.content_hash,
    )

    active_state = derive_r6_qualification_lifecycle_state((promotion,), evaluated_at=NOW)
    retired_state = derive_r6_qualification_lifecycle_state(
        (retirement, promotion), evaluated_at=NOW + timedelta(minutes=10)
    )
    authorization = _authorization(
        ref,
        action=R6QualificationLifecycleAction.PROMOTE,
        sequence=1,
        recorded_at=NOW,
    )

    assert authorization.is_active_at(authorization.issued_at) is True
    assert authorization.is_active_at(authorization.valid_until) is False
    assert active_state.active is True
    assert active_state.sequence == 1
    assert active_state.head_event_hash == promotion.content_hash
    assert retired_state.active is False
    assert retired_state.sequence == 2
    assert retired_state.head_event_hash == retirement.content_hash
    assert promotion.research_only is True
    assert promotion.must_not_use_for_decision is True
    assert promotion.must_not_replace_regime is True


def test_lifecycle_construction_rejects_invalid_owner_clock_hash_and_research_flags() -> None:
    ref = _ref()
    authorization = _authorization(
        ref,
        action=R6QualificationLifecycleAction.PROMOTE,
        sequence=1,
        recorded_at=NOW,
    )

    with pytest.raises(ValueError, match="bounded non-blank token"):
        replace(authorization, authorization_id="")
    with pytest.raises(ValueError, match="cannot contain whitespace"):
        replace(authorization, event_id="event with whitespace")
    with pytest.raises(ValueError, match="owner must be research"):
        replace(authorization, owner="operator")
    with pytest.raises(ValueError, match="action is invalid"):
        replace(authorization, action="rollback")
    with pytest.raises(ValueError, match="sequence is invalid"):
        replace(authorization, expected_sequence=0)
    with pytest.raises(ValueError, match="clocks are invalid"):
        replace(authorization, valid_until=authorization.recorded_at)
    with pytest.raises(ValueError, match="reasons must be unique"):
        replace(authorization, reason_codes=("same", "same"))
    with pytest.raises(ValueError, match="research-only"):
        replace(authorization, research_only=False)
    object.__setattr__(authorization, "content_hash", "f" * 64)
    with pytest.raises(ValueError, match="content hash mismatch"):
        authorization.__post_init__()

    with pytest.raises(ValueError, match="timezone-aware"):
        authorization.is_active_at(datetime(2026, 8, 5, 12))
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        R6QualificationRef("bad-ref", "not-a-sha")


def test_event_validation_and_factory_reject_invalid_append_inputs() -> None:
    ref = _ref()
    event = _event(
        ref,
        action=R6QualificationLifecycleAction.PROMOTE,
        sequence=1,
        recorded_at=NOW,
    )

    with pytest.raises(ValueError, match="action is invalid"):
        replace(event, action="revoke")
    with pytest.raises(ValueError, match="sequence is invalid"):
        replace(event, sequence=0)
    with pytest.raises(ValueError, match="recorded_at cannot precede"):
        replace(event, recorded_at=event.occurred_at - timedelta(seconds=1))
    with pytest.raises(ValueError, match="reasons must be unique"):
        replace(event, reason_codes=("same", "same"))
    with pytest.raises(ValueError, match="research-only"):
        replace(event, must_not_use_for_decision=False)
    object.__setattr__(event, "authorization_hash", "f" * 64)
    with pytest.raises(ValueError, match="content hash mismatch"):
        event.__post_init__()

    authorization = _authorization(
        ref,
        action=R6QualificationLifecycleAction.PROMOTE,
        sequence=1,
        recorded_at=NOW,
    )
    with pytest.raises(ValueError, match="sequence differs"):
        create_r6_qualification_lifecycle_event(
            authorization=authorization,
            sequence=2,
            occurred_at=NOW,
            recorded_at=NOW,
            previous_event_hash=None,
        )
    with pytest.raises(ValueError, match="inactive at occurrence"):
        create_r6_qualification_lifecycle_event(
            authorization=authorization,
            sequence=1,
            occurred_at=authorization.valid_until,
            recorded_at=authorization.valid_until,
            previous_event_hash=None,
        )


def test_lifecycle_replay_rejects_empty_future_fork_gap_hash_and_head_inconsistency() -> None:
    ref = _ref()
    other_ref = _ref("other-qualification")
    first = _event(
        ref,
        action=R6QualificationLifecycleAction.PROMOTE,
        sequence=1,
        recorded_at=NOW,
    )
    second = _event(
        ref,
        action=R6QualificationLifecycleAction.RETIRE,
        sequence=2,
        recorded_at=NOW + timedelta(minutes=1),
        previous_event_hash=first.content_hash,
    )

    with pytest.raises(ValueError, match="has no events"):
        derive_r6_qualification_lifecycle_state((), evaluated_at=NOW)
    with pytest.raises(ValueError, match="timezone-aware"):
        derive_r6_qualification_lifecycle_state((first,), evaluated_at=datetime(2026, 8, 5, 12))
    with pytest.raises(ValueError, match="crosses assessment identities"):
        derive_r6_qualification_lifecycle_state(
            (first, replace(second, qualification_ref=other_ref)),
            evaluated_at=NOW + timedelta(minutes=1),
        )
    with pytest.raises(ValueError, match="sequence is discontinuous"):
        derive_r6_qualification_lifecycle_state(
            (first, replace(second, sequence=3)),
            evaluated_at=NOW + timedelta(minutes=1),
        )
    with pytest.raises(ValueError, match="future evidence"):
        derive_r6_qualification_lifecycle_state(
            (first,), evaluated_at=NOW - timedelta(microseconds=1)
        )
    with pytest.raises(ValueError, match="hash chain is broken"):
        derive_r6_qualification_lifecycle_state(
            (first, replace(second, previous_event_hash="b" * 64)),
            evaluated_at=NOW + timedelta(minutes=1),
        )


def test_lifecycle_replay_rejects_root_retire_duplicate_promote_and_inactive_retire() -> None:
    ref = _ref()
    root_retire = _event(
        ref,
        action=R6QualificationLifecycleAction.RETIRE,
        sequence=1,
        recorded_at=NOW,
    )
    with pytest.raises(ValueError, match="root must promote"):
        derive_r6_qualification_lifecycle_state((root_retire,), evaluated_at=NOW)

    first = _event(
        ref,
        action=R6QualificationLifecycleAction.PROMOTE,
        sequence=1,
        recorded_at=NOW,
    )
    second_promote = _event(
        ref,
        action=R6QualificationLifecycleAction.PROMOTE,
        sequence=2,
        recorded_at=NOW + timedelta(minutes=1),
        previous_event_hash=first.content_hash,
    )
    with pytest.raises(ValueError, match="already active"):
        derive_r6_qualification_lifecycle_state(
            (first, second_promote), evaluated_at=NOW + timedelta(minutes=1)
        )

    second_retire = _event(
        ref,
        action=R6QualificationLifecycleAction.RETIRE,
        sequence=2,
        recorded_at=NOW + timedelta(minutes=1),
        previous_event_hash=first.content_hash,
    )
    third_retire = _event(
        ref,
        action=R6QualificationLifecycleAction.RETIRE,
        sequence=3,
        recorded_at=NOW + timedelta(minutes=2),
        previous_event_hash=second_retire.content_hash,
    )
    with pytest.raises(ValueError, match="retires an inactive item"):
        derive_r6_qualification_lifecycle_state(
            (first, second_retire, third_retire), evaluated_at=NOW + timedelta(minutes=2)
        )
