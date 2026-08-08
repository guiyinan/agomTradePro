"""Fail-closed edge coverage for the expanded Equity Domain contracts."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from apps.equity.domain.forecast_baseline import (
    BaselineCostRule,
    BaselineFamily,
    BaselineInvalidationRule,
    BaselineMetricRule,
    CostApplicability,
    ForecastErrorMetric,
    InvalidationApplicability,
    InvalidationOperator,
    MapeZeroActualRule,
)
from apps.equity.domain.operating_forecast import (
    ForecastInputKind,
    OperatingForecastSourceKind,
    OperatingForecastSourceLineageStatus,
)
from tests.unit.equity.test_forecast_baseline import H, _artifact, _spec
from tests.unit.equity.test_operating_forecast import (
    AS_OF,
    _assumptions,
    _fact,
    _forecast,
    _projections,
)


@pytest.mark.parametrize(
    ("mutations", "message"),
    [
        ({"maximum_forecast_error": Decimal("-1")}, "cannot be negative"),
        ({"minimum_improvement": Decimal("-1")}, "cannot be negative"),
        ({"minimum_sample_count": 0}, "must be positive"),
        ({"minimum_sample_count": True}, "must be positive"),
        ({"minimum_coverage": Decimal("0")}, "within"),
        ({"minimum_coverage": Decimal("1.1")}, "within"),
    ],
)
def test_baseline_metric_rule_rejects_invalid_thresholds(
    mutations: dict[str, object], message: str
) -> None:
    """Metric gates must reject invalid numeric and sample boundaries."""

    valid = BaselineMetricRule(
        metric_code="revenue",
        error_metric=ForecastErrorMetric.MAE,
        maximum_forecast_error=Decimal("3"),
        minimum_improvement=Decimal("0.5"),
        minimum_sample_count=2,
        minimum_coverage=Decimal("1"),
        mape_zero_actual_rule=MapeZeroActualRule.BLOCK,
    )

    with pytest.raises(ValueError, match=message):
        replace(valid, **mutations)


def test_cost_and_invalidation_rules_reject_inconsistent_shapes() -> None:
    """Cost and invalidation rules must not accept ambiguous identities."""

    applicable = BaselineCostRule(
        applicability=CostApplicability.APPLICABLE,
        cost_model_version="cost.v1",
        cost_model_content_hash=H,
        not_applicable_reason="",
    )
    not_applicable = BaselineCostRule(
        applicability=CostApplicability.NOT_APPLICABLE,
        cost_model_version="",
        cost_model_content_hash="",
        not_applicable_reason="No execution cost in a research-only trial.",
    )
    invalidation = BaselineInvalidationRule(
        rule_code="revenue_break",
        metric_code="revenue",
        operator=InvalidationOperator.GREATER_THAN,
        threshold=Decimal("5"),
        consecutive_periods=2,
    )

    invalid_cases = (
        (applicable, {"not_applicable_reason": "contradiction"}),
        (not_applicable, {"cost_model_version": "cost.v1"}),
        (applicable, {"applicability": object()}),
        (invalidation, {"consecutive_periods": 0}),
        (invalidation, {"consecutive_periods": True}),
    )
    for value, mutations in invalid_cases:
        with pytest.raises(ValueError):
            replace(value, **mutations)


@pytest.mark.parametrize(
    ("mutations", "message"),
    [
        ({"owner": "research"}, "owner must be equity"),
        ({"approval_owner": "research"}, "approval owner must be equity"),
        ({"approval_status": object()}, "status must be approved"),
        ({"candidate_scenario": "base"}, "ForecastScenario"),
        ({"horizon_quarters": 0}, "must be positive"),
        ({"horizon_quarters": True}, "must be positive"),
        ({"family": BaselineFamily.LAST_AVAILABLE_ACTUAL}, "no implemented"),
        ({"computation_method": object()}, "not implemented"),
        ({"seasonal_lag_periods": 0}, "positive approved lag"),
        ({"seasonal_lag_periods": True}, "positive approved lag"),
        (
            {
                "family": BaselineFamily.EXTERNAL_CONSENSUS,
                "seasonal_lag_periods": 4,
            },
            "non-seasonal",
        ),
        ({"expected_period_ends": ()}, "expected periods"),
        ({"metric_rules": ()}, "metric rules"),
        ({"metric_evaluation_order": ()}, "tie-break order"),
        ({"invalidation_applicability": object()}, "applicability is invalid"),
        ({"research_only": False}, "research-only"),
        ({"must_not_use_for_decision": False}, "research-only"),
        ({"must_not_execute": False}, "research-only"),
        ({"content_hash": "0" * 64}, "content hash mismatch"),
    ],
)
def test_forecast_baseline_spec_rejects_invalid_contract_mutations(
    mutations: dict[str, object], message: str
) -> None:
    """A sealed baseline spec must fail closed for every governed dimension."""

    with pytest.raises(ValueError, match=message):
        replace(_spec(), **mutations)


def test_forecast_baseline_spec_rejects_time_and_collection_inconsistency() -> None:
    """Temporal, ordering, calendar and invalidation evidence must remain exact."""

    spec = _spec()
    invalid_cases: tuple[tuple[dict[str, object], str], ...] = (
        ({"valid_until": spec.approved_at}, "validity"),
        ({"approval_recorded_at": spec.approved_at - timedelta(seconds=1)}, "validity"),
        ({"training_window_start": spec.training_window_end + timedelta(days=1)}, "training"),
        (
            {"expected_period_ends": tuple(reversed(spec.expected_period_ends))},
            "expected periods",
        ),
        ({"period_horizons": spec.period_horizons[:1]}, "period horizon mapping"),
        ({"pit_inputs": ()}, "PIT input roles"),
        ({"pit_inputs": (spec.pit_inputs[0], spec.pit_inputs[0])}, "PIT input roles"),
        ({"metric_rules": (spec.metric_rules[0], spec.metric_rules[0])}, "metric rules"),
        (
            {
                "invalidation_applicability": InvalidationApplicability.NOT_APPLICABLE,
                "invalidation_rules": spec.invalidation_rules,
                "invalidation_not_applicable_reason": "Not applicable.",
            },
            "cannot carry rules",
        ),
        (
            {
                "invalidation_applicability": InvalidationApplicability.APPLICABLE,
                "invalidation_rules": (),
            },
            "requires non-empty rules",
        ),
    )
    for mutations, message in invalid_cases:
        with pytest.raises(ValueError, match=message):
            replace(spec, **mutations)


@pytest.mark.parametrize(
    ("mutations", "message"),
    [
        ({"owner": "research"}, "owner must be equity"),
        ({"candidate_scenario": "base"}, "ForecastScenario"),
        ({"horizon_quarters": 0}, "must be positive"),
        ({"horizon_quarters": True}, "must be positive"),
        ({"family": BaselineFamily.LAST_AVAILABLE_ACTUAL}, "not implemented"),
        ({"computation_method": object()}, "not implemented"),
        ({"seasonal_lag_periods": 0}, "positive lag"),
        (
            {
                "family": BaselineFamily.EXTERNAL_CONSENSUS,
                "seasonal_lag_periods": 4,
            },
            "non-seasonal",
        ),
        ({"forecasts": ()}, "exact evaluation periods"),
        ({"predictions": ()}, "full period-metric"),
        ({"research_only": False}, "research-only"),
        ({"must_not_use_for_decision": False}, "research-only"),
        ({"must_not_execute": False}, "research-only"),
        ({"content_hash": "0" * 64}, "content hash mismatch"),
    ],
)
def test_forecast_baseline_artifact_rejects_invalid_contract_mutations(
    mutations: dict[str, object], message: str
) -> None:
    """A sealed artifact must reject scope, time and evidence substitution."""

    spec = _spec()
    with pytest.raises(ValueError, match=message):
        replace(_artifact(spec), **mutations)


@pytest.mark.parametrize(
    ("mutations", "message"),
    [
        ({"version_id": 0}, "must be positive"),
        ({"available_at": AS_OF - timedelta(days=100)}, "before it is effective"),
        ({"content_hash": "bad"}, "sha256"),
        ({"value": Decimal("NaN")}, "finite Decimal"),
    ],
)
def test_operating_fact_rejects_invalid_evidence(
    mutations: dict[str, object], message: str
) -> None:
    """PIT operating facts must remain finite, ordered and content addressed."""

    with pytest.raises(ValueError, match=message):
        replace(_fact(), **mutations)


def test_operating_assumption_rejects_mixed_input_identities() -> None:
    """Observed, human and model assumptions must keep disjoint identities."""

    observed = _assumptions()[0]
    human = _assumptions()[1]
    invalid_cases: tuple[tuple[object, dict[str, object]], ...] = (
        (observed, {"scenario": "base"}),
        (observed, {"input_kind": "observed_fact"}),
        (observed, {"observed_fact_version_id": 0}),
        (observed, {"observed_fact_content_hash": "bad"}),
        (observed, {"input_kind": ForecastInputKind.HUMAN_ASSUMPTION}),
        (human, {"human_assumption_ref": ""}),
        (human, {"input_kind": ForecastInputKind.MODEL_INFERENCE}),
    )
    for value, mutations in invalid_cases:
        with pytest.raises(ValueError):
            replace(value, **mutations)


def test_projection_and_version_reject_incomplete_financial_graphs() -> None:
    """Forecast graphs must retain all scenarios, stages, facts and promotion evidence."""

    projection = _projections()[0]
    projection_cases: tuple[dict[str, object], ...] = (
        {"scenario": "base"},
        {"revenue": Decimal("0")},
        {"sensitivities": ()},
        {"sensitivities": (projection.sensitivities[0], projection.sensitivities[0])},
        {"stage_values": projection.stage_values[:-1]},
    )
    for mutations in projection_cases:
        with pytest.raises(ValueError):
            replace(projection, **mutations)

    forecast = _forecast()
    version_cases: tuple[dict[str, object], ...] = (
        {"forecast_version": 0},
        {"target_period_end": forecast.as_of_time.date() - timedelta(days=1)},
        {"horizon_quarters": 0},
        {"source_kind": OperatingForecastSourceKind.LEGACY_MANUAL},
        {"evidence_schema_version": 1},
        {"source_lineage_status": OperatingForecastSourceLineageStatus.LEGACY_UNBOUND},
        {"template_version": 0},
        {"template_content_hash": "bad"},
        {"template_run_version": 0},
        {"template_run_content_hash": "bad"},
        {"valuation_consumable": "yes"},
        {"valuation_consumable": True},
        {"facts": ()},
        {"facts": (forecast.facts[0], forecast.facts[0])},
        {"assumptions": (forecast.assumptions[0], forecast.assumptions[0])},
        {"projections": forecast.projections[:2]},
    )
    for mutations in version_cases:
        with pytest.raises(ValueError):
            replace(forecast, **mutations)
