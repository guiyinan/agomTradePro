"""Tests for evidence-led scenario research quick wins."""

from datetime import UTC, date, datetime

import pytest

from apps.risk_center.application.quick_wins import (
    BuildDecisionScorecard,
    BuildFixedIncomeSpreadRadar,
    BuildMarketStateEvidenceCard,
    CompareAssetGroups,
    GenerateStructuredStrategyBrief,
    PreviewScenarioMatrix,
    RunSensitivityWorksheet,
    infer_dimension_direction,
)
from apps.risk_center.domain.quick_wins import (
    AssetGroupRevision,
    EvidenceDirection,
    EvidencePoint,
    EvidenceState,
    MarketDimension,
    ScenarioImpact,
    ScoreComponent,
    SensitivityOperator,
    SensitivityStep,
    SensitivityTemplate,
)

NOW = datetime(2026, 8, 5, 1, 0, tzinfo=UTC)


def _evidence(
    key: str,
    *,
    state: EvidenceState = EvidenceState.FRESH,
    value: float | str | None = 1.0,
    direction: EvidenceDirection = EvidenceDirection.POSITIVE,
) -> EvidencePoint:
    return EvidencePoint(
        key=key,
        value=None if state is EvidenceState.MISSING else value,
        source="published:test",
        observed_at=None if state is EvidenceState.MISSING else NOW,
        state=state,
        coverage=0.9,
        direction=direction,
    )


def test_scorecard_blocks_instead_of_imputing_missing_critical_evidence() -> None:
    environment = (
        ScoreComponent("regime", 80.0, 0.6, _evidence("regime")),
        ScoreComponent(
            "liquidity",
            None,
            0.4,
            _evidence("liquidity", state=EvidenceState.MISSING),
        ),
    )
    valuation = (ScoreComponent("valuation", 65.0, 1.0, _evidence("valuation")),)

    result = BuildDecisionScorecard().execute(
        environment_components=environment,
        valuation_components=valuation,
        weight_configuration_version="score-weights-v3",
        as_of_time=NOW,
    )

    assert result.environment_fit_score is None
    assert result.valuation_odds_score is None
    assert result.must_not_use_for_decision is True
    assert result.missing_items == ("liquidity",)


def test_scorecard_publishes_both_scores_with_components_and_config_version() -> None:
    result = BuildDecisionScorecard().execute(
        environment_components=(
            ScoreComponent("regime", 80.0, 0.75, _evidence("regime")),
            ScoreComponent("pulse", 40.0, 0.25, _evidence("pulse")),
        ),
        valuation_components=(ScoreComponent("percentile", 70.0, 1.0, _evidence("percentile")),),
        weight_configuration_version="score-weights-v4",
        as_of_time=NOW,
    )

    assert result.environment_fit_score == 70.0
    assert result.valuation_odds_score == 70.0
    assert result.weight_configuration_version == "score-weights-v4"
    assert result.must_not_use_for_decision is False


def test_market_state_requires_five_dimensions_and_preserves_conflicts() -> None:
    conflict_evidence = (
        _evidence("turnover", direction=EvidenceDirection.POSITIVE),
        _evidence("margin", direction=EvidenceDirection.NEGATIVE),
    )
    dimensions = tuple(
        MarketDimension(
            key=key,
            label=key,
            evidence=(conflict_evidence if key == "liquidity" else (_evidence(key),)),
            direction=(
                infer_dimension_direction(conflict_evidence)
                if key == "liquidity"
                else EvidenceDirection.POSITIVE
            ),
            conflicts=("turnover vs margin",) if key == "liquidity" else (),
        )
        for key in ("macro", "industry", "earnings", "liquidity", "valuation")
    )

    card = BuildMarketStateEvidenceCard().execute(dimensions=dimensions, as_of_time=NOW)

    liquidity = next(item for item in card.dimensions if item.key == "liquidity")
    assert liquidity.direction is EvidenceDirection.MIXED
    assert liquidity.conflicts == ("turnover vs margin",)
    assert card.must_not_use_for_decision is False


