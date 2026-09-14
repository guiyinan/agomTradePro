"""Additional fail-closed boundary coverage for the R7 monitoring Domain."""

from __future__ import annotations

import copy
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from apps.research.domain.r7_post_promotion_monitoring import (
    R7ForecastRealizationFact,
    R7ForecastRealizationMember,
    R7ForecastRealizationOwnerRecord,
    R7MonitoringBlockerCode,
    calculate_r7_brier_score,
    calculate_r7_forecast_outcome_coverage,
    derive_r7_monitoring_status,
    evaluate_r7_post_promotion_monitoring,
    realization_member_hash,
)
from apps.research.domain.r7_post_promotion_monitoring_contracts import (
    R7LifecycleStreamOwnerEvidence,
    R7MonitoringActiveResult,
    R7MonitoringPeriodEntry,
    R7MonitoringPredictionMember,
    active_result_hash,
    monitoring_calendar_hash,
    period_entry_hash,
    prediction_member_hash,
)
from apps.research.domain.scenario_probability_contracts import (
    ForecastLedgerOutcomeObservation,
    ScenarioInvalidationEvidence,
)
from apps.signal.domain.forecast_scenario_evidence import ScenarioProbabilitySource
from tests.unit.research.r7_research_result_factories import make_result
from tests.unit.research.test_r7_post_promotion_monitoring import (
    _active_period_and_fact,
    _lifecycle_owner_evidence,
    _promotion_stream,
)


def _copy_with(value: object, **changes: object) -> object:
    """Copy a frozen Domain value and deliberately alter one guard input."""

    candidate = copy.copy(value)
    for name, replacement in changes.items():
        object.__setattr__(candidate, name, replacement)
    return candidate


def _fresh_member(
    member: R7ForecastRealizationMember,
    **changes: object,
) -> R7ForecastRealizationMember:
    """Return a validly sealed member after changing a clock or outcome."""

    candidate = replace(member)
    for name, replacement in changes.items():
        object.__setattr__(candidate, name, replacement)
    object.__setattr__(candidate, "content_hash", realization_member_hash(candidate))
    candidate.__post_init__()
    return candidate


def _fresh_prediction(
    prediction: R7MonitoringPredictionMember,
    **changes: object,
) -> R7MonitoringPredictionMember:
    """Return a validly sealed prediction after changing source metadata."""

    candidate = replace(prediction)
    for name, replacement in changes.items():
        object.__setattr__(candidate, name, replacement)
    object.__setattr__(candidate, "content_hash", prediction_member_hash(candidate))
    candidate.__post_init__()
    return candidate


def _fresh_active(
    active: R7MonitoringActiveResult,
    predictions: tuple[R7MonitoringPredictionMember, ...],
) -> R7MonitoringActiveResult:
    """Return an active projection with a recomputed top-level seal."""

    candidate = copy.copy(active)
    object.__setattr__(candidate, "predictions", predictions)
    object.__setattr__(candidate, "content_hash", active_result_hash(candidate))
    candidate.validate_live()
    return candidate


def _fact_with_members(
    period: R7MonitoringPeriodEntry,
    fact: R7ForecastRealizationFact,
    members: tuple[R7ForecastRealizationMember, ...],
) -> R7ForecastRealizationFact:
    """Rebuild an owner fact while retaining the exact period binding."""

    owner = fact.owner_record
    owner_copy = R7ForecastRealizationOwnerRecord.create(
        owner_record_id=f"{owner.owner_record_id}:variant",
        owner_record_version=owner.owner_record_version,
        period=period,
        pit_as_of=owner.pit_as_of,
        available_at=owner.available_at,
        recorded_at=owner.recorded_at,
        valid_until=owner.valid_until,
        evidence_ref=f"{owner.evidence_ref}:variant",
        members=members,
    )
    return R7ForecastRealizationFact.from_owner_record(
        period=period,
        owner_record=owner_copy,
    )


def _observation_without_outcome(
    observation: ForecastLedgerOutcomeObservation,
) -> ForecastLedgerOutcomeObservation:
    """Build the explicitly unresolved form of one forecast observation."""

    return ForecastLedgerOutcomeObservation.create(
        observation_version=observation.observation_version,
        entry_id=observation.entry_id,
        forecast_group_id=observation.forecast_group_id,
        binding=observation.binding,
        pit_manifest_id=observation.pit_manifest_id,
        pit_manifest_version=observation.pit_manifest_version,
        pit_manifest_hash=observation.pit_manifest_hash,
        censoring_rule_version=observation.censoring_rule_version,
        published_at=observation.published_at,
        horizon_end=observation.horizon_end,
        scenario_realized=None,
        outcome_recorded_at=None,
        outcome_evidence_valid_until=None,
    )


