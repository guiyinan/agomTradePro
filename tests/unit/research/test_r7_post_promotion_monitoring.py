"""R7 post-promotion monitoring contracts stay evidence-bound and research-only."""

from __future__ import annotations

from dataclasses import fields
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from apps.research.domain.r7_post_promotion_monitoring import (
    R7ForecastRealizationFact,
    R7ForecastRealizationMember,
    R7ForecastRealizationOwnerRecord,
    R7MonitoringBlockerCode,
    R7MonitoringStatus,
    calculate_r7_brier_score,
    calculate_r7_forecast_outcome_coverage,
    calculate_r7_probability_coverage,
    derive_r7_monitoring_status,
    evaluate_r7_post_promotion_monitoring,
)
from apps.research.domain.r7_post_promotion_monitoring_contracts import (
    R7LifecycleStreamOwnerEvidence,
    R7MonitoringActiveResult,
    R7MonitoringPeriodCalendar,
    R7MonitoringPeriodEntry,
    R7MonitoringPredictionMember,
    active_result_hash,
)
from apps.research.domain.r7_research_result_lifecycle import (
    R7ResearchResultRef,
    R7ResultLifecycleAction,
    R7ResultLifecycleEvent,
    R7ResultPromotionAuthorization,
    create_r7_result_lifecycle_event,
)
from apps.research.domain.scenario_probability_contracts import (
    ForecastLedgerOutcomeObservation,
)
from apps.signal.domain.forecast_scenario_evidence import (
    ScenarioForecastBinding,
    ScenarioProbabilitySource,
)
from tests.unit.research.r7_research_result_factories import make_result


def _promotion_stream() -> tuple[R7ResultLifecycleEvent, ...]:
    result = make_result()
    result_ref = R7ResearchResultRef(
        result.result_id,
        result.result_version,
        result.content_hash,
    )
    recorded_at = result.recorded_at + timedelta(minutes=1)
    authorization = R7ResultPromotionAuthorization(
        authorization_id="r7-monitoring-promotion:1",
        authorization_version="r7-result-authorization.v1",
        result_ref=result_ref,
        event_id="r7-monitoring-promotion-event:1",
        event_version="r7-result-lifecycle-event.v1",
        action=R7ResultLifecycleAction.PROMOTE,
        expected_sequence=1,
        owner="research",
        issued_at=recorded_at - timedelta(seconds=1),
        recorded_at=recorded_at,
        valid_until=recorded_at + timedelta(days=30),
        reason_codes=("research-owner-reviewed",),
        evidence_ref="research://r7-monitoring-promotion/1",
    )
    event = create_r7_result_lifecycle_event(
        authorization=authorization,
        occurred_at=recorded_at,
        recorded_at=recorded_at + timedelta(seconds=1),
        previous_event_hash=None,
    )
    return (event,)


def _retired_stream() -> tuple[R7ResultLifecycleEvent, ...]:
    promotion = _promotion_stream()[0]
    result = make_result()
    result_ref = R7ResearchResultRef(
        result.result_id,
        result.result_version,
        result.content_hash,
    )
    recorded_at = promotion.recorded_at + timedelta(minutes=1)
    authorization = R7ResultPromotionAuthorization(
        authorization_id="r7-monitoring-retirement:1",
        authorization_version="r7-result-authorization.v1",
        result_ref=result_ref,
        event_id="r7-monitoring-retirement-event:1",
        event_version="r7-result-lifecycle-event.v1",
        action=R7ResultLifecycleAction.RETIRE,
        expected_sequence=2,
        owner="research",
        issued_at=recorded_at - timedelta(seconds=1),
        recorded_at=recorded_at,
        valid_until=recorded_at + timedelta(days=30),
        reason_codes=("research-owner-retired",),
        evidence_ref="research://r7-monitoring-retirement/1",
    )
    retirement = create_r7_result_lifecycle_event(
        authorization=authorization,
        occurred_at=recorded_at,
        recorded_at=recorded_at + timedelta(seconds=1),
        previous_event_hash=promotion.content_hash,
    )
    return (promotion, retirement)


