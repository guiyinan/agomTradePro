"""Boundary coverage for Risk Center's pure-domain governance values."""

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from apps.risk_center.domain import scenarios as scenario_domain
from apps.risk_center.domain.quick_wins import (
    AssetGroupRevision,
    DecisionScorecard,
    EvidenceDirection,
    EvidencePoint,
    EvidenceState,
    MarketDimension,
    MarketStateEvidenceCard,
    ScenarioImpact,
    ScenarioMatrixPreview,
    ScoreComponent,
    SensitivityOperator,
    SensitivityStep,
    SensitivityTemplate,
    StrategyBrief,
)
from apps.risk_center.domain.scenario_governance import (
    ScenarioGovernanceActor,
    ScenarioGovernanceActorKind,
    ScenarioGovernanceAuditRecord,
    ScenarioGovernanceError,
    ScenarioGovernanceOperation,
    ScenarioGovernanceOutcome,
    ScenarioGovernancePreview,
    ScenarioGovernanceProposal,
    ScenarioGovernanceStatus,
    governance_json_value,
    require_human_staff,
    stable_governance_hash,
)
from apps.risk_center.domain.scenarios import (
    AssetImpactAssumption,
    AssetReturnSeries,
    HistoricalReturnPoint,
    HistoricalWindowParameters,
    MacroDriverPath,
    MacroPathNode,
    MacroPathParameters,
    ParametricShock,
    ParametricShockParameters,
    PortfolioExposure,
    ProbabilitySource,
    RollingDirection,
    RollingExtremeParameters,
    RollingMetric,
    ScenarioActivation,
    ScenarioDefinition,
    ScenarioRevision,
    ScenarioRevisionStatus,
    ScenarioRunEvidence,
    ScenarioSet,
    ScenarioSetMember,
    ScenarioSetRevision,
    ScenarioSourceType,
    ScenarioType,
    ShockUnit,
)

NOW = datetime(2026, 8, 8, 0, 0, tzinfo=UTC)
SHA = "a" * 64


