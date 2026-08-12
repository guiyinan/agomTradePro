"""Synthetic contract tests for the R2 explanatory trial and monitoring."""

from __future__ import annotations

from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from apps.research.application.r2_market_structure_trial_monitoring import (
    EvaluateR2MarketStructureExplanatoryTrial,
    EvaluateR2MarketStructureMonitoring,
    EvaluateR2MarketStructureTrialCommand,
)
from apps.research.domain.r2_market_structure_trial_monitoring import (
    R2_AUDIT_OUTCOME_VERSION,
    R2_MONITORING_FACT_VERSION,
    R2AuditExplanatoryOutcome,
    R2AuditMetric,
    R2CanonicalPublicationEvidence,
    R2CyclePITEvidence,
    R2EvidenceRef,
    R2ExplanatoryMetricKey,
    R2MarketStructureTrialPolicy,
    R2MonitoringRawFact,
    R2MonitoringStatus,
    R2PublicationKind,
    R2PublicationRef,
    R2ThresholdDirection,
    R2TrialBlockerCode,
    R2TrialStatus,
    derive_r2_audit_outcome_id,
    derive_r2_monitoring_fact_id,
    derive_r2_pit_manifest_ref,
    evaluate_r2_explanatory_trial,
    evaluate_r2_monitoring,
    r2_audit_outcome_hash,
    r2_monitoring_fact_hash,
    r2_trial_policy_hash,
)
from tests.unit.research.r2_market_structure_trial_monitoring_factories import (
    NOW,
    R2SyntheticScenario,
    build_r2_scenario,
    digest,
)


def _trial(
    scenario: R2SyntheticScenario,
    *,
    taxonomy: R2CanonicalPublicationEvidence | None = None,
    calendar: R2CanonicalPublicationEvidence | None = None,
    cycles: tuple[R2CyclePITEvidence, ...] | None = None,
    audit: R2AuditExplanatoryOutcome | None = None,
):
    return evaluate_r2_explanatory_trial(
        policy=scenario.policy,
        taxonomy_publication=taxonomy or scenario.taxonomy,
        calendar_publication=calendar or scenario.calendar,
        cycle_evidence=cycles if cycles is not None else scenario.cycles,
        audit_outcome=audit or scenario.audit,
        assessed_at=NOW,
    )


def test_preregistered_two_cycle_policy_is_exact_and_non_predictive() -> None:
    scenario = build_r2_scenario()

    assessment = _trial(scenario)

    assert scenario.policy.registered_at < scenario.policy.selection_as_of
    assert len(scenario.policy.cycles) == 2
    assert scenario.policy.cycles[0].cycle_end <= scenario.policy.cycles[1].cycle_start
    assert assessment.status is R2TrialStatus.PASSED
    assert assessment.research_only is True
    assert assessment.must_not_use_as_predictive_signal is True
    assert assessment.must_not_publish_current is True
    assert assessment.must_not_use_for_decision is True
    assert assessment.must_not_execute is True
    assert assessment.is_attested_ready is False


def test_policy_rejects_overlapping_expected_periods() -> None:
    scenario = build_r2_scenario()
    periods = list(scenario.policy.expected_periods)
    periods[1] = replace(
        periods[1],
        period_start=periods[0].period_end - timedelta(hours=1),
    )

    with pytest.raises(ValueError, match="expected periods cannot overlap"):
        replace(scenario.policy, expected_periods=tuple(periods))


@pytest.mark.parametrize(
    ("metric_key", "value"),
    (
        (R2ExplanatoryMetricKey.STABILITY_SCORE, Decimal("0.60")),
        (R2ExplanatoryMetricKey.INCREMENTAL_EXPLANATORY_POWER, Decimal("0.01")),
    ),
)
def test_trial_threshold_breach_is_descriptive_only(
    metric_key: R2ExplanatoryMetricKey,
    value: Decimal,
) -> None:
    scenario = build_r2_scenario()
    metrics = tuple(
        (
            replace(metric, value=value)
            if metric.metric_key is metric_key and metric.cycle_id == "cycle_2"
            else metric
        )
        for metric in scenario.audit.metrics
    )

    assessment = _trial(scenario, audit=replace(scenario.audit, metrics=metrics))

    assert assessment.status is R2TrialStatus.BREACHED
    assert metric_key in assessment.breached_metrics
    assert assessment.must_not_use_as_predictive_signal is True
    assert assessment.must_not_use_for_decision is True


def test_multiple_testing_adjustment_is_bound_to_preregistered_family() -> None:
    scenario = build_r2_scenario()
    metrics = tuple(
        (
            replace(
                metric,
                raw_p_value=(Decimal("0.03") if metric.cycle_id == "cycle_1" else Decimal("0.04")),
            )
            if metric.metric_key is R2ExplanatoryMetricKey.INCREMENTAL_EXPLANATORY_POWER
            else metric
        )
        for metric in scenario.audit.metrics
    )

    assessment = _trial(scenario, audit=replace(scenario.audit, metrics=metrics))

    assert assessment.status is R2TrialStatus.BREACHED
    assert R2ExplanatoryMetricKey.INCREMENTAL_EXPLANATORY_POWER in (assessment.breached_metrics)
    assert tuple(item.hypothesis_id for item in assessment.holm_adjustments) == (
        "cycle_1:incremental_explanatory_power",
        "cycle_2:incremental_explanatory_power",
    )
    assert tuple(item.adjusted_p_value for item in assessment.holm_adjustments) == (
        Decimal("0.06"),
        Decimal("0.06"),
    )
    assert "adjusted_p_value" not in R2AuditMetric.__dataclass_fields__

    wrong_family = tuple(
        (
            replace(metric, test_family_id="different-family")
            if metric.metric_key is R2ExplanatoryMetricKey.INCREMENTAL_EXPLANATORY_POWER
            else metric
        )
        for metric in scenario.audit.metrics
    )
    blocked = _trial(scenario, audit=replace(scenario.audit, metrics=wrong_family))
    assert blocked.status is R2TrialStatus.BLOCKED
    assert R2TrialBlockerCode.MULTIPLE_TEST_BINDING_INVALID in blocked.blockers