def _lifecycle_owner_evidence(
    stream: tuple[R7ResultLifecycleEvent, ...],
) -> R7LifecycleStreamOwnerEvidence:
    return R7LifecycleStreamOwnerEvidence.create(
        attestation_id="r7-lifecycle-stream-owner:1",
        attestation_version="r7-lifecycle-stream-owner-evidence.v1",
        owner="research",
        lifecycle_stream=stream,
        recorded_at=stream[-1].recorded_at + timedelta(seconds=1),
        valid_until=stream[-1].recorded_at + timedelta(days=30),
        evidence_ref="research://r7-lifecycle-stream/1",
    )


def _active_period_and_fact() -> tuple[
    R7MonitoringActiveResult,
    R7MonitoringPeriodCalendar,
    R7MonitoringPeriodEntry,
    R7ForecastRealizationFact,
]:
    stream = _promotion_stream()
    result = make_result()
    active = R7MonitoringActiveResult.from_owner_graph(
        result=result,
        lifecycle_stream=stream,
        lifecycle_owner_evidence=_lifecycle_owner_evidence(stream),
    )
    period = R7MonitoringPeriodEntry.create(
        calendar_id="r7-monitoring-calendar",
        calendar_version="v1",
        period_start=max(item.published_at for item in active.predictions) + timedelta(seconds=1),
        period_end=active.predictions[0].horizon_end,
    )
    calendar = R7MonitoringPeriodCalendar.create(
        calendar_id=period.calendar_id,
        calendar_version=period.calendar_version,
        periods=(period,),
        recorded_at=period.period_start - timedelta(seconds=1),
        valid_from=period.period_start,
        valid_until=period.period_end,
    )
    latest_outcome_clock = max(
        observation.outcome_recorded_at or observation.horizon_end
        for observation in result.evidence_graph.forecast_observations
    )
    member_available_at = latest_outcome_clock + timedelta(minutes=1)
    member_recorded_at = member_available_at + timedelta(minutes=1)
    members = tuple(
        R7ForecastRealizationMember.from_owner_observation(
            observation=observation,
            available_at=member_available_at,
            recorded_at=member_recorded_at,
            evidence_ref=f"signal://forecast-realization/{observation.entry_id}",
        )
        for observation in result.evidence_graph.forecast_observations
    )
    owner_record = R7ForecastRealizationOwnerRecord.create(
        owner_record_id="forecast-realization-owner:1",
        owner_record_version="signal-forecast-realization-owner.v1",
        period=period,
        pit_as_of=member_recorded_at + timedelta(minutes=2),
        available_at=member_recorded_at,
        recorded_at=member_recorded_at + timedelta(minutes=1),
        valid_until=active.lifecycle_valid_until,
        evidence_ref="signal://forecast-realization-owner/1",
        members=members,
    )
    fact = R7ForecastRealizationFact.from_owner_record(
        period=period,
        owner_record=owner_record,
    )
    return active, calendar, period, fact


def test_active_result_requires_complete_promoted_lifecycle_stream() -> None:
    result = make_result()
    stream = _promotion_stream()
    owner_evidence = _lifecycle_owner_evidence(stream)

    active = R7MonitoringActiveResult.from_owner_graph(
        result=result,
        lifecycle_stream=stream,
        lifecycle_owner_evidence=owner_evidence,
    )

    assert active.lifecycle_sequence == 1
    assert active.lifecycle_head_hash == stream[-1].content_hash
    assert active.predictions
    assert all(item.published_at < item.horizon_end for item in active.predictions)

    constructor_values = {item.name: getattr(active, item.name) for item in fields(active)}
    with pytest.raises(TypeError, match="minted from owner graph"):
        R7MonitoringActiveResult(**constructor_values)

    with pytest.raises(ValueError, match="lifecycle"):
        R7MonitoringActiveResult.from_owner_graph(
            result=result,
            lifecycle_stream=(),
            lifecycle_owner_evidence=owner_evidence,
        )

    retired_stream = _retired_stream()
    with pytest.raises(ValueError, match="currently promoted"):
        R7MonitoringActiveResult.from_owner_graph(
            result=result,
            lifecycle_stream=retired_stream,
            lifecycle_owner_evidence=_lifecycle_owner_evidence(retired_stream),
        )

    with pytest.raises(ValueError, match="attestation"):
        R7MonitoringActiveResult.from_owner_graph(
            result=result,
            lifecycle_stream=retired_stream[:1],
            lifecycle_owner_evidence=_lifecycle_owner_evidence(retired_stream),
        )


