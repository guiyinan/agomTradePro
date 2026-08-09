"""Synthetic contract factories for R2 explanatory trial and monitoring tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256

from apps.research.domain.r2_market_structure_trial_monitoring import (
    R2_AUDIT_OUTCOME_VERSION,
    R2_MONITORING_FACT_VERSION,
    R2AuditExplanatoryOutcome,
    R2AuditMetric,
    R2CanonicalPublicationEvidence,
    R2CyclePITEvidence,
    R2EvidenceRef,
    R2ExpectedPeriod,
    R2ExpectedSeriesPeriodEntry,
    R2ExplanatoryMetricKey,
    R2MarketCycleDefinition,
    R2MarketStructureTrialPolicy,
    R2MeasureKind,
    R2MeasureSemantic,
    R2MetricRule,
    R2MonitoringMetricObservation,
    R2MonitoringRawFact,
    R2MultipleTestingRule,
    R2PublicationKind,
    R2PublicationProjectionSeal,
    R2PublicationRef,
    R2SeriesPeriodSample,
    R2ThresholdDirection,
    derive_r2_audit_outcome_id,
    derive_r2_monitoring_fact_id,
    derive_r2_pit_manifest_ref,
)

NOW = datetime(2026, 8, 9, 12, tzinfo=UTC)


def digest(label: str) -> str:
    """Return a deterministic SHA-256 digest for a synthetic identity."""

    return sha256(label.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class R2SyntheticScenario:
    """One complete synthetic evidence graph; never production attestation."""

    policy: R2MarketStructureTrialPolicy
    taxonomy: R2CanonicalPublicationEvidence
    calendar: R2CanonicalPublicationEvidence
    cycles: tuple[R2CyclePITEvidence, ...]
    audit: R2AuditExplanatoryOutcome
    monitoring_facts: tuple[R2MonitoringRawFact, ...]


def _publication_ref(kind: str) -> R2PublicationRef:
    return R2PublicationRef(
        owner="canonical_publication_owner",
        publication_id=f"r2-{kind}",
        publication_version="v1",
        publication_hash=digest(f"{kind}:publication"),
        artifact_hash=digest(f"{kind}:artifact"),
    )


def _semantics() -> tuple[R2MeasureSemantic, ...]:
    return (
        R2MeasureSemantic(
            series_code="direct_flow",
            series_version="v1",
            actor_code="institutional",
            measure_kind=R2MeasureKind.FLOW,
            unit="yuan",
            frequency="monthly",
            source="canonical_source",
            revision_policy_ref="revision-policy-v1",
            is_proxy=False,
        ),
        R2MeasureSemantic(
            series_code="proxy_holding_change",
            series_version="v1",
            actor_code="custodian_proxy",
            measure_kind=R2MeasureKind.HOLDING_CHANGE,
            unit="shares",
            frequency="monthly",
            source="canonical_source",
            revision_policy_ref="revision-policy-v1",
            is_proxy=True,
            proxy_target_actor_code="foreign_investor",
            proxy_methodology_ref="proxy-methodology-v1",
        ),
    )


def _periods() -> tuple[R2ExpectedPeriod, ...]:
    return (
        R2ExpectedPeriod("cycle_1_p1", NOW - timedelta(days=150), NOW - timedelta(days=140)),
        R2ExpectedPeriod("cycle_1_p2", NOW - timedelta(days=140), NOW - timedelta(days=130)),
        R2ExpectedPeriod("cycle_2_p1", NOW - timedelta(days=110), NOW - timedelta(days=100)),
        R2ExpectedPeriod("cycle_2_p2", NOW - timedelta(days=100), NOW - timedelta(days=90)),
        R2ExpectedPeriod("monitor_p1", NOW - timedelta(days=3), NOW - timedelta(days=2)),
        R2ExpectedPeriod("monitor_p2", NOW - timedelta(days=2), NOW - timedelta(days=1)),
        R2ExpectedPeriod("monitor_p3", NOW - timedelta(days=1), NOW - timedelta(hours=12)),
    )


def _expected_series_period_entries(
    *,
    periods: tuple[R2ExpectedPeriod, ...],
    semantics: tuple[R2MeasureSemantic, ...],
) -> tuple[R2ExpectedSeriesPeriodEntry, ...]:
    entries: list[R2ExpectedSeriesPeriodEntry] = []
    for period in periods:
        for semantic in semantics:
            observation_refs = tuple(
                R2EvidenceRef(
                    evidence_id=(
                        f"observation-{period.period_id}-{semantic.series_code}-{index:02d}"
                    ),
                    evidence_version="v1",
                    content_hash=digest(
                        f"observation:{period.period_id}:{semantic.series_code}:{index:02d}"
                    ),
                )
                for index in range(10)
            )
            entries.append(
                R2ExpectedSeriesPeriodEntry(
                    period_id=period.period_id,
                    series_code=semantic.series_code,
                    series_version=semantic.series_version,
                    expected_observation_refs=observation_refs,
                    pit_manifest_ref=derive_r2_pit_manifest_ref(
                        period_id=period.period_id,
                        series_code=semantic.series_code,
                        series_version=semantic.series_version,
                        observation_refs=observation_refs,
                    ),
                )
            )
    return tuple(entries)


def _cycle_evidence(
    *,
    cycle_id: str,
    period_ids: tuple[str, ...],
    period_by_id: dict[str, R2ExpectedPeriod],
    semantics: tuple[R2MeasureSemantic, ...],
    expected_entries: tuple[R2ExpectedSeriesPeriodEntry, ...],
    taxonomy_ref: R2PublicationRef,
    calendar_ref: R2PublicationRef,
) -> R2CyclePITEvidence:
    cycle_end = period_by_id[period_ids[-1]].period_end
    available_at = cycle_end + timedelta(hours=1)
    entry_by_cell = {
        (item.period_id, item.series_code, item.series_version): item for item in expected_entries
    }
    samples = tuple(
        R2SeriesPeriodSample(
            period_id=period_id,
            series_code=semantic.series_code,
            series_version=semantic.series_version,
            measure_kind=semantic.measure_kind,
            is_proxy=semantic.is_proxy,
            unit=semantic.unit,
            observation_refs=entry_by_cell[
                (period_id, semantic.series_code, semantic.series_version)
            ].expected_observation_refs,
            available_at=available_at,
            pit_manifest_ref=entry_by_cell[
                (period_id, semantic.series_code, semantic.series_version)
            ].pit_manifest_ref,
            evidence_ref=f"synthetic://{cycle_id}/{period_id}/{semantic.series_code}",
        )
        for period_id in period_ids
        for semantic in semantics
    )
    return R2CyclePITEvidence(
        evidence_id=f"{cycle_id}-pit",
        evidence_version="v1",
        source_owner="cycle_pit_owner",
        cycle_id=cycle_id,
        taxonomy_publication_ref=taxonomy_ref,
        calendar_publication_ref=calendar_ref,
        samples=samples,
        observed_at=cycle_end,
        available_at=available_at,
        recorded_at=available_at + timedelta(hours=1),
        valid_from=available_at + timedelta(hours=1),
        valid_until=NOW + timedelta(days=10),
    )


def _audit_metrics() -> tuple[R2AuditMetric, ...]:
    metrics: list[R2AuditMetric] = []
    for cycle_id in ("cycle_1", "cycle_2"):
        metrics.extend(
            (
                R2AuditMetric(
                    cycle_id=cycle_id,
                    metric_key=R2ExplanatoryMetricKey.COVERAGE_RATIO,
                    unit="ratio",
                    value=Decimal("1"),
                    sample_count=40,
                    expected_sample_count=40,
                ),
                R2AuditMetric(
                    cycle_id=cycle_id,
                    metric_key=R2ExplanatoryMetricKey.STABILITY_SCORE,
                    unit="score",
                    value=Decimal("0.80"),
                    sample_count=2,
                    expected_sample_count=2,
                ),
                R2AuditMetric(
                    cycle_id=cycle_id,
                    metric_key=R2ExplanatoryMetricKey.INCREMENTAL_EXPLANATORY_POWER,
                    unit="delta_r2",
                    value=Decimal("0.15"),
                    sample_count=2,
                    expected_sample_count=2,
                    raw_p_value=Decimal("0.01"),
                    test_family_id="r2-two-cycle-family",
                    multiple_testing_method_version="holm-v1",
                ),
            )
        )
    return tuple(metrics)


def _monitoring_metrics(*, breached: bool = False) -> tuple[R2MonitoringMetricObservation, ...]:
    coverage_sample_count = 10 if breached else 20
    return (
        R2MonitoringMetricObservation(
            metric_key=R2ExplanatoryMetricKey.COVERAGE_RATIO,
            unit="ratio",
            value=Decimal("0.50") if breached else Decimal("1"),
            sample_count=coverage_sample_count,
            expected_sample_count=20,
        ),
        R2MonitoringMetricObservation(
            metric_key=R2ExplanatoryMetricKey.STABILITY_SCORE,
            unit="score",
            value=Decimal("0.40") if breached else Decimal("0.78"),
            sample_count=20,
            expected_sample_count=20,
        ),
        R2MonitoringMetricObservation(
            metric_key=R2ExplanatoryMetricKey.INCREMENTAL_EXPLANATORY_POWER,
            unit="delta_r2",
            value=Decimal("0.01") if breached else Decimal("0.12"),
            sample_count=20,
            expected_sample_count=20,
        ),
    )


def _monitoring_fact(
    *,
    period: R2ExpectedPeriod,
    policy: R2MarketStructureTrialPolicy,
    breached: bool = False,
    label_hash: str | None = None,
) -> R2MonitoringRawFact:
    observed_at = period.period_end
    return R2MonitoringRawFact(
        fact_id=derive_r2_monitoring_fact_id(
            policy_ref=policy.reference,
            period_id=period.period_id,
        ),
        fact_version=R2_MONITORING_FACT_VERSION,
        source_owner="audit_owner",
        policy_ref=policy.reference,
        taxonomy_publication_ref=policy.taxonomy_publication_ref,
        calendar_publication_ref=policy.calendar_publication_ref,
        period_id=period.period_id,
        period_start=period.period_start,
        period_end=period.period_end,
        metrics=_monitoring_metrics(breached=breached),
        label_protocol_version=policy.label_protocol_version,
        observed_label_set_hash=label_hash or policy.expected_label_set_hash,
        observed_at=observed_at,
        available_at=observed_at + timedelta(minutes=10),
        recorded_at=observed_at + timedelta(minutes=20),
        valid_from=observed_at + timedelta(minutes=20),
        valid_until=NOW + timedelta(days=10),
    )


def build_r2_scenario(
    *,
    monitoring_breaches: tuple[bool, bool, bool] = (False, False, False),
    latest_label_hash: str | None = None,
) -> R2SyntheticScenario:
    """Build a valid synthetic graph used only to exercise the contracts."""

    taxonomy_ref = _publication_ref("taxonomy")
    calendar_ref = _publication_ref("calendar")
    semantics = _semantics()
    periods = _periods()
    expected_entries = _expected_series_period_entries(
        periods=periods,
        semantics=semantics,
    )
    publication_available_at = NOW - timedelta(days=45)
    taxonomy = R2CanonicalPublicationEvidence(
        kind=R2PublicationKind.TAXONOMY,
        reference=taxonomy_ref,
        available_at=publication_available_at,
        recorded_at=publication_available_at + timedelta(hours=1),
        valid_from=publication_available_at + timedelta(hours=1),
        valid_until=NOW + timedelta(days=30),
        measure_semantics=semantics,
    )
    calendar = R2CanonicalPublicationEvidence(
        kind=R2PublicationKind.EXPECTED_PERIOD_CALENDAR,
        reference=calendar_ref,
        available_at=publication_available_at,
        recorded_at=publication_available_at + timedelta(hours=1),
        valid_from=publication_available_at + timedelta(hours=1),
        valid_until=NOW + timedelta(days=30),
        expected_periods=periods,
        expected_series_period_entries=expected_entries,
    )
    period_by_id = {item.period_id: item for item in periods}
    cycles = (
        _cycle_evidence(
            cycle_id="cycle_1",
            period_ids=("cycle_1_p1", "cycle_1_p2"),
            period_by_id=period_by_id,
            semantics=semantics,
            expected_entries=expected_entries,
            taxonomy_ref=taxonomy_ref,
            calendar_ref=calendar_ref,
        ),
        _cycle_evidence(
            cycle_id="cycle_2",
            period_ids=("cycle_2_p1", "cycle_2_p2"),
            period_by_id=period_by_id,
            semantics=semantics,
            expected_entries=expected_entries,
            taxonomy_ref=taxonomy_ref,
            calendar_ref=calendar_ref,
        ),
    )
    policy = R2MarketStructureTrialPolicy(
        policy_id="r2-two-cycle-trial",
        policy_version="v1",
        taxonomy_publication_ref=taxonomy_ref,
        calendar_publication_ref=calendar_ref,
        taxonomy_projection_seal=R2PublicationProjectionSeal(
            reference=taxonomy.reference,
            projection_hash=taxonomy.content_hash,
            available_at=taxonomy.available_at,
            recorded_at=taxonomy.recorded_at,
        ),
        calendar_projection_seal=R2PublicationProjectionSeal(
            reference=calendar.reference,
            projection_hash=calendar.content_hash,
            available_at=calendar.available_at,
            recorded_at=calendar.recorded_at,
        ),
        measure_semantics=semantics,
        expected_periods=periods,
        expected_series_period_entries=expected_entries,
        cycles=(
            R2MarketCycleDefinition(
                cycle_id="cycle_1",
                cycle_label="historical_contraction_expansion_one",
                classification_version="canonical-cycle-v1",
                cycle_start=period_by_id["cycle_1_p1"].period_start,
                cycle_end=period_by_id["cycle_1_p2"].period_end,
                expected_period_ids=("cycle_1_p1", "cycle_1_p2"),
                evidence_ref=cycles[0].reference,
            ),
            R2MarketCycleDefinition(
                cycle_id="cycle_2",
                cycle_label="historical_contraction_expansion_two",
                classification_version="canonical-cycle-v1",
                cycle_start=period_by_id["cycle_2_p1"].period_start,
                cycle_end=period_by_id["cycle_2_p2"].period_end,
                expected_period_ids=("cycle_2_p1", "cycle_2_p2"),
                evidence_ref=cycles[1].reference,
            ),
        ),
        metric_rules=(
            R2MetricRule(
                R2ExplanatoryMetricKey.COVERAGE_RATIO,
                "ratio",
                R2ThresholdDirection.AT_LEAST,
                Decimal("0.90"),
                Decimal("0.85"),
                2,
            ),
            R2MetricRule(
                R2ExplanatoryMetricKey.STABILITY_SCORE,
                "score",
                R2ThresholdDirection.AT_LEAST,
                Decimal("0.70"),
                Decimal("0.65"),
                2,
            ),
            R2MetricRule(
                R2ExplanatoryMetricKey.INCREMENTAL_EXPLANATORY_POWER,
                "delta_r2",
                R2ThresholdDirection.AT_LEAST,
                Decimal("0.05"),
                Decimal("0.03"),
                2,
            ),
        ),
        multiple_testing=R2MultipleTestingRule(
            family_id="r2-two-cycle-family",
            method_version="holm-v1",
            hypothesis_count=2,
            maximum_adjusted_p_value=Decimal("0.05"),
        ),
        audit_plan_ref=R2EvidenceRef("r2-audit-plan", "v1", digest("audit-plan")),
        expected_cycle_evidence_owner="cycle_pit_owner",
        expected_audit_owner="audit_owner",
        minimum_observations_per_series_period=10,
        minimum_monitoring_sample_count=10,
        maximum_monitoring_age_seconds=172800,
        label_protocol_version="canonical-label-v1",
        expected_label_set_hash=digest("expected-label-set"),
        registered_at=NOW - timedelta(days=31),
        selection_as_of=NOW - timedelta(days=30),
        active_from=NOW - timedelta(days=60),
        active_until=NOW + timedelta(days=30),
    )
    cycle_evidence_refs = tuple(item.reference for item in cycles)
    audit = R2AuditExplanatoryOutcome(
        outcome_id=derive_r2_audit_outcome_id(
            policy_ref=policy.reference,
            audit_plan_ref=policy.audit_plan_ref,
            cycle_evidence_refs=cycle_evidence_refs,
        ),
        outcome_version=R2_AUDIT_OUTCOME_VERSION,
        source_owner="audit_owner",
        policy_ref=policy.reference,
        audit_plan_ref=policy.audit_plan_ref,
        taxonomy_publication_ref=taxonomy_ref,
        calendar_publication_ref=calendar_ref,
        cycle_evidence_refs=cycle_evidence_refs,
        selection_as_of=policy.selection_as_of,
        metrics=_audit_metrics(),
        observed_at=NOW - timedelta(days=20),
        available_at=NOW - timedelta(days=19),
        recorded_at=NOW - timedelta(days=18),
        valid_from=NOW - timedelta(days=18),
        valid_until=NOW + timedelta(days=10),
    )
    monitoring_periods = periods[-3:]
    monitoring_facts = tuple(
        _monitoring_fact(
            period=period,
            policy=policy,
            breached=monitoring_breaches[index],
            label_hash=(latest_label_hash if index == 2 else None),
        )
        for index, period in enumerate(monitoring_periods)
    )
    return R2SyntheticScenario(
        policy=policy,
        taxonomy=taxonomy,
        calendar=calendar,
        cycles=cycles,
        audit=audit,
        monitoring_facts=monitoring_facts,
    )


__all__ = ["NOW", "R2SyntheticScenario", "build_r2_scenario", "digest"]