def _observation_with_invalidation(
    observation: ForecastLedgerOutcomeObservation,
) -> ForecastLedgerOutcomeObservation:
    """Build an owner-invalidated observation with no synthesized outcome."""

    invalidation = ScenarioInvalidationEvidence.create(
        evidence_version="scenario-invalidation.v1",
        scenario_revision_id=observation.binding.scenario_revision_id,
        scenario_set_revision_id=observation.binding.scenario_set_revision_id,
        invalidated_at=observation.horizon_end + timedelta(hours=1),
        invalidation_rule_version="r7-test-rule.v1",
        pit_manifest_id=observation.pit_manifest_id,
        evidence_refs=(f"research://r7/invalidation/{observation.entry_id}",),
    )
    return ForecastLedgerOutcomeObservation.create(
        observation_version=observation.observation_version,
        entry_id=observation.entry_id,
        forecast_group_id=observation.forecast_group_id,
        binding=observation.binding,
        pit_manifest_id=observation.pit_manifest_id,
        pit_manifest_version=observation.pit_manifest_version,
        pit_manifest_hash=observation.pit_manifest_hash,
        censoring_rule_version=observation.censoring_rule_version,
        published_at=observation.published_at,
        horizon_end=observation.horizon_end,
        scenario_realized=None,
        outcome_recorded_at=None,
        outcome_evidence_valid_until=None,
        invalidation=invalidation,
    )


def test_realization_member_projects_unresolved_and_invalidated_owner_states() -> None:
    """The projection preserves explicit unresolved and invalidated source states."""

    _, _, _, fact = _active_period_and_fact()
    source = make_result().evidence_graph.forecast_observations[0]
    unresolved = _observation_without_outcome(source)
    unresolved_member = R7ForecastRealizationMember.from_owner_observation(
        observation=unresolved,
        available_at=source.horizon_end + timedelta(minutes=1),
        recorded_at=source.horizon_end + timedelta(minutes=2),
        evidence_ref="signal://r7/unresolved",
    )
    assert unresolved_member.realized is None
    assert unresolved_member.invalidated is False

    invalidated = _observation_with_invalidation(source)
    invalidated_member = R7ForecastRealizationMember.from_owner_observation(
        observation=invalidated,
        available_at=invalidated.horizon_end + timedelta(hours=1, minutes=1),
        recorded_at=invalidated.horizon_end + timedelta(hours=1, minutes=2),
        evidence_ref="signal://r7/invalidated",
    )
    assert invalidated_member.realized is None
    assert invalidated_member.invalidated is True
    assert fact.members


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("member_version", "r7-realization.v2", "version is unsupported"),
        ("observation_id", "other-entry", "identity is aliased"),
        ("scenario_revision_id", "not-a-uuid", "scenario revision is invalid"),
        ("realized", 1, "exact bool"),
        ("invalidated", 1, "invalidation flag"),
        ("available_at", None, "member clocks are invalid"),
    ),
)
def test_realization_member_rejects_tampered_types_and_clocks(
    field: str,
    value: object,
    message: str,
) -> None:
    """Every member identity, type, and clock boundary remains fail-closed."""

    _, _, _, fact = _active_period_and_fact()
    member = fact.members[0]
    if field == "available_at":
        value = member.horizon_end - timedelta(seconds=1)
    with pytest.raises((TypeError, ValueError), match=message):
        replace(member, **{field: value})

    if field == "invalidated":
        with pytest.raises(ValueError, match="mutually exclusive"):
            replace(member, invalidated=True)