def test_brier_uses_independent_exact_realization_members_by_source() -> None:
    result = make_result()
    observations = result.evidence_graph.forecast_observations
    stream = _promotion_stream()
    active = R7MonitoringActiveResult.from_owner_graph(
        result=result,
        lifecycle_stream=stream,
        lifecycle_owner_evidence=_lifecycle_owner_evidence(stream),
    )
    first, second = active.predictions
    period = R7MonitoringPeriodEntry.create(
        calendar_id="r7-monitoring-calendar",
        calendar_version="v1",
        period_start=max(first.published_at, second.published_at) + timedelta(seconds=1),
        period_end=first.horizon_end,
    )
    latest_outcome_clock = max(
        observation.outcome_recorded_at or observation.horizon_end for observation in observations
    )
    member_available_at = latest_outcome_clock + timedelta(minutes=1)
    member_recorded_at = member_available_at + timedelta(minutes=1)
    owner_record = R7ForecastRealizationOwnerRecord.create(
        owner_record_id="forecast-realization-owner:brier",
        owner_record_version="signal-forecast-realization-owner.v1",
        period=period,
        pit_as_of=member_recorded_at + timedelta(minutes=2),
        available_at=member_recorded_at,
        recorded_at=member_recorded_at + timedelta(minutes=1),
        valid_until=member_recorded_at + timedelta(days=2),
        evidence_ref="signal://forecast-realization-owner/brier",
        members=tuple(
            R7ForecastRealizationMember.from_owner_observation(
                observation=observation,
                available_at=member_available_at,
                recorded_at=member_recorded_at,
                evidence_ref=f"signal://forecast-realization/{observation.entry_id}",
            )
            for observation in observations
        ),
    )
    fact = R7ForecastRealizationFact.from_owner_record(
        period=period,
        owner_record=owner_record,
    )

    subjective = calculate_r7_brier_score(
        active=active,
        period=period,
        realization=fact,
        source=ScenarioProbabilitySource.SUBJECTIVE,
    )
    model = calculate_r7_brier_score(
        active=active,
        period=period,
        realization=fact,
        source=ScenarioProbabilitySource.MODEL_INFERRED,
    )

    assert subjective == Decimal("0.1225")
    assert model is None
    assert calculate_r7_probability_coverage(
        active=active,
        period=period,
        realization=fact,
        source=ScenarioProbabilitySource.SUBJECTIVE,
    ) == Decimal("1")
    assert calculate_r7_probability_coverage(
        active=active,
        period=period,
        realization=fact,
        source=ScenarioProbabilitySource.MODEL_INFERRED,
    ) == Decimal("0")


def test_prediction_projection_ignores_embedded_post_period_outcome() -> None:
    result = make_result()
    observation = result.evidence_graph.forecast_observations[0]
    replacement = ForecastLedgerOutcomeObservation.create(
        observation_version=observation.observation_version,
        entry_id=observation.entry_id,
        forecast_group_id=observation.forecast_group_id,
        binding=ScenarioForecastBinding.from_values(
            scenario_revision_id=observation.binding.scenario_revision_id,
            scenario_set_revision_id=observation.binding.scenario_set_revision_id,
            subjective_probability=observation.binding.subjective_probability,
            subjective_probability_source_version=(
                observation.binding.subjective_probability_source_version
            ),
        ),
        pit_manifest_id=observation.pit_manifest_id,
        pit_manifest_version=observation.pit_manifest_version,
        pit_manifest_hash=observation.pit_manifest_hash,
        censoring_rule_version=observation.censoring_rule_version,
        published_at=observation.published_at,
        horizon_end=observation.horizon_end,
        scenario_realized=not observation.scenario_realized,
        outcome_recorded_at=observation.outcome_recorded_at,
        outcome_evidence_valid_until=observation.outcome_evidence_valid_until,
    )

    assert replacement.content_hash != observation.content_hash
    assert R7MonitoringActiveResult.prediction_hash_from_observation(replacement) == (
        R7MonitoringActiveResult.prediction_hash_from_observation(observation)
    )


