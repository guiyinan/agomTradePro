"""Coverage ratchet for every Sector operating-template domain entry point."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from apps.sector.domain import industry_operating_template as domain
from apps.sector.domain.industry_operating_template import (
    DriverInputKind,
    ExpressionNode,
    ExpressionOperator,
    FinancialStage,
    ForecastAssumptionDraft,
    ForecastProjectionDraft,
    ForecastScenario,
    ImmutableTemplateRunEvidence,
    IndustryTemplateRunResult,
    OperatingForecastDraft,
    PITDriverFact,
    ScenarioDriverOverride,
    StageOutput,
    StageValue,
    TemplateEvaluationError,
    TemplateRunStatus,
    UnitDerivationRule,
    ValueReference,
    ValueReferenceKind,
    build_template_run_evidence,
    evaluate_template,
    restore_template_run_result,
)
from tests.unit.sector.test_industry_operating_template import (
    AS_OF,
    _driver,
    _fact,
    _template,
)

SHA = "a" * 64


@pytest.mark.parametrize("value", ["", " ", "x" * 11])
def test_text_guard_rejects_blank_and_long_values(value: str) -> None:
    with pytest.raises(ValueError):
        domain._require_text(value, "value", maximum=10)


def test_token_guard_rejects_whitespace() -> None:
    with pytest.raises(ValueError, match="whitespace"):
        domain._require_token("bad token", "value", maximum=20)


def test_primitive_guards_reject_naive_non_finite_and_bad_hash() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        domain._require_aware(datetime(2026, 1, 1), "value")
    with pytest.raises(ValueError, match="finite Decimal"):
        domain._require_finite(Decimal("NaN"), "value")
    with pytest.raises(ValueError, match="SHA-256"):
        domain._require_sha256("bad", "value")
    assert domain._decimal_text(Decimal("0.00")) == "0"


def test_driver_definition_rejects_every_binding_shape() -> None:
    valid = _driver("volume", "unit_count", fact_backed=True)
    with pytest.raises(ValueError, match="allowed_input_kinds is invalid"):
        replace(valid, allowed_input_kinds=("observed_fact",))
    with pytest.raises(ValueError, match="cannot be empty"):
        replace(valid, allowed_input_kinds=())
    with pytest.raises(ValueError, match="cannot contain duplicates"):
        replace(
            valid,
            allowed_input_kinds=(
                DriverInputKind.OBSERVED_FACT,
                DriverInputKind.OBSERVED_FACT,
            ),
        )
    with pytest.raises(ValueError, match="metric_definition_version"):
        replace(valid, metric_definition_version=0)
    non_fact = _driver("expense", "CNY", fact_backed=False)
    with pytest.raises(ValueError, match="cannot carry"):
        replace(non_fact, metric_code="EXPENSE")


def test_unit_reference_node_and_stage_guards() -> None:
    rule = UnitDerivationRule(
        rule_key="multiply-v1",
        operator=ExpressionOperator.MULTIPLY,
        left_unit="unit",
        right_unit="price",
        output_unit="CNY",
        methodology_ref="method://v1",
    )
    with pytest.raises(ValueError, match="only support"):
        replace(rule, operator=ExpressionOperator.ADD)
    with pytest.raises(ValueError, match="kind is invalid"):
        ValueReference("driver", "volume")
    reference = ValueReference(ValueReferenceKind.DRIVER, "volume")
    node = ExpressionNode(
        node_key="revenue",
        stage=FinancialStage.REVENUE,
        operator=ExpressionOperator.IDENTITY,
        operands=(reference,),
        output_unit="unit",
    )
    with pytest.raises(ValueError, match="stage is invalid"):
        replace(node, stage="revenue")
    with pytest.raises(ValueError, match="operator is invalid"):
        replace(node, operator="identity")
    with pytest.raises(ValueError, match="operand count"):
        replace(node, operands=(reference, reference))
    with pytest.raises(ValueError, match="cannot carry"):
        replace(node, unit_rule_key="unexpected")
    with pytest.raises(ValueError, match="StageOutput.stage is invalid"):
        StageOutput("revenue", "revenue")


def _node(template, key: str) -> ExpressionNode:
    return next(item for item in template.nodes if item.node_key == key)


def _replace_node(template, key: str, changed: ExpressionNode):
    return replace(
        template,
        nodes=tuple(changed if item.node_key == key else item for item in template.nodes),
    )


def test_template_metadata_guards() -> None:
    template = _template()
    with pytest.raises(ValueError, match="template_version"):
        replace(template, template_version=True)
    with pytest.raises(ValueError, match="effective_to must follow"):
        replace(template, effective_to=template.effective_at)
    with pytest.raises(ValueError, match="lifecycle is invalid"):
        replace(template, lifecycle="active")
    with pytest.raises(ValueError, match="active template cannot carry"):
        replace(template, lifecycle_reason="unexpected")
    with pytest.raises(ValueError, match="supersedes_version"):
        replace(template, template_version=2, supersedes_version=2)
    with pytest.raises(ValueError, match="research-only"):
        replace(template, research_only=False)


def test_template_collection_guards() -> None:
    template = _template()
    with pytest.raises(ValueError, match="requires drivers"):
        replace(template, drivers=())
    with pytest.raises(ValueError, match="driver keys must be unique"):
        replace(template, drivers=(*template.drivers, template.drivers[0]))
    with pytest.raises(ValueError, match="node keys must be unique"):
        replace(template, nodes=(*template.nodes, template.nodes[0]))
    with pytest.raises(ValueError, match="unit rule keys must be unique"):
        replace(template, unit_rules=(*template.unit_rules, template.unit_rules[0]))
    overlapping = replace(template.drivers[0], driver_key=template.nodes[0].node_key)
    with pytest.raises(ValueError, match="cannot overlap"):
        replace(template, drivers=(overlapping, *template.drivers[1:]))
    with pytest.raises(ValueError, match="every financial stage"):
        replace(template, stage_outputs=template.stage_outputs[:-1])
    revenue_output = next(
        item for item in template.stage_outputs if item.stage is FinancialStage.REVENUE
    )
    wrong_output = replace(revenue_output, node_key="cash_flow")
    with pytest.raises(ValueError, match="same stage"):
        replace(
            template,
            stage_outputs=tuple(
                wrong_output if item.stage is FinancialStage.REVENUE else item
                for item in template.stage_outputs
            ),
        )


def test_template_reference_and_unit_guards() -> None:
    template = _template()
    revenue = _node(template, "revenue")
    missing_driver = replace(
        revenue,
        operands=(
            ValueReference(ValueReferenceKind.DRIVER, "missing"),
            revenue.operands[1],
        ),
    )
    with pytest.raises(ValueError, match="missing driver reference"):
        _replace_node(template, "revenue", missing_driver)
    gross = _node(template, "gross_profit")
    missing_node = replace(
        gross,
        operands=(ValueReference(ValueReferenceKind.NODE, "missing"), gross.operands[1]),
    )
    with pytest.raises(ValueError, match="missing node reference"):
        _replace_node(template, "gross_profit", missing_node)
    cost = _node(template, "cost")
    backwards = replace(
        cost,
        operands=(ValueReference(ValueReferenceKind.NODE, "net_profit"), cost.operands[1]),
    )
    with pytest.raises(ValueError, match="points backward"):
        _replace_node(template, "cost", backwards)
    expense = _node(template, "expense")
    with pytest.raises(ValueError, match="identity expression unit mismatch"):
        _replace_node(template, "expense", replace(expense, output_unit="USD"))
    with pytest.raises(ValueError, match="unit derivation rule is missing"):
        _replace_node(template, "revenue", replace(revenue, unit_rule_key="missing"))
    bad_rule = replace(template.unit_rules[0], left_unit="wrong")
    with pytest.raises(ValueError, match="unit rule mismatch"):
        replace(template, unit_rules=(bad_rule, *template.unit_rules[1:]))


def test_template_financial_dependency_guards() -> None:
    template = _template()
    gross = _node(template, "gross_profit")
    detached_gross = replace(
        gross,
        operands=(
            ValueReference(ValueReferenceKind.DRIVER, "expense_input"),
            ValueReference(ValueReferenceKind.DRIVER, "cash_adjustment"),
        ),
    )
    with pytest.raises(ValueError, match="gross-profit output must depend"):
        _replace_node(template, "gross_profit", detached_gross)

    net_profit = _node(template, "net_profit")
    detached_profit = replace(
        net_profit,
        operands=(
            ValueReference(ValueReferenceKind.NODE, "revenue"),
            ValueReference(ValueReferenceKind.NODE, "expense"),
        ),
    )
    with pytest.raises(ValueError, match="net-profit output must depend on gross profit or cost"):
        _replace_node(template, "net_profit", detached_profit)

    no_expense = replace(
        net_profit,
        operands=(
            ValueReference(ValueReferenceKind.NODE, "gross_profit"),
            ValueReference(ValueReferenceKind.NODE, "revenue"),
        ),
    )
    with pytest.raises(ValueError, match="must depend on expense"):
        _replace_node(template, "net_profit", no_expense)

    cash_flow = _node(template, "cash_flow")
    detached_cash = replace(
        cash_flow,
        operands=(
            ValueReference(ValueReferenceKind.NODE, "gross_profit"),
            ValueReference(ValueReferenceKind.DRIVER, "cash_adjustment"),
        ),
    )
    with pytest.raises(ValueError, match="cash-flow output must depend"):
        _replace_node(template, "cash_flow", detached_cash)


def test_transitive_dependencies_skips_already_seen_nodes() -> None:
    assert domain._transitive_dependencies({"a": (), "b": ("a", "a"), "c": ("b", "a")})["c"] == {
        "a",
        "b",
    }


def _pit_fact() -> PITDriverFact:
    return _fact(_driver("volume", "unit_count", fact_backed=True), "10", 1)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"version_id": True}, "version_id"),
        ({"metric_definition_version": 0}, "metric_definition_version"),
        ({"available_at": datetime(2025, 2, 1, tzinfo=UTC)}, "before effective"),
        ({"is_verified": 1}, "must be a boolean"),
    ],
)
def test_pit_fact_rejects_invalid_values(changes: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        replace(_pit_fact(), **changes)


def _override() -> ScenarioDriverOverride:
    return ScenarioDriverOverride(
        scenario=ForecastScenario.BASE,
        driver_key="expense",
        value=Decimal("1"),
        unit="CNY",
        input_kind=DriverInputKind.HUMAN_ASSUMPTION,
        rationale="manual input",
        lineage_ref="assumption://1",
    )


def test_scenario_override_rejects_invalid_scenario_and_kind() -> None:
    with pytest.raises(ValueError, match="scenario is invalid"):
        replace(_override(), scenario="base")
    with pytest.raises(ValueError, match="human assumptions or model"):
        replace(_override(), input_kind=DriverInputKind.OBSERVED_FACT)


def _assumption(
    *,
    scenario: ForecastScenario = ForecastScenario.BASE,
    kind: DriverInputKind = DriverInputKind.OBSERVED_FACT,
) -> ForecastAssumptionDraft:
    return ForecastAssumptionDraft(
        scenario=scenario,
        assumption_key="volume",
        value=Decimal("10"),
        unit="unit_count",
        input_kind=kind,
        rationale="governed input",
        observed_fact_version_id=1 if kind is DriverInputKind.OBSERVED_FACT else None,
        human_assumption_ref="human://1" if kind is DriverInputKind.HUMAN_ASSUMPTION else "",
        model_version="model-v1" if kind is DriverInputKind.MODEL_INFERENCE else "",
    )


def test_forecast_assumption_rejects_invalid_type_version_and_lineage() -> None:
    valid = _assumption()
    with pytest.raises(ValueError, match="scenario is invalid"):
        replace(valid, scenario="base")
    with pytest.raises(ValueError, match="input_kind is invalid"):
        replace(valid, input_kind="observed_fact")
    with pytest.raises(ValueError, match="must be positive"):
        replace(valid, observed_fact_version_id=True)
    with pytest.raises(ValueError, match="exactly one input kind"):
        replace(valid, observed_fact_version_id=None)
    with pytest.raises(ValueError, match="exactly one input kind"):
        replace(valid, human_assumption_ref="also-populated")
    assert _assumption(kind=DriverInputKind.HUMAN_ASSUMPTION).lineage_ref == "human://1"
    assert _assumption(kind=DriverInputKind.MODEL_INFERENCE).lineage_ref == "model-v1"


def _stage_values() -> tuple[StageValue, ...]:
    return evaluate_template(
        _template(),
        {
            "volume": Decimal("10"),
            "price": Decimal("12"),
            "unit_cost": Decimal("5"),
            "expense_input": Decimal("10"),
            "cash_adjustment": Decimal("2"),
        },
    )


def test_stage_and_projection_guards() -> None:
    value = StageValue(FinancialStage.REVENUE, "revenue", Decimal("1"), "CNY")
    with pytest.raises(ValueError, match="StageValue.stage is invalid"):
        replace(value, stage="revenue")
    projection = ForecastProjectionDraft(
        ForecastScenario.BASE,
        Decimal("120"),
        Decimal("60"),
        Decimal("62"),
        "CNY",
        _stage_values(),
    )
    with pytest.raises(ValueError, match="scenario is invalid"):
        replace(projection, scenario="base")
    with pytest.raises(ValueError, match="revenue must be positive"):
        replace(projection, revenue=Decimal("0"))
    with pytest.raises(ValueError, match="every financial stage"):
        replace(projection, stage_values=projection.stage_values[:-1])


def _forecast_draft() -> OperatingForecastDraft:
    stages = _stage_values()
    by_stage = {item.stage: item.value for item in stages}
    projections = tuple(
        ForecastProjectionDraft(
            scenario=scenario,
            revenue=by_stage[FinancialStage.REVENUE],
            net_profit=by_stage[FinancialStage.NET_PROFIT],
            cash_flow=by_stage[FinancialStage.CASH_FLOW],
            currency_unit="CNY",
            stage_values=stages,
        )
        for scenario in ForecastScenario
    )
    assumptions = tuple(_assumption(scenario=scenario) for scenario in ForecastScenario)
    template = _template()
    return OperatingForecastDraft(
        forecast_id="forecast-1",
        forecast_key="test",
        forecast_version=1,
        subject_code="TEST.ASSET",
        industry_code="TEST_INDUSTRY",
        as_of_time=AS_OF,
        target_period_end=date(2025, 6, 30),
        horizon_quarters=1,
        methodology_ref="method://forecast-v1",
        created_by_ref="researcher-1",
        template_code=template.template_code,
        template_version=template.template_version,
        template_content_hash=template.content_hash,
        fact_version_ids=(1,),
        assumptions=assumptions,
        projections=projections,
    )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"forecast_version": True}, "must be positive"),
        ({"target_period_end": date(2025, 1, 1)}, "precedes"),
        ({"research_only": False}, "research-only"),
        ({"fact_version_ids": ()}, "unique PIT fact versions"),
        ({"fact_version_ids": (True,)}, "must be positive"),
        ({"projections": ()}, "exactly base, bull and bear"),
        (
            {
                "assumptions": tuple(
                    item
                    for item in _forecast_draft().assumptions
                    if item.scenario is not ForecastScenario.BEAR
                )
            },
            "requires assumptions",
        ),
        (
            {
                "assumptions": tuple(
                    replace(
                        item,
                        input_kind=DriverInputKind.HUMAN_ASSUMPTION,
                        observed_fact_version_id=None,
                        human_assumption_ref="human://1",
                    )
                    for item in _forecast_draft().assumptions
                )
            },
            "need captured PIT facts",
        ),
    ],
)
def test_operating_forecast_rejects_invalid_values(
    changes: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        replace(_forecast_draft(), **changes)


def _blocked_result() -> IndustryTemplateRunResult:
    return IndustryTemplateRunResult(
        run_key="run-1",
        run_version=1,
        template_code="TEST_TEMPLATE",
        template_version=1,
        template_content_hash=SHA,
        subject_code="TEST.ASSET",
        industry_code="TEST_INDUSTRY",
        as_of_time=AS_OF,
        status=TemplateRunStatus.BLOCKED,
        facts=(),
        forecast_draft=None,
        blocked_reasons=("missing driver",),
    )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"run_version": True}, "run_version"),
        ({"template_version": 0}, "template_version"),
        ({"status": "blocked"}, "status is invalid"),
        ({"research_only": False}, "research-only"),
        ({"blocked_reasons": ()}, "blocked template run"),
        ({"status": TemplateRunStatus.AVAILABLE}, "available template run"),
    ],
)
def test_run_result_rejects_invalid_state(changes: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        replace(_blocked_result(), **changes)


def test_immutable_evidence_rejects_invalid_metadata_and_payload() -> None:
    evidence = build_template_run_evidence(_blocked_result())
    with pytest.raises(ValueError, match="run_version"):
        replace(evidence, run_version=True)
    with pytest.raises(ValueError, match="template_version"):
        replace(evidence, template_version=0)
    with pytest.raises(ValueError, match="status is invalid"):
        replace(evidence, status="blocked")
    with pytest.raises(ValueError, match="research-only"):
        replace(evidence, research_only=False)
    with pytest.raises(ValueError, match="payload_json is invalid"):
        replace(evidence, payload_json="{")
    with pytest.raises(ValueError, match="must encode an object"):
        replace(evidence, payload_json="[]")
    payload = json.loads(evidence.payload_json)
    payload["run_key"] = "tampered"
    with pytest.raises(ValueError, match="content_hash mismatch"):
        replace(evidence, payload_json=json.dumps(payload))
    payload = json.loads(evidence.payload_json)
    payload["status"] = TemplateRunStatus.AVAILABLE.value
    digest = domain._canonical_hash(payload)
    with pytest.raises(ValueError, match="status conflicts"):
        replace(evidence, payload_json=json.dumps(payload), content_hash=digest)


@pytest.mark.parametrize(
    ("function", "value", "message"),
    [
        (domain._evidence_object, [], "must be an object"),
        (domain._evidence_list, {}, "must be a list"),
        (domain._evidence_text, None, "must be text"),
        (domain._evidence_int, True, "must be an integer"),
        (domain._evidence_bool, 1, "must be a boolean"),
        (domain._evidence_decimal, None, "finite decimal"),
        (domain._evidence_decimal, "bad", "finite decimal"),
        (domain._evidence_decimal, "NaN", "finite decimal"),
        (domain._evidence_datetime, "bad", "ISO datetime"),
        (domain._evidence_date, "bad", "ISO date"),
    ],
)
def test_evidence_codec_guards(function, value: object, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        function(value, "value")


def test_assumption_restore_rejects_invalid_observed_lineage() -> None:
    raw = _assumption().to_payload()
    raw["lineage_ref"] = "wrong:1"
    with pytest.raises(ValueError, match="lineage_ref is invalid"):
        domain._restore_assumption(raw)
    raw["lineage_ref"] = "data_center_pit_fact:not-an-int"
    with pytest.raises(ValueError, match="lineage_ref is invalid"):
        domain._restore_assumption(raw)
    assert (
        domain._restore_assumption(
            _assumption(kind=DriverInputKind.MODEL_INFERENCE).to_payload()
        ).model_version
        == "model-v1"
    )


def test_restore_rejects_conflicting_evidence_metadata() -> None:
    evidence = build_template_run_evidence(_blocked_result())
    conflicting = ImmutableTemplateRunEvidence(
        run_key="different-metadata",
        run_version=evidence.run_version,
        template_code=evidence.template_code,
        template_version=evidence.template_version,
        template_content_hash=evidence.template_content_hash,
        as_of_time=evidence.as_of_time,
        status=evidence.status,
        content_hash=evidence.content_hash,
        payload_json=evidence.payload_json,
        research_only=True,
        must_not_use_for_decision=True,
        must_not_execute=True,
    )
    with pytest.raises(ValueError, match="metadata conflicts"):
        restore_template_run_result(conflicting)


def test_evaluator_rejects_wrong_driver_set_and_non_finite_values() -> None:
    values = {
        "volume": Decimal("10"),
        "price": Decimal("12"),
        "unit_cost": Decimal("5"),
        "expense_input": Decimal("10"),
        "cash_adjustment": Decimal("2"),
    }
    with pytest.raises(TemplateEvaluationError, match="driver_set_mismatch"):
        evaluate_template(_template(), {**values, "extra": Decimal("1")})
    with pytest.raises(TemplateEvaluationError, match="driver_value_non_finite"):
        evaluate_template(_template(), {**values, "volume": Decimal("NaN")})


def test_evaluator_rejects_division_by_zero() -> None:
    template = _template()
    expense = _node(template, "expense")
    divide = replace(
        expense,
        operator=ExpressionOperator.DIVIDE,
        operands=(
            ValueReference(ValueReferenceKind.DRIVER, "expense_input"),
            ValueReference(ValueReferenceKind.DRIVER, "cash_adjustment"),
        ),
        unit_rule_key="cny-divide-cny",
    )
    rule = UnitDerivationRule(
        rule_key="cny-divide-cny",
        operator=ExpressionOperator.DIVIDE,
        left_unit="CNY",
        right_unit="CNY",
        output_unit="CNY",
        methodology_ref="method://division-v1",
    )
    divided = replace(
        template,
        nodes=tuple(divide if item.node_key == "expense" else item for item in template.nodes),
        unit_rules=(*template.unit_rules, rule),
    )
    with pytest.raises(TemplateEvaluationError, match="division_by_zero"):
        evaluate_template(
            divided,
            {
                "volume": Decimal("10"),
                "price": Decimal("12"),
                "unit_cost": Decimal("5"),
                "expense_input": Decimal("10"),
                "cash_adjustment": Decimal("0"),
            },
        )