def test_realization_owner_rejects_noncanonical_duplicate_and_member_clock_inputs() -> None:
    """Owner membership is canonical, unique, typed, period-bound, and availability-safe."""

    _, _, period, fact = _active_period_and_fact()
    owner = fact.owner_record
    first, second = owner.members

    sort_shape = SimpleNamespace(
        entry_id=first.entry_id,
        observation_version=first.observation_version,
        observation_id=first.observation_id,
    )
    with pytest.raises(TypeError, match="owner member type"):
        R7ForecastRealizationOwnerRecord.create(
            owner_record_id="r7-owner-shaped-member",
            owner_record_version=owner.owner_record_version,
            period=period,
            pit_as_of=owner.pit_as_of,
            available_at=owner.available_at,
            recorded_at=owner.recorded_at,
            valid_until=owner.valid_until,
            evidence_ref="signal://r7/shaped-member",
            members=(sort_shape,),
        )

    reversed_owner = _copy_with(owner, members=(second, first))
    with pytest.raises(ValueError, match="canonical and unique"):
        reversed_owner.__post_init__()

    duplicate = _fresh_member(
        second,
        entry_id=first.entry_id,
        observation_id=first.observation_id,
        observation_version="r7-forecast-observation.v2",
    )
    duplicate_owner = _copy_with(owner, members=(first, duplicate))
    with pytest.raises(ValueError, match="duplicate forecast entries"):
        duplicate_owner.__post_init__()

    fake_member = SimpleNamespace(
        entry_id=first.entry_id,
        observation_version=first.observation_version,
        observation_id=first.observation_id,
    )
    fake_owner = _copy_with(owner, members=(fake_member,))
    with pytest.raises(TypeError, match="owner member type"):
        fake_owner.__post_init__()

    short_horizon = _fresh_member(
        first,
        horizon_end=period.period_end - timedelta(seconds=1),
    )
    with pytest.raises(ValueError, match="horizon does not match"):
        R7ForecastRealizationOwnerRecord.create(
            owner_record_id="r7-owner-short-horizon",
            owner_record_version=owner.owner_record_version,
            period=period,
            pit_as_of=owner.pit_as_of,
            available_at=owner.available_at,
            recorded_at=owner.recorded_at,
            valid_until=owner.valid_until,
            evidence_ref="signal://r7/short-horizon",
            members=(short_horizon, second),
        )

    late_member = _fresh_member(
        first,
        available_at=owner.available_at + timedelta(seconds=1),
        recorded_at=owner.recorded_at + timedelta(seconds=1),
    )
    with pytest.raises(ValueError, match="predates one of its members"):
        R7ForecastRealizationOwnerRecord.create(
            owner_record_id="r7-owner-late-member",
            owner_record_version=owner.owner_record_version,
            period=period,
            pit_as_of=owner.pit_as_of,
            available_at=owner.available_at,
            recorded_at=owner.recorded_at,
            valid_until=owner.valid_until,
            evidence_ref="signal://r7/late-member",
            members=(late_member, second),
        )


def test_realization_fact_and_matched_pairs_reject_types_and_period_substitution() -> None:
    """Fact and metric entrypoints reject aliases before any denominator calculation."""

    active, _, period, fact = _active_period_and_fact()
    with pytest.raises(TypeError, match="owner record type"):
        R7ForecastRealizationFact.from_owner_record(period=period, owner_record=object())
    bad_fact = _copy_with(fact, owner_record=object())
    with pytest.raises(TypeError, match="fact owner record type"):
        bad_fact.__post_init__()
    with pytest.raises(ValueError, match="fact version is unsupported"):
        replace(fact, fact_version="r7-realization-fact.v2")

    alias = R7MonitoringPeriodEntry.create(
        calendar_id=period.calendar_id,
        calendar_version=period.calendar_version,
        period_start=period.period_start + timedelta(seconds=1),
        period_end=period.period_end,
    )
    with pytest.raises(ValueError, match="period substitution"):
        calculate_r7_forecast_outcome_coverage(
            active=active,
            period=alias,
            realization=fact,
        )

    with pytest.raises(TypeError, match="monitoring period type"):
        calculate_r7_forecast_outcome_coverage(
            active=active,
            period=object(),
            realization=fact,
        )
    with pytest.raises(TypeError, match="monitoring realization type"):
        calculate_r7_forecast_outcome_coverage(
            active=active,
            period=period,
            realization=object(),
        )
    with pytest.raises(TypeError, match="probability source"):
        calculate_r7_brier_score(
            active=active,
            period=period,
            realization=fact,
            source=object(),
        )