def test_realization_requires_exact_owner_members_and_live_seals() -> None:
    active, _, period, fact = _active_period_and_fact()
    first, second = fact.members
    source = next(
        item
        for item in make_result().evidence_graph.forecast_observations
        if item.entry_id == first.entry_id
    )
    substituted_observation = ForecastLedgerOutcomeObservation.create(
        observation_version=source.observation_version,
        entry_id=source.entry_id,
        forecast_group_id=source.forecast_group_id,
        binding=ScenarioForecastBinding.from_values(
            scenario_revision_id=uuid4(),
            scenario_set_revision_id=source.binding.scenario_set_revision_id,
            subjective_probability=source.binding.subjective_probability,
            subjective_probability_source_version=(
                source.binding.subjective_probability_source_version
            ),
            model_probability=source.binding.model_probability,
            model_probability_source_version=(source.binding.model_probability_source_version),
            model_promotion_decision_id=source.binding.model_promotion_decision_id,
        ),
        pit_manifest_id=source.pit_manifest_id,
        pit_manifest_version=source.pit_manifest_version,
        pit_manifest_hash=source.pit_manifest_hash,
        censoring_rule_version=source.censoring_rule_version,
        published_at=source.published_at,
        horizon_end=source.horizon_end,
        scenario_realized=source.scenario_realized,
        outcome_recorded_at=source.outcome_recorded_at,
        outcome_evidence_valid_until=source.outcome_evidence_valid_until,
        invalidation=source.invalidation,
    )
    substituted_member = R7ForecastRealizationMember.from_owner_observation(
        observation=substituted_observation,
        available_at=first.available_at,
        recorded_at=first.recorded_at,
        evidence_ref=first.evidence_ref,
    )
    owner_record = R7ForecastRealizationOwnerRecord.create(
        owner_record_id="forecast-realization-owner:substituted",
        owner_record_version=fact.owner_record.owner_record_version,
        period=period,
        pit_as_of=fact.owner_record.pit_as_of,
        available_at=fact.owner_record.available_at,
        recorded_at=fact.owner_record.recorded_at,
        valid_until=fact.owner_record.valid_until,
        evidence_ref="signal://forecast-realization-owner/substituted",
        members=(substituted_member, second),
    )
    substituted = R7ForecastRealizationFact.from_owner_record(
        period=period,
        owner_record=owner_record,
    )

    with pytest.raises(ValueError, match="exact predictions"):
        calculate_r7_forecast_outcome_coverage(
            active=active,
            period=period,
            realization=substituted,
        )

    with pytest.raises(ValueError, match="PIT clocks"):
        R7ForecastRealizationOwnerRecord.create(
            owner_record_id="forecast-realization-owner:early-cutoff",
            owner_record_version=fact.owner_record.owner_record_version,
            period=period,
            pit_as_of=fact.owner_record.available_at - timedelta(microseconds=1),
            available_at=fact.owner_record.available_at,
            recorded_at=fact.owner_record.recorded_at,
            valid_until=fact.owner_record.valid_until,
            evidence_ref="signal://forecast-realization-owner/early-cutoff",
            members=fact.members,
        )

    object.__setattr__(first, "realized", not first.realized)
    with pytest.raises(ValueError, match="content hash mismatch"):
        fact.validated_copy()


def test_missing_supplemental_owner_evidence_stays_blocked_and_research_only() -> None:
    active, calendar, period, fact = _active_period_and_fact()

    assessment = evaluate_r7_post_promotion_monitoring(
        active=active,
        calendar=calendar,
        period=period,
        realization=fact,
        evaluated_at=active.lifecycle_recorded_at + timedelta(seconds=1),
        maximum_subjective_brier_score=Decimal("0.20"),
        maximum_model_brier_score=Decimal("0.20"),
        minimum_forecast_outcome_coverage=Decimal("1"),
    )

    assert assessment.status is R7MonitoringStatus.BLOCKED
    assert assessment.blocker_codes == (
        R7MonitoringBlockerCode.CALIBRATION_EVIDENCE_UNAVAILABLE,
        R7MonitoringBlockerCode.HISTORICAL_ANALOGY_EVIDENCE_UNAVAILABLE,
        R7MonitoringBlockerCode.PATH_EVIDENCE_UNAVAILABLE,
    )
    assert assessment.research_only is True
    assert assessment.manual_retirement_review_required is False
    assert assessment.automatic_retirement is False
    assert assessment.trains_probability_model is False
    assert assessment.publishes_model_probability is False
    assert assessment.publishes_probability_current is False
    assert assessment.produces_decision is False
    assert assessment.executes_orders is False
    assert assessment.must_not_use_for_decision is True
    assert assessment.must_not_execute is True


