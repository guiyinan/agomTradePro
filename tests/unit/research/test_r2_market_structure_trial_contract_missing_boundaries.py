"""Reachable fail-closed boundaries for the R2 contract value objects."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from apps.research.domain.r2_market_structure_trial_contracts import (
    R2ExpectedPeriod,
    R2MarketCycleDefinition,
    R2MeasureKind,
    R2MeasureSemantic,
    R2MetricRule,
    R2PublicationProjectionSeal,
    R2ThresholdDirection,
)
from tests.unit.research.r2_market_structure_trial_monitoring_factories import (
    NOW,
    build_r2_scenario,
)


def _direct_semantic() -> R2MeasureSemantic:
    """Build one valid direct measure semantic for boundary mutations."""

    return R2MeasureSemantic(
        series_code="direct_flow",
        series_version="v1",
        actor_code="institutional",
        measure_kind=R2MeasureKind.FLOW,
        unit="yuan",
        frequency="monthly",
        source="canonical_source",
        revision_policy_ref="revision-policy-v1",
        is_proxy=False,
    )


def test_leaf_contracts_reject_text_hash_domain_clock_and_type_substitutions() -> None:
    """Leaf objects reject malformed values before any canonical projection."""

    scenario = build_r2_scenario()

    with pytest.raises(ValueError, match="bounded non-blank text"):
        replace(_direct_semantic(), revision_policy_ref="")

    with pytest.raises(ValueError, match="SHA-256 digest"):
        replace(scenario.policy.audit_plan_ref, content_hash="x" * 64)

    with pytest.raises(ValueError, match="requires delta_r2"):
        R2MetricRule(
            metric_key=scenario.policy.metric_rules[2].metric_key,
            unit="ratio",
            direction=R2ThresholdDirection.AT_LEAST,
            trial_threshold=Decimal("0.05"),
            monitoring_threshold=Decimal("0.03"),
            retirement_review_consecutive_breaches=2,
        )

    with pytest.raises(ValueError, match="knowledge clocks"):
        replace(
            R2PublicationProjectionSeal(
                reference=scenario.taxonomy.reference,
                projection_hash=scenario.taxonomy.content_hash,
                available_at=scenario.taxonomy.available_at,
                recorded_at=scenario.taxonomy.recorded_at,
            ),
            available_at=scenario.taxonomy.recorded_at + timedelta(seconds=1),
        )

    with pytest.raises(ValueError, match="measure_kind is invalid"):
        replace(_direct_semantic(), measure_kind=object())

    with pytest.raises(ValueError, match="is_proxy must be boolean"):
        replace(_direct_semantic(), is_proxy=1)


def test_expected_period_and_series_entry_membership_are_strict() -> None:
    """Expected calendars reject empty windows, duplicate refs, and reordering."""

    scenario = build_r2_scenario()
    period = scenario.calendar.expected_periods[0]
    entry = scenario.calendar.expected_series_period_entries[0]

    with pytest.raises(ValueError, match="must be non-empty"):
        R2ExpectedPeriod(period.period_id, period.period_start, period.period_start)

    with pytest.raises(ValueError, match="observations are required"):
        replace(entry, expected_observation_refs=())

    duplicate_refs = (entry.expected_observation_refs[0],) * 2
    with pytest.raises(ValueError, match="identities must be unique"):
        replace(entry, expected_observation_refs=duplicate_refs)

    with pytest.raises(ValueError, match="canonical order"):
        replace(
            entry,
            expected_observation_refs=tuple(reversed(entry.expected_observation_refs)),
        )


def test_cycle_and_metric_rules_reject_incomplete_configuration() -> None:
    """Cycle, metric, and multiple-test rules keep their registered domains closed."""

    scenario = build_r2_scenario()
    cycle = R2MarketCycleDefinition(
        cycle_id="cycle-test",
        cycle_label="test-cycle",
        classification_version="canonical-cycle-v1",
        cycle_start=NOW - timedelta(days=2),
        cycle_end=NOW - timedelta(days=1),
        expected_period_ids=("period-1",),
        evidence_ref=scenario.cycles[0].reference,
    )
    metric = scenario.policy.metric_rules[0]
    multiple_testing = scenario.policy.multiple_testing

    with pytest.raises(ValueError, match="window must be complete"):
        replace(cycle, expected_period_ids=())

    with pytest.raises(ValueError, match="periods must be unique"):
        replace(cycle, expected_period_ids=("period-1", "period-1"))

    with pytest.raises(ValueError, match="metric_key is invalid"):
        replace(metric, metric_key=object())

    with pytest.raises(ValueError, match="direction is invalid"):
        replace(metric, direction=object())

    with pytest.raises(ValueError, match="count must be positive"):
        replace(metric, retirement_review_consecutive_breaches=0)

    with pytest.raises(ValueError, match="hypothesis_count must be positive"):
        replace(multiple_testing, hypothesis_count=0)

    with pytest.raises(ValueError, match="threshold must be within"):
        replace(multiple_testing, maximum_adjusted_p_value=Decimal("1.1"))


def test_publication_projections_keep_kind_clock_and_payload_shapes() -> None:
    """Taxonomy and calendar projections cannot exchange payload families."""

    scenario = build_r2_scenario()

    with pytest.raises(ValueError, match="kind is invalid"):
        replace(scenario.taxonomy, kind=object())

    with pytest.raises(ValueError, match="Publication clocks are invalid"):
        replace(
            scenario.taxonomy,
            available_at=scenario.taxonomy.recorded_at + timedelta(seconds=1),
        )

    with pytest.raises(ValueError, match="only measure semantics"):
        replace(scenario.taxonomy, expected_periods=scenario.calendar.expected_periods)

    with pytest.raises(ValueError, match="only expected periods"):
        replace(scenario.calendar, measure_semantics=scenario.policy.measure_semantics)


def test_samples_reject_type_membership_and_pit_substitution() -> None:
    """A sample remains bound to ordered raw refs and its exact PIT manifest."""

    scenario = build_r2_scenario()
    sample = scenario.cycles[0].samples[0]

    with pytest.raises(ValueError, match="measure_kind is invalid"):
        replace(sample, measure_kind=object())

    with pytest.raises(ValueError, match="is_proxy must be boolean"):
        replace(sample, is_proxy=1)

    duplicate_refs = (sample.observation_refs[0],) * 2
    with pytest.raises(ValueError, match="refs must be unique"):
        replace(sample, observation_refs=duplicate_refs)

    with pytest.raises(ValueError, match="refs must be canonical"):
        replace(sample, observation_refs=tuple(reversed(sample.observation_refs)))

    with pytest.raises(ValueError, match="PIT manifest seal is invalid"):
        replace(sample, pit_manifest_ref=scenario.policy.audit_plan_ref)


def test_cycle_pit_evidence_rejects_empty_duplicate_and_temporal_shapes() -> None:
    """Cycle evidence requires unique samples and ordered knowledge/validity clocks."""

    scenario = build_r2_scenario()
    cycle = scenario.cycles[0]
    sample = cycle.samples[0]

    with pytest.raises(ValueError, match="requires samples"):
        replace(cycle, samples=())

    with pytest.raises(ValueError, match="samples must have unique identities"):
        replace(cycle, samples=(sample, sample))

    with pytest.raises(ValueError, match="knowledge clocks are invalid"):
        replace(cycle, observed_at=cycle.available_at + timedelta(seconds=1))

    with pytest.raises(ValueError, match="validity clocks are invalid"):
        replace(cycle, valid_until=cycle.valid_from)


__all__ = [
    "test_cycle_and_metric_rules_reject_incomplete_configuration",
    "test_cycle_pit_evidence_rejects_empty_duplicate_and_temporal_shapes",
    "test_expected_period_and_series_entry_membership_are_strict",
    "test_leaf_contracts_reject_text_hash_domain_clock_and_type_substitutions",
    "test_publication_projections_keep_kind_clock_and_payload_shapes",
    "test_samples_reject_type_membership_and_pit_substitution",
]