def test_publication_private_mutation_is_detected_by_live_seal_recomputation() -> None:
    scenario = build_r2_scenario()
    object.__setattr__(scenario.taxonomy, "valid_until", NOW - timedelta(seconds=1))

    assessment = _trial(scenario)

    assert assessment.status is R2TrialStatus.BLOCKED
    assert R2TrialBlockerCode.PUBLICATION_REPLACED in assessment.blockers
    assert R2TrialBlockerCode.PUBLICATION_STALE in assessment.blockers


def test_policy_seals_selection_known_publication_projections() -> None:
    scenario = build_r2_scenario()

    assert scenario.policy.taxonomy_projection_seal.projection_hash == (
        scenario.taxonomy.content_hash
    )
    assert scenario.policy.calendar_projection_seal.projection_hash == (
        scenario.calendar.content_hash
    )
    assert scenario.policy.taxonomy_projection_seal.recorded_at <= (scenario.policy.registered_at)
    assert scenario.policy.calendar_projection_seal.recorded_at <= (scenario.policy.registered_at)

    late_seal = replace(
        scenario.policy.taxonomy_projection_seal,
        recorded_at=scenario.policy.registered_at + timedelta(seconds=1),
    )
    with pytest.raises(ValueError, match="known before policy registration"):
        replace(scenario.policy, taxonomy_projection_seal=late_seal)

    same_reference_replacement = replace(
        scenario.taxonomy,
        valid_until=scenario.taxonomy.valid_until + timedelta(days=1),
    )
    assessment = _trial(scenario, taxonomy=same_reference_replacement)
    assert assessment.status is R2TrialStatus.BLOCKED
    assert R2TrialBlockerCode.PUBLICATION_REPLACED in assessment.blockers


def test_cycle_future_knowledge_and_unit_substitution_fail_closed() -> None:
    scenario = build_r2_scenario()
    future = replace(
        scenario.cycles[0],
        observed_at=NOW + timedelta(hours=1),
        available_at=NOW + timedelta(hours=1),
        recorded_at=NOW + timedelta(hours=1),
        valid_from=NOW + timedelta(hours=1),
        valid_until=NOW + timedelta(days=1),
    )
    substituted_period = next(
        item
        for item in scenario.policy.expected_periods
        if item.period_id == scenario.cycles[1].samples[0].period_id
    )
    substituted_sample = replace(
        scenario.cycles[1].samples[0],
        unit="percent",
        available_at=substituted_period.period_end - timedelta(seconds=1),
    )
    substituted = replace(
        scenario.cycles[1],
        samples=(substituted_sample, *scenario.cycles[1].samples[1:]),
    )

    assessment = _trial(scenario, cycles=(future, substituted))

    assert assessment.status is R2TrialStatus.BLOCKED
    assert R2TrialBlockerCode.CYCLE_EVIDENCE_FROM_FUTURE in assessment.blockers
    assert R2TrialBlockerCode.CYCLE_EVIDENCE_INVALID in assessment.blockers
    assert R2TrialBlockerCode.UNIT_MISMATCH in assessment.blockers


def test_cycle_evidence_is_selection_known_and_bound_to_calendar_membership() -> None:
    scenario = build_r2_scenario()
    selection = scenario.policy.selection_as_of
    after_selection = replace(
        scenario.cycles[0],
        available_at=selection + timedelta(hours=1),
        recorded_at=selection + timedelta(hours=2),
        valid_from=selection + timedelta(hours=2),
    )
    late_assessment = _trial(
        scenario,
        cycles=(after_selection, scenario.cycles[1]),
    )
    assert R2TrialBlockerCode.SELECTION_LEAKAGE in late_assessment.blockers

    sample = scenario.cycles[0].samples[0]
    foreign_observation = R2EvidenceRef(
        evidence_id="foreign-observation",
        evidence_version="v1",
        content_hash=digest("foreign-observation"),
    )
    foreign_sample = replace(
        sample,
        observation_refs=(foreign_observation, *sample.observation_refs[1:]),
        pit_manifest_ref=derive_r2_pit_manifest_ref(
            period_id=sample.period_id,
            series_code=sample.series_code,
            series_version=sample.series_version,
            observation_refs=(foreign_observation, *sample.observation_refs[1:]),
        ),
    )
    wrong_manifest_sample = replace(scenario.cycles[1].samples[0])
    object.__setattr__(
        wrong_manifest_sample,
        "pit_manifest_ref",
        R2EvidenceRef(
            evidence_id="different-manifest",
            evidence_version="v1",
            content_hash=digest("different-manifest"),
        ),
    )
    changed_cycles = (
        replace(
            scenario.cycles[0],
            samples=(foreign_sample, *scenario.cycles[0].samples[1:]),
        ),
        replace(
            scenario.cycles[1],
            samples=(wrong_manifest_sample, *scenario.cycles[1].samples[1:]),
        ),
    )
    manifest_assessment = _trial(scenario, cycles=changed_cycles)
    assert R2TrialBlockerCode.SAMPLE_DENOMINATOR_INVALID in (manifest_assessment.blockers)
    assert R2TrialBlockerCode.CYCLE_EVIDENCE_INVALID in manifest_assessment.blockers
    assert "observation_count" not in sample.__dataclass_fields__
    assert "expected_observation_count" not in sample.__dataclass_fields__
    with pytest.raises(ValueError, match="expected PIT manifest seal is invalid"):
        replace(
            scenario.policy.expected_series_period_entries[0],
            pit_manifest_ref=R2EvidenceRef(
                evidence_id="changed-expected-manifest",
                evidence_version="v1",
                content_hash=digest("changed-expected-manifest"),
            ),
        )


