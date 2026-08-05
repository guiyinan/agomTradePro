"""Pure-domain contracts for governed stress scenarios."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

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
    ScenarioRevision,
    ScenarioRevisionStatus,
    ScenarioSetMember,
    ScenarioSetRevision,
    ScenarioSourceType,
    ScenarioType,
    ShockUnit,
    evaluate_scenario,
    scenario_parameters_from_mapping,
)

NOW = datetime(2026, 8, 5, 8, 0, tzinfo=UTC)


def _revision(
    parameters: (
        HistoricalWindowParameters
        | RollingExtremeParameters
        | ParametricShockParameters
        | MacroPathParameters
    ),
    *,
    revision_id: str = "revision-1",
) -> ScenarioRevision:
    return ScenarioRevision(
        revision_id=revision_id,
        scenario_key="scenario.alpha",
        version=1,
        status=ScenarioRevisionStatus.APPROVED,
        scenario_type=ScenarioType.for_parameters(parameters),
        parameters=parameters,
        assumptions=("typed assumptions only",),
        source_type=ScenarioSourceType.HUMAN,
        created_by="tester",
        change_reason="domain contract",
        created_at=NOW,
    )


def test_four_scenario_types_validate_and_hash_stably() -> None:
    historical = HistoricalWindowParameters(
        start_date=date(2020, 1, 14),
        end_date=date(2020, 3, 23),
        source="published-price-bars",
        event_description="pandemic shock",
    )
    rolling = RollingExtremeParameters(
        lookback_days=252,
        window_days=20,
        selection_indicator="portfolio_return",
        selection_metric=RollingMetric.CUMULATIVE_RETURN,
        direction=RollingDirection.MINIMUM,
        recalculation_frequency="weekly",
    )
    parametric = ParametricShockParameters(
        shocks=(
            ParametricShock(
                target_kind="asset",
                target="000001.SH",
                shock_kind="return",
                magnitude=Decimal("-0.20"),
                unit=ShockUnit.PERCENT,
                horizon_days=5,
            ),
        ),
        correlation_assumption="unchanged",
    )
    macro = MacroPathParameters(
        drivers=(
            MacroDriverPath(
                driver_key="credit_impulse",
                state="tightening",
                proxy_indicator="CN_CREDIT_IMPULSE",
                unit="index",
                nodes=(MacroPathNode(path_date=date(2026, 12, 31), value=Decimal("-1")),),
            ),
        ),
        probability=Decimal("0.25"),
        probability_source=ProbabilitySource.SUBJECTIVE,
        asset_impacts=(
            AssetImpactAssumption(
                target_kind="asset",
                target="000001.SH",
                cumulative_return=Decimal("-0.12"),
                rationale="earnings and liquidity pressure",
            ),
        ),
        invalidation_conditions=("credit impulse turns positive",),
        review_date=date(2026, 9, 1),
    )

    revisions = tuple(
        _revision(item, revision_id=f"revision-{index}")
        for index, item in enumerate((historical, rolling, parametric, macro), start=1)
    )

    assert {item.scenario_type for item in revisions} == set(ScenarioType)
    assert all(len(item.content_hash) == 64 for item in revisions)
    assert replace(revisions[0], revision_id="other-id").content_hash == revisions[0].content_hash
    with pytest.raises(FrozenInstanceError):
        revisions[0].version = 2  # type: ignore[misc]


@pytest.mark.parametrize(
    ("scenario_type", "payload", "message"),
    [
        (
            ScenarioType.HISTORICAL_WINDOW,
            {
                "start_date": "2020-03-23",
                "end_date": "2020-01-14",
                "source": "published",
                "event_description": "bad range",
            },
            "end_date",
        ),
        (
            ScenarioType.ROLLING_EXTREME,
            {
                "lookback_days": 10,
                "window_days": 20,
                "selection_indicator": "portfolio_return",
                "selection_metric": "cumulative_return",
                "direction": "minimum",
                "recalculation_frequency": "weekly",
            },
            "window_days",
        ),
        (
            ScenarioType.PARAMETRIC_SHOCK,
            {
                "shocks": [],
                "correlation_assumption": "unchanged",
            },
            "shock",
        ),
        (
            ScenarioType.MACRO_PATH,
            {
                "drivers": [],
                "probability": "1.1",
                "probability_source": "subjective",
                "asset_impacts": [],
                "invalidation_conditions": [],
                "review_date": "2026-09-01",
            },
            "driver",
        ),
    ],
)
def test_four_scenario_types_reject_invalid_boundaries(
    scenario_type: ScenarioType,
    payload: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        scenario_parameters_from_mapping(scenario_type, payload)


def test_parameter_parser_rejects_unknown_fields() -> None:
    with pytest.raises(ValueError, match="unknown fields"):
        scenario_parameters_from_mapping(
            ScenarioType.HISTORICAL_WINDOW,
            {
                "start_date": "2020-01-14",
                "end_date": "2020-03-23",
                "source": "published",
                "event_description": "pandemic",
                "python_expression": "__import__('os')",
            },
        )


def test_scenario_set_requires_unique_members_and_probability_conservation() -> None:
    valid = ScenarioSetRevision(
        revision_id="set-revision-1",
        set_key="macro.two-axis",
        version=1,
        status=ScenarioRevisionStatus.APPROVED,
        members=(
            ScenarioSetMember(
                scenario_revision_id="one",
                probability=Decimal("0.4"),
                probability_source=ProbabilitySource.SUBJECTIVE,
                sort_order=1,
            ),
            ScenarioSetMember(
                scenario_revision_id="two",
                probability=Decimal("0.6"),
                probability_source=ProbabilitySource.SUBJECTIVE,
                sort_order=2,
            ),
        ),
        driver_axes=("growth", "liquidity"),
        created_by="tester",
        change_reason="initial set",
        created_at=NOW,
    )

    assert len(valid.content_hash) == 64
    with pytest.raises(ValueError, match="sum to 1"):
        replace(
            valid,
            revision_id="set-revision-2",
            members=(replace(valid.members[0], probability=Decimal("0.3")), valid.members[1]),
            content_hash="",
        )
    with pytest.raises(ValueError, match="duplicate"):
        replace(
            valid,
            revision_id="set-revision-3",
            members=(valid.members[0], replace(valid.members[1], scenario_revision_id="one")),
            content_hash="",
        )


def test_pure_engine_calculates_historical_rolling_parametric_and_macro_impacts() -> None:
    exposures = (
        PortfolioExposure(asset_code="000001.SH", weight=Decimal("0.6")),
        PortfolioExposure(asset_code="000002.SH", weight=Decimal("0.3")),
    )
    series = (
        AssetReturnSeries(
            asset_code="000001.SH",
            points=tuple(
                HistoricalReturnPoint(date(2020, 1, 14 + index), value)
                for index, value in enumerate(
                    (Decimal("-0.10"), Decimal("0.05"), Decimal("-0.02"), Decimal("0.01"))
                )
            ),
        ),
        AssetReturnSeries(
            asset_code="000002.SH",
            points=tuple(
                HistoricalReturnPoint(date(2020, 1, 14 + index), value)
                for index, value in enumerate(
                    (Decimal("-0.04"), Decimal("0.02"), Decimal("-0.01"), Decimal("0.00"))
                )
            ),
        ),
    )
    historical = _revision(
        HistoricalWindowParameters(
            start_date=date(2020, 1, 14),
            end_date=date(2020, 1, 17),
            source="published",
            event_description="test",
        ),
        revision_id="historical",
    )
    rolling = _revision(
        RollingExtremeParameters(
            lookback_days=4,
            window_days=2,
            selection_indicator="portfolio_return",
            selection_metric=RollingMetric.CUMULATIVE_RETURN,
            direction=RollingDirection.MINIMUM,
            recalculation_frequency="weekly",
        ),
        revision_id="rolling",
    )
    parametric = _revision(
        ParametricShockParameters(
            shocks=(
                ParametricShock(
                    target_kind="asset",
                    target="000001.SH",
                    shock_kind="return",
                    magnitude=Decimal("-0.20"),
                    unit=ShockUnit.PERCENT,
                    horizon_days=5,
                ),
            ),
            correlation_assumption="unchanged",
        ),
        revision_id="parametric",
    )
    macro = _revision(
        MacroPathParameters(
            drivers=(
                MacroDriverPath(
                    driver_key="growth",
                    state="down",
                    proxy_indicator="PMI",
                    unit="index",
                    nodes=(MacroPathNode(date(2026, 12, 31), Decimal("48")),),
                ),
            ),
            probability=Decimal("0.3"),
            probability_source=ProbabilitySource.SUBJECTIVE,
            asset_impacts=(
                AssetImpactAssumption("asset", "000002.SH", Decimal("-0.10"), "growth"),
            ),
            invalidation_conditions=("PMI above 50",),
            review_date=date(2026, 9, 1),
        ),
        revision_id="macro",
    )

    historical_result = evaluate_scenario(
        historical,
        exposures=exposures,
        initial_value=Decimal("1000"),
        return_series=series,
    )
    rolling_result = evaluate_scenario(
        rolling,
        exposures=exposures,
        initial_value=Decimal("1000"),
        return_series=series,
    )
    parametric_result = evaluate_scenario(
        parametric,
        exposures=exposures,
        initial_value=Decimal("1000"),
        return_series=(),
    )
    macro_result = evaluate_scenario(
        macro,
        exposures=exposures,
        initial_value=Decimal("1000"),
        return_series=(),
    )

    assert historical_result.total_return < 0
    assert rolling_result.period_start == date(2020, 1, 14)
    assert rolling_result.period_end == date(2020, 1, 15)
    assert parametric_result.total_return == Decimal("-0.12")
    assert macro_result.total_return == Decimal("-0.03")
    assert all(
        len(item.result_hash) == 64
        for item in (
            historical_result,
            rolling_result,
            parametric_result,
            macro_result,
        )
    )