def test_calendar_membership_and_strict_pre_period_publication_are_required() -> None:
    active, calendar, period, fact = _active_period_and_fact()
    alias = R7MonitoringPeriodEntry.create(
        calendar_id=period.calendar_id,
        calendar_version=period.calendar_version,
        period_start=period.period_start + timedelta(seconds=1),
        period_end=period.period_end,
    )

    with pytest.raises(ValueError, match="calendar member"):
        evaluate_r7_post_promotion_monitoring(
            active=active,
            calendar=calendar,
            period=alias,
            realization=fact,
            evaluated_at=fact.owner_record.recorded_at,
            maximum_subjective_brier_score=Decimal("0.20"),
            maximum_model_brier_score=Decimal("0.20"),
            minimum_forecast_outcome_coverage=Decimal("1"),
        )

    equal_start = R7MonitoringPeriodEntry.create(
        calendar_id=period.calendar_id,
        calendar_version="equal-start",
        period_start=active.predictions[0].published_at,
        period_end=period.period_end,
    )
    equal_owner = R7ForecastRealizationOwnerRecord.create(
        owner_record_id="forecast-realization-owner:equal-start",
        owner_record_version=fact.owner_record.owner_record_version,
        period=equal_start,
        pit_as_of=fact.owner_record.pit_as_of,
        available_at=fact.owner_record.available_at,
        recorded_at=fact.owner_record.recorded_at,
        valid_until=fact.owner_record.valid_until,
        evidence_ref="signal://forecast-realization-owner/equal-start",
        members=fact.members,
    )
    equal_fact = R7ForecastRealizationFact.from_owner_record(
        period=equal_start,
        owner_record=equal_owner,
    )
    with pytest.raises(ValueError, match="pre-period"):
        calculate_r7_forecast_outcome_coverage(
            active=active,
            period=equal_start,
            realization=equal_fact,
        )


def test_later_horizon_prediction_does_not_block_an_earlier_period() -> None:
    active, _, period, fact = _active_period_and_fact()
    source = make_result().evidence_graph.forecast_observations[0]
    future_horizon = period.period_end + timedelta(days=90)
    future_observation = ForecastLedgerOutcomeObservation.create(
        observation_version=source.observation_version,
        entry_id="r7-forecast:future",
        forecast_group_id="r7-forecast-group:future",
        binding=source.binding,
        pit_manifest_id=source.pit_manifest_id,
        pit_manifest_version=source.pit_manifest_version,
        pit_manifest_hash=source.pit_manifest_hash,
        censoring_rule_version=source.censoring_rule_version,
        published_at=period.period_start + timedelta(days=1),
        horizon_end=future_horizon,
        scenario_realized=True,
        outcome_recorded_at=future_horizon + timedelta(hours=1),
        outcome_evidence_valid_until=future_horizon + timedelta(days=30),
    )
    future_prediction = R7MonitoringPredictionMember.from_observation(future_observation)
    object.__setattr__(
        active,
        "predictions",
        tuple(
            sorted(
                (*active.predictions, future_prediction),
                key=lambda item: (item.entry_id, item.observation_version),
            )
        ),
    )
    object.__setattr__(active, "content_hash", active_result_hash(active))
    active.validate_live()

    assert calculate_r7_forecast_outcome_coverage(
        active=active,
        period=period,
        realization=fact,
    ) == Decimal("1")


def test_monitoring_status_precedence_is_explicit_and_manual() -> None:
    assert (
        derive_r7_monitoring_status(
            blocker_codes=(),
            threshold_breached=False,
            falsification_detected=False,
        )
        is R7MonitoringStatus.HEALTHY
    )
    assert (
        derive_r7_monitoring_status(
            blocker_codes=(),
            threshold_breached=True,
            falsification_detected=False,
        )
        is R7MonitoringStatus.BREACHED
    )
    assert (
        derive_r7_monitoring_status(
            blocker_codes=(),
            threshold_breached=True,
            falsification_detected=True,
        )
        is R7MonitoringStatus.RETIREMENT_REVIEW_REQUIRED
    )
    assert (
        derive_r7_monitoring_status(
            blocker_codes=(R7MonitoringBlockerCode.PATH_EVIDENCE_UNAVAILABLE,),
            threshold_breached=True,
            falsification_detected=True,
        )
        is R7MonitoringStatus.BLOCKED
    )
