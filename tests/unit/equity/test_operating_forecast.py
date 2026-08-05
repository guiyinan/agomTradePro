"""Unit contracts for the R1 operating-forecast ledger."""

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from apps.equity.application.operating_forecast import (
    CreateOperatingForecastCommand,
    CreateOperatingForecastVersionUseCase,
    OperatingForecastPromotionError,
    RecordQuarterlyActualCommand,
    RecordQuarterlyOperatingActualUseCase,
)
from apps.equity.domain.operating_forecast import (
    ForecastInputKind,
    ForecastScenario,
    OperatingFactEvidence,
    OperatingForecastAssumption,
    OperatingForecastEvaluation,
    OperatingForecastProjection,
    OperatingForecastSourceKind,
    OperatingForecastSourceLineageStatus,
    OperatingForecastStage,
    OperatingForecastStageValue,
    OperatingForecastVersion,
    ValuationSensitivityPoint,
    build_quarterly_evaluations,
)

AS_OF = datetime(2026, 4, 30, 8, tzinfo=UTC)
TARGET = date(2026, 6, 30)


def _fact(
    version_id: int = 11,
    *,
    metric_code: str = "store_count",
    value: str = "100",
    unit: str = "count",
) -> OperatingFactEvidence:
    return OperatingFactEvidence(
        version_id=version_id,
        dataset="research.operating_observation.v1",
        business_key=f"{metric_code}|company|000001.SZ|{version_id}",
        metric_code=metric_code,
        subject_type="company",
        subject_code="000001.SZ",
        effective_at=datetime(2026, 3, 31, tzinfo=UTC),
        available_at=datetime(2026, 4, 20, tzinfo=UTC),
        source_record_id=f"annual-report-{version_id}",
        content_hash=f"{version_id:064x}",
        value=Decimal(value),
        unit=unit,
    )


def _assumptions(
    *,
    fact_id: int = 11,
    include_model: bool = False,
) -> tuple[OperatingForecastAssumption, ...]:
    items: list[OperatingForecastAssumption] = []
    fact = _fact(fact_id)
    for scenario, growth in (
        (ForecastScenario.BASE, "5"),
        (ForecastScenario.BULL, "8"),
        (ForecastScenario.BEAR, "-2"),
    ):
        items.append(
            OperatingForecastAssumption(
                scenario=scenario,
                assumption_key="store_count",
                value=fact.value,
                unit=fact.unit,
                input_kind=ForecastInputKind.OBSERVED_FACT,
                rationale="Latest public PIT store count available at forecast freeze.",
                observed_fact_version_id=fact_id,
                observed_metric_code=fact.metric_code,
                observed_fact_content_hash=fact.content_hash,
                observed_subject_type=fact.subject_type,
                observed_subject_code=fact.subject_code,
            )
        )
        items.append(
            OperatingForecastAssumption(
                scenario=scenario,
                assumption_key="same_store_growth",
                value=Decimal(growth),
                unit="percent",
                input_kind=(
                    ForecastInputKind.MODEL_INFERENCE
                    if include_model and scenario is ForecastScenario.BASE
                    else ForecastInputKind.HUMAN_ASSUMPTION
                ),
                rationale="Scenario-specific growth input; no formula embedded in code.",
                human_assumption_ref=(
                    "assumption-set-2026q2"
                    if not (include_model and scenario is ForecastScenario.BASE)
                    else ""
                ),
                model_version=(
                    "model-trial-v3" if include_model and scenario is ForecastScenario.BASE else ""
                ),
            )
        )
    return tuple(items)


def _projections() -> tuple[OperatingForecastProjection, ...]:
    result: list[OperatingForecastProjection] = []
    for scenario, revenue, profit, cash_flow, output in (
        (ForecastScenario.BASE, "120", "12", "10", "1200"),
        (ForecastScenario.BULL, "130", "16", "14", "1500"),
        (ForecastScenario.BEAR, "95", "4", "2", "700"),
    ):
        result.append(
            OperatingForecastProjection(
                scenario=scenario,
                revenue=Decimal(revenue),
                net_profit=Decimal(profit),
                cash_flow=Decimal(cash_flow),
                currency_unit="CNY_million",
                stage_values=(
                    OperatingForecastStageValue(
                        stage=OperatingForecastStage.REVENUE,
                        node_key="revenue_node",
                        value=Decimal(revenue),
                        unit="CNY_million",
                    ),
                    OperatingForecastStageValue(
                        stage=OperatingForecastStage.COST,
                        node_key="cost_node",
                        value=Decimal("60"),
                        unit="CNY_million",
                    ),
                    OperatingForecastStageValue(
                        stage=OperatingForecastStage.GROSS_PROFIT,
                        node_key="gross_profit_node",
                        value=Decimal(revenue) - Decimal("60"),
                        unit="CNY_million",
                    ),
                    OperatingForecastStageValue(
                        stage=OperatingForecastStage.EXPENSE,
                        node_key="expense_node",
                        value=Decimal("20"),
                        unit="CNY_million",
                    ),
                    OperatingForecastStageValue(
                        stage=OperatingForecastStage.NET_PROFIT,
                        node_key="net_profit_node",
                        value=Decimal(profit),
                        unit="CNY_million",
                    ),
                    OperatingForecastStageValue(
                        stage=OperatingForecastStage.CASH_FLOW,
                        node_key="cash_flow_node",
                        value=Decimal(cash_flow),
                        unit="CNY_million",
                    ),
                ),
                sensitivities=(
                    ValuationSensitivityPoint(
                        sensitivity_key="pe_multiple",
                        input_value=Decimal("10"),
                        input_unit="multiple",
                        output_value=Decimal(output),
                        output_unit="CNY_million",
                        method_version="sensitivity-sheet-v1",
                        source_artifact_ref="valuation://worksheet/r1/v1",
                        source_artifact_hash="c" * 64,
                    ),
                ),
            )
        )
    return tuple(result)