def test_missing_cycle_and_bad_audit_denominator_fail_closed() -> None:
    scenario = build_r2_scenario()
    missing = _trial(scenario, cycles=(scenario.cycles[0],))
    metrics = tuple(
        (
            replace(metric, sample_count=39)
            if metric.cycle_id == "cycle_1"
            and metric.metric_key is R2ExplanatoryMetricKey.COVERAGE_RATIO
            else metric
        )
        for metric in scenario.audit.metrics
    )
    bad_denominator = _trial(
        scenario,
        audit=replace(scenario.audit, metrics=metrics),
    )

    assert R2TrialBlockerCode.CYCLE_EVIDENCE_MISSING in missing.blockers
    assert R2TrialBlockerCode.SAMPLE_DENOMINATOR_INVALID in bad_denominator.blockers


def test_audit_outcome_cannot_be_known_before_selection() -> None:
    scenario = build_r2_scenario()
    selection = scenario.policy.selection_as_of
    leaked = replace(
        scenario.audit,
        observed_at=selection - timedelta(days=3),
        available_at=selection - timedelta(days=2),
        recorded_at=selection - timedelta(days=1),
        valid_from=selection - timedelta(days=1),
    )

    assessment = _trial(scenario, audit=leaked)

    assert assessment.status is R2TrialStatus.BLOCKED
    assert R2TrialBlockerCode.SELECTION_LEAKAGE in assessment.blockers


def test_audit_outcome_clocks_follow_both_cycle_evidence_records() -> None:
    scenario = build_r2_scenario()
    latest_cycle_record = max(item.recorded_at for item in scenario.cycles)
    premature = replace(
        scenario.audit,
        observed_at=latest_cycle_record,
        available_at=latest_cycle_record + timedelta(minutes=1),
        recorded_at=latest_cycle_record + timedelta(minutes=2),
        valid_from=latest_cycle_record + timedelta(minutes=2),
    )

    assessment = _trial(scenario, audit=premature)

    assert assessment.status is R2TrialStatus.BLOCKED
    assert R2TrialBlockerCode.SELECTION_LEAKAGE in assessment.blockers


def _monitoring(scenario: R2SyntheticScenario):
    return evaluate_r2_monitoring(
        policy=scenario.policy,
        taxonomy_publication=scenario.taxonomy,
        calendar_publication=scenario.calendar,
        trial_assessment=_trial(scenario),
        facts=scenario.monitoring_facts,
        assessed_at=NOW,
    )


def test_monitoring_healthy_facts_remain_research_only() -> None:
    assessment = _monitoring(build_r2_scenario())

    assert assessment.status is R2MonitoringStatus.HEALTHY
    assert assessment.retirement_review_required is False
    assert assessment.automatic_retirement is False
    assert assessment.must_not_use_as_predictive_signal is True
    assert assessment.must_not_publish_current is True
    assert assessment.must_not_use_for_decision is True
    assert assessment.must_not_execute is True


def test_one_breach_does_not_auto_retire_but_two_require_manual_review() -> None:
    one = _monitoring(build_r2_scenario(monitoring_breaches=(False, False, True)))
    two = _monitoring(build_r2_scenario(monitoring_breaches=(False, True, True)))

    assert one.status is R2MonitoringStatus.BREACHED
    assert one.retirement_review_required is False
    assert two.status is R2MonitoringStatus.RETIREMENT_REVIEW_REQUIRED
    assert two.retirement_review_required is True
    assert two.automatic_retirement is False
    assert any(reason.startswith("consecutive_breach:") for reason in two.review_reasons)


def test_label_drift_requires_manual_retirement_review() -> None:
    assessment = _monitoring(build_r2_scenario(latest_label_hash=digest("substituted-label-set")))

    assert assessment.status is R2MonitoringStatus.RETIREMENT_REVIEW_REQUIRED
    assert assessment.review_reasons == ("label_drift",)
    assert assessment.automatic_retirement is False


def test_monitoring_stale_overlap_unit_and_private_mutation_fail_closed() -> None:
    scenario = build_r2_scenario()
    stale = replace(
        scenario.monitoring_facts[-1],
        valid_until=NOW - timedelta(seconds=1),
    )
    overlapping = replace(
        scenario.monitoring_facts[1],
        period_start=scenario.monitoring_facts[0].period_end - timedelta(hours=1),
    )
    bad_metric = replace(scenario.monitoring_facts[-1].metrics[0])
    object.__setattr__(bad_metric, "unit", "percent")
    bad_unit = replace(
        scenario.monitoring_facts[-1],
        metrics=(bad_metric, *scenario.monitoring_facts[-1].metrics[1:]),
    )
    tampered = replace(scenario.monitoring_facts[-1])
    object.__setattr__(tampered, "source_owner", "substituted_owner")

    cases = (
        (*scenario.monitoring_facts[:-1], stale),
        (scenario.monitoring_facts[0], overlapping, scenario.monitoring_facts[2]),
        (*scenario.monitoring_facts[:-1], bad_unit),
        (*scenario.monitoring_facts[:-1], tampered),
        (scenario.monitoring_facts[0], scenario.monitoring_facts[2]),
    )
    expected = (
        R2TrialBlockerCode.MONITORING_FACT_STALE,
        R2TrialBlockerCode.MONITORING_PERIOD_OVERLAP,
        R2TrialBlockerCode.UNIT_MISMATCH,
        R2TrialBlockerCode.MONITORING_FACT_REPLACED,
        R2TrialBlockerCode.MONITORING_PERIOD_INVALID,
    )

    for facts, blocker in zip(cases, expected, strict=True):
        assessment = evaluate_r2_monitoring(
            policy=scenario.policy,
            taxonomy_publication=scenario.taxonomy,
            calendar_publication=scenario.calendar,
            trial_assessment=_trial(scenario),
            facts=facts,
            assessed_at=NOW,
        )
        assert assessment.status is R2MonitoringStatus.BLOCKED
        assert blocker in assessment.blockers


