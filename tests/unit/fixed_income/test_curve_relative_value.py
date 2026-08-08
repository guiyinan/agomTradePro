"""Signed topology, cash, cost, and capacity coverage for R5 curve portfolios."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from apps.fixed_income.domain.curve_relative_value import (
    BondMasterEvidence,
    CashFlowEvidence,
    CurveCarryCostSemantics,
    CurveCashFundingEvidence,
    CurveLegRole,
    CurveLegSide,
    CurveLiquidityResultSeal,
    CurveRelativeValueAssessment,
    CurveRelativeValueBlockerCode,
    CurveRelativeValueEvidence,
    CurveRelativeValueLeg,
    CurveRelativeValuePolicy,
    CurveRelativeValueStatus,
    CurveRoleKindPair,
    CurveStrategyKind,
    CurveStrategyTopology,
    CurveTopologyLegSpec,
    CurveTradingCalendarEvidence,
    DirectionalCapacityEvidence,
    KeyRateAnalytics,
    KeyRateNeutralityTolerance,
    LiquidityCapacityEvidence,
    SignedKeyRateExposure,
    evaluate_curve_relative_value,
)
from apps.fixed_income.domain.entities import CurveKind
from apps.fixed_income.domain.evidence import EvidenceRole, ExactEvidence, canonical_hash
from apps.fixed_income.domain.liquidity_premium import (
    LiquidityCostBasis,
    LiquidityCostRule,
    LiquidityMeasure,
    LiquidityMeasureRole,
    LiquidityPremiumEvidence,
    LiquidityPremiumPolicy,
    LiquidityPremiumRule,
    LiquidityPremiumStatus,
    MarketSpreadSemantics,
)

_EVALUATED_AT = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
_OBSERVED_AT = _EVALUATED_AT - timedelta(seconds=60)
_AVAILABLE_AT = _OBSERVED_AT + timedelta(seconds=10)
_VALID_UNTIL = _EVALUATED_AT + timedelta(days=60)
_SETTLEMENT_AT = datetime(2026, 6, 2, tzinfo=UTC)
_HOLDING_DAYS = 30


def _digest(value: str) -> str:
    return canonical_hash({"value": value})


def _exact(
    *,
    role: EvidenceRole,
    evidence_id: str,
    version: str,
    subject_id: str,
    content_hash: str,
    curve_role: str,
    currency: str | None = "CNY",
    observed_at: datetime = _OBSERVED_AT,
    available_at: datetime = _AVAILABLE_AT,
    upstream_hashes: tuple[str, ...] = (),
) -> ExactEvidence:
    owner = (
        "research"
        if role is EvidenceRole.POLICY
        else (
            "portfolio"
            if role is EvidenceRole.PORTFOLIO_INPUT
            else (
                "fixed_income"
                if role
                in {
                    EvidenceRole.FIXED_INCOME_ANALYTICS,
                    EvidenceRole.FIXED_INCOME_CANDIDATE,
                }
                else "data_center"
            )
        )
    )
    return ExactEvidence(
        role=role,
        owner=owner,
        evidence_id=evidence_id,
        version=version,
        subject_id=subject_id,
        content_hash=content_hash,
        observed_at=observed_at,
        available_at=available_at,
        valid_until=_VALID_UNTIL,
        currency=currency,
        curve_role=curve_role,
        upstream_hashes=tuple(sorted(upstream_hashes)),
    )


def _liquidity_policy(
    included_role: LiquidityMeasureRole | None = None,
) -> LiquidityPremiumPolicy:
    premium_units = {
        LiquidityMeasureRole.BID_ASK_BP: "bp",
        LiquidityMeasureRole.FUNDING_PRESSURE_BP: "bp",
        LiquidityMeasureRole.ISSUE_SIZE: "CNY",
        LiquidityMeasureRole.QUOTE_AGE_SECONDS: "seconds",
        LiquidityMeasureRole.TURNOVER_RATIO: "ratio",
    }
    premium_rules = tuple(
        LiquidityPremiumRule(
            measure_role=role,
            expected_unit=premium_units[role],
            reference_value=(
                Decimal("60") if role is LiquidityMeasureRole.QUOTE_AGE_SECONDS else Decimal("0")
            ),
            coefficient_bp_per_unit=(
                Decimal("1")
                if role
                in {
                    LiquidityMeasureRole.BID_ASK_BP,
                    LiquidityMeasureRole.FUNDING_PRESSURE_BP,
                }
                else Decimal("0")
            ),
        )
        for role in sorted(premium_units, key=lambda item: item.value)
    )
    cost_roles = (
        LiquidityMeasureRole.FINANCING_CARRY_COST_BP,
        LiquidityMeasureRole.LIQUIDATION_COST_BP,
        LiquidityMeasureRole.MARKET_IMPACT_COST_BP,
        LiquidityMeasureRole.TRANSACTION_COST_BP,
    )
    cost_rules = tuple(
        LiquidityCostRule(
            measure_role=role,
            expected_unit="bp",
            cost_basis=LiquidityCostBasis.GROSS_TRADED_NOTIONAL,
            quoted_horizon_days=_HOLDING_DAYS,
            applied_horizon_days=_HOLDING_DAYS,
            application_multiplier=Decimal("1"),
            already_in_gross_relative_value=role is included_role,
        )
        for role in sorted(cost_roles, key=lambda item: item.value)
    )
    return LiquidityPremiumPolicy(
        policy_id="liquidity-policy",
        policy_version="v1",
        market_spread_semantics=MarketSpreadSemantics.INCLUDES_LIQUIDITY_PREMIUM,
        premium_rules=premium_rules,
        cost_rules=cost_rules,
        decomposition_tolerance_bp=Decimal("0"),
        maximum_quote_age_seconds=120,
        minimum_turnover_ratio=Decimal("0"),
        minimum_issue_size=Decimal("1"),
        allow_negative_model_premium=False,
        allow_negative_market_implied_premium=False,
        gross_cost_treatment_version="v1",
        evidence=_exact(
            role=EvidenceRole.POLICY,
            evidence_id="liquidity-policy",
            version="v1",
            subject_id="liquidity-policy",
            content_hash=_digest("liquidity-policy"),
            curve_role="liquidity_premium_policy",
            currency=None,
        ),
    )


def _liquidity_input(
    subject_id: str,
    *,
    included_role: LiquidityMeasureRole | None = None,
) -> LiquidityPremiumEvidence:
    values = {
        LiquidityMeasureRole.BID_ASK_BP: Decimal("2"),
        LiquidityMeasureRole.TURNOVER_RATIO: Decimal("0.2"),
        LiquidityMeasureRole.ISSUE_SIZE: Decimal("1000"),
        LiquidityMeasureRole.FUNDING_PRESSURE_BP: Decimal("1"),
        LiquidityMeasureRole.MARKET_SPREAD_BP: Decimal("10"),
        LiquidityMeasureRole.EXPECTED_CREDIT_LOSS_BP: Decimal("4"),
        LiquidityMeasureRole.OPTION_COST_BP: Decimal("2"),
        LiquidityMeasureRole.OTHER_SPREAD_BP: Decimal("1"),
        LiquidityMeasureRole.FINANCING_CARRY_COST_BP: Decimal("1"),
        LiquidityMeasureRole.TRANSACTION_COST_BP: Decimal("1"),
        LiquidityMeasureRole.MARKET_IMPACT_COST_BP: Decimal("1"),
        LiquidityMeasureRole.LIQUIDATION_COST_BP: Decimal("1"),
        LiquidityMeasureRole.GROSS_RELATIVE_VALUE_BP: Decimal("12"),
    }
    gross_record = _digest(f"gross-{subject_id}")
    included_roles = (included_role,) if included_role is not None else ()
    gross_manifest = canonical_hash(
        {
            "subject_id": subject_id,
            "currency": "CNY",
            "measure_role": LiquidityMeasureRole.GROSS_RELATIVE_VALUE_BP,
            "gross_record_hash": gross_record,
            "observed_at": _OBSERVED_AT,
            "available_at": _AVAILABLE_AT,
            "included_cost_roles": included_roles,
            "treatment_version": "v1",
        }
    )
    measures: list[LiquidityMeasure] = []
    for role in sorted(values, key=lambda item: item.value):
        record_hash = (
            gross_record
            if role is LiquidityMeasureRole.GROSS_RELATIVE_VALUE_BP
            else _digest(f"{subject_id}-{role.value}")
        )
        unit = (
            "ratio"
            if role is LiquidityMeasureRole.TURNOVER_RATIO
            else "CNY" if role is LiquidityMeasureRole.ISSUE_SIZE else "bp"
        )
        publication = _exact(
            role=EvidenceRole.PUBLICATION,
            evidence_id=f"{subject_id}-{role.value}",
            version="v1",
            subject_id=subject_id,
            content_hash=record_hash,
            curve_role=f"liquidity:{role.value}",
            upstream_hashes=(
                (gross_manifest,) if role is LiquidityMeasureRole.GROSS_RELATIVE_VALUE_BP else ()
            ),
        )
        measures.append(
            LiquidityMeasure(
                subject_id=subject_id,
                currency="CNY",
                role=role,
                value=values[role],
                unit=unit,
                observed_at=_OBSERVED_AT,
                available_at=_AVAILABLE_AT,
                record_hash=record_hash,
                publication=publication,
            )
        )
    measure_tuple = tuple(measures)
    return LiquidityPremiumEvidence(
        evidence_id=f"liquidity-{subject_id}",
        evidence_version="v1",
        subject_id=subject_id,
        currency="CNY",
        measures=measure_tuple,
        gross_included_cost_roles=included_roles,
        gross_cost_treatment_version="v1",
        gross_inclusion_manifest_hash=gross_manifest,
        source=_exact(
            role=EvidenceRole.EXACT_PIT_INPUT,
            evidence_id=f"liquidity-{subject_id}",
            version="v1",
            subject_id=subject_id,
            content_hash=_digest(f"liquidity-input-{subject_id}"),
            curve_role="liquidity_premium",
            upstream_hashes=tuple(
                sorted((*(item.seal_hash for item in measure_tuple), gross_manifest))
            ),
        ),
    )


def _pair(role: str, kind: CurveKind) -> CurveRoleKindPair:
    return CurveRoleKindPair(curve_role=role, curve_kind=kind)


def _topology(
    kind: CurveStrategyKind,
    specs: tuple[tuple[CurveLegRole, CurveLegSide, CurveRoleKindPair], ...],
) -> CurveStrategyTopology:
    return CurveStrategyTopology(
        strategy_kind=kind,
        legs=tuple(
            sorted(
                (
                    CurveTopologyLegSpec(
                        leg_role=role,
                        side=side,
                        curve_pair=pair,
                    )
                    for role, side, pair in specs
                ),
                key=lambda item: item.leg_role.value,
            )
        ),
    )


def _curve_policy() -> CurveRelativeValuePolicy:
    front = _pair("gov_front", CurveKind.GOVERNMENT)
    back = _pair("gov_back", CurveKind.GOVERNMENT)
    left = _pair("gov_left", CurveKind.GOVERNMENT)
    belly = _pair("gov_belly", CurveKind.GOVERNMENT)
    right = _pair("gov_right", CurveKind.GOVERNMENT)
    credit = _pair("credit", CurveKind.CREDIT)
    pairs = tuple(
        sorted(
            {front, back, left, belly, right, credit},
            key=lambda item: (item.curve_role, item.curve_kind.value),
        )
    )
    topologies = (
        _topology(
            CurveStrategyKind.BUTTERFLY,
            (
                (CurveLegRole.LEFT_WING, CurveLegSide.LONG, left),
                (CurveLegRole.BELLY, CurveLegSide.SHORT, belly),
                (CurveLegRole.RIGHT_WING, CurveLegSide.LONG, right),
            ),
        ),
        _topology(
            CurveStrategyKind.CREDIT_SPREAD,
            (
                (CurveLegRole.CREDIT, CurveLegSide.LONG, credit),
                (CurveLegRole.HEDGE, CurveLegSide.SHORT, back),
            ),
        ),
        _topology(
            CurveStrategyKind.FLATTENING,
            (
                (CurveLegRole.FRONT_END, CurveLegSide.SHORT, front),
                (CurveLegRole.BACK_END, CurveLegSide.LONG, back),
            ),
        ),
        _topology(
            CurveStrategyKind.KEY_RATE,
            (
                (CurveLegRole.FRONT_END, CurveLegSide.LONG, front),
                (CurveLegRole.BACK_END, CurveLegSide.SHORT, back),
            ),
        ),
        _topology(
            CurveStrategyKind.STEEPENER,
            (
                (CurveLegRole.FRONT_END, CurveLegSide.LONG, front),
                (CurveLegRole.BACK_END, CurveLegSide.SHORT, back),
            ),
        ),
    )
    return CurveRelativeValuePolicy(
        policy_id="curve-policy",
        policy_version="v1",
        required_key_rate_tenors=("10Y", "2Y"),
        key_rate_tolerances=(
            KeyRateNeutralityTolerance("10Y", Decimal("100")),
            KeyRateNeutralityTolerance("2Y", Decimal("100")),
        ),
        absolute_dv01_tolerance=Decimal("0"),
        absolute_cs01_tolerance=Decimal("0"),
        absolute_convexity_tolerance=Decimal("0"),
        cash_tolerance=Decimal("0"),
        maximum_absolute_residual_cash=Decimal("0"),
        price_identity_tolerance=Decimal("0"),
        risk_identity_tolerance=Decimal("0"),
        policy_max_participation=Decimal("0.5"),
        maximum_liquidation_horizon_days=_HOLDING_DAYS,
        allowed_curve_pairs=pairs,
        allowed_instrument_kinds=("bond",),
        strategy_topologies=topologies,
        evidence=_exact(
            role=EvidenceRole.POLICY,
            evidence_id="curve-policy",
            version="v1",
            subject_id="curve-policy",
            content_hash=_digest("curve-policy"),
            curve_role="curve_relative_value_policy",
            currency=None,
        ),
    )


def _master(bond_id: str, *, instrument_kind: str = "bond") -> BondMasterEvidence:
    record = _digest(f"master-{bond_id}")
    return BondMasterEvidence(
        bond_id=bond_id,
        currency="CNY",
        instrument_kind=instrument_kind,
        issue_size=Decimal("10000"),
        record_hash=record,
        evidence=_exact(
            role=EvidenceRole.BOND_MASTER,
            evidence_id=f"master-{bond_id}",
            version="v1",
            subject_id=bond_id,
            content_hash=record,
            curve_role="bond_master",
        ),
    )


def _cash_flow(bond_id: str) -> CashFlowEvidence:
    record = _digest(f"cash-{bond_id}")
    return CashFlowEvidence(
        schedule_id=f"schedule-{bond_id}",
        bond_id=bond_id,
        currency="CNY",
        face_value=Decimal("100"),
        accrued_interest_per_100=Decimal("1"),
        record_hash=record,
        evidence=_exact(
            role=EvidenceRole.CASH_FLOW,
            evidence_id=f"cash-{bond_id}",
            version="v1",
            subject_id=bond_id,
            content_hash=record,
            curve_role="cash_flow",
        ),
    )


def _calendar() -> CurveTradingCalendarEvidence:
    record = _digest("curve-calendar")
    return CurveTradingCalendarEvidence(
        calendar_id="curve-calendar",
        calendar_version="v1",
        settlement_at=_SETTLEMENT_AT,
        horizon_ends_at=_SETTLEMENT_AT + timedelta(days=_HOLDING_DAYS),
        holding_horizon_days=_HOLDING_DAYS,
        record_hash=record,
        evidence=_exact(
            role=EvidenceRole.CALENDAR,
            evidence_id="curve-calendar",
            version="v1",
            subject_id="curve-calendar",
            content_hash=record,
            curve_role="curve_trading_calendar",
            currency=None,
        ),
    )


def _capacity(bond_id: str, side: CurveLegSide) -> DirectionalCapacityEvidence:
    record = _digest(f"capacity-{bond_id}-{side.value}")
    return DirectionalCapacityEvidence(
        bond_id=bond_id,
        currency="CNY",
        side=side,
        available_notional=Decimal("1000"),
        owner_max_participation=Decimal("0.5"),
        borrow_cost_bp=Decimal("1") if side is CurveLegSide.SHORT else None,
        borrow_cost_basis=(
            LiquidityCostBasis.GROSS_TRADED_NOTIONAL if side is CurveLegSide.SHORT else None
        ),
        borrow_cost_horizon_days=(_HOLDING_DAYS if side is CurveLegSide.SHORT else None),
        record_hash=record,
        evidence=_exact(
            role=EvidenceRole.PUBLICATION,
            evidence_id=f"capacity-{bond_id}-{side.value}",
            version="v1",
            subject_id=bond_id,
            content_hash=record,
            curve_role=f"capacity:{side.value}",
        ),
    )


def _liquidity_capacity(
    bond_id: str,
    side: CurveLegSide,
    *,
    horizon_days: int = _HOLDING_DAYS,
) -> LiquidityCapacityEvidence:
    record = _digest(f"liquidity-capacity-{bond_id}-{side.value}")
    return LiquidityCapacityEvidence(
        bond_id=bond_id,
        currency="CNY",
        side=side,
        liquidatable_notional=Decimal("1000"),
        horizon_days=horizon_days,
        record_hash=record,
        evidence=_exact(
            role=EvidenceRole.PUBLICATION,
            evidence_id=f"liquidity-capacity-{bond_id}-{side.value}",
            version="v1",
            subject_id=bond_id,
            content_hash=record,
            curve_role=f"liquidity_capacity:{side.value}",
        ),
    )


def _leg(
    *,
    leg_id: str,
    leg_role: CurveLegRole,
    bond_id: str,
    side: CurveLegSide,
    curve_role: str,
    master: BondMasterEvidence,
    cash_flow: CashFlowEvidence,
    liquidity: LiquidityPremiumEvidence,
    calendar: CurveTradingCalendarEvidence,
    missing_tenor: bool = False,
    settlement_at: datetime = _SETTLEMENT_AT,
    risk_mismatch: bool = False,
) -> CurveRelativeValueLeg:
    if leg_role is CurveLegRole.FRONT_END:
        nodes = (KeyRateAnalytics("2Y", Decimal("100"), Decimal("10")),)
    else:
        nodes = (KeyRateAnalytics("10Y", Decimal("100"), Decimal("10")),)
    if not missing_tenor:
        nodes = tuple(
            sorted(
                (
                    *nodes,
                    KeyRateAnalytics(
                        "10Y" if leg_role is CurveLegRole.FRONT_END else "2Y",
                        Decimal("0"),
                        Decimal("0"),
                    ),
                ),
                key=lambda item: item.tenor,
            )
        )
    analytics_record = _digest(f"analytics-{bond_id}")
    carry_manifest = canonical_hash(
        {
            "analytics_record_hash": analytics_record,
            "notional": Decimal("100"),
            "holding_horizon_days": _HOLDING_DAYS,
            "carry_cash": Decimal("10"),
            "roll_down_cash": Decimal("5"),
            "cost_semantics": (CurveCarryCostSemantics.GROSS_BEFORE_LIQUIDITY_AND_BORROW_COSTS),
        }
    )
    source = _exact(
        role=EvidenceRole.FIXED_INCOME_ANALYTICS,
        evidence_id=f"analytics-{bond_id}",
        version="v1",
        subject_id=bond_id,
        content_hash=analytics_record,
        curve_role=curve_role,
        upstream_hashes=(carry_manifest,),
    )
    return CurveRelativeValueLeg(
        leg_id=leg_id,
        leg_role=leg_role,
        bond_id=bond_id,
        side=side,
        notional=Decimal("100"),
        analytics_notional=Decimal("100"),
        currency="CNY",
        curve_kind=CurveKind.GOVERNMENT,
        curve_role=curve_role,
        settlement_at=settlement_at,
        holding_horizon_days=_HOLDING_DAYS,
        calendar_hash=calendar.calendar_hash,
        clean_price_per_100=Decimal("99"),
        accrued_interest_per_100=Decimal("1"),
        dirty_price_per_100=Decimal("100"),
        key_rate_analytics=nodes,
        dv01=Decimal("101") if risk_mismatch else Decimal("100"),
        cs01=Decimal("0"),
        convexity=Decimal("10"),
        carry_cash=Decimal("10"),
        roll_down_cash=Decimal("5"),
        carry_cost_semantics=(CurveCarryCostSemantics.GROSS_BEFORE_LIQUIDITY_AND_BORROW_COSTS),
        carry_cost_manifest_hash=carry_manifest,
        bond_master_hash=master.master_hash,
        cash_flow_hash=cash_flow.schedule_hash,
        liquidity_evidence_hash=liquidity.evidence_hash,
        analytics_record_hash=analytics_record,
        source=source,
    )


def _evidence(
    *,
    missing_tenor: bool = False,
    omit_short_capacity: bool = False,
    cost_overlap: bool = False,
    liquidity_horizon_days: int = _HOLDING_DAYS,
    leg_settlement_mismatch: bool = False,
    risk_mismatch: bool = False,
    unauthorized_curve_pair: bool = False,
    unauthorized_instrument: bool = False,
) -> CurveRelativeValueEvidence:
    calendar = _calendar()
    front_master = _master(
        "bond-front",
        instrument_kind="etf" if unauthorized_instrument else "bond",
    )
    back_master = _master("bond-back")
    front_cash = _cash_flow("bond-front")
    back_cash = _cash_flow("bond-back")
    front_liquidity = _liquidity_input(
        "bond-front",
        included_role=(LiquidityMeasureRole.TRANSACTION_COST_BP if cost_overlap else None),
    )
    back_liquidity = _liquidity_input(
        "bond-back",
        included_role=(LiquidityMeasureRole.TRANSACTION_COST_BP if cost_overlap else None),
    )
    front_leg = _leg(
        leg_id="leg-front",
        leg_role=CurveLegRole.FRONT_END,
        bond_id="bond-front",
        side=CurveLegSide.LONG,
        curve_role="rogue_curve" if unauthorized_curve_pair else "gov_front",
        master=front_master,
        cash_flow=front_cash,
        liquidity=front_liquidity,
        calendar=calendar,
        missing_tenor=missing_tenor,
        settlement_at=(
            _SETTLEMENT_AT + timedelta(days=1) if leg_settlement_mismatch else _SETTLEMENT_AT
        ),
        risk_mismatch=risk_mismatch,
    )
    back_leg = _leg(
        leg_id="leg-back",
        leg_role=CurveLegRole.BACK_END,
        bond_id="bond-back",
        side=CurveLegSide.SHORT,
        curve_role="gov_back",
        master=back_master,
        cash_flow=back_cash,
        liquidity=back_liquidity,
        calendar=calendar,
    )
    cash_funding_record = _digest("cash-funding")
    cash_funding = CurveCashFundingEvidence(
        candidate_id="curve-candidate",
        currency="CNY",
        settlement_at=_SETTLEMENT_AT,
        financing_cash=Decimal("0"),
        residual_cash=Decimal("0"),
        owner_maximum_absolute_residual_cash=Decimal("0"),
        record_hash=cash_funding_record,
        evidence=_exact(
            role=EvidenceRole.PORTFOLIO_INPUT,
            evidence_id="cash-funding",
            version="v1",
            subject_id="curve-candidate",
            content_hash=cash_funding_record,
            curve_role="curve_cash_funding",
        ),
    )
    legs = tuple(sorted((front_leg, back_leg), key=lambda item: item.leg_id))
    masters = tuple(sorted((front_master, back_master), key=lambda item: item.bond_id))
    cash_flows = tuple(sorted((front_cash, back_cash), key=lambda item: item.bond_id))
    capacity_items = [_capacity("bond-front", CurveLegSide.LONG)]
    if not omit_short_capacity:
        capacity_items.append(_capacity("bond-back", CurveLegSide.SHORT))
    capacities = tuple(sorted(capacity_items, key=lambda item: (item.bond_id, item.side.value)))
    liquidity_capacities = tuple(
        sorted(
            (
                _liquidity_capacity(
                    "bond-front",
                    CurveLegSide.LONG,
                    horizon_days=liquidity_horizon_days,
                ),
                _liquidity_capacity("bond-back", CurveLegSide.SHORT),
            ),
            key=lambda item: (item.bond_id, item.side.value),
        )
    )
    liquidity_inputs = tuple(
        sorted((front_liquidity, back_liquidity), key=lambda item: item.subject_id)
    )
    manifest_hash = canonical_hash(
        {
            "evidence_id": "curve-input",
            "evidence_version": "v1",
            "candidate_id": "curve-candidate",
            "strategy_kind": CurveStrategyKind.KEY_RATE,
            "currency": "CNY",
            "leg_hashes": tuple(item.raw_leg_hash for item in legs),
            "master_hashes": tuple(item.master_hash for item in masters),
            "cash_flow_hashes": tuple(item.schedule_hash for item in cash_flows),
            "capacity_hashes": tuple(item.capacity_hash for item in capacities),
            "liquidity_capacity_hashes": tuple(
                item.liquidity_hash for item in liquidity_capacities
            ),
            "liquidity_input_hashes": tuple(item.evidence_hash for item in liquidity_inputs),
            "calendar_hash": calendar.calendar_hash,
            "funding_hash": cash_funding.funding_hash,
        }
    )
    upstreams = tuple(
        sorted(
            (
                *(item.raw_leg_hash for item in legs),
                *(item.master_hash for item in masters),
                *(item.schedule_hash for item in cash_flows),
                *(item.capacity_hash for item in capacities),
                *(item.liquidity_hash for item in liquidity_capacities),
                *(item.evidence_hash for item in liquidity_inputs),
                calendar.calendar_hash,
                cash_funding.funding_hash,
            )
        )
    )
    return CurveRelativeValueEvidence(
        evidence_id="curve-input",
        evidence_version="v1",
        candidate_id="curve-candidate",
        strategy_kind=CurveStrategyKind.KEY_RATE,
        currency="CNY",
        legs=legs,
        bond_masters=masters,
        cash_flows=cash_flows,
        capacities=capacities,
        liquidity_capacities=liquidity_capacities,
        liquidity_inputs=liquidity_inputs,
        trading_calendar=calendar,
        cash_funding=cash_funding,
        source=_exact(
            role=EvidenceRole.FIXED_INCOME_CANDIDATE,
            evidence_id="curve-input",
            version="v1",
            subject_id="curve-candidate",
            content_hash=manifest_hash,
            curve_role="curve_relative_value",
            upstream_hashes=upstreams,
        ),
    )


def _evaluate_curve(
    evidence: CurveRelativeValueEvidence,
    *,
    included_role: LiquidityMeasureRole | None = None,
) -> CurveRelativeValueAssessment:
    return evaluate_curve_relative_value(
        evidence,
        policy=_curve_policy(),
        liquidity_policy=_liquidity_policy(included_role),
        evaluated_at=_EVALUATED_AT,
    )


def test_signed_curve_candidate_preserves_cash_risk_and_once_only_costs() -> None:
    evidence = _evidence()
    result = _evaluate_curve(evidence)

    assert result.status is CurveRelativeValueStatus.AVAILABLE
    assert evidence.source.owner == "fixed_income"
    assert all(leg.source.owner == "fixed_income" for leg in evidence.legs)
    assert evidence.cash_funding.evidence.owner == "portfolio"
    assert result.signed_dv01 == result.signed_cs01 == result.signed_convexity == 0
    assert result.trade_cash + result.financing_cash + result.residual_cash == 0
    assert result.total_cost_cash == Decimal("0.09")
    assert result.net_relative_value_cash == Decimal("-0.09")
    assert result.output_hash == result.calculated_output_hash


def test_missing_key_rate_node_returns_blocked_instead_of_stop_iteration() -> None:
    result = _evaluate_curve(_evidence(missing_tenor=True))

    assert result.status is CurveRelativeValueStatus.BLOCKED
    assert CurveRelativeValueBlockerCode.KEY_RATE_UNIVERSE_MISMATCH in {
        blocker.code for blocker in result.blockers
    }


def test_short_leg_without_exact_borrow_capacity_fails_closed() -> None:
    result = _evaluate_curve(_evidence(omit_short_capacity=True))

    assert result.status is CurveRelativeValueStatus.BLOCKED
    codes = {blocker.code for blocker in result.blockers}
    assert CurveRelativeValueBlockerCode.SHORTABILITY_MISSING in codes
    assert CurveRelativeValueBlockerCode.CAPACITY_MISSING in codes


def test_cost_marked_in_unbound_liquidity_gross_cannot_escape_curve_deduction() -> None:
    result = _evaluate_curve(
        _evidence(cost_overlap=True),
        included_role=LiquidityMeasureRole.TRANSACTION_COST_BP,
    )

    assert result.status is CurveRelativeValueStatus.BLOCKED
    assert CurveRelativeValueBlockerCode.LIQUIDITY_ASSESSMENT_MISSING in {
        blocker.code for blocker in result.blockers
    }


def test_liquidation_horizon_longer_than_holding_returns_blocked() -> None:
    result = _evaluate_curve(_evidence(liquidity_horizon_days=_HOLDING_DAYS + 1))

    assert result.status is CurveRelativeValueStatus.BLOCKED
    assert CurveRelativeValueBlockerCode.LIQUIDITY_EXCEEDED in {
        blocker.code for blocker in result.blockers
    }


def test_leg_settlement_mismatch_returns_blocked() -> None:
    result = _evaluate_curve(_evidence(leg_settlement_mismatch=True))

    assert result.status is CurveRelativeValueStatus.BLOCKED
    assert CurveRelativeValueBlockerCode.SETTLEMENT_HORIZON_MISMATCH in {
        blocker.code for blocker in result.blockers
    }


def test_key_rate_sum_mismatch_returns_blocked() -> None:
    result = _evaluate_curve(_evidence(risk_mismatch=True))

    assert result.status is CurveRelativeValueStatus.BLOCKED
    assert CurveRelativeValueBlockerCode.KEY_RATE_DV01_IDENTITY_FAILED in {
        blocker.code for blocker in result.blockers
    }


def test_unauthorized_curve_pair_and_instrument_return_blocked() -> None:
    for evidence, expected_code in (
        (
            _evidence(unauthorized_curve_pair=True),
            CurveRelativeValueBlockerCode.CURVE_PAIR_MISMATCH,
        ),
        (
            _evidence(unauthorized_instrument=True),
            CurveRelativeValueBlockerCode.INSTRUMENT_KIND_MISMATCH,
        ),
    ):
        result = _evaluate_curve(evidence)
        assert result.status is CurveRelativeValueStatus.BLOCKED
        assert expected_code in {blocker.code for blocker in result.blockers}


def test_invalid_strategy_kind_is_rejected_at_typed_domain_boundary() -> None:
    evidence = _evidence()
    with pytest.raises(ValueError, match="strategy kind"):
        object.__setattr__(evidence, "strategy_kind", "unknown")
        evidence.__post_init__()


def test_extra_liquidity_subject_is_rejected_before_evaluation() -> None:
    evidence = _evidence()
    extra = _liquidity_input("bond-extra")

    with pytest.raises(ValueError, match="exactly cover"):
        replace(
            evidence,
            liquidity_inputs=tuple(
                sorted(
                    (*evidence.liquidity_inputs, extra),
                    key=lambda item: item.subject_id,
                )
            ),
        )


def test_curve_cost_cannot_diverge_from_consumed_liquidity_seal() -> None:
    result = _evaluate_curve(_evidence())
    front = next(leg for leg in result.leg_assessments if leg.bond_id == "bond-front")
    tampered_front = replace(
        front,
        liquidity_cost_bp=Decimal("0"),
        gross_cost_cash=Decimal("0"),
    )
    tampered_legs = tuple(
        tampered_front if leg.bond_id == front.bond_id else leg for leg in result.leg_assessments
    )
    total_cost = sum(
        (leg.gross_cost_cash for leg in tampered_legs),
        start=Decimal("0"),
    )

    with pytest.raises(ValueError, match="costs must equal"):
        replace(
            result,
            leg_assessments=tampered_legs,
            total_cost_cash=total_cost,
            net_relative_value_cash=(
                result.gross_carry_cash + result.gross_roll_down_cash - total_cost
            ),
        )


def test_curve_result_value_objects_reject_invalid_boundaries() -> None:
    result = _evaluate_curve(_evidence())
    exposure = result.key_rate_exposures[0]
    with pytest.raises(ValueError, match=r"\+1bp P&L"):
        replace(exposure, plus_one_bp_pnl=exposure.plus_one_bp_pnl + Decimal("1"))

    seal = result.liquidity_result_seals[0]
    invalid: Any = "invalid"
    mutations: tuple[tuple[dict[str, object], str], ...] = (
        ({"status": invalid}, "status is invalid"),
        ({"applied_cost_bp": Decimal("-1")}, "cannot be negative"),
        ({"blocker_codes": ("z", "a")}, "must be canonical"),
        ({"blocker_codes": ("blocked",)}, "cannot have blockers"),
    )
    for kwargs, message in mutations:
        with pytest.raises(ValueError, match=message):
            replace(seal, **kwargs)

    blocked_seal = CurveLiquidityResultSeal(
        subject_id=seal.subject_id,
        evaluated_at=seal.evaluated_at,
        input_hash=seal.input_hash,
        output_hash=seal.output_hash,
        policy_hash=seal.policy_hash,
        status=LiquidityPremiumStatus.BLOCKED,
        applied_cost_bp=seal.applied_cost_bp,
        blocker_codes=("blocked",),
    )
    assert blocked_seal.blocker_codes == ("blocked",)


def test_curve_leg_assessment_rejects_tampered_risk_cash_and_capacity() -> None:
    result = _evaluate_curve(_evidence())
    long_leg = next(item for item in result.leg_assessments if item.side is CurveLegSide.LONG)
    short_leg = next(item for item in result.leg_assessments if item.side is CurveLegSide.SHORT)
    invalid: Any = "invalid"
    mutations: tuple[tuple[object, dict[str, object], str], ...] = (
        (long_leg, {"side": invalid}, "enums are invalid"),
        (long_leg, {"notional": Decimal("0")}, "invalid raw values"),
        (long_leg, {"long_key_rate_analytics": ()}, "key-rate universe is invalid"),
        (long_leg, {"long_dv01": long_leg.long_dv01 + Decimal("1")}, "DV01 identity"),
        (
            long_leg,
            {"long_convexity": long_leg.long_convexity + Decimal("1")},
            "convexity identity",
        ),
        (
            long_leg,
            {"dirty_market_value": long_leg.dirty_market_value + Decimal("1")},
            "dirty market value",
        ),
        (
            long_leg,
            {"signed_trade_cash": long_leg.signed_trade_cash + Decimal("1")},
            "signed cash",
        ),
        (
            long_leg,
            {"signed_dv01": long_leg.signed_dv01 + Decimal("1")},
            "signed risk/carry",
        ),
        (short_leg, {"borrow_cost_bp": None}, "requires borrow cost"),
        (long_leg, {"borrow_cost_bp": Decimal("1")}, "cannot carry borrow cost"),
        (
            long_leg,
            {"gross_cost_cash": long_leg.gross_cost_cash + Decimal("1")},
            "gross cost",
        ),
        (
            long_leg,
            {"capacity_limit": long_leg.capacity_limit + Decimal("1")},
            "capacity is not owner-derived",
        ),
        (
            long_leg,
            {"liquidity_limit": long_leg.liquidity_limit + Decimal("1")},
            "effective trade limit",
        ),
    )
    for leg, kwargs, message in mutations:
        with pytest.raises(ValueError, match=message):
            replace(leg, **kwargs)


def test_curve_assessment_rejects_tampered_policy_portfolio_and_seals() -> None:
    result = _evaluate_curve(_evidence())
    first_seal = result.liquidity_result_seals[0]
    first_leg = result.leg_assessments[0]
    first_exposure = result.key_rate_exposures[0]
    mutations: tuple[tuple[dict[str, object], str], ...] = (
        ({"curve_policy_hash": "0" * 64}, "composite policy hash"),
        ({"research_only": False}, "must remain research-only"),
        ({"requested_leg_ids": tuple(reversed(result.requested_leg_ids))}, "leg ids"),
        (
            {"requested_liquidity_subjects": tuple(reversed(result.requested_liquidity_subjects))},
            "liquidity subjects",
        ),
        ({"liquidity_result_seals": result.liquidity_result_seals[:-1]}, "exactly cover"),
        (
            {
                "liquidity_result_seals": (
                    replace(
                        first_seal, evaluated_at=first_seal.evaluated_at + timedelta(seconds=1)
                    ),
                    *result.liquidity_result_seals[1:],
                )
            },
            "curve cutoff",
        ),
        (
            {
                "liquidity_result_seals": (
                    replace(first_seal, applied_cost_bp=first_seal.applied_cost_bp + Decimal("1")),
                    *result.liquidity_result_seals[1:],
                )
            },
            "leg costs",
        ),
        (
            {"leg_assessments": result.leg_assessments + (first_leg,)},
            "assessed leg ids",
        ),
        ({"allowed_curve_pairs": tuple(reversed(result.allowed_curve_pairs))}, "curve pairs"),
        (
            {"allowed_instrument_kinds": ("z", "a")},
            "instrument kinds must be canonical",
        ),
        ({"required_key_rate_tenors": result.required_key_rate_tenors[:-1]}, "policy universe"),
        ({"policy_max_participation": Decimal("0")}, "capacity/risk/horizon"),
        ({"signed_dv01": result.signed_dv01 + Decimal("1")}, "risk totals"),
        ({"plus_one_bp_pnl": result.plus_one_bp_pnl + Decimal("1")}, r"\+1bp P&L"),
        ({"trade_cash": result.trade_cash + Decimal("1")}, "trade cash"),
        ({"gross_carry_cash": result.gross_carry_cash + Decimal("1")}, "carry/roll-down"),
        (
            {
                "key_rate_exposures": (
                    SignedKeyRateExposure(
                        tenor=first_exposure.tenor,
                        signed_dv01=first_exposure.signed_dv01 + Decimal("1"),
                        signed_convexity=first_exposure.signed_convexity,
                        plus_one_bp_pnl=-(first_exposure.signed_dv01 + Decimal("1")),
                    ),
                    *result.key_rate_exposures[1:],
                )
            },
            "key-rate vector",
        ),
        ({"total_cost_cash": result.total_cost_cash + Decimal("1")}, "cost is not recomputable"),
        (
            {"net_relative_value_cash": result.net_relative_value_cash + Decimal("1")},
            "net relative value",
        ),
        ({"output_hash": "0" * 64}, "output hash mismatch"),
    )
    for kwargs, message in mutations:
        with pytest.raises(ValueError, match=message):
            replace(result, **kwargs)