def test_brier_score_rejects_unresolved_and_mixed_probability_owners() -> None:
    """Brier metrics never fill missing outcomes or merge source versions."""

    active, _, period, fact = _active_period_and_fact()
    unresolved_member = _fresh_member(fact.members[0], realized=None)
    unresolved = _fact_with_members(
        period,
        fact,
        (unresolved_member, fact.members[1]),
    )
    assert (
        calculate_r7_brier_score(
            active=active,
            period=period,
            realization=unresolved,
            source=ScenarioProbabilitySource.SUBJECTIVE,
        )
        is None
    )

    first, second = active.predictions
    mixed_subjective = _fresh_prediction(
        second,
        subjective_probability_source_version="committee-probability.v2",
    )
    active_subjective = _fresh_active(active, (first, mixed_subjective))
    subjective_fact = _fact_with_members(
        period,
        fact,
        (
            fact.members[0],
            _fresh_member(fact.members[1], prediction_hash=mixed_subjective.content_hash),
        ),
    )
    with pytest.raises(ValueError, match="subjective probability source versions"):
        calculate_r7_brier_score(
            active=active_subjective,
            period=period,
            realization=subjective_fact,
            source=ScenarioProbabilitySource.SUBJECTIVE,
        )

    model_first = _fresh_prediction(
        first,
        model_probability=Decimal("0.55"),
        model_probability_source_version="model.v1",
        model_promotion_decision_id="model-decision:1",
    )
    partial_model = _fresh_active(active, (model_first, second))
    partial_fact = _fact_with_members(
        period,
        fact,
        (
            _fresh_member(fact.members[0], prediction_hash=model_first.content_hash),
            fact.members[1],
        ),
    )
    with pytest.raises(ValueError, match="coverage is incomplete"):
        calculate_r7_brier_score(
            active=partial_model,
            period=period,
            realization=partial_fact,
            source=ScenarioProbabilitySource.MODEL_INFERRED,
        )

    model_second = _fresh_prediction(
        second,
        model_probability=Decimal("0.45"),
        model_probability_source_version="model.v1",
        model_promotion_decision_id="model-decision:2",
    )
    mixed_model = _fresh_active(active, (model_first, model_second))
    mixed_model_fact = _fact_with_members(
        period,
        fact,
        (
            _fresh_member(fact.members[0], prediction_hash=model_first.content_hash),
            _fresh_member(fact.members[1], prediction_hash=model_second.content_hash),
        ),
    )
    with pytest.raises(ValueError, match="owner versions are mixed"):
        calculate_r7_brier_score(
            active=mixed_model,
            period=period,
            realization=mixed_model_fact,
            source=ScenarioProbabilitySource.MODEL_INFERRED,
        )


def test_assessment_and_status_contracts_reject_noncanonical_inputs() -> None:
    """Assessment seals preserve research-only flags and canonical blocker order."""

    active, calendar, period, fact = _active_period_and_fact()
    assessment = evaluate_r7_post_promotion_monitoring(
        active=active,
        calendar=calendar,
        period=period,
        realization=fact,
        evaluated_at=fact.owner_record.recorded_at,
        maximum_subjective_brier_score=Decimal("0.2"),
        maximum_model_brier_score=Decimal("0.2"),
        minimum_forecast_outcome_coverage=Decimal("1"),
    )
    with pytest.raises(ValueError, match="assessment version is unsupported"):
        replace(assessment, assessment_version="r7-monitoring-assessment.v2")
    with pytest.raises(ValueError, match="subjective_brier_score is invalid"):
        replace(assessment, subjective_brier_score=Decimal("2"))
    with pytest.raises(TypeError, match="blockers are invalid"):
        replace(assessment, blocker_codes=(object(),))
    with pytest.raises(ValueError, match="blockers are not canonical"):
        replace(
            assessment,
            blocker_codes=(
                R7MonitoringBlockerCode.PATH_EVIDENCE_UNAVAILABLE,
                R7MonitoringBlockerCode.CALIBRATION_EVIDENCE_UNAVAILABLE,
            ),
        )
    with pytest.raises(TypeError, match="assessment status is invalid"):
        replace(assessment, status="blocked")
    with pytest.raises(ValueError, match="research-only"):
        replace(assessment, automatic_retirement=True)
    with pytest.raises(ValueError, match="manual-review flag"):
        replace(assessment, manual_retirement_review_required=True)

    with pytest.raises(TypeError, match="blockers are invalid"):
        derive_r7_monitoring_status(
            blocker_codes=(object(),),
            threshold_breached=False,
            falsification_detected=False,
        )
    with pytest.raises(TypeError, match="exact booleans"):
        derive_r7_monitoring_status(
            blocker_codes=(),
            threshold_breached=1,
            falsification_detected=False,
        )