def test_scenario_matrix_is_weighted_and_references_all_versions() -> None:
    impacts = (
        ScenarioImpact(
            scenario_revision_id="scenario-a:v2",
            probability=0.6,
            portfolio_return=0.1,
            asset_impacts={"equity": 0.2},
            invalidation_logic="proxy falls below threshold",
            evidence=(_evidence("proxy-a"),),
        ),
        ScenarioImpact(
            scenario_revision_id="scenario-b:v4",
            probability=0.4,
            portfolio_return=-0.2,
            asset_impacts={"equity": -0.3},
            invalidation_logic="credit spread normalizes",
            evidence=(_evidence("proxy-b"),),
        ),
    )

    preview = PreviewScenarioMatrix().execute(
        scenario_set_revision_id="set:macro:v7",
        portfolio_snapshot_id="portfolio:9:snapshot:12",
        allocation_policy_version="allocation:v5",
        impacts=impacts,
        as_of_time=NOW,
    )

    assert preview.weighted_portfolio_return == pytest.approx(-0.02)
    assert preview.must_not_use_for_decision is False
    assert preview.allocation_policy_version == "allocation:v5"


def test_scenario_matrix_blocks_stale_evidence_and_never_publishes_weighted_result() -> None:
    impact = ScenarioImpact(
        scenario_revision_id="scenario-a:v2",
        probability=1.0,
        portfolio_return=0.1,
        asset_impacts={},
        invalidation_logic="proxy changes",
        evidence=(_evidence("proxy-a", state=EvidenceState.STALE),),
    )

    preview = PreviewScenarioMatrix().execute(
        scenario_set_revision_id="set:v1",
        portfolio_snapshot_id="snapshot:v1",
        allocation_policy_version="allocation:v1",
        impacts=(impact,),
        as_of_time=NOW,
    )

    assert preview.weighted_portfolio_return is None
    assert preview.must_not_use_for_decision is True


def test_strategy_brief_requires_structured_sections_and_fact_references() -> None:
    sections = {
        "environment": "Recovery / P1 / Pulse improving",
        "market_state": "Five dimensions retain one liquidity conflict",
        "scenarios": "Main 60%, alternative 40%",
        "scorecard": "Environment 70; valuation 65",
        "portfolio_vulnerabilities": "Growth concentration",
        "counter_view": "AI capex may slow",
        "data_quality": "All critical evidence fresh",
    }

    brief = GenerateStructuredStrategyBrief().execute(
        title="Weekly strategy brief",
        sections=sections,
        fact_references=("regime:rev-8", "scenario-set:rev-7"),
        scenario_set_revision_id="scenario-set:rev-7",
        prompt_version="strategy-brief:v3",
        generated_at=NOW,
    )

    assert brief.sections["counter_view"] == "AI capex may slow"
    assert brief.must_not_use_for_decision is False


def test_fixed_income_radar_fails_closed_until_all_series_are_fresh() -> None:
    result = BuildFixedIncomeSpreadRadar().execute(
        {"government_10y": _evidence("government_10y", value=2.1)}
    )

    assert result["status"] == "blocked"
    assert result["must_not_use_for_decision"] is True
    assert result["spreads"] == {}


def test_asset_group_comparison_retains_versions_and_is_descriptive_only() -> None:
    left = AssetGroupRevision(
        group_key="growth",
        version=2,
        members=("A", "B"),
        effective_from=date(2026, 1, 1),
        effective_to=None,
        source="database",
    )
    right = AssetGroupRevision(
        group_key="value",
        version=3,
        members=("C", "D"),
        effective_from=date(2026, 1, 1),
        effective_to=None,
        source="database",
    )

    result = CompareAssetGroups().execute(
        left=left,
        right=right,
        metrics={
            "growth": {"return": _evidence("growth.return", value=0.1)},
            "value": {"return": _evidence("value.return", value=0.05)},
        },
    )

    assert result["status"] == "descriptive"
    assert result["interpretation"] == "structure_description_only"
    assert result["group_versions"] == {"growth": 2, "value": 3}


def test_sensitivity_worksheet_supports_only_finite_typed_operators() -> None:
    template = SensitivityTemplate(
        template_key="restaurant",
        version=1,
        source="database",
        steps=(
            SensitivityStep(
                output_key="revenue",
                operator=SensitivityOperator.MULTIPLY,
                input_keys=("stores", "same_store_sales", "ticket"),
            ),
            SensitivityStep(
                output_key="profit",
                operator=SensitivityOperator.MULTIPLY,
                input_keys=("revenue", "margin"),
            ),
        ),
    )

    result = RunSensitivityWorksheet().execute(
        template=template,
        assumptions={"stores": 100, "same_store_sales": 1.1, "ticket": 20, "margin": 0.1},
    )

    assert result["revenue"] == pytest.approx(2200)
    assert result["profit"] == pytest.approx(220)