def _forecast(
    *,
    include_model: bool = False,
    valuation_consumable: bool = False,
    promotion_decision_id: str = "",
) -> OperatingForecastVersion:
    return OperatingForecastVersion(
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
        source_kind=OperatingForecastSourceKind.INDUSTRY_TEMPLATE,
        evidence_schema_version=2,
        source_lineage_status=OperatingForecastSourceLineageStatus.TEMPLATE_BOUND,
        template_code="consumer-service-v1",
        template_version=1,
        template_content_hash="a" * 64,
        template_run_key="consumer-service-000001-2026q2",
        template_run_version=1,
        template_run_content_hash="b" * 64,
        facts=(_fact(),),
        assumptions=_assumptions(include_model=include_model),
        projections=_projections(),
        valuation_consumable=valuation_consumable,
        promotion_decision_id=promotion_decision_id,
    )


def test_forecast_requires_exact_scenarios_and_observed_grounding() -> None:
    valid = _forecast()
    assert valid.usage_scope == "research_only"
    assert len(valid.content_hash) == 64
    assert {projection.scenario for projection in valid.projections} == set(ForecastScenario)

    with pytest.raises(ValueError, match="exactly base, bull and bear"):
        replace(valid, projections=valid.projections[:-1])

    bear_without_fact = tuple(
        item
        for item in valid.assumptions
        if not (
            item.scenario is ForecastScenario.BEAR
            and item.input_kind is ForecastInputKind.OBSERVED_FACT
        )
    )
    with pytest.raises(ValueError, match="bear requires observed PIT fact grounding"):
        replace(valid, assumptions=bear_without_fact)


def test_assumption_lineage_is_mutually_exclusive_and_reconstructible() -> None:
    with pytest.raises(ValueError, match="sha256"):
        replace(_fact(), content_hash="z" * 64)

    with pytest.raises(ValueError, match="exactly one input_kind"):
        OperatingForecastAssumption(
            scenario=ForecastScenario.BASE,
            assumption_key="conflicted",
            value=Decimal("1"),
            unit="percent",
            input_kind=ForecastInputKind.HUMAN_ASSUMPTION,
            rationale="Conflicting lineage must fail.",
            observed_fact_version_id=11,
            human_assumption_ref="human-v1",
        )

    model_forecast = _forecast(include_model=True)
    assert model_forecast.contains_model_inference is True
    model_input = next(
        item
        for item in model_forecast.assumptions
        if item.input_kind is ForecastInputKind.MODEL_INFERENCE
    )
    assert model_input.lineage_ref == "model-trial-v3"


def test_observed_assumption_rejects_tampered_value_metric_and_subject() -> None:
    valid = _forecast()
    with pytest.raises(ValueError, match="subject, metric, value and unit"):
        replace(valid, facts=(replace(_fact(), value=Decimal("101")),))
    with pytest.raises(ValueError, match="subject, metric, value and unit"):
        replace(valid, facts=(replace(_fact(), metric_code="net_profit"),))
    with pytest.raises(ValueError, match="forecast company subject"):
        replace(valid, facts=(replace(_fact(), subject_code="OTHER.SZ"),))