@pytest.mark.parametrize("field", ("active", "calendar", "period", "realization"))
def test_evaluator_rejects_non_exact_top_level_contracts(field: str) -> None:
    """The evaluator rejects every substituted top-level owner before reading it."""

    active, calendar, period, fact = _active_period_and_fact()
    values: dict[str, object] = {
        "active": active,
        "calendar": calendar,
        "period": period,
        "realization": fact,
    }
    values[field] = object()
    with pytest.raises(TypeError, match="type is invalid"):
        evaluate_r7_post_promotion_monitoring(
            active=values["active"],
            calendar=values["calendar"],
            period=values["period"],
            realization=values["realization"],
            evaluated_at=fact.owner_record.recorded_at,
            maximum_subjective_brier_score=Decimal("0.2"),
            maximum_model_brier_score=Decimal("0.2"),
            minimum_forecast_outcome_coverage=Decimal("1"),
        )


def test_evaluator_marks_clock_expiry_and_incomplete_outcomes() -> None:
    """Live-clock and unresolved-outcome blockers are derived instead of hidden."""

    active, calendar, period, fact = _active_period_and_fact()
    expired = evaluate_r7_post_promotion_monitoring(
        active=active,
        calendar=calendar,
        period=period,
        realization=fact,
        evaluated_at=fact.owner_record.valid_until,
        maximum_subjective_brier_score=Decimal("0.2"),
        maximum_model_brier_score=Decimal("0.2"),
        minimum_forecast_outcome_coverage=Decimal("1"),
    )
    assert R7MonitoringBlockerCode.ACTIVE_RESULT_INVALID in expired.blocker_codes
    assert R7MonitoringBlockerCode.REALIZATION_FUTURE_OR_EXPIRED in expired.blocker_codes

    unresolved_member = _fresh_member(fact.members[0], realized=None)
    unresolved = _fact_with_members(
        period,
        fact,
        (unresolved_member, fact.members[1]),
    )
    incomplete = evaluate_r7_post_promotion_monitoring(
        active=active,
        calendar=calendar,
        period=period,
        realization=unresolved,
        evaluated_at=fact.owner_record.recorded_at,
        maximum_subjective_brier_score=Decimal("0.2"),
        maximum_model_brier_score=Decimal("0.2"),
        minimum_forecast_outcome_coverage=Decimal("1"),
    )
    assert R7MonitoringBlockerCode.FORECAST_OUTCOME_INCOMPLETE in incomplete.blocker_codes


def test_prediction_and_active_projection_validate_all_nested_seals() -> None:
    """Prediction and active projections reject source, version, clock, and seal drift."""

    active, _, _, _ = _active_period_and_fact()
    prediction = active.predictions[0]
    with pytest.raises(TypeError, match="exact forecast row"):
        R7MonitoringPredictionMember.from_observation(object())
    cases = (
        ("prediction_version", "r7-monitoring-prediction.v2", "version is unsupported"),
        ("scenario_revision_id", "bad", "scenario revision is invalid"),
        ("scenario_set_revision_id", "bad", "scenario-set revision is invalid"),
        ("subjective_probability", Decimal("2"), "subjective probability is invalid"),
        ("model_probability", Decimal("0.5"), "projection is incomplete"),
        ("horizon_end", prediction.published_at, "horizon is invalid"),
        ("content_hash", "0" * 64, "content hash mismatch"),
    )
    for field, value, message in cases:
        with pytest.raises((TypeError, ValueError), match=message):
            replace(prediction, **{field: value})
    with pytest.raises(ValueError, match="model probability is invalid"):
        replace(
            prediction,
            model_probability=Decimal("2"),
            model_probability_source_version="model.v1",
            model_promotion_decision_id="decision:1",
        )

    def invalid_active(field: str, value: object, message: str) -> None:
        candidate = _copy_with(active, **{field: value})
        with pytest.raises((TypeError, ValueError), match=message):
            candidate.validate_live()

    invalid_active("active_version", "r7-active.v2", "version is unsupported")
    invalid_active("lifecycle_attestation_version", "bad", "attestation version is unsupported")
    invalid_active("lifecycle_event_count", 0, "event count is invalid")
    invalid_active("lifecycle_sequence", 0, "lifecycle sequence is invalid")
    invalid_active("lifecycle_sequence", 2, "count and sequence diverge")
    invalid_active(
        "lifecycle_recorded_at",
        active.promoted_at - timedelta(seconds=1),
        "lifecycle clocks are invalid",
    )
    invalid_active("predictions", (), "prediction projection is empty")
    fake_prediction = SimpleNamespace(
        entry_id=prediction.entry_id,
        observation_version=prediction.observation_version,
    )
    invalid_active("predictions", (fake_prediction,), "prediction member type is invalid")
    invalid_active("predictions", (prediction, prediction), "canonical and unique")
    invalid_active("predictions", tuple(reversed(active.predictions)), "canonical and unique")
    invalid_active("content_hash", "0" * 64, "content hash mismatch")


