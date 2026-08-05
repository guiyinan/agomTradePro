"""Fail-closed research-only orchestration for the R5 vertical slice."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.fixed_income.domain.entities import (
    AnalyticsReconciliationSpec,
    CanonicalPublicationReference,
    FixedIncomeResearchInputs,
    FixedIncomeResearchPreview,
    ImmutableResearchResult,
    InputRole,
    RelativeValueMetrics,
    ResearchPreviewStatus,
    YieldSolverSpec,
)
from apps.fixed_income.domain.services import (
    analyze_bond_from_dirty_price,
    estimate_carry,
    estimate_roll_down,
    reconcile_analytics,
    spread_between_curves_bp,
    tenor_spread_bp,
)


class FixedIncomeResearchResultRepositoryProtocol(Protocol):
    """Persistence boundary for immutable research evidence."""

    def add(self, result: ImmutableResearchResult) -> ImmutableResearchResult: ...

    def get(self, result_id: str) -> ImmutableResearchResult | None: ...


@dataclass(frozen=True)
class FixedIncomeResearchRequest:
    """Explicit calculation policy and version-bound optional input bundle."""

    valuation_at: datetime
    method_version: str
    inputs: FixedIncomeResearchInputs
    solver: YieldSolverSpec
    reconciliation: AnalyticsReconciliationSpec


def _reference_reason(
    reference: CanonicalPublicationReference,
    *,
    expected_role: InputRole,
    prefix: str,
    valuation_at: datetime,
) -> str | None:
    if reference.role is not expected_role:
        return f"{prefix}_publication_role_mismatch"
    reason = reference.usability_reason(valuation_at)
    if reason is None:
        return None
    suffix = "future" if reason == "publication_from_future" else "stale"
    return f"{prefix}_publication_{suffix}"


class RunFixedIncomeResearchPreview:
    """Calculate R5 analytics only when every canonical input and gold check passes."""

    def execute(self, request: FixedIncomeResearchRequest) -> FixedIncomeResearchPreview:
        """Return a research-only preview or all stable blocking reasons."""

        inputs = request.inputs
        blocked: list[str] = []
        references: list[CanonicalPublicationReference] = []

        if inputs.bond is None:
            blocked.append("bond_master_missing")
        else:
            references.append(inputs.bond.master_reference)
        if inputs.schedule is None:
            blocked.append("cash_flow_schedule_missing")
        else:
            references.extend(
                (inputs.schedule.schedule_reference, inputs.schedule.calendar_reference)
            )
        if inputs.government_curve is None:
            blocked.append("government_curve_missing")
        else:
            references.append(inputs.government_curve.reference)
        if inputs.policy_bank_curve is None:
            blocked.append("policy_bank_curve_missing")
        else:
            references.append(inputs.policy_bank_curve.reference)
        if inputs.credit_curve is None:
            blocked.append("credit_valuation_missing")
        else:
            references.append(inputs.credit_curve.reference)
        if inputs.carry_inputs is None:
            blocked.append("carry_cost_inputs_missing")
        else:
            references.extend(
                (
                    inputs.carry_inputs.financing_reference,
                    inputs.carry_inputs.transaction_cost_reference,
                    inputs.carry_inputs.liquidity_reference,
                    inputs.carry_inputs.calendar_reference,
                )
            )
        if inputs.market_dirty_price is None:
            blocked.append("market_dirty_price_missing")
        elif inputs.market_dirty_price <= 0:
            blocked.append("market_dirty_price_invalid")
        if inputs.roll_down_horizon_years is None:
            blocked.append("roll_down_horizon_missing")
        elif inputs.roll_down_horizon_years <= 0:
            blocked.append("roll_down_horizon_invalid")

        expected_roles = {
            InputRole.BOND_MASTER: "bond_master",
            InputRole.CASH_FLOW_SCHEDULE: "cash_flow_schedule",
            InputRole.TRADING_CALENDAR: "trading_calendar",
            InputRole.GOVERNMENT_CURVE: "government_curve",
            InputRole.POLICY_BANK_CURVE: "policy_bank_curve",
            InputRole.CREDIT_VALUATION: "credit_valuation",
            InputRole.FINANCING_COST: "financing_cost",
            InputRole.TRANSACTION_COST: "transaction_cost",
            InputRole.LIQUIDITY_COST: "liquidity_cost",
        }
        for reference in references:
            prefix = expected_roles.get(reference.role, reference.role.value)
            reason = _reference_reason(
                reference,
                expected_role=reference.role,
                prefix=prefix,
                valuation_at=request.valuation_at,
            )
            if reason is not None:
                blocked.append(reason)

        publication_ids = tuple(sorted({reference.publication_id for reference in references}))
        bond_id = inputs.bond.bond_id if inputs.bond is not None else None
        if blocked:
            return FixedIncomeResearchPreview(
                status=ResearchPreviewStatus.BLOCKED,
                method_version=request.method_version,
                bond_id=bond_id,
                valuation_at=request.valuation_at,
                analytics=None,
                relative_value=None,
                reconciliation=None,
                publication_ids=publication_ids,
                blocked_reasons=tuple(sorted(set(blocked))),
                research_only=True,
                must_not_execute=True,
                must_not_use_for_decision=True,
            )

        bond = inputs.bond
        schedule = inputs.schedule
        government_curve = inputs.government_curve
        policy_bank_curve = inputs.policy_bank_curve
        credit_curve = inputs.credit_curve
        carry_inputs = inputs.carry_inputs
        dirty_price = inputs.market_dirty_price
        horizon = inputs.roll_down_horizon_years
        assert bond is not None
        assert schedule is not None
        assert government_curve is not None
        assert policy_bank_curve is not None
        assert credit_curve is not None
        assert carry_inputs is not None
        assert dirty_price is not None
        assert horizon is not None

        try:
            analytics = analyze_bond_from_dirty_price(
                bond=bond,
                schedule=schedule,
                dirty_price=dirty_price,
                solver=request.solver,
            )
            current_tenor = schedule.cash_flows[-1].time_years
            relative_value = RelativeValueMetrics(
                credit_spread_bp=spread_between_curves_bp(
                    credit_curve,
                    government_curve,
                    current_tenor,
                ),
                policy_bank_spread_bp=spread_between_curves_bp(
                    policy_bank_curve,
                    government_curve,
                    current_tenor,
                ),
                government_tenor_spread_bp=tenor_spread_bp(
                    government_curve,
                    current_tenor,
                    current_tenor - horizon,
                ),
                carry=estimate_carry(carry_inputs),
                roll_down=estimate_roll_down(
                    curve=government_curve,
                    current_tenor_years=current_tenor,
                    horizon_years=horizon,
                    modified_duration_years=analytics.modified_duration_years,
                    convexity_years_squared=analytics.convexity_years_squared,
                ),
            )
            reconciliation = reconcile_analytics(analytics, request.reconciliation)
        except ValueError as exc:
            return FixedIncomeResearchPreview(
                status=ResearchPreviewStatus.BLOCKED,
                method_version=request.method_version,
                bond_id=bond_id,
                valuation_at=request.valuation_at,
                analytics=None,
                relative_value=None,
                reconciliation=None,
                publication_ids=publication_ids,
                blocked_reasons=(f"fixed_income_calculation_invalid:{exc}",),
                research_only=True,
                must_not_execute=True,
                must_not_use_for_decision=True,
            )

        if not reconciliation.is_reconciled:
            return FixedIncomeResearchPreview(
                status=ResearchPreviewStatus.BLOCKED,
                method_version=request.method_version,
                bond_id=bond_id,
                valuation_at=request.valuation_at,
                analytics=analytics,
                relative_value=relative_value,
                reconciliation=reconciliation,
                publication_ids=publication_ids,
                blocked_reasons=("duration_convexity_reconciliation_failed",),
                research_only=True,
                must_not_execute=True,
                must_not_use_for_decision=True,
            )
        return FixedIncomeResearchPreview(
            status=ResearchPreviewStatus.AVAILABLE,
            method_version=request.method_version,
            bond_id=bond_id,
            valuation_at=request.valuation_at,
            analytics=analytics,
            relative_value=relative_value,
            reconciliation=reconciliation,
            publication_ids=publication_ids,
            blocked_reasons=(),
            research_only=True,
            must_not_execute=True,
            must_not_use_for_decision=True,
        )


class PersistFixedIncomeResearchResult:
    """Persist one pre-built immutable research record through an injected repository."""

    def __init__(self, repository: FixedIncomeResearchResultRepositoryProtocol) -> None:
        self._repository = repository

    def execute(self, result: ImmutableResearchResult) -> ImmutableResearchResult:
        """Store the immutable, non-executable research result."""

        return self._repository.add(result)