def test_monitoring_coverage_is_recomputed_from_sample_denominator() -> None:
    scenario = build_r2_scenario()
    coverage = scenario.monitoring_facts[-1].metrics[0]
    inconsistent_coverage = replace(coverage, value=Decimal("0.99"))
    changed_fact = replace(
        scenario.monitoring_facts[-1],
        metrics=(inconsistent_coverage, *scenario.monitoring_facts[-1].metrics[1:]),
    )

    assessment = evaluate_r2_monitoring(
        policy=scenario.policy,
        taxonomy_publication=scenario.taxonomy,
        calendar_publication=scenario.calendar,
        trial_assessment=_trial(scenario),
        facts=(*scenario.monitoring_facts[:-1], changed_fact),
        assessed_at=NOW,
    )

    assert assessment.status is R2MonitoringStatus.BLOCKED
    assert R2TrialBlockerCode.SAMPLE_DENOMINATOR_INVALID in assessment.blockers


def test_monitoring_freshness_remains_anchored_to_source_period() -> None:
    scenario = build_r2_scenario()
    period_end = scenario.monitoring_facts[0].period_end
    premature_fact = replace(
        scenario.monitoring_facts[0],
        observed_at=period_end - timedelta(minutes=3),
        available_at=period_end - timedelta(minutes=2),
        recorded_at=period_end - timedelta(minutes=1),
        valid_from=period_end - timedelta(minutes=1),
    )
    premature_assessment = evaluate_r2_monitoring(
        policy=scenario.policy,
        taxonomy_publication=scenario.taxonomy,
        calendar_publication=scenario.calendar,
        trial_assessment=_trial(scenario),
        facts=(premature_fact, *scenario.monitoring_facts[1:]),
        assessed_at=NOW,
    )
    assert R2TrialBlockerCode.MONITORING_PERIOD_INVALID in (premature_assessment.blockers)

    assessed_at = NOW + timedelta(days=3)
    refreshed_record = replace(
        scenario.monitoring_facts[-1],
        available_at=NOW + timedelta(days=2),
        recorded_at=NOW + timedelta(days=2, minutes=1),
        valid_from=NOW + timedelta(days=2, minutes=1),
    )

    assessment = evaluate_r2_monitoring(
        policy=scenario.policy,
        taxonomy_publication=scenario.taxonomy,
        calendar_publication=scenario.calendar,
        trial_assessment=evaluate_r2_explanatory_trial(
            policy=scenario.policy,
            taxonomy_publication=scenario.taxonomy,
            calendar_publication=scenario.calendar,
            cycle_evidence=scenario.cycles,
            audit_outcome=scenario.audit,
            assessed_at=assessed_at,
        ),
        facts=(*scenario.monitoring_facts[:-1], refreshed_record),
        assessed_at=assessed_at,
    )

    assert assessment.status is R2MonitoringStatus.BLOCKED
    assert R2TrialBlockerCode.MONITORING_FACT_STALE in assessment.blockers


def test_metric_domains_and_threshold_direction_are_closed() -> None:
    scenario = build_r2_scenario()
    audit_coverage = next(
        item
        for item in scenario.audit.metrics
        if item.metric_key is R2ExplanatoryMetricKey.COVERAGE_RATIO
    )
    monitoring_stability = next(
        item
        for item in scenario.monitoring_facts[-1].metrics
        if item.metric_key is R2ExplanatoryMetricKey.STABILITY_SCORE
    )
    coverage_rule = next(
        item
        for item in scenario.policy.metric_rules
        if item.metric_key is R2ExplanatoryMetricKey.COVERAGE_RATIO
    )
    audit_incremental = next(
        item
        for item in scenario.audit.metrics
        if item.metric_key is R2ExplanatoryMetricKey.INCREMENTAL_EXPLANATORY_POWER
    )
    monitoring_incremental = next(
        item
        for item in scenario.monitoring_facts[-1].metrics
        if item.metric_key is R2ExplanatoryMetricKey.INCREMENTAL_EXPLANATORY_POWER
    )
    incremental_rule = next(
        item
        for item in scenario.policy.metric_rules
        if item.metric_key is R2ExplanatoryMetricKey.INCREMENTAL_EXPLANATORY_POWER
    )

    with pytest.raises(ValueError, match=r"within \[0, 1\]"):
        replace(audit_coverage, value=Decimal("1.01"))
    with pytest.raises(ValueError, match=r"within \[0, 1\]"):
        replace(monitoring_stability, value=Decimal("-0.01"))
    with pytest.raises(ValueError, match="at-least direction"):
        replace(coverage_rule, direction=R2ThresholdDirection.AT_MOST)
    for invalid_value in (Decimal("-0.01"), Decimal("1.01")):
        with pytest.raises(ValueError, match=r"within \[0, 1\]"):
            replace(audit_incremental, value=invalid_value)
        with pytest.raises(ValueError, match=r"within \[0, 1\]"):
            replace(monitoring_incremental, value=invalid_value)
        with pytest.raises(ValueError, match=r"within \[0, 1\]"):
            replace(incremental_rule, trial_threshold=invalid_value)
        with pytest.raises(ValueError, match=r"within \[0, 1\]"):
            replace(incremental_rule, monitoring_threshold=invalid_value)