def test_lifecycle_attestation_and_stream_boundaries_are_explicit() -> None:
    """Owner stream attestations reject malformed, stale, or non-canonical evidence."""

    stream = _promotion_stream()
    attestation = _lifecycle_owner_evidence(stream)
    with pytest.raises(ValueError, match="complete stream"):
        R7LifecycleStreamOwnerEvidence.create(
            attestation_id="r7-empty",
            attestation_version=attestation.attestation_version,
            owner="research",
            lifecycle_stream=(),
            recorded_at=attestation.recorded_at,
            valid_until=attestation.valid_until,
            evidence_ref="research://r7/empty",
        )
    with pytest.raises(TypeError, match="invalid event"):
        R7LifecycleStreamOwnerEvidence.create(
            attestation_id="r7-object",
            attestation_version=attestation.attestation_version,
            owner="research",
            lifecycle_stream=(object(),),
            recorded_at=attestation.recorded_at,
            valid_until=attestation.valid_until,
            evidence_ref="research://r7/object",
        )
    for field, value, message in (
        ("attestation_version", "bad", "version is unsupported"),
        ("owner", "signal", "must be research"),
        ("event_count", 0, "event count is invalid"),
        ("recorded_at", attestation.valid_until, "already expired"),
        ("content_hash", "0" * 64, "content hash mismatch"),
    ):
        with pytest.raises(ValueError, match=message):
            replace(attestation, **{field: value})
    with pytest.raises(ValueError, match="stream is incomplete"):
        attestation.validate_stream(())
    with pytest.raises(TypeError, match="invalid event"):
        attestation.validate_stream((object(),))

    early = R7LifecycleStreamOwnerEvidence.create(
        attestation_id="r7-early-head",
        attestation_version=attestation.attestation_version,
        owner=attestation.owner,
        lifecycle_stream=stream,
        recorded_at=stream[-1].recorded_at - timedelta(seconds=1),
        valid_until=attestation.valid_until,
        evidence_ref="research://r7/early-head",
    )
    with pytest.raises(ValueError, match="predates its exact head"):
        early.validate_stream(stream)

    bad_sequence = copy.copy(stream[0])
    object.__setattr__(bad_sequence, "sequence", 2)
    object.__setattr__(bad_sequence, "content_hash", bad_sequence.calculated_content_hash)
    malformed_attestation = R7LifecycleStreamOwnerEvidence.create(
        attestation_id="r7-bad-sequence",
        attestation_version=attestation.attestation_version,
        owner=attestation.owner,
        lifecycle_stream=(bad_sequence,),
        recorded_at=attestation.recorded_at,
        valid_until=attestation.valid_until,
        evidence_ref="research://r7/bad-sequence",
    )
    result = make_result()
    with pytest.raises(ValueError, match="not canonical"):
        R7MonitoringActiveResult.from_owner_graph(
            result=result,
            lifecycle_stream=(bad_sequence,),
            lifecycle_owner_evidence=malformed_attestation,
        )


def test_active_graph_rejects_substituted_owner_types_before_projection() -> None:
    """Active projection keeps result, stream, and attestation owner types exact."""

    stream = _promotion_stream()
    attestation = _lifecycle_owner_evidence(stream)
    result = make_result()
    with pytest.raises(TypeError, match="result owner object"):
        R7MonitoringActiveResult.from_owner_graph(
            result=object(),
            lifecycle_stream=stream,
            lifecycle_owner_evidence=attestation,
        )
    with pytest.raises(TypeError, match="lifecycle owner evidence"):
        R7MonitoringActiveResult.from_owner_graph(
            result=result,
            lifecycle_stream=stream,
            lifecycle_owner_evidence=object(),
        )
    with pytest.raises(TypeError, match="lifecycle stream contains"):
        R7MonitoringActiveResult.from_owner_graph(
            result=result,
            lifecycle_stream=(object(),),
            lifecycle_owner_evidence=attestation,
        )