def _evidence(**changes: object) -> EvidencePoint:
    values = {
        "key": "growth",
        "value": 1.0,
        "source": "published:test",
        "observed_at": NOW,
        "state": EvidenceState.FRESH,
        "coverage": 1.0,
        "direction": EvidenceDirection.POSITIVE,
    }
    values.update(changes)
    return EvidencePoint(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "changes",
    [
        {"key": ""},
        {"key": "ok", "source": ""},
        {"coverage": -0.1},
        {"observed_at": datetime(2026, 1, 1)},
        {"observed_at": None},
        {"state": EvidenceState.MISSING, "observed_at": None},
    ],
)
def test_evidence_point_rejects_every_invalid_shape(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _evidence(**changes)


def _component(**changes: object) -> ScoreComponent:
    values = {"key": "growth", "score": 50.0, "weight": 1.0, "evidence": _evidence()}
    values.update(changes)
    return ScoreComponent(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "changes",
    [{"key": ""}, {"weight": 0.0}, {"score": -1.0}, {"score": 101.0}],
)
def test_score_component_rejects_invalid_values(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _component(**changes)


def _scorecard(**changes: object) -> DecisionScorecard:
    values = {
        "environment_fit_score": 50.0,
        "valuation_odds_score": 60.0,
        "environment_components": (_component(),),
        "valuation_components": (_component(),),
        "weight_configuration_version": "v1",
        "as_of_time": NOW,
        "missing_items": (),
        "blocked_reasons": (),
        "must_not_use_for_decision": False,
    }
    values.update(changes)
    return DecisionScorecard(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "changes",
    [
        {"as_of_time": datetime(2026, 1, 1)},
        {"weight_configuration_version": ""},
        {"environment_fit_score": -1.0},
        {"environment_fit_score": None, "valuation_odds_score": 101.0},
        {"must_not_use_for_decision": True},
    ],
)
def test_scorecard_rejects_invalid_publication_state(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _scorecard(**changes)


def _dimension(**changes: object) -> MarketDimension:
    values = {
        "key": "macro",
        "label": "Macro",
        "evidence": (_evidence(),),
        "direction": EvidenceDirection.POSITIVE,
    }
    values.update(changes)
    return MarketDimension(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("changes", [{"key": ""}, {"label": ""}, {"evidence": ()}])
def test_market_dimension_rejects_invalid_identity(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _dimension(**changes)


def test_market_cards_require_aware_time_and_canonical_dimensions() -> None:
    dimensions = tuple(
        _dimension(key=key, label=key)
        for key in ("macro", "industry", "earnings", "liquidity", "valuation")
    )
    with pytest.raises(ValueError):
        MarketStateEvidenceCard(dimensions, datetime(2026, 1, 1), (), False)
    with pytest.raises(ValueError):
        MarketStateEvidenceCard(dimensions[:-1], NOW, (), False)


def _impact(**changes: object) -> ScenarioImpact:
    values = {
        "scenario_revision_id": "rev-1",
        "probability": 1.0,
        "portfolio_return": 0.1,
        "asset_impacts": {"equity": 0.1},
        "invalidation_logic": "spread normalizes",
        "evidence": (_evidence(),),
    }
    values.update(changes)
    return ScenarioImpact(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "changes",
    [
        {"scenario_revision_id": ""},
        {"invalidation_logic": ""},
        {"probability": -0.1},
        {"probability": 1.1},
    ],
)
def test_scenario_impact_rejects_invalid_values(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _impact(**changes)


def _preview(**changes: object) -> ScenarioMatrixPreview:
    values = {
        "scenario_set_revision_id": "set-1",
        "portfolio_snapshot_id": "portfolio-1",
        "allocation_policy_version": "policy-1",
        "impacts": (_impact(),),
        "weighted_portfolio_return": 0.1,
        "as_of_time": NOW,
        "blocked_reasons": (),
        "must_not_use_for_decision": False,
    }
    values.update(changes)
    return ScenarioMatrixPreview(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "changes",
    [
        {"as_of_time": datetime(2026, 1, 1)},
        {"scenario_set_revision_id": ""},
        {"portfolio_snapshot_id": ""},
        {"allocation_policy_version": ""},
        {"impacts": (_impact(probability=0.5),)},
        {"must_not_use_for_decision": True},
    ],
)
def test_scenario_preview_rejects_invalid_values(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _preview(**changes)


def _sections() -> dict[str, str]:
    return {
        "environment": "ok",
        "market_state": "ok",
        "scenarios": "ok",
        "scorecard": "ok",
        "portfolio_vulnerabilities": "ok",
        "counter_view": "ok",
        "data_quality": "ok",
    }


def test_strategy_brief_rejects_naive_time_sections_and_missing_facts() -> None:
    base = StrategyBrief("title", _sections(), ("fact",), "set", "prompt", NOW, (), False)
    with pytest.raises(ValueError):
        replace(base, generated_at=datetime(2026, 1, 1))
    with pytest.raises(ValueError):
        replace(base, sections={})
    with pytest.raises(ValueError):
        replace(base, fact_references=())


def _group(**changes: object) -> AssetGroupRevision:
    values = {
        "group_key": "growth",
        "version": 1,
        "members": ("A", "B"),
        "effective_from": date(2026, 1, 1),
        "effective_to": None,
        "source": "database",
    }
    values.update(changes)
    return AssetGroupRevision(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "changes",
    [
        {"group_key": ""},
        {"source": ""},
        {"version": 0},
        {"members": ()},
        {"members": ("A", "")},
        {"members": ("A", "A")},
        {"effective_to": date(2025, 1, 1)},
    ],
)
def test_asset_group_rejects_invalid_values(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _group(**changes)


def _step(**changes: object) -> SensitivityStep:
    values = {
        "output_key": "revenue",
        "operator": SensitivityOperator.MULTIPLY,
        "input_keys": ("price", "volume"),
    }
    values.update(changes)
    return SensitivityStep(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "changes",
    [{"output_key": ""}, {"input_keys": ("one",)}, {"input_keys": ("one", "")}],
)
def test_sensitivity_step_rejects_invalid_values(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _step(**changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"template_key": ""},
        {"version": 0},
        {"source": ""},
        {"steps": ()},
    ],
)
def test_sensitivity_template_rejects_invalid_values(changes: dict[str, object]) -> None:
    values = {"template_key": "t", "version": 1, "steps": (_step(),), "source": "db"}
    values.update(changes)
    with pytest.raises(ValueError):
        SensitivityTemplate(**values)  # type: ignore[arg-type]


def _actor(**changes: object) -> ScenarioGovernanceActor:
    values = {
        "actor_id": "staff:1",
        "kind": ScenarioGovernanceActorKind.HUMAN,
        "is_staff": True,
        "user_id": 1,
        "roles": ("risk", "risk", ""),
    }
    values.update(changes)
    return ScenarioGovernanceActor(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "changes",
    [
        {"actor_id": ""},
        {"actor_id": "x" * 151},
        {"user_id": True},
        {"user_id": 0},
        {"user_id": None},
    ],
)
def test_governance_actor_rejects_invalid_identity(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _actor(**changes)


def _governance_preview(**changes: object) -> ScenarioGovernancePreview:
    values = {
        "preview_id": "preview-1",
        "actor_id": "staff:1",
        "actor_kind": ScenarioGovernanceActorKind.HUMAN,
        "capability_key": "risk.scenario",
        "operation": ScenarioGovernanceOperation.PROPOSE,
        "scenario_key": "scenario-1",
        "request_fingerprint": SHA,
        "base_version": 1,
        "base_hash": SHA,
        "after_hash": SHA,
        "expires_at": NOW + timedelta(minutes=5),
        "created_at": NOW,
        "consumed_at": None,
    }
    values.update(changes)
    return ScenarioGovernancePreview(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "changes",
    [
        {"preview_id": ""},
        {"actor_id": ""},
        {"capability_key": ""},
        {"request_fingerprint": "bad"},
        {"after_hash": "bad"},
        {"base_hash": "bad"},
        {"base_version": 0},
        {"expires_at": datetime(2026, 1, 1)},
        {"created_at": datetime(2026, 1, 1)},
        {"consumed_at": datetime(2026, 1, 1)},
        {"expires_at": NOW},
    ],
)
def test_governance_preview_rejects_invalid_values(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _governance_preview(**changes)


def _proposal(**changes: object) -> ScenarioGovernanceProposal:
    values = {
        "proposal_id": 1,
        "operation": ScenarioGovernanceOperation.PROPOSE,
        "creator_actor_id": "staff:1",
        "creator_actor_kind": ScenarioGovernanceActorKind.HUMAN,
        "capability_key": "risk.scenario",
        "request_fingerprint": SHA,
        "preview_id": "preview-1",
        "status": "approved",
        "approved_at": None,
        "executed_at": None,
    }
    values.update(changes)
    return ScenarioGovernanceProposal(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "changes",
    [
        {"proposal_id": True},
        {"proposal_id": 0},
        {"creator_actor_id": ""},
        {"capability_key": ""},
        {"preview_id": ""},
        {"status": ""},
        {"request_fingerprint": "bad"},
        {"approved_at": datetime(2026, 1, 1)},
        {"executed_at": datetime(2026, 1, 1)},
    ],
)
def test_governance_proposal_rejects_invalid_values(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _proposal(**changes)


def _audit(**changes: object) -> ScenarioGovernanceAuditRecord:
    values = {
        "operation": "propose",
        "actor_id": "staff:1",
        "actor_kind": ScenarioGovernanceActorKind.HUMAN,
        "capability_key": "risk.scenario",
        "request_fingerprint": SHA,
        "correlation_id": "corr-1",
    }
    values.update(changes)
    return ScenarioGovernanceAuditRecord(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "changes",
    [
        {"operation": ""},
        {"actor_id": ""},
        {"capability_key": ""},
        {"correlation_id": ""},
        {"request_fingerprint": "bad"},
        {"before_hash": "bad"},
        {"after_hash": "bad"},
    ],
)
def test_governance_audit_rejects_invalid_values(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _audit(**changes)


def _outcome(**changes: object) -> ScenarioGovernanceOutcome:
    values = {
        "status": ScenarioGovernanceStatus.CREATED,
        "operation": ScenarioGovernanceOperation.PROPOSE,
        "correlation_id": "corr-1",
        "version": 1,
        "content_hash": SHA,
        "request_fingerprint": SHA,
        "base_hash": SHA,
        "after_hash": SHA,
        "expires_at": NOW,
        "warnings": ("warn",),
        "details": {"amount": Decimal("1.20")},
    }
    values.update(changes)
    return ScenarioGovernanceOutcome(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "changes",
    [
        {"correlation_id": ""},
        {"version": 0},
        {"content_hash": "bad"},
        {"request_fingerprint": "bad"},
        {"base_hash": "bad"},
        {"after_hash": "bad"},
        {"expires_at": datetime(2026, 1, 1)},
    ],
)
def test_governance_outcome_rejects_invalid_values(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _outcome(**changes)


def test_governance_outcome_round_trip_and_stored_value_guards() -> None:
    payload = _outcome().as_dict()
    assert ScenarioGovernanceOutcome.from_mapping(payload).as_replay().replayed is True
    assert ScenarioGovernanceOutcome.from_mapping({**payload, "warnings": "bad"}).warnings == ()
    assert ScenarioGovernanceOutcome.from_mapping({**payload, "details": []}).details == {}
    for field, value in (("version", True), ("version", 1.2), ("version", 0)):
        with pytest.raises(ValueError):
            ScenarioGovernanceOutcome.from_mapping({**payload, field: value})


def test_governance_permission_error_and_json_projection_edges() -> None:
    with pytest.raises(ScenarioGovernanceError) as caught:
        require_human_staff(
            ScenarioGovernanceActor("service", ScenarioGovernanceActorKind.SERVICE, True),
            action="activate",
        )
    assert caught.value.as_dict(correlation_id="corr")["must_not_use_for_decision"] is True

    @dataclass(frozen=True)
    class Value:
        amount: Decimal

    projected = governance_json_value(
        {
            "enum": ScenarioGovernanceOperation.ACTIVATE,
            "decimal": Decimal("1.20"),
            "datetime": NOW,
            "date": NOW.date(),
            "dataclass": Value(Decimal("2")),
            "sequence": (1, None, True),
        }
    )
    assert projected["decimal"] == "1.2"  # type: ignore[index]
    assert stable_governance_hash({"payload": projected})
    with pytest.raises(ValueError):
        governance_json_value(datetime(2026, 1, 1))
    with pytest.raises(TypeError):
        governance_json_value(object())


def _historical(**changes: object) -> HistoricalWindowParameters:
    values = {
        "start_date": date(2020, 1, 1),
        "end_date": date(2020, 1, 2),
        "source": "published",
        "event_description": "shock",
    }
    values.update(changes)
    return HistoricalWindowParameters(**values)  # type: ignore[arg-type]


def _rolling(**changes: object) -> RollingExtremeParameters:
    values = {
        "lookback_days": 20,
        "window_days": 5,
        "selection_indicator": "portfolio_return",
        "selection_metric": RollingMetric.CUMULATIVE_RETURN,
        "direction": RollingDirection.MINIMUM,
        "recalculation_frequency": "weekly",
    }
    values.update(changes)
    return RollingExtremeParameters(**values)  # type: ignore[arg-type]


def _shock(**changes: object) -> ParametricShock:
    values = {
        "target_kind": "asset",
        "target": "000001.SZ",
        "shock_kind": "return",
        "magnitude": Decimal("-0.1"),
        "unit": ShockUnit.PERCENT,
        "horizon_days": 5,
    }
    values.update(changes)
    return ParametricShock(**values)  # type: ignore[arg-type]


def _driver(**changes: object) -> MacroDriverPath:
    values = {
        "driver_key": "growth",
        "state": "down",
        "proxy_indicator": "PMI",
        "unit": "index",
        "nodes": (MacroPathNode(date(2026, 9, 1), Decimal("48")),),
    }
    values.update(changes)
    return MacroDriverPath(**values)  # type: ignore[arg-type]


def _asset_impact(**changes: object) -> AssetImpactAssumption:
    values = {
        "target_kind": "asset",
        "target": "000001.SZ",
        "cumulative_return": Decimal("-0.1"),
        "rationale": "growth shock",
    }
    values.update(changes)
    return AssetImpactAssumption(**values)  # type: ignore[arg-type]


def _macro(**changes: object) -> MacroPathParameters:
    values = {
        "drivers": (_driver(),),
        "probability": Decimal("0.3"),
        "probability_source": ProbabilitySource.SUBJECTIVE,
        "asset_impacts": (_asset_impact(),),
        "invalidation_conditions": ("PMI above 50",),
        "review_date": date(2026, 9, 1),
    }
    values.update(changes)
    return MacroPathParameters(**values)  # type: ignore[arg-type]


def _revision(**changes: object) -> ScenarioRevision:
    parameters = changes.pop("parameters", _historical())
    values = {
        "revision_id": "rev-1",
        "scenario_key": "scenario-1",
        "version": 1,
        "status": ScenarioRevisionStatus.APPROVED,
        "scenario_type": ScenarioType.for_parameters(parameters),
        "parameters": parameters,
        "assumptions": ("bounded",),
        "source_type": ScenarioSourceType.HUMAN,
        "created_by": "tester",
        "change_reason": "test",
        "created_at": NOW,
    }
    values.update(changes)
    return ScenarioRevision(**values)  # type: ignore[arg-type]


def test_scenario_low_level_strict_parsers_cover_all_rejections() -> None:
    assert scenario_domain._decimal("1.2", "value") == Decimal("1.2")
    for value in (True, object(), "bad", "NaN"):
        with pytest.raises(ValueError):
            scenario_domain._decimal(value, "value")
    assert scenario_domain._parse_date(NOW, "date") == NOW.date()
    assert scenario_domain._parse_date(NOW.date(), "date") == NOW.date()
    assert scenario_domain._parse_date("2026-08-08", "date") == NOW.date()
    for value in (1, "bad"):
        with pytest.raises(ValueError):
            scenario_domain._parse_date(value, "date")
    assert scenario_domain._strict_mapping(
        {"required": 1, "optional": 2},
        context="payload",
        required={"required"},
        optional={"optional"},
    )
    for value, required in (([], set()), ({}, {"required"}), ({"extra": 1}, set())):
        with pytest.raises(ValueError):
            scenario_domain._strict_mapping(
                value,
                context="payload",
                required=required,
            )
    assert scenario_domain._sequence([1], "items") == [1]
    for value in ("text", object()):
        with pytest.raises(ValueError):
            scenario_domain._sequence(value, "items")
    with pytest.raises(ValueError):
        ScenarioType.for_parameters(object())


@pytest.mark.parametrize(
    "factory,changes",
    [
        (_historical, {"source": ""}),
        (_historical, {"event_description": ""}),
        (_historical, {"end_date": date(2019, 1, 1)}),
        (_rolling, {"lookback_days": True}),
        (_rolling, {"lookback_days": 0}),
        (_rolling, {"window_days": True}),
        (_rolling, {"window_days": 0}),
        (_rolling, {"window_days": 21}),
        (_rolling, {"selection_indicator": ""}),
        (_rolling, {"recalculation_frequency": ""}),
        (_rolling, {"recalculation_frequency": "yearly"}),
        (_shock, {"target_kind": ""}),
        (_shock, {"target": ""}),
        (_shock, {"shock_kind": ""}),
        (_shock, {"target_kind": "country"}),
        (_shock, {"magnitude": Decimal("NaN")}),
        (_shock, {"horizon_days": 0}),
        (_shock, {"unit": ShockUnit.CORRELATION, "magnitude": Decimal("1.1")}),
        (_shock, {"magnitude": Decimal("-1.1")}),
        (_driver, {"driver_key": ""}),
        (_driver, {"state": ""}),
        (_driver, {"proxy_indicator": ""}),
        (_driver, {"unit": ""}),
        (_driver, {"nodes": ()}),
        (_asset_impact, {"target_kind": "country"}),
        (_asset_impact, {"target": ""}),
        (_asset_impact, {"rationale": ""}),
        (_asset_impact, {"cumulative_return": Decimal("NaN")}),
        (_asset_impact, {"cumulative_return": Decimal("-1.1")}),
        (_macro, {"drivers": ()}),
        (_macro, {"probability": Decimal("-0.1")}),
        (_macro, {"probability": Decimal("1.1")}),
        (_macro, {"asset_impacts": ()}),
        (_macro, {"invalidation_conditions": ()}),
        (_macro, {"invalidation_conditions": ("",)}),
    ],
)
def test_scenario_parameter_values_reject_every_boundary(factory, changes) -> None:
    with pytest.raises(ValueError):
        factory(**changes)


def test_scenario_parameter_collections_reject_duplicates_and_ordering() -> None:
    shock = _shock()
    with pytest.raises(ValueError):
        ParametricShockParameters((), "unchanged")
    with pytest.raises(ValueError):
        ParametricShockParameters((shock,), "")
    with pytest.raises(ValueError):
        ParametricShockParameters((shock, shock), "unchanged")
    with pytest.raises(ValueError):
        MacroPathNode(date(2026, 1, 1), Decimal("NaN"))
    first = MacroPathNode(date(2026, 2, 1), Decimal("1"))
    second = MacroPathNode(date(2026, 1, 1), Decimal("1"))
    with pytest.raises(ValueError):
        _driver(nodes=(first, second))
    with pytest.raises(ValueError):
        _driver(nodes=(first, first))
    with pytest.raises(ValueError):
        _macro(drivers=(_driver(), _driver()))


def _definition(**changes: object) -> ScenarioDefinition:
    values = {
        "scenario_key": "scenario-1",
        "name": "Scenario",
        "category": "macro",
        "owner": "risk",
        "created_at": NOW,
    }
    values.update(changes)
    return ScenarioDefinition(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "changes",
    [
        {"scenario_key": ""},
        {"name": ""},
        {"category": ""},
        {"owner": ""},
        {"legacy_aliases": ("",)},
        {"legacy_aliases": ("a", "a")},
        {"created_at": datetime(2026, 1, 1)},
    ],
)
def test_scenario_definition_rejects_invalid_values(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _definition(**changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"revision_id": ""},
        {"scenario_key": ""},
        {"created_by": ""},
        {"change_reason": ""},
        {"version": 0},
        {"version": 2, "based_on_version": 0},
        {"version": 2, "based_on_version": 2},
        {"scenario_type": ScenarioType.MACRO_PATH},
        {"assumptions": ("",)},
        {"created_at": datetime(2026, 1, 1)},
        {"effective_at": datetime(2026, 1, 1)},
        {"content_hash": "bad"},
    ],
)
def test_scenario_revision_rejects_invalid_values(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _revision(**changes)


def _member(**changes: object) -> ScenarioSetMember:
    values = {
        "scenario_revision_id": "rev-1",
        "probability": Decimal("1"),
        "probability_source": ProbabilitySource.SUBJECTIVE,
        "sort_order": 0,
    }
    values.update(changes)
    return ScenarioSetMember(**values)  # type: ignore[arg-type]


def _set_revision(**changes: object) -> ScenarioSetRevision:
    values = {
        "revision_id": "set-rev-1",
        "set_key": "set-1",
        "version": 1,
        "status": ScenarioRevisionStatus.APPROVED,
        "members": (_member(),),
        "driver_axes": ("growth",),
        "created_by": "tester",
        "change_reason": "test",
        "created_at": NOW,
    }
    values.update(changes)
    return ScenarioSetRevision(**values)  # type: ignore[arg-type]


def test_scenario_set_and_member_validation_edges() -> None:
    for changes in ({"set_key": ""}, {"name": ""}, {"purpose": ""}, {"owner": ""}):
        values = {"set_key": "set", "name": "Set", "purpose": "risk", "owner": "owner"}
        values.update(changes)
        with pytest.raises(ValueError):
            ScenarioSet(**values)
    for changes in (
        {"scenario_revision_id": ""},
        {"probability": Decimal("-0.1")},
        {"probability": Decimal("1.1")},
        {"sort_order": -1},
    ):
        with pytest.raises(ValueError):
            _member(**changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"revision_id": ""},
        {"set_key": ""},
        {"created_by": ""},
        {"change_reason": ""},
        {"version": 0},
        {"members": ()},
        {"members": (_member(probability=Decimal("0.5")),)},
        {"driver_axes": ("",)},
        {"created_at": datetime(2026, 1, 1)},
        {"effective_from": datetime(2026, 1, 1)},
        {"effective_to": datetime(2026, 1, 1)},
        {"effective_from": NOW, "effective_to": NOW},
        {"content_hash": "bad"},
    ],
)
def test_scenario_set_revision_rejects_invalid_values(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _set_revision(**changes)


def test_scenario_set_revision_rejects_duplicate_members() -> None:
    first = _member(probability=Decimal("0.5"))
    with pytest.raises(ValueError):
        _set_revision(members=(first, replace(first, sort_order=1)))


def test_activation_run_and_market_series_guards() -> None:
    activation_values = {
        "activation_id": "a",
        "environment": "prod",
        "purpose": "risk",
        "scenario_set_revision_id": "set",
        "activated_by": "staff",
        "reason": "reviewed",
        "activated_at": NOW,
    }
    for field in (
        "activation_id",
        "environment",
        "purpose",
        "scenario_set_revision_id",
        "activated_by",
        "reason",
    ):
        with pytest.raises(ValueError):
            ScenarioActivation(**{**activation_values, field: ""})
    with pytest.raises(ValueError):
        ScenarioActivation(**{**activation_values, "activated_at": datetime(2026, 1, 1)})

    run_values = {
        "run_id": "run",
        "scenario_revision_id": "rev",
        "portfolio_snapshot_id": "portfolio",
        "portfolio_snapshot_hash": SHA,
        "as_of_time": NOW,
        "data_evidence_ids": ("evidence",),
        "result_hash": SHA,
        "allocation_policy_version": "policy",
        "code_version": "code",
        "created_at": NOW,
    }
    for field in (
        "run_id",
        "scenario_revision_id",
        "portfolio_snapshot_id",
        "portfolio_snapshot_hash",
        "allocation_policy_version",
        "code_version",
    ):
        with pytest.raises(ValueError):
            ScenarioRunEvidence(**{**run_values, field: ""})
    for field in ("as_of_time", "created_at"):
        with pytest.raises(ValueError):
            ScenarioRunEvidence(**{**run_values, field: datetime(2026, 1, 1)})
    with pytest.raises(ValueError):
        ScenarioRunEvidence(
            **{**run_values, "must_not_use_for_decision": True, "blocked_reason": ""}
        )
    for changes in (
        {"data_evidence_ids": ()},
        {"data_evidence_ids": ("",)},
        {"result_hash": "bad"},
    ):
        with pytest.raises(ValueError):
            ScenarioRunEvidence(**{**run_values, **changes})

    for weight in (Decimal("NaN"), Decimal("-0.1"), Decimal("1.1")):
        with pytest.raises(ValueError):
            PortfolioExposure("asset", weight)
    with pytest.raises(ValueError):
        PortfolioExposure("", Decimal("0.5"))
    for value in (Decimal("NaN"), Decimal("-1.1")):
        with pytest.raises(ValueError):
            HistoricalReturnPoint(date(2026, 1, 1), value)
    point = HistoricalReturnPoint(date(2026, 1, 1), Decimal("0"))
    with pytest.raises(ValueError):
        AssetReturnSeries("", (point,))
    with pytest.raises(ValueError):
        AssetReturnSeries("asset", (point, point))


def test_scenario_parameter_parser_round_trips_every_supported_shape() -> None:
    payloads = {
        ScenarioType.HISTORICAL_WINDOW: {
            "start_date": "2020-01-01",
            "end_date": "2020-01-02",
            "source": "published",
            "event_description": "shock",
        },
        ScenarioType.ROLLING_EXTREME: {
            "lookback_days": 20,
            "window_days": 5,
            "selection_indicator": "portfolio_return",
            "selection_metric": "realized_volatility",
            "direction": "maximum",
            "recalculation_frequency": "monthly",
        },
        ScenarioType.PARAMETRIC_SHOCK: {
            "shocks": [
                {
                    "target_kind": "asset_class",
                    "target": "equity",
                    "shock_kind": "spread_return",
                    "magnitude": "-0.1",
                    "unit": "absolute",
                    "horizon_days": 5,
                }
            ],
            "correlation_assumption": "unchanged",
        },
        ScenarioType.MACRO_PATH: {
            "drivers": [
                {
                    "driver_key": "growth",
                    "state": "down",
                    "proxy_indicator": "PMI",
                    "unit": "index",
                    "nodes": [{"path_date": "2026-09-01", "value": "48"}],
                }
            ],
            "probability": "0.3",
            "probability_source": "model_inferred",
            "asset_impacts": [
                {
                    "target_kind": "factor",
                    "target": "growth",
                    "cumulative_return": "-0.1",
                    "rationale": "growth shock",
                }
            ],
            "invalidation_conditions": ["PMI above 50"],
            "review_date": "2026-09-01",
        },
    }
    for scenario_type, payload in payloads.items():
        parsed = scenario_domain.scenario_parameters_from_mapping(scenario_type, payload)
        assert scenario_domain.scenario_parameters_to_dict(parsed)


def test_scenario_engine_guard_and_alternative_calculation_branches(monkeypatch) -> None:
    exposure = PortfolioExposure("asset", Decimal("0.5"), (("asset_class", "equity"),))
    other = PortfolioExposure("other", Decimal("0.4"), (("factor", "growth"),))
    with pytest.raises(ValueError):
        scenario_domain._validate_exposures(())
    with pytest.raises(ValueError):
        scenario_domain._validate_exposures((exposure, exposure))
    with pytest.raises(ValueError):
        scenario_domain._validate_exposures((replace(exposure, weight=Decimal("0.7")), other))

    point = HistoricalReturnPoint(date(2026, 1, 1), Decimal("0.1"))
    series = AssetReturnSeries("asset", (point,))
    with pytest.raises(ValueError):
        scenario_domain._aggregate_returns((exposure, other), (series,))
    with pytest.raises(ValueError):
        scenario_domain._aggregate_returns(
            (exposure,),
            (series,),
            start=date(2027, 1, 1),
        )
    with pytest.raises(ValueError):
        scenario_domain._aggregate_returns(
            (exposure, other),
            (
                series,
                AssetReturnSeries(
                    "other",
                    (HistoricalReturnPoint(date(2026, 1, 2), Decimal("0.1")),),
                ),
            ),
        )
    with pytest.raises(ValueError):
        scenario_domain._select_rolling_window([(date(2026, 1, 1), Decimal("0"))], _rolling())
    volatility_window = scenario_domain._select_rolling_window(
        [
            (date(2026, 1, 1), Decimal("0.1")),
            (date(2026, 1, 2), Decimal("-0.1")),
            (date(2026, 1, 3), Decimal("0.2")),
        ],
        _rolling(
            lookback_days=3,
            window_days=2,
            selection_metric=RollingMetric.REALIZED_VOLATILITY,
            direction=RollingDirection.MAXIMUM,
        ),
    )
    assert len(volatility_window) == 2
    assert scenario_domain._matches(exposure, "asset_class", "equity") is True
    assert scenario_domain._shock_return(_shock(shock_kind="unsupported")) == 0
    assert scenario_domain._shock_return(
        _shock(unit=ShockUnit.BASIS_POINTS, magnitude=Decimal("100"))
    ) == Decimal("0.01")
    assert (
        scenario_domain._shock_return(_shock(unit=ShockUnit.ABSOLUTE, magnitude=Decimal("2"))) == 2
    )
    assert (
        scenario_domain._shock_return(
            _shock(unit=ShockUnit.CORRELATION, shock_kind="price", magnitude=Decimal("0.5"))
        )
        == 0
    )
    result = scenario_domain._impact_result(
        "rev",
        Decimal("100"),
        [(date(2026, 1, 1), Decimal("0.1")), (date(2026, 1, 2), Decimal("-0.2"))],
    )
    assert result.max_drawdown > 0
    with pytest.raises(ValueError):
        scenario_domain.evaluate_scenario(
            _revision(),
            exposures=(exposure,),
            initial_value=Decimal("0"),
            return_series=(series,),
        )
    monkeypatch.setattr(scenario_domain, "_json_value", lambda value: [])
    with pytest.raises(ValueError):
        scenario_domain.scenario_parameters_to_dict(_historical())