def test_evaluators_revalidate_resealed_delta_r2_values() -> None:
    scenario = build_r2_scenario()
    invalid_audit_metric = next(
        item
        for item in scenario.audit.metrics
        if item.metric_key is R2ExplanatoryMetricKey.INCREMENTAL_EXPLANATORY_POWER
    )
    object.__setattr__(invalid_audit_metric, "value", Decimal("1.01"))
    object.__setattr__(scenario.audit, "content_hash", r2_audit_outcome_hash(scenario.audit))

    trial = _trial(scenario)

    assert trial.status is R2TrialStatus.BLOCKED
    assert R2TrialBlockerCode.METRIC_DOMAIN_INVALID in trial.blockers

    scenario = build_r2_scenario()
    trial = _trial(scenario)
    invalid_monitoring_metric = next(
        item
        for item in scenario.monitoring_facts[-1].metrics
        if item.metric_key is R2ExplanatoryMetricKey.INCREMENTAL_EXPLANATORY_POWER
    )
    object.__setattr__(invalid_monitoring_metric, "value", Decimal("1.01"))
    object.__setattr__(
        scenario.monitoring_facts[-1],
        "content_hash",
        r2_monitoring_fact_hash(scenario.monitoring_facts[-1]),
    )

    monitoring = evaluate_r2_monitoring(
        policy=scenario.policy,
        taxonomy_publication=scenario.taxonomy,
        calendar_publication=scenario.calendar,
        trial_assessment=trial,
        facts=scenario.monitoring_facts,
        assessed_at=NOW,
    )

    assert monitoring.status is R2MonitoringStatus.BLOCKED
    assert R2TrialBlockerCode.METRIC_DOMAIN_INVALID in monitoring.blockers

    scenario = build_r2_scenario()
    invalid_rule = next(
        item
        for item in scenario.policy.metric_rules
        if item.metric_key is R2ExplanatoryMetricKey.INCREMENTAL_EXPLANATORY_POWER
    )
    object.__setattr__(invalid_rule, "trial_threshold", Decimal("1.01"))
    object.__setattr__(scenario.policy, "content_hash", r2_trial_policy_hash(scenario.policy))

    policy_assessment = _trial(scenario)

    assert policy_assessment.status is R2TrialStatus.BLOCKED
    assert R2TrialBlockerCode.METRIC_DOMAIN_INVALID in policy_assessment.blockers


@dataclass
class _Clock:
    current: datetime = NOW
    unit_of_work_key: str = "django:r2-test"

    def now(self) -> datetime:
        return self.current


class _UnavailableClock:
    unit_of_work_key = "django:r2-test"

    def now(self) -> datetime:
        raise RuntimeError("clock unavailable")


@dataclass
class _UnitOfWork:
    unit_of_work_key: str = "django:r2-test"
    entries: int = 0

    @contextmanager
    def atomic(self) -> AbstractContextManager[None]:
        self.entries += 1
        yield


