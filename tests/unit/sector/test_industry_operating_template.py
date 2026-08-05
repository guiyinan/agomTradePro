"""Unit coverage for the safe, fail-closed R1 industry template engine."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import cast

import pytest

from apps.sector.application.industry_operating_template import (
    IndustryTemplateRunRequest,
    RunIndustryOperatingTemplate,
)
from apps.sector.domain.industry_operating_template import (
    DriverDefinition,
    DriverInputKind,
    ExpressionNode,
    ExpressionOperator,
    FinancialStage,
    ForecastScenario,
    ImmutableTemplateRunEvidence,
    IndustryOperatingTemplate,
    PITDriverFact,
    ScenarioDriverOverride,
    StageOutput,
    TemplateLifecycle,
    TemplateRunStatus,
    UnitDerivationRule,
    ValueReference,
    ValueReferenceKind,
    evaluate_template,
)

AS_OF = datetime(2025, 3, 31, tzinfo=UTC)


def _driver(
    key: str,
    unit: str,
    *,
    fact_backed: bool,
) -> DriverDefinition:
    kinds = (
        (DriverInputKind.OBSERVED_FACT, DriverInputKind.HUMAN_ASSUMPTION)
        if fact_backed
        else (DriverInputKind.HUMAN_ASSUMPTION, DriverInputKind.MODEL_INFERENCE)
    )
    return DriverDefinition(
        driver_key=key,
        name=key,
        unit=unit,
        frequency="quarterly",
        source="test_source",
        allowed_input_kinds=kinds,
        metric_code=f"METRIC_{key}" if fact_backed else "",
        metric_definition_version=1 if fact_backed else 0,
        subject_type="asset" if fact_backed else "",
    )


def _ref(kind: ValueReferenceKind, key: str) -> ValueReference:
    return ValueReference(kind=kind, key=key)


def _template(
    *,
    lifecycle: TemplateLifecycle = TemplateLifecycle.ACTIVE,
) -> IndustryOperatingTemplate:
    nodes = (
        ExpressionNode(
            node_key="revenue",
            stage=FinancialStage.REVENUE,
            operator=ExpressionOperator.MULTIPLY,
            operands=(
                _ref(ValueReferenceKind.DRIVER, "volume"),
                _ref(ValueReferenceKind.DRIVER, "price"),
            ),
            output_unit="CNY",
            unit_rule_key="volume_price_to_cny",
        ),
        ExpressionNode(
            node_key="cost",
            stage=FinancialStage.COST,
            operator=ExpressionOperator.MULTIPLY,
            operands=(
                _ref(ValueReferenceKind.DRIVER, "volume"),
                _ref(ValueReferenceKind.DRIVER, "unit_cost"),
            ),
            output_unit="CNY",
            unit_rule_key="volume_cost_to_cny",
        ),
        ExpressionNode(
            node_key="gross_profit",
            stage=FinancialStage.GROSS_PROFIT,
            operator=ExpressionOperator.SUBTRACT,
            operands=(
                _ref(ValueReferenceKind.NODE, "revenue"),
                _ref(ValueReferenceKind.NODE, "cost"),
            ),
            output_unit="CNY",
        ),
        ExpressionNode(
            node_key="expense",
            stage=FinancialStage.EXPENSE,
            operator=ExpressionOperator.IDENTITY,
            operands=(_ref(ValueReferenceKind.DRIVER, "expense_input"),),
            output_unit="CNY",
        ),
        ExpressionNode(
            node_key="net_profit",
            stage=FinancialStage.NET_PROFIT,
            operator=ExpressionOperator.SUBTRACT,
            operands=(
                _ref(ValueReferenceKind.NODE, "gross_profit"),
                _ref(ValueReferenceKind.NODE, "expense"),
            ),
            output_unit="CNY",
        ),
        ExpressionNode(
            node_key="cash_flow",
            stage=FinancialStage.CASH_FLOW,
            operator=ExpressionOperator.ADD,
            operands=(
                _ref(ValueReferenceKind.NODE, "net_profit"),
                _ref(ValueReferenceKind.DRIVER, "cash_adjustment"),
            ),
            output_unit="CNY",
        ),
    )
    return IndustryOperatingTemplate(
        template_code="TEST_TEMPLATE",
        template_version=1,
        industry_code="TEST_INDUSTRY",
        name="Caller supplied test template",
        methodology_ref="governance://industry-template/v1",
        effective_at=datetime(2025, 1, 1, tzinfo=UTC),
        lifecycle=lifecycle,
        lifecycle_reason="retired by owner" if lifecycle is not TemplateLifecycle.ACTIVE else "",
        drivers=(
            _driver("volume", "unit_count", fact_backed=True),
            _driver("price", "CNY_per_unit", fact_backed=True),
            _driver("unit_cost", "CNY_per_unit", fact_backed=True),
            _driver("expense_input", "CNY", fact_backed=False),
            _driver("cash_adjustment", "CNY", fact_backed=False),
        ),
        unit_rules=(
            UnitDerivationRule(
                rule_key="volume_price_to_cny",
                operator=ExpressionOperator.MULTIPLY,
                left_unit="unit_count",
                right_unit="CNY_per_unit",
                output_unit="CNY",
                methodology_ref="governance://unit-rule/volume-price/v1",
            ),
            UnitDerivationRule(
                rule_key="volume_cost_to_cny",
                operator=ExpressionOperator.MULTIPLY,
                left_unit="unit_count",
                right_unit="CNY_per_unit",
                output_unit="CNY",
                methodology_ref="governance://unit-rule/volume-cost/v1",
            ),
        ),
        nodes=nodes,
        stage_outputs=tuple(
            StageOutput(stage=node.stage, node_key=node.node_key) for node in nodes
        ),
    )


def _fact(driver: DriverDefinition, value: str, version_id: int) -> PITDriverFact:
    return PITDriverFact(
        version_id=version_id,
        dataset="research.operating_observation.v1",
        business_key=f"{driver.driver_key}|TEST.ASSET",
        metric_code=driver.metric_code,
        metric_definition_version=driver.metric_definition_version,
        subject_code="TEST.ASSET",
        effective_at=datetime(2025, 3, 1, tzinfo=UTC),
        available_at=datetime(2025, 3, 10, tzinfo=UTC),
        value=Decimal(value),
        unit=driver.unit,
        frequency=driver.frequency,
        source=driver.source,
        source_record_id=f"source-{version_id}",
        content_hash=f"{version_id:x}".rjust(64, "0"),
        is_verified=True,
    )


def _overrides() -> tuple[ScenarioDriverOverride, ...]:
    rows: list[ScenarioDriverOverride] = []
    for scenario, expense, cash in (
        (ForecastScenario.BASE, "100", "50"),
        (ForecastScenario.BULL, "110", "50"),
        (ForecastScenario.BEAR, "90", "40"),
    ):
        rows.extend(
            (
                ScenarioDriverOverride(
                    scenario=scenario,
                    driver_key="expense_input",
                    value=Decimal(expense),
                    unit="CNY",
                    input_kind=DriverInputKind.HUMAN_ASSUMPTION,
                    rationale="scenario expense",
                    lineage_ref=f"assumption://expense/{scenario.value}",
                ),
                ScenarioDriverOverride(
                    scenario=scenario,
                    driver_key="cash_adjustment",
                    value=Decimal(cash),
                    unit="CNY",
                    input_kind=DriverInputKind.HUMAN_ASSUMPTION,
                    rationale="scenario cash adjustment",
                    lineage_ref=f"assumption://cash/{scenario.value}",
                ),
            )
        )
    rows.extend(
        (
            ScenarioDriverOverride(
                scenario=ForecastScenario.BULL,
                driver_key="price",
                value=Decimal("12"),
                unit="CNY_per_unit",
                input_kind=DriverInputKind.HUMAN_ASSUMPTION,
                rationale="bull price",
                lineage_ref="assumption://price/bull",
            ),
            ScenarioDriverOverride(
                scenario=ForecastScenario.BEAR,
                driver_key="price",
                value=Decimal("8"),
                unit="CNY_per_unit",
                input_kind=DriverInputKind.HUMAN_ASSUMPTION,
                rationale="bear price",
                lineage_ref="assumption://price/bear",
            ),
        )
    )
    return tuple(rows)


def _request(
    *,
    overrides: tuple[ScenarioDriverOverride, ...] | None = None,
) -> IndustryTemplateRunRequest:
    return IndustryTemplateRunRequest(
        run_key="TEST_RUN",
        run_version=1,
        template_code="TEST_TEMPLATE",
        template_version=1,
        forecast_id="TEST_FORECAST",
        forecast_key="TEST_FORECAST_KEY",
        forecast_version=1,
        subject_code="TEST.ASSET",
        industry_code="TEST_INDUSTRY",
        as_of_time=AS_OF,
        target_period_end=date(2025, 6, 30),
        horizon_quarters=1,
        created_by_ref="researcher:test",
        overrides=_overrides() if overrides is None else overrides,
    )


class _Repository:
    def __init__(self, template: IndustryOperatingTemplate | None) -> None:
        self.template = template
        self.evidence: ImmutableTemplateRunEvidence | None = None

    def append_template(
        self,
        template: IndustryOperatingTemplate,
    ) -> IndustryOperatingTemplate:
        self.template = template
        return template

    def get_template(
        self,
        *,
        template_code: str,
        template_version: int,
    ) -> IndustryOperatingTemplate | None:
        return self.template

    def append_run_evidence(
        self,
        evidence: ImmutableTemplateRunEvidence,
    ) -> ImmutableTemplateRunEvidence:
        self.evidence = evidence
        return evidence

    def get_run_evidence(
        self,
        *,
        run_key: str,
        run_version: int,
    ) -> ImmutableTemplateRunEvidence | None:
        return self.evidence


class _FactProvider:
    def __init__(self, template: IndustryOperatingTemplate, *, future: bool = False) -> None:
        fact_drivers = [
            driver
            for driver in template.drivers
            if DriverInputKind.OBSERVED_FACT in driver.allowed_input_kinds
        ]
        values = {"volume": "100", "price": "10", "unit_cost": "6"}
        self.facts = {
            driver.driver_key: _fact(
                driver,
                values[driver.driver_key],
                index + 1,
            )
            for index, driver in enumerate(fact_drivers)
        }
        if future:
            price = self.facts["price"]
            self.facts["price"] = replace(
                price,
                available_at=AS_OF + timedelta(days=1),
            )

    def get_fact(
        self,
        driver: DriverDefinition,
        *,
        subject_code: str,
        as_of_time: datetime,
    ) -> PITDriverFact | None:
        return self.facts.get(driver.driver_key)


def test_template_rejects_cycle_before_any_expression_can_execute() -> None:
    template = _template()
    nodes = list(template.nodes)
    cost = next(node for node in nodes if node.node_key == "cost")
    nodes[nodes.index(cost)] = replace(
        cost,
        operands=(
            _ref(ValueReferenceKind.NODE, "gross_profit"),
            _ref(ValueReferenceKind.DRIVER, "unit_cost"),
        ),
    )

    with pytest.raises(ValueError, match="cycle"):
        replace(template, nodes=tuple(nodes))


def test_template_rejects_unit_mismatch_and_unknown_string_operator() -> None:
    template = _template()
    gross = next(node for node in template.nodes if node.node_key == "gross_profit")
    with pytest.raises(ValueError, match="unit mismatch"):
        replace(
            template,
            nodes=tuple(
                replace(node, output_unit="USD") if node is gross else node
                for node in template.nodes
            ),
        )
    with pytest.raises(ValueError, match="operator is invalid"):
        ExpressionNode(
            node_key="unsafe",
            stage=FinancialStage.REVENUE,
            operator=cast(ExpressionOperator, "eval"),
            operands=(_ref(ValueReferenceKind.DRIVER, "volume"),),
            output_unit="unit_count",
        )


def test_finite_evaluator_calculates_required_dependency_chain() -> None:
    template = _template()
    values = {
        "volume": Decimal("100"),
        "price": Decimal("10"),
        "unit_cost": Decimal("6"),
        "expense_input": Decimal("100"),
        "cash_adjustment": Decimal("50"),
    }

    outputs = {item.stage: item for item in evaluate_template(template, values)}

    assert outputs[FinancialStage.REVENUE].value == Decimal("1000")
    assert outputs[FinancialStage.COST].value == Decimal("600")
    assert outputs[FinancialStage.GROSS_PROFIT].value == Decimal("400")
    assert outputs[FinancialStage.NET_PROFIT].value == Decimal("300")
    assert outputs[FinancialStage.CASH_FLOW].value == Decimal("350")


def test_run_builds_three_scenario_equity_compatible_research_draft() -> None:
    template = _template()
    repository = _Repository(template)

    result = RunIndustryOperatingTemplate(
        repository=repository,
        fact_provider=_FactProvider(template),
    ).execute(_request())

    assert result.status is TemplateRunStatus.AVAILABLE
    assert result.research_only is True
    assert result.must_not_use_for_decision is True
    assert repository.evidence is not None
    assert repository.evidence.content_hash == result.content_hash
    assert result.forecast_draft is not None
    assert result.forecast_draft.template_content_hash == template.content_hash
    assert len(result.forecast_draft.assumptions) == 15
    projections = {
        projection.scenario: projection for projection in result.forecast_draft.projections
    }
    assert projections[ForecastScenario.BASE].revenue == Decimal("1000")
    assert projections[ForecastScenario.BASE].net_profit == Decimal("300")
    assert projections[ForecastScenario.BULL].revenue == Decimal("1200")
    assert projections[ForecastScenario.BEAR].revenue == Decimal("800")


def test_missing_driver_fails_closed_without_partial_projection() -> None:
    template = _template()
    overrides = tuple(
        override
        for override in _overrides()
        if not (
            override.scenario is ForecastScenario.BEAR and override.driver_key == "expense_input"
        )
    )

    result = RunIndustryOperatingTemplate(
        repository=_Repository(template),
        fact_provider=_FactProvider(template),
    ).execute(_request(overrides=overrides))

    assert result.status is TemplateRunStatus.BLOCKED
    assert result.forecast_draft is None
    assert "driver_missing:bear:expense_input" in result.blocked_reasons


def test_future_pit_fact_fails_closed() -> None:
    template = _template()

    result = RunIndustryOperatingTemplate(
        repository=_Repository(template),
        fact_provider=_FactProvider(template, future=True),
    ).execute(_request())

    assert result.status is TemplateRunStatus.BLOCKED
    assert result.forecast_draft is None
    assert "pit_fact_mismatch:price" in result.blocked_reasons


@pytest.mark.parametrize(
    "lifecycle",
    [TemplateLifecycle.INVALIDATED, TemplateLifecycle.RETIRED],
)
def test_invalidated_or_retired_template_cannot_run(
    lifecycle: TemplateLifecycle,
) -> None:
    template = _template(lifecycle=lifecycle)

    result = RunIndustryOperatingTemplate(
        repository=_Repository(template),
        fact_provider=_FactProvider(template),
    ).execute(_request())

    assert result.status is TemplateRunStatus.BLOCKED
    assert f"template_{lifecycle.value}" in result.blocked_reasons


def test_template_hash_changes_with_versioned_semantics() -> None:
    template = _template()
    changed_driver = replace(template.drivers[0], frequency="monthly")

    changed = replace(
        template,
        template_version=2,
        supersedes_version=1,
        drivers=(changed_driver, *template.drivers[1:]),
    )

    assert changed.content_hash != template.content_hash
