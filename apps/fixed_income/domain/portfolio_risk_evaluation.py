"""Fixed-income portfolio stress evaluation split from its contracts."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from apps.fixed_income.domain.portfolio_risk import (
    _BASIS_POINT,
    FixedIncomePortfolioRiskAssessment,
    FixedIncomePositionRiskInput,
    FixedIncomeRiskBudgetPolicy,
    PortfolioRiskBlocker,
    PortfolioRiskBlockerCode,
    PortfolioRiskInputBundle,
    PortfolioRiskStatus,
    PortfolioRiskTotals,
    PortfolioStressScenario,
    PositionRiskContribution,
    PositionStressContribution,
    StressScenarioResult,
    _block,
    _position_risk_contribution,
    _require_aware,
    _risk_totals,
    _validate_evidence,
    build_portfolio_risk_output_hash,
)


def _stress_position(
    position: FixedIncomePositionRiskInput,
    scenario: PortfolioStressScenario,
) -> PositionStressContribution:
    rate_shocks = {item.tenor_years: item.shock_bp * _BASIS_POINT for item in scenario.rate_shocks}
    credit_shocks = {
        item.credit_bucket: item.shock_bp * _BASIS_POINT for item in scenario.credit_shocks
    }
    rate_first_order = -position.market_value * sum(
        (
            item.duration_years * rate_shocks[item.tenor_years]
            for item in position.key_rate_exposures
        ),
        start=Decimal("0"),
    )
    rate_convexity = (
        Decimal("0.5")
        * position.market_value
        * sum(
            (
                item.convexity_years_squared
                * rate_shocks[item.tenor_years]
                * rate_shocks[item.tenor_years]
                for item in position.key_rate_exposures
            ),
            start=Decimal("0"),
        )
    )
    credit_pnl = (
        -position.market_value
        * position.credit_spread_duration_years
        * credit_shocks[position.credit_bucket]
        if position.credit_spread_duration_years > 0
        else Decimal("0")
    )
    total_pnl = rate_first_order + rate_convexity + credit_pnl
    return PositionStressContribution(
        position_id=position.position_id,
        rate_first_order_pnl=rate_first_order,
        rate_convexity_pnl=rate_convexity,
        credit_pnl=credit_pnl,
        total_pnl=total_pnl,
    )


def _stress_result(
    positions: tuple[FixedIncomePositionRiskInput, ...],
    scenario: PortfolioStressScenario,
) -> StressScenarioResult:
    contributions = tuple(_stress_position(position, scenario) for position in positions)
    rate_first_order = sum(
        (item.rate_first_order_pnl for item in contributions),
        start=Decimal("0"),
    )
    rate_convexity = sum(
        (item.rate_convexity_pnl for item in contributions),
        start=Decimal("0"),
    )
    credit_pnl = sum((item.credit_pnl for item in contributions), start=Decimal("0"))
    total_pnl = rate_first_order + rate_convexity + credit_pnl
    return StressScenarioResult(
        scenario_id=scenario.scenario_id,
        scenario_version=scenario.scenario_version,
        rate_shock_kind=scenario.rate_shock_kind,
        rate_first_order_pnl=rate_first_order,
        rate_convexity_pnl=rate_convexity,
        credit_pnl=credit_pnl,
        total_pnl=total_pnl,
        loss=max(-total_pnl, Decimal("0")),
        position_contributions=contributions,
    )


def _identity_blockers(
    totals: PortfolioRiskTotals,
    contributions: tuple[PositionRiskContribution, ...],
    stress_results: tuple[StressScenarioResult, ...],
    tolerance: Decimal,
) -> list[PortfolioRiskBlocker]:
    blockers: list[PortfolioRiskBlocker] = []
    risk_pairs = (
        (totals.market_value, sum((item.market_value for item in contributions), Decimal("0"))),
        (totals.dv01, sum((item.dv01 for item in contributions), Decimal("0"))),
        (totals.cs01, sum((item.cs01 for item in contributions), Decimal("0"))),
        (
            totals.convexity_exposure,
            sum((item.convexity_exposure for item in contributions), Decimal("0")),
        ),
        (
            totals.liquidatable_value,
            sum((item.liquidatable_value for item in contributions), Decimal("0")),
        ),
        (
            totals.liquidity_cost,
            sum((item.liquidity_cost for item in contributions), Decimal("0")),
        ),
    )
    if any(abs(total - contribution_sum) > tolerance for total, contribution_sum in risk_pairs):
        blockers.append(
            _block(
                PortfolioRiskBlockerCode.CONTRIBUTION_IDENTITY_FAILED,
                "portfolio risk contribution identity failed",
            )
        )
    for result in stress_results:
        contribution_sum = sum(
            (item.total_pnl for item in result.position_contributions),
            start=Decimal("0"),
        )
        component_sum = result.rate_first_order_pnl + result.rate_convexity_pnl + result.credit_pnl
        if (
            abs(result.total_pnl - contribution_sum) > tolerance
            or abs(result.total_pnl - component_sum) > tolerance
        ):
            blockers.append(
                _block(
                    PortfolioRiskBlockerCode.CONTRIBUTION_IDENTITY_FAILED,
                    "stress contribution identity failed",
                    scenario_id=result.scenario_id,
                )
            )
    return blockers


def _budget_blockers(
    totals: PortfolioRiskTotals,
    stress_results: tuple[StressScenarioResult, ...],
    policy: FixedIncomeRiskBudgetPolicy,
) -> list[PortfolioRiskBlocker]:
    blockers: list[PortfolioRiskBlocker] = []
    if abs(totals.dv01) > policy.maximum_absolute_dv01:
        blockers.append(
            _block(PortfolioRiskBlockerCode.DV01_BUDGET_BREACHED, "DV01 budget breached")
        )
    if abs(totals.cs01) > policy.maximum_absolute_cs01:
        blockers.append(
            _block(PortfolioRiskBlockerCode.CS01_BUDGET_BREACHED, "CS01 budget breached")
        )
    if abs(totals.convexity_exposure) > policy.maximum_convexity_exposure:
        blockers.append(
            _block(PortfolioRiskBlockerCode.CONVEXITY_BUDGET_BREACHED, "convexity budget breached")
        )
    if totals.liquidatable_fraction < policy.minimum_liquidatable_fraction:
        blockers.append(
            _block(
                PortfolioRiskBlockerCode.LIQUIDITY_FRACTION_BREACHED,
                "liquidatable fraction budget breached",
            )
        )
    if totals.liquidity_cost > policy.maximum_liquidity_cost:
        blockers.append(
            _block(
                PortfolioRiskBlockerCode.LIQUIDITY_COST_BREACHED,
                "liquidity cost budget breached",
            )
        )
    if any(result.loss > policy.maximum_stress_loss for result in stress_results):
        blockers.append(
            _block(
                PortfolioRiskBlockerCode.STRESS_LOSS_BUDGET_BREACHED,
                "at least one stress scenario loss budget was breached",
            )
        )
    return blockers


def _assessment(
    bundle: PortfolioRiskInputBundle,
    *,
    policy: FixedIncomeRiskBudgetPolicy,
    evaluated_at: datetime,
    totals: PortfolioRiskTotals | None,
    position_contributions: tuple[PositionRiskContribution, ...],
    stress_results: tuple[StressScenarioResult, ...],
    blockers: tuple[PortfolioRiskBlocker, ...],
) -> FixedIncomePortfolioRiskAssessment:
    status = PortfolioRiskStatus.BLOCKED if blockers else PortfolioRiskStatus.AVAILABLE
    output_hash = build_portfolio_risk_output_hash(
        status=status,
        bundle_id=bundle.bundle_id,
        portfolio_snapshot_id=bundle.portfolio_snapshot_id,
        portfolio_snapshot_hash=bundle.portfolio_snapshot_hash,
        policy_version=policy.policy_version,
        policy_hash=policy.policy_hash,
        evaluated_at=evaluated_at,
        input_hash=bundle.input_hash,
        totals=totals,
        position_contributions=position_contributions,
        stress_results=stress_results,
        blockers=blockers,
        research_only=True,
        must_not_use_for_decision=True,
        must_not_execute=True,
    )
    return FixedIncomePortfolioRiskAssessment(
        status=status,
        bundle_id=bundle.bundle_id,
        portfolio_snapshot_id=bundle.portfolio_snapshot_id,
        portfolio_snapshot_hash=bundle.portfolio_snapshot_hash,
        policy_version=policy.policy_version,
        policy_hash=policy.policy_hash,
        evaluated_at=evaluated_at,
        input_hash=bundle.input_hash,
        totals=totals,
        position_contributions=position_contributions,
        stress_results=stress_results,
        blockers=blockers,
        output_hash=output_hash,
    )


def evaluate_fixed_income_portfolio_risk(
    bundle: PortfolioRiskInputBundle,
    *,
    policy: FixedIncomeRiskBudgetPolicy,
    evaluated_at: datetime,
) -> FixedIncomePortfolioRiskAssessment:
    """Validate evidence, calculate contributions, and enforce risk budgets."""

    _require_aware(evaluated_at, "evaluated_at")
    evidence_blockers = tuple(_validate_evidence(bundle, policy, evaluated_at))
    if evidence_blockers:
        return _assessment(
            bundle,
            policy=policy,
            evaluated_at=evaluated_at,
            totals=None,
            position_contributions=(),
            stress_results=(),
            blockers=evidence_blockers,
        )
    position_contributions = tuple(
        _position_risk_contribution(position) for position in bundle.positions
    )
    totals = _risk_totals(position_contributions)
    stress_results = tuple(
        _stress_result(bundle.positions, scenario) for scenario in bundle.stress_scenarios
    )
    blockers = tuple(
        _identity_blockers(
            totals,
            position_contributions,
            stress_results,
            policy.identity_tolerance,
        )
        + _budget_blockers(totals, stress_results, policy)
    )
    return _assessment(
        bundle,
        policy=policy,
        evaluated_at=evaluated_at,
        totals=totals,
        position_contributions=position_contributions,
        stress_results=stress_results,
        blockers=blockers,
    )


__all__ = ["evaluate_fixed_income_portfolio_risk"]