@dataclass
class _PolicyProvider:
    policy: R2MarketStructureTrialPolicy | None
    calls: int = 0
    unit_of_work_key: str = "django:r2-test"

    def get_exact(
        self,
        *,
        policy_id: str,
        policy_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> R2MarketStructureTrialPolicy | None:
        self.calls += 1
        return self.policy


@dataclass
class _PolicySequenceProvider:
    policies: tuple[R2MarketStructureTrialPolicy | None, ...]
    calls: int = 0
    unit_of_work_key: str = "django:r2-test"

    def get_exact(
        self,
        *,
        policy_id: str,
        policy_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> R2MarketStructureTrialPolicy | None:
        selected = self.policies[min(self.calls, len(self.policies) - 1)]
        self.calls += 1
        return selected


@dataclass
class _PublicationProvider:
    taxonomy: R2CanonicalPublicationEvidence | None
    calendar: R2CanonicalPublicationEvidence | None
    calls: int = 0
    selectors: list[tuple[R2PublicationKind, str, datetime, datetime]] | None = None
    unit_of_work_key: str = "django:r2-test"

    def get_exact(
        self,
        *,
        kind: R2PublicationKind,
        reference: R2PublicationRef,
        expected_projection_hash: str,
        expected_available_at: datetime,
        expected_recorded_at: datetime,
        as_of: datetime,
    ) -> R2CanonicalPublicationEvidence | None:
        self.calls += 1
        if self.selectors is None:
            self.selectors = []
        self.selectors.append(
            (
                kind,
                expected_projection_hash,
                expected_available_at,
                expected_recorded_at,
            )
        )
        if kind is R2PublicationKind.TAXONOMY:
            return self.taxonomy
        return self.calendar


@dataclass
class _CycleProvider:
    cycles: tuple[R2CyclePITEvidence, ...]
    calls: int = 0
    unit_of_work_key: str = "django:r2-test"

    def get_exact(
        self,
        *,
        evidence_ref: R2EvidenceRef,
        taxonomy_publication_ref: R2PublicationRef,
        calendar_publication_ref: R2PublicationRef,
        as_of: datetime,
    ) -> R2CyclePITEvidence | None:
        self.calls += 1
        return next((item for item in self.cycles if item.reference == evidence_ref), None)


@dataclass
class _AuditProvider:
    outcome: R2AuditExplanatoryOutcome | None
    calls: int = 0
    expected_identity: tuple[str, str] | None = None
    unit_of_work_key: str = "django:r2-test"

    def get_exact(
        self,
        *,
        policy_ref: R2EvidenceRef,
        audit_plan_ref: R2EvidenceRef,
        cycle_evidence_refs: tuple[R2EvidenceRef, ...],
        expected_outcome_id: str,
        expected_outcome_version: str,
        as_of: datetime,
    ) -> R2AuditExplanatoryOutcome | None:
        self.calls += 1
        self.expected_identity = (expected_outcome_id, expected_outcome_version)
        return self.outcome


@dataclass
class _FactProvider:
    facts: tuple[R2MonitoringRawFact, ...]
    calls: int = 0
    expected_identities: tuple[tuple[str, str], ...] | None = None
    unit_of_work_key: str = "django:r2-test"

    def list_exact(
        self,
        *,
        policy_ref: R2EvidenceRef,
        taxonomy_publication_ref: R2PublicationRef,
        calendar_publication_ref: R2PublicationRef,
        expected_fact_identities: tuple[tuple[str, str], ...],
        as_of: datetime,
    ) -> tuple[R2MonitoringRawFact, ...]:
        self.calls += 1
        self.expected_identities = expected_fact_identities
        return self.facts


def _command(scenario: R2SyntheticScenario) -> EvaluateR2MarketStructureTrialCommand:
    return EvaluateR2MarketStructureTrialCommand(
        policy_id=scenario.policy.policy_id,
        policy_version=scenario.policy.policy_version,
        expected_policy_hash=scenario.policy.content_hash,
        as_of=NOW,
    )


def _application(
    scenario: R2SyntheticScenario,
    *,
    policy_provider: _PolicyProvider | None = None,
    publication_provider: _PublicationProvider | None = None,
    cycle_provider: _CycleProvider | None = None,
    audit_provider: _AuditProvider | None = None,
):
    policy = policy_provider or _PolicyProvider(scenario.policy)
    publications = publication_provider or _PublicationProvider(
        scenario.taxonomy, scenario.calendar
    )
    cycles = cycle_provider or _CycleProvider(scenario.cycles)
    audit = audit_provider or _AuditProvider(scenario.audit)
    use_case = EvaluateR2MarketStructureExplanatoryTrial(
        policy_provider=policy,
        publication_provider=publications,
        cycle_provider=cycles,
        audit_provider=audit,
        clock=_Clock(),
        unit_of_work=_UnitOfWork(),
    )
    return use_case, policy, publications, cycles, audit


def test_application_command_has_only_exact_policy_selector_and_as_of() -> None:
    scenario = build_r2_scenario()
    use_case, policy, publications, cycles, audit = _application(scenario)

    assessment = use_case.execute(_command(scenario))

    assert set(EvaluateR2MarketStructureTrialCommand.__dataclass_fields__) == {
        "policy_id",
        "policy_version",
        "expected_policy_hash",
        "as_of",
    }
    assert assessment.status is R2TrialStatus.PASSED
    assert (policy.calls, publications.calls, cycles.calls, audit.calls) == (2, 4, 4, 2)
    assert (
        publications.selectors
        == [
            (
                R2PublicationKind.TAXONOMY,
                scenario.policy.taxonomy_projection_seal.projection_hash,
                scenario.policy.taxonomy_projection_seal.available_at,
                scenario.policy.taxonomy_projection_seal.recorded_at,
            ),
            (
                R2PublicationKind.EXPECTED_PERIOD_CALENDAR,
                scenario.policy.calendar_projection_seal.projection_hash,
                scenario.policy.calendar_projection_seal.available_at,
                scenario.policy.calendar_projection_seal.recorded_at,
            ),
        ]
        * 2
    )
    assert audit.expected_identity == (
        derive_r2_audit_outcome_id(
            policy_ref=scenario.policy.reference,
            audit_plan_ref=scenario.policy.audit_plan_ref,
            cycle_evidence_refs=tuple(item.reference for item in scenario.cycles),
        ),
        R2_AUDIT_OUTCOME_VERSION,
    )
    with pytest.raises(TypeError):
        EvaluateR2MarketStructureTrialCommand(  # type: ignore[call-arg]
            policy_id=scenario.policy.policy_id,
            policy_version=scenario.policy.policy_version,
            expected_policy_hash=scenario.policy.content_hash,
            as_of=NOW,
            outcome="passed",
        )


def test_application_uses_one_shared_atomic_uow_and_blocks_owner_drift() -> None:
    scenario = build_r2_scenario()
    changed_policy = replace(
        scenario.policy,
        active_until=scenario.policy.active_until + timedelta(days=1),
    )
    policy = _PolicySequenceProvider((scenario.policy, changed_policy))
    publications = _PublicationProvider(scenario.taxonomy, scenario.calendar)
    cycles = _CycleProvider(scenario.cycles)
    audit = _AuditProvider(scenario.audit)
    uow = _UnitOfWork()
    use_case = EvaluateR2MarketStructureExplanatoryTrial(
        policy_provider=policy,
        publication_provider=publications,
        cycle_provider=cycles,
        audit_provider=audit,
        clock=_Clock(),
        unit_of_work=uow,
    )

    assessment = use_case.execute(_command(scenario))

    assert uow.entries == 1
    assert policy.calls == 2
    assert assessment.status is R2TrialStatus.BLOCKED
    assert assessment.blockers == (R2TrialBlockerCode.POLICY_HASH_MISMATCH,)


def test_application_blocks_unit_of_work_identity_mismatch_and_runtime_drift() -> None:
    scenario = build_r2_scenario()
    with pytest.raises(ValueError, match="share one unit of work"):
        EvaluateR2MarketStructureExplanatoryTrial(
            policy_provider=_PolicyProvider(
                scenario.policy,
                unit_of_work_key="django:other",
            ),
            publication_provider=_PublicationProvider(scenario.taxonomy, scenario.calendar),
            cycle_provider=_CycleProvider(scenario.cycles),
            audit_provider=_AuditProvider(scenario.audit),
            clock=_Clock(),
            unit_of_work=_UnitOfWork(),
        )

    policy = _PolicyProvider(scenario.policy)
    use_case, *_ = _application(scenario, policy_provider=policy)
    policy.unit_of_work_key = "django:changed"

    assessment = use_case.execute(_command(scenario))

    assert assessment.status is R2TrialStatus.BLOCKED
    assert assessment.blockers == (R2TrialBlockerCode.OWNER_EVIDENCE_UNAVAILABLE,)
    assert policy.calls == 0


def test_application_recomputes_policy_seal_before_owner_graph_reads() -> None:
    scenario = build_r2_scenario()
    original_hash = scenario.policy.content_hash
    object.__setattr__(scenario.policy, "maximum_monitoring_age_seconds", 3153600000)
    policy = _PolicyProvider(scenario.policy)
    publications = _PublicationProvider(scenario.taxonomy, scenario.calendar)
    use_case, _, _, cycles, audit = _application(
        scenario,
        policy_provider=policy,
        publication_provider=publications,
    )
    command = EvaluateR2MarketStructureTrialCommand(
        policy_id=scenario.policy.policy_id,
        policy_version=scenario.policy.policy_version,
        expected_policy_hash=original_hash,
        as_of=NOW,
    )

    assessment = use_case.execute(command)

    assert assessment.blockers == (R2TrialBlockerCode.POLICY_HASH_MISMATCH,)
    assert publications.calls == 0
    assert cycles.calls == 0
    assert audit.calls == 0


def test_application_rejects_changed_owner_bodies_under_expected_selectors() -> None:
    scenario = build_r2_scenario()
    changed_taxonomy = replace(
        scenario.taxonomy,
        valid_until=scenario.taxonomy.valid_until + timedelta(days=1),
    )
    publications = _PublicationProvider(changed_taxonomy, scenario.calendar)
    use_case, _, _, cycles, audit = _application(
        scenario,
        publication_provider=publications,
    )

    publication_assessment = use_case.execute(_command(scenario))

    assert publication_assessment.blockers == (R2TrialBlockerCode.PUBLICATION_REPLACED,)
    assert cycles.calls == 0
    assert audit.calls == 0

    changed_audit = replace(scenario.audit)
    object.__setattr__(changed_audit, "source_owner", "changed-audit-owner")
    use_case, *_ = _application(
        scenario,
        audit_provider=_AuditProvider(changed_audit),
    )
    audit_assessment = use_case.execute(_command(scenario))
    assert audit_assessment.blockers == (R2TrialBlockerCode.AUDIT_OUTCOME_REPLACED,)


def test_application_missing_cycle_or_audit_fails_closed_without_fabrication() -> None:
    scenario = build_r2_scenario()
    missing_cycle = _CycleProvider((scenario.cycles[0],))
    audit = _AuditProvider(scenario.audit)
    use_case, _, _, _, _ = _application(
        scenario,
        cycle_provider=missing_cycle,
        audit_provider=audit,
    )

    cycle_assessment = use_case.execute(_command(scenario))

    assert cycle_assessment.blockers == (R2TrialBlockerCode.CYCLE_EVIDENCE_MISSING,)
    assert audit.calls == 0

    use_case, *_ = _application(scenario, audit_provider=_AuditProvider(None))
    audit_assessment = use_case.execute(_command(scenario))
    assert audit_assessment.blockers == (R2TrialBlockerCode.AUDIT_OUTCOME_MISSING,)


def test_application_monitoring_rereads_trial_and_uses_only_raw_facts() -> None:
    scenario = build_r2_scenario(monitoring_breaches=(False, True, True))
    policy = _PolicyProvider(scenario.policy)
    publications = _PublicationProvider(scenario.taxonomy, scenario.calendar)
    cycles = _CycleProvider(scenario.cycles)
    audit = _AuditProvider(scenario.audit)
    facts = _FactProvider(scenario.monitoring_facts)
    use_case = EvaluateR2MarketStructureMonitoring(
        policy_provider=policy,
        publication_provider=publications,
        cycle_provider=cycles,
        audit_provider=audit,
        monitoring_fact_provider=facts,
        clock=_Clock(),
        unit_of_work=_UnitOfWork(),
    )

    assessment = use_case.execute(_command(scenario))

    assert assessment.status is R2MonitoringStatus.RETIREMENT_REVIEW_REQUIRED
    assert assessment.automatic_retirement is False
    assert facts.calls == 2
    assert (policy.calls, publications.calls, cycles.calls, audit.calls) == (2, 4, 4, 2)
    assert facts.expected_identities == tuple(
        (
            derive_r2_monitoring_fact_id(
                policy_ref=scenario.policy.reference,
                period_id=item.period_id,
            ),
            R2_MONITORING_FACT_VERSION,
        )
        for item in scenario.policy.expected_periods
        if item.period_start >= scenario.policy.selection_as_of and item.period_end <= NOW
    )


def test_application_monitoring_reseals_facts_and_preserves_missing_semantics() -> None:
    scenario = build_r2_scenario()
    changed_fact = replace(scenario.monitoring_facts[-1])
    object.__setattr__(changed_fact, "source_owner", "changed-fact-owner")
    changed_facts = _FactProvider((*scenario.monitoring_facts[:-1], changed_fact))
    changed_use_case = EvaluateR2MarketStructureMonitoring(
        policy_provider=_PolicyProvider(scenario.policy),
        publication_provider=_PublicationProvider(scenario.taxonomy, scenario.calendar),
        cycle_provider=_CycleProvider(scenario.cycles),
        audit_provider=_AuditProvider(scenario.audit),
        monitoring_fact_provider=changed_facts,
        clock=_Clock(),
        unit_of_work=_UnitOfWork(),
    )

    changed_assessment = changed_use_case.execute(_command(scenario))

    assert changed_assessment.blockers == (R2TrialBlockerCode.MONITORING_FACT_REPLACED,)

    missing_use_case = EvaluateR2MarketStructureMonitoring(
        policy_provider=_PolicyProvider(scenario.policy),
        publication_provider=_PublicationProvider(scenario.taxonomy, scenario.calendar),
        cycle_provider=_CycleProvider(scenario.cycles),
        audit_provider=_AuditProvider(scenario.audit),
        monitoring_fact_provider=_FactProvider(()),
        clock=_Clock(),
        unit_of_work=_UnitOfWork(),
    )
    missing_assessment = missing_use_case.execute(_command(scenario))
    assert missing_assessment.blockers == (R2TrialBlockerCode.MONITORING_FACTS_MISSING,)


def test_application_future_cutoff_and_owner_exception_are_stable_zero_write_blocks() -> None:
    scenario = build_r2_scenario()
    policy = _PolicyProvider(scenario.policy)
    publications = _PublicationProvider(scenario.taxonomy, scenario.calendar)
    cycles = _CycleProvider(scenario.cycles)
    audit = _AuditProvider(scenario.audit)
    use_case = EvaluateR2MarketStructureExplanatoryTrial(
        policy_provider=policy,
        publication_provider=publications,
        cycle_provider=cycles,
        audit_provider=audit,
        clock=_Clock(),
        unit_of_work=_UnitOfWork(),
    )
    future = replace(_command(scenario), as_of=NOW + timedelta(seconds=1))

    assessment = use_case.execute(future)

    assert assessment.blockers == (R2TrialBlockerCode.POLICY_FROM_FUTURE,)
    assert (policy.calls, publications.calls, cycles.calls, audit.calls) == (0, 0, 0, 0)


@pytest.mark.parametrize(
    "clock",
    (_UnavailableClock(), _Clock(datetime(2026, 8, 9, 12, 0))),
)
def test_application_normalizes_unavailable_authoritative_clock(
    clock: _UnavailableClock | _Clock,
) -> None:
    scenario = build_r2_scenario()
    use_case = EvaluateR2MarketStructureExplanatoryTrial(
        policy_provider=_PolicyProvider(scenario.policy),
        publication_provider=_PublicationProvider(scenario.taxonomy, scenario.calendar),
        cycle_provider=_CycleProvider(scenario.cycles),
        audit_provider=_AuditProvider(scenario.audit),
        clock=clock,
        unit_of_work=_UnitOfWork(),
    )

    assessment = use_case.execute(_command(scenario))

    assert assessment.status is R2TrialStatus.BLOCKED
    assert assessment.blockers == (R2TrialBlockerCode.AUTHORITATIVE_CLOCK_UNAVAILABLE,)


def test_application_normalizes_invalid_live_owner_objects() -> None:
    scenario = build_r2_scenario()
    changed_policy = replace(scenario.policy)
    object.__setattr__(changed_policy, "metric_rules", (object(),))
    use_case, *_ = _application(
        scenario,
        policy_provider=_PolicyProvider(changed_policy),
    )

    trial = use_case.execute(_command(scenario))

    assert trial.status is R2TrialStatus.BLOCKED
    assert trial.blockers == (R2TrialBlockerCode.OWNER_EVIDENCE_UNAVAILABLE,)

    scenario = build_r2_scenario()
    changed_fact = replace(scenario.monitoring_facts[-1])
    object.__setattr__(changed_fact, "period_start", "invalid-period-start")
    monitoring_use_case = EvaluateR2MarketStructureMonitoring(
        policy_provider=_PolicyProvider(scenario.policy),
        publication_provider=_PublicationProvider(scenario.taxonomy, scenario.calendar),
        cycle_provider=_CycleProvider(scenario.cycles),
        audit_provider=_AuditProvider(scenario.audit),
        monitoring_fact_provider=_FactProvider((*scenario.monitoring_facts[:-1], changed_fact)),
        clock=_Clock(),
        unit_of_work=_UnitOfWork(),
    )

    monitoring = monitoring_use_case.execute(_command(scenario))

    assert monitoring.status is R2MonitoringStatus.BLOCKED
    assert monitoring.blockers == (R2TrialBlockerCode.OWNER_EVIDENCE_UNAVAILABLE,)


def test_metric_direction_is_explicitly_preregistered() -> None:
    scenario = build_r2_scenario()

    assert all(
        rule.direction is R2ThresholdDirection.AT_LEAST for rule in scenario.policy.metric_rules
    )
    assert {rule.metric_key for rule in scenario.policy.metric_rules} == set(R2ExplanatoryMetricKey)