def test_period_and_calendar_contracts_reject_invalid_members_and_identity() -> None:
    """Period and calendar guards reject gaps, aliases, and timestamp/hash drift."""

    _, calendar, period, _ = _active_period_and_fact()
    with pytest.raises(ValueError, match="version is unsupported"):
        _copy_with(period, period_version="r7-monitoring-period.v2").__post_init__()
    with pytest.raises(ValueError, match="non-empty half-open"):
        _copy_with(period, period_end=period.period_start).__post_init__()
    with pytest.raises(ValueError, match="identity or hash mismatch"):
        _copy_with(period, content_hash="0" * 64).__post_init__()

    for field, value, message in (
        ("periods", (), "membership is incomplete"),
        ("periods", (object(),), "calendar member is invalid"),
    ):
        with pytest.raises((TypeError, ValueError), match=message):
            _copy_with(calendar, **{field: value}).__post_init__()

    foreign = R7MonitoringPeriodEntry.create(
        calendar_id="foreign-calendar",
        calendar_version="v1",
        period_start=period.period_start,
        period_end=period.period_end,
    )
    with pytest.raises(ValueError, match="member substitution"):
        _copy_with(calendar, periods=(foreign,)).__post_init__()

    midpoint = period.period_start + (period.period_end - period.period_start) / 2
    first = R7MonitoringPeriodEntry.create(
        calendar_id=period.calendar_id,
        calendar_version=period.calendar_version,
        period_start=period.period_start,
        period_end=midpoint,
    )
    second = R7MonitoringPeriodEntry.create(
        calendar_id=period.calendar_id,
        calendar_version=period.calendar_version,
        period_start=midpoint + timedelta(seconds=1),
        period_end=period.period_end,
    )
    with pytest.raises(ValueError, match="not contiguous"):
        _copy_with(calendar, periods=(first, second)).__post_init__()

    with pytest.raises(ValueError, match="not recorded"):
        _copy_with(
            calendar,
            recorded_at=calendar.valid_from + timedelta(seconds=1),
        ).__post_init__()
    with pytest.raises(ValueError, match="does not start"):
        _copy_with(
            calendar,
            valid_from=calendar.valid_from + timedelta(seconds=1),
        ).__post_init__()
    with pytest.raises(ValueError, match="does not end"):
        _copy_with(
            calendar,
            valid_until=calendar.valid_until + timedelta(seconds=1),
        ).__post_init__()
    with pytest.raises(ValueError, match="content hash mismatch"):
        _copy_with(calendar, content_hash="0" * 64).__post_init__()
    with pytest.raises(TypeError, match="candidate type"):
        calendar.require_exact_member(object())

    # Keep the public hash helpers exercised with the exact objects used above.
    assert period_entry_hash(period) == period.content_hash
    assert monitoring_calendar_hash(calendar) == calendar.content_hash


def test_evaluator_marks_invalid_active_and_expired_realization_clocks() -> None:
    """Evaluation emits both live-root and owner-expiry blockers at their boundaries."""

    active, calendar, period, fact = _active_period_and_fact()
    stale = evaluate_r7_post_promotion_monitoring(
        active=active,
        calendar=calendar,
        period=period,
        realization=fact,
        evaluated_at=active.lifecycle_recorded_at - timedelta(seconds=1),
        maximum_subjective_brier_score=Decimal("0.2"),
        maximum_model_brier_score=Decimal("0.2"),
        minimum_forecast_outcome_coverage=Decimal("1"),
    )
    assert R7MonitoringBlockerCode.ACTIVE_RESULT_INVALID in stale.blocker_codes

    with pytest.raises(ValueError, match="threshold is invalid"):
        evaluate_r7_post_promotion_monitoring(
            active=active,
            calendar=calendar,
            period=period,
            realization=fact,
            evaluated_at=fact.owner_record.recorded_at,
            maximum_subjective_brier_score=Decimal("NaN"),
            maximum_model_brier_score=Decimal("0.2"),
            minimum_forecast_outcome_coverage=Decimal("1"),
        )