def test_quarterly_evaluation_calculates_signed_mae_mape_and_margin_error() -> None:
    evaluations = build_quarterly_evaluations(
        _forecast(),
        actual_period_end=TARGET,
        recorded_at=datetime(2026, 8, 15, tzinfo=UTC),
        actual_facts=(
            _fact(21, metric_code="revenue", value="100", unit="CNY_million"),
            _fact(22, metric_code="net_profit", value="8", unit="CNY_million"),
        ),
        actual_revenue=Decimal("100"),
        actual_net_profit=Decimal("8"),
        currency_unit="CNY_million",
    )
    base = next(item for item in evaluations if item.scenario is ForecastScenario.BASE)
    assert base.revenue_error == Decimal("20")
    assert base.revenue_absolute_error == Decimal("20")
    assert base.revenue_absolute_percentage_error == Decimal("20")
    assert base.net_profit_error == Decimal("4")
    assert base.net_profit_absolute_percentage_error == Decimal("50")
    assert base.profit_margin_error == Decimal("2")
    assert len(base.content_hash) == 64

    with pytest.raises(ValueError, match="quarterly actual must exactly match"):
        build_quarterly_evaluations(
            _forecast(),
            actual_period_end=TARGET,
            recorded_at=datetime(2026, 8, 15, tzinfo=UTC),
            actual_facts=(
                _fact(21, metric_code="revenue", value="999", unit="CNY_million"),
                _fact(22, metric_code="net_profit", value="8", unit="CNY_million"),
            ),
            actual_revenue=Decimal("100"),
            actual_net_profit=Decimal("8"),
            currency_unit="CNY_million",
        )


class _FactProvider:
    def __init__(self, facts: tuple[OperatingFactEvidence, ...]) -> None:
        self.facts = facts

    def get_operating_facts(
        self,
        version_ids: tuple[int, ...],
        *,
        as_of_time: datetime,
    ) -> tuple[OperatingFactEvidence, ...]:
        del version_ids, as_of_time
        return self.facts


class _PromotionChecker:
    def __init__(self, approved: bool) -> None:
        self.approved = approved

    def is_approved(self, decision_id: str) -> bool:
        return self.approved and decision_id == "promotion-approved-v1"


class _RunEvidenceProvider:
    def get_run_evidence(
        self,
        *,
        run_key: str,
        run_version: int,
    ) -> None:
        del run_key, run_version
        return None


class _ForecastRepository:
    def __init__(self, forecast: OperatingForecastVersion | None = None) -> None:
        self.forecast = forecast
        self.evaluations: tuple[OperatingForecastEvaluation, ...] = ()

    def append_version(self, forecast: OperatingForecastVersion) -> OperatingForecastVersion:
        self.forecast = forecast
        return forecast

    def get_version(self, forecast_id: str) -> OperatingForecastVersion | None:
        if self.forecast is None or self.forecast.forecast_id != forecast_id:
            return None
        return self.forecast

    def append_evaluations(
        self,
        evaluations: tuple[OperatingForecastEvaluation, ...],
    ) -> tuple[OperatingForecastEvaluation, ...]:
        self.evaluations = evaluations
        return evaluations


def _create_command(*, valuation_consumable: bool) -> CreateOperatingForecastCommand:
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
        template_code="consumer-service-v1",
        template_version=1,
        template_content_hash="a" * 64,
        template_run_key="consumer-service-000001-2026q2",
        template_run_version=1,
        template_run_content_hash="b" * 64,
        fact_version_ids=(11,),
        assumptions=_assumptions(include_model=True),
        projections=_projections(),
        valuation_consumable=valuation_consumable,
        promotion_decision_id="promotion-approved-v1" if valuation_consumable else "",
    )


def test_schema_v2_promotion_stays_closed_even_for_legacy_approved_decision() -> None:
    repository = _ForecastRepository()
    use_case = CreateOperatingForecastVersionUseCase(
        repository,
        _FactProvider((_fact(),)),
        _PromotionChecker(approved=False),
        _RunEvidenceProvider(),
    )
    with pytest.raises(OperatingForecastPromotionError, match="exact artifact binding"):
        use_case.execute(_create_command(valuation_consumable=True))
    assert repository.forecast is None

    legacy_approved = CreateOperatingForecastVersionUseCase(
        repository,
        _FactProvider((_fact(),)),
        _PromotionChecker(approved=True),
        _RunEvidenceProvider(),
    )
    with pytest.raises(OperatingForecastPromotionError, match="exact artifact binding"):
        legacy_approved.execute(_create_command(valuation_consumable=True))
    assert repository.forecast is None


def test_record_actual_use_case_appends_all_three_scenarios() -> None:
    repository = _ForecastRepository(_forecast())
    use_case = RecordQuarterlyOperatingActualUseCase(
        repository,
        _FactProvider(
            (
                _fact(21, metric_code="revenue", value="100", unit="CNY_million"),
                _fact(22, metric_code="net_profit", value="8", unit="CNY_million"),
            )
        ),
    )
    result = use_case.execute(
        RecordQuarterlyActualCommand(
            forecast_id="forecast-000001-2026q2-v1",
            actual_period_end=TARGET,
            recorded_at=datetime(2026, 8, 15, tzinfo=UTC),
            actual_fact_version_ids=(21, 22),
            actual_revenue=Decimal("100"),
            actual_net_profit=Decimal("8"),
            currency_unit="CNY_million",
        )
    )
    assert {item.scenario for item in result} == set(ForecastScenario)
    assert repository.evaluations == result
