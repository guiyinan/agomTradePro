"""Component coverage for the R1 operating-forecast persistence boundary."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.data_center.domain.research_data_foundation import (
    OPERATING_OBSERVATION_DATASET,
)
from apps.data_center.infrastructure.pit_models import PITFactVersionModel
from apps.equity.application.operating_forecast import (
    CreateOperatingForecastCommand,
    OperatingForecastEvidenceError,
    RecordQuarterlyActualCommand,
)
from apps.equity.domain.operating_forecast import (
    ForecastInputKind,
    ForecastScenario,
    OperatingForecastAssumption,
    OperatingForecastProjection,
    OperatingMetricRole,
    ValuationSensitivityPoint,
)
from apps.equity.infrastructure.operating_forecast_models import (
    OperatingForecastAssumptionModel,
    OperatingForecastEvaluationModel,
    OperatingForecastFactReferenceModel,
    OperatingForecastProjectionModel,
    OperatingForecastSensitivityModel,
    OperatingForecastVersionModel,
)
from apps.equity.infrastructure.operating_forecast_repository import (
    DjangoOperatingFactEvidenceProvider,
)
from apps.equity.operating_forecast_composition import (
    build_create_operating_forecast_use_case,
    build_record_quarterly_actual_use_case,
)
from apps.research.infrastructure.models import (
    ExperimentTrial,
    MultipleTestFamily,
    PromotionDecision,
    ResearchExperiment,
)

AS_OF = datetime(2026, 4, 30, 8, tzinfo=UTC)
TARGET = date(2026, 6, 30)


def _append_operating_fact(
    *,
    business_key: str,
    effective_at: datetime,
    available_at: datetime,
    revision_number: int = 0,
    value_kind: str = "observed_fact",
    pit_quality: str = "verified",
    metric_code: str = "revenue",
    value: str = "100",
    unit: str = "CNY_million",
    subject_code: str = "000001.SZ",
) -> PITFactVersionModel:
    payload = {
        "metric_code": metric_code,
        "definition_version": 1,
        "subject_type": "company",
        "subject_code": subject_code,
        "effective_at": effective_at.isoformat(),
        "effective_to": None,
        "available_at": available_at.isoformat(),
        "revision_number": revision_number,
        "value": value,
        "unit": unit,
        "frequency": "quarterly",
        "source": "licensed-report",
        "value_kind": value_kind,
        "source_record_id": f"source-{business_key}-{revision_number}",
        "assumption_set_id": "" if value_kind == "observed_fact" else "assumption-v1",
        "model_version": "",
    }
    return PITFactVersionModel._default_manager.create(
        dataset=OPERATING_OBSERVATION_DATASET,
        business_key=business_key,
        effective_at=effective_at,
        effective_to=None,
        available_at=available_at,
        ingested_at=available_at,
        superseded_at=None,
        revision_number=revision_number,
        source_record_id=f"source-{business_key}-{revision_number}",
        content_hash=f"{business_key}-{revision_number}".encode().hex().ljust(64, "0")[:64],
        pit_quality=pit_quality,
        payload=payload,
    )


def _create_approved_promotion() -> PromotionDecision:
    experiment = ResearchExperiment._default_manager.create(
        experiment_id="r1-operating-forecast",
        question="Can governed operating inputs improve the quarterly baseline?",
        hypothesis="The frozen trial beats its registered baseline out of sample.",
        status="completed",
    )
    family = MultipleTestFamily._default_manager.create(
        family_id="r1-operating-family",
        experiment=experiment,
        planned_trial_count=1,
    )
    trial = ExperimentTrial._default_manager.create(
        trial_id="r1-operating-trial-v1",
        experiment=experiment,
        family=family,
        status="eligible_for_promotion",
        pit_manifest_id="pit-manifest-r1-v1",
        backtest_id=None,
        backtest_trust_status="trusted",
        code_commit="a" * 40,
        dependency_lock_hash="b" * 64,
        engine_version="r1-evaluator-v1",
        parameters={"forecast_contract": "operating-forecast-v1"},
        parameter_hash="c" * 64,
        random_seed=7,
        benchmark_spec={"type": "seasonal_naive"},
        cost_spec={"type": "not_applicable"},
        slippage_spec={"type": "not_applicable"},
        universe_spec={"subject_code": "000001.SZ"},
    )
    return PromotionDecision._default_manager.create(
        decision_id="promotion-approved-v1",
        trial=trial,
        decision="approved",
        evidence={"forecast_contract": "operating-forecast-v1"},
    )


def _assumptions(fact_id: int) -> tuple[OperatingForecastAssumption, ...]:
    result: list[OperatingForecastAssumption] = []
    for scenario, growth in (
        (ForecastScenario.BASE, "5"),
        (ForecastScenario.BULL, "8"),
        (ForecastScenario.BEAR, "-2"),
    ):
        result.extend(
            (
                OperatingForecastAssumption(
                    scenario=scenario,
                    assumption_key="revenue_anchor",
                    value=Decimal("100"),
                    unit="CNY_million",
                    input_kind=ForecastInputKind.OBSERVED_FACT,
                    rationale="Frozen public PIT operating observation.",
                    observed_fact_version_id=fact_id,
                    observed_metric_role=OperatingMetricRole.REVENUE,
                ),
                OperatingForecastAssumption(
                    scenario=scenario,
                    assumption_key="growth_input",
                    value=Decimal(growth),
                    unit="percent",
                    input_kind=(
                        ForecastInputKind.MODEL_INFERENCE
                        if scenario is ForecastScenario.BASE
                        else ForecastInputKind.HUMAN_ASSUMPTION
                    ),
                    rationale="Externally supplied scenario input.",
                    human_assumption_ref=(
                        "assumption-set-v1" if scenario is not ForecastScenario.BASE else ""
                    ),
                    model_version=(
                        "r1-operating-trial-v1" if scenario is ForecastScenario.BASE else ""
                    ),
                ),
            )
        )
    return tuple(result)


def _projections() -> tuple[OperatingForecastProjection, ...]:
    return tuple(
        OperatingForecastProjection(
            scenario=scenario,
            revenue=Decimal(revenue),
            net_profit=Decimal(profit),
            currency_unit="CNY_million",
            sensitivities=(
                ValuationSensitivityPoint(
                    sensitivity_key="pe_multiple",
                    input_value=Decimal("10"),
                    input_unit="multiple",
                    output_value=Decimal(output),
                    output_unit="CNY_million",
                    method_version="sensitivity-sheet-v1",
                ),
            ),
        )
        for scenario, revenue, profit, output in (
            (ForecastScenario.BASE, "120", "12", "1200"),
            (ForecastScenario.BULL, "130", "16", "1500"),
            (ForecastScenario.BEAR, "95", "4", "700"),
        )
    )


def _command(fact_id: int) -> CreateOperatingForecastCommand:
    return CreateOperatingForecastCommand(
        forecast_id="forecast-000001-2026q2-v1",
        forecast_key="000001.SZ-2026Q2",
        forecast_version=1,
        subject_code="000001.SZ",
        industry_code="consumer-service",
        as_of_time=AS_OF,
        target_period_end=TARGET,
        horizon_quarters=1,
        methodology_ref="research-note-2026q2-v1",
        created_by_ref="analyst-7",
        fact_version_ids=(fact_id,),
        assumptions=_assumptions(fact_id),
        projections=_projections(),
        valuation_consumable=True,
        promotion_decision_id="promotion-approved-v1",
    )


@pytest.mark.django_db
def test_operating_fact_provider_rejects_inference_and_superseded_versions() -> None:
    inferred = _append_operating_fact(
        business_key="inferred-kpi",
        effective_at=datetime(2026, 3, 31, tzinfo=UTC),
        available_at=datetime(2026, 4, 20, tzinfo=UTC),
        value_kind="human_assumption",
        pit_quality="estimated",
    )
    provider = DjangoOperatingFactEvidenceProvider()
    with pytest.raises(OperatingForecastEvidenceError, match="verified PIT quality"):
        provider.get_operating_facts((inferred.pk,), as_of_time=AS_OF)

    old = _append_operating_fact(
        business_key="revised-kpi",
        effective_at=datetime(2026, 3, 31, tzinfo=UTC),
        available_at=datetime(2026, 4, 10, tzinfo=UTC),
    )
    latest = _append_operating_fact(
        business_key="revised-kpi",
        effective_at=datetime(2026, 3, 31, tzinfo=UTC),
        available_at=datetime(2026, 4, 20, tzinfo=UTC),
        revision_number=1,
        value="101",
    )
    with pytest.raises(OperatingForecastEvidenceError, match="latest public"):
        provider.get_operating_facts((old.pk,), as_of_time=AS_OF)
    assert provider.get_operating_facts((latest.pk,), as_of_time=AS_OF)[0].value == Decimal("101")


@pytest.mark.django_db
def test_forecast_repository_round_trip_promotion_and_quarterly_errors() -> None:
    source = _append_operating_fact(
        business_key="store-count-v1",
        effective_at=datetime(2026, 3, 31, tzinfo=UTC),
        available_at=datetime(2026, 4, 20, tzinfo=UTC),
    )
    _create_approved_promotion()
    create_use_case = build_create_operating_forecast_use_case()
    stored = create_use_case.execute(_command(source.pk))
    assert stored.usage_scope == "valuation_approved"
    assert stored.contains_model_inference is True
    assert OperatingForecastVersionModel._default_manager.count() == 1
    assert OperatingForecastFactReferenceModel._default_manager.count() == 1
    assert OperatingForecastAssumptionModel._default_manager.count() == 6
    assert OperatingForecastProjectionModel._default_manager.count() == 3
    assert OperatingForecastSensitivityModel._default_manager.count() == 3

    replay = create_use_case.execute(_command(source.pk))
    assert replay.content_hash == stored.content_hash
    assert OperatingForecastVersionModel._default_manager.count() == 1

    header = OperatingForecastVersionModel._default_manager.get(pk=stored.forecast_id)
    header.subject_code = "MUTATED"
    with pytest.raises(ValidationError, match="immutable"):
        header.save()
    with pytest.raises(ValidationError, match="cannot be updated"):
        OperatingForecastVersionModel.objects.filter(pk=header.pk).update(subject_code="MUTATED")
    with pytest.raises(ValidationError, match="bulk updated"):
        OperatingForecastVersionModel.objects.filter(pk=header.pk).bulk_update(
            [header], ["subject_code"]
        )
    with pytest.raises(ValidationError, match="cannot be deleted"):
        OperatingForecastVersionModel.objects.filter(pk=header.pk).delete()
    with pytest.raises(ValidationError, match="cannot be updated"):
        PITFactVersionModel.objects.filter(pk=source.pk).update(pit_quality="unknown")
    with pytest.raises(ValidationError, match="cannot be deleted"):
        PITFactVersionModel.objects.filter(pk=source.pk).delete()

    actual_revenue = _append_operating_fact(
        business_key="quarter-actual-revenue-v1",
        effective_at=datetime(2026, 6, 30, tzinfo=UTC),
        available_at=datetime(2026, 8, 15, tzinfo=UTC),
        metric_code="revenue",
        value="100",
        unit="CNY_million",
    )
    actual_profit = _append_operating_fact(
        business_key="quarter-actual-profit-v1",
        effective_at=datetime(2026, 6, 30, tzinfo=UTC),
        available_at=datetime(2026, 8, 15, tzinfo=UTC),
        metric_code="net_profit",
        value="8",
        unit="CNY_million",
    )
    evaluations = build_record_quarterly_actual_use_case().execute(
        RecordQuarterlyActualCommand(
            forecast_id=stored.forecast_id,
            actual_period_end=TARGET,
            recorded_at=datetime(2026, 8, 20, tzinfo=UTC),
            actual_fact_version_ids=(actual_revenue.pk, actual_profit.pk),
            actual_revenue=Decimal("100"),
            actual_net_profit=Decimal("8"),
            currency_unit="CNY_million",
        )
    )
    assert len(evaluations) == 3
    assert OperatingForecastEvaluationModel._default_manager.count() == 3
    base = OperatingForecastEvaluationModel._default_manager.get(scenario="base")
    assert base.revenue_error == Decimal("20")
    assert base.net_profit_absolute_percentage_error == Decimal("50")
    assert base.profit_margin_error == Decimal("2")
    assert {item["version_id"] for item in base.actual_fact_evidence} == {
        actual_revenue.pk,
        actual_profit.pk,
    }
    base.revenue_error = Decimal("999")
    with pytest.raises(ValidationError, match="immutable"):
        base.save()
