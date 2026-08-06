"""Pure evaluation flow for signed curve-relative-value research portfolios."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from apps.fixed_income.domain.curve_relative_value_contracts import (
    CurveLegSide,
    CurveRelativeValueBlocker,
    CurveRelativeValueBlockerCode,
    CurveRelativeValueEvidence,
    CurveRelativeValuePolicy,
    CurveRelativeValueStatus,
)
from apps.fixed_income.domain.curve_relative_value_results import (
    CurveLegAssessment,
    CurveRelativeValueAssessment,
    SignedKeyRateExposure,
    _matches_topology,
    _valid_structure,
    seal_curve_liquidity_results,
)
from apps.fixed_income.domain.evidence import (
    ExactEvidence,
    canonical_hash,
    require_aware,
    require_sha256,
)
from apps.fixed_income.domain.liquidity_premium import (
    LiquidityCostBasis,
    LiquidityPremiumAssessment,
    LiquidityPremiumPolicy,
    LiquidityPremiumStatus,
    evaluate_liquidity_premium,
)

_BP = Decimal("0.0001")


def curve_relative_value_input_hash(
    evidence: CurveRelativeValueEvidence,
    policy: CurveRelativeValuePolicy,
    liquidity_policy: LiquidityPremiumPolicy,
    *,
    evaluated_at: datetime,
) -> str:
    """Hash candidate, curve/liquidity policies, and PIT cutoff."""

    require_aware(evaluated_at, "evaluated_at")
    return canonical_hash(
        {
            "evidence_hash": evidence.evidence_hash,
            "curve_policy_hash": policy.policy_hash,
            "liquidity_policy_hash": liquidity_policy.policy_hash,
            "evaluated_at": evaluated_at,
        }
    )


def _blocker(
    code: CurveRelativeValueBlockerCode,
    detail: str,
) -> CurveRelativeValueBlocker:
    return CurveRelativeValueBlocker(code=code, detail=detail)


def _owner_reason(
    exact: ExactEvidence,
    evaluated_at: datetime,
) -> CurveRelativeValueBlocker | None:
    reason = exact.usability_reason(evaluated_at)
    if reason == "evidence_from_future":
        return _blocker(
            CurveRelativeValueBlockerCode.EVIDENCE_FROM_FUTURE,
            "owner evidence from future",
        )
    if reason == "evidence_stale":
        return _blocker(
            CurveRelativeValueBlockerCode.EVIDENCE_STALE,
            "owner evidence stale",
        )
    return None


def _make_assessment(
    *,
    status: CurveRelativeValueStatus,
    evidence: CurveRelativeValueEvidence,
    policy: CurveRelativeValuePolicy,
    liquidity_policy: LiquidityPremiumPolicy,
    evaluated_at: datetime,
    input_hash: str,
    liquidity_results: tuple[LiquidityPremiumAssessment, ...],
    legs: tuple[CurveLegAssessment, ...],
    key_rates: tuple[SignedKeyRateExposure, ...],
    blockers: tuple[CurveRelativeValueBlocker, ...],
) -> CurveRelativeValueAssessment:
    composite_policy_hash = canonical_hash(
        {
            "curve_policy_hash": policy.policy_hash,
            "liquidity_policy_hash": liquidity_policy.policy_hash,
        }
    )
    selected_topology = next(
        item for item in policy.strategy_topologies if item.strategy_kind is evidence.strategy_kind
    )
    signed_dv01 = sum((leg.signed_dv01 for leg in legs), start=Decimal("0"))
    signed_cs01 = sum((leg.signed_cs01 for leg in legs), start=Decimal("0"))
    signed_convexity = sum((leg.signed_convexity for leg in legs), start=Decimal("0"))
    trade_cash = sum((leg.signed_trade_cash for leg in legs), start=Decimal("0"))
    carry = sum((leg.signed_carry_cash for leg in legs), start=Decimal("0"))
    roll = sum((leg.signed_roll_down_cash for leg in legs), start=Decimal("0"))
    total_cost = (
        sum((leg.gross_cost_cash for leg in legs), start=Decimal("0"))
        if len(legs) == len(evidence.legs)
        else None
    )
    net = carry + roll - total_cost if total_cost is not None else None
    liquidity_result_seals = seal_curve_liquidity_results(liquidity_results)
    values: dict[str, object] = {
        "status": status,
        "evaluated_at": evaluated_at,
        "input_hash": input_hash,
        "policy_hash": composite_policy_hash,
        "curve_policy_hash": policy.policy_hash,
        "liquidity_policy_hash": liquidity_policy.policy_hash,
        "candidate_id": evidence.candidate_id,
        "strategy_kind": evidence.strategy_kind,
        "currency": evidence.currency,
        "requested_leg_ids": tuple(sorted(leg.leg_id for leg in evidence.legs)),
        "requested_liquidity_subjects": tuple(
            item.subject_id for item in evidence.liquidity_inputs
        ),
        "liquidity_result_seals": liquidity_result_seals,
        "required_key_rate_tenors": policy.required_key_rate_tenors,
        "key_rate_tolerances": policy.key_rate_tolerances,
        "absolute_dv01_tolerance": policy.absolute_dv01_tolerance,
        "absolute_cs01_tolerance": policy.absolute_cs01_tolerance,
        "absolute_convexity_tolerance": policy.absolute_convexity_tolerance,
        "cash_tolerance": policy.cash_tolerance,
        "maximum_absolute_residual_cash": min(
            policy.maximum_absolute_residual_cash,
            evidence.cash_funding.owner_maximum_absolute_residual_cash,
        ),
        "policy_max_participation": policy.policy_max_participation,
        "risk_identity_tolerance": policy.risk_identity_tolerance,
        "maximum_liquidation_horizon_days": (policy.maximum_liquidation_horizon_days),
        "holding_horizon_days": evidence.trading_calendar.holding_horizon_days,
        "allowed_curve_pairs": policy.allowed_curve_pairs,
        "allowed_instrument_kinds": policy.allowed_instrument_kinds,
        "strategy_topology": selected_topology,
        "calendar_hash": evidence.trading_calendar.calendar_hash,
        "funding_hash": evidence.cash_funding.funding_hash,
        "leg_assessments": legs,
        "key_rate_exposures": key_rates,
        "signed_dv01": signed_dv01,
        "plus_one_bp_pnl": -signed_dv01,
        "signed_cs01": signed_cs01,
        "signed_convexity": signed_convexity,
        "trade_cash": trade_cash,
        "financing_cash": evidence.cash_funding.financing_cash,
        "residual_cash": evidence.cash_funding.residual_cash,
        "gross_carry_cash": carry,
        "gross_roll_down_cash": roll,
        "total_cost_cash": total_cost,
        "net_relative_value_cash": net,
        "blockers": blockers,
        "research_only": True,
        "must_not_execute": True,
        "must_not_use_for_decision": True,
    }
    output_hash = canonical_hash(values)
    return CurveRelativeValueAssessment(
        status=status,
        evaluated_at=evaluated_at,
        input_hash=input_hash,
        output_hash=output_hash,
        policy_hash=composite_policy_hash,
        curve_policy_hash=policy.policy_hash,
        liquidity_policy_hash=liquidity_policy.policy_hash,
        candidate_id=evidence.candidate_id,
        strategy_kind=evidence.strategy_kind,
        currency=evidence.currency,
        requested_leg_ids=tuple(sorted(leg.leg_id for leg in evidence.legs)),
        requested_liquidity_subjects=tuple(item.subject_id for item in evidence.liquidity_inputs),
        liquidity_result_seals=liquidity_result_seals,
        required_key_rate_tenors=policy.required_key_rate_tenors,
        key_rate_tolerances=policy.key_rate_tolerances,
        absolute_dv01_tolerance=policy.absolute_dv01_tolerance,
        absolute_cs01_tolerance=policy.absolute_cs01_tolerance,
        absolute_convexity_tolerance=policy.absolute_convexity_tolerance,
        cash_tolerance=policy.cash_tolerance,
        maximum_absolute_residual_cash=min(
            policy.maximum_absolute_residual_cash,
            evidence.cash_funding.owner_maximum_absolute_residual_cash,
        ),
        policy_max_participation=policy.policy_max_participation,
        risk_identity_tolerance=policy.risk_identity_tolerance,
        maximum_liquidation_horizon_days=policy.maximum_liquidation_horizon_days,
        holding_horizon_days=evidence.trading_calendar.holding_horizon_days,
        allowed_curve_pairs=policy.allowed_curve_pairs,
        allowed_instrument_kinds=policy.allowed_instrument_kinds,
        strategy_topology=selected_topology,
        calendar_hash=evidence.trading_calendar.calendar_hash,
        funding_hash=evidence.cash_funding.funding_hash,
        leg_assessments=legs,
        key_rate_exposures=key_rates,
        signed_dv01=signed_dv01,
        plus_one_bp_pnl=-signed_dv01,
        signed_cs01=signed_cs01,
        signed_convexity=signed_convexity,
        trade_cash=trade_cash,
        financing_cash=evidence.cash_funding.financing_cash,
        residual_cash=evidence.cash_funding.residual_cash,
        gross_carry_cash=carry,
        gross_roll_down_cash=roll,
        total_cost_cash=total_cost,
        net_relative_value_cash=net,
        blockers=blockers,
        research_only=True,
        must_not_execute=True,
        must_not_use_for_decision=True,
    )


def evaluate_curve_relative_value(
    evidence: CurveRelativeValueEvidence,
    *,
    policy: CurveRelativeValuePolicy,
    liquidity_policy: LiquidityPremiumPolicy,
    evaluated_at: datetime,
    expected_input_hash: str | None = None,
) -> CurveRelativeValueAssessment:
    """Evaluate exact signed legs with PIT, neutrality, cash, cost, and capacity gates."""

    require_aware(evaluated_at, "evaluated_at")
    input_hash = curve_relative_value_input_hash(
        evidence,
        policy,
        liquidity_policy,
        evaluated_at=evaluated_at,
    )
    blockers: list[CurveRelativeValueBlocker] = []
    if expected_input_hash is not None:
        require_sha256(expected_input_hash, "expected_input_hash")
        if expected_input_hash != input_hash:
            blockers.append(
                _blocker(CurveRelativeValueBlockerCode.INPUT_HASH_MISMATCH, "input hash mismatch")
            )
    if policy.evidence.usability_reason(evaluated_at) is not None:
        blockers.append(_blocker(CurveRelativeValueBlockerCode.POLICY_INACTIVE, "policy inactive"))
    if liquidity_policy.evidence.usability_reason(evaluated_at) is not None:
        blockers.append(
            _blocker(
                CurveRelativeValueBlockerCode.POLICY_INACTIVE,
                "liquidity policy inactive",
            )
        )
    exact_records = (
        evidence.source,
        evidence.trading_calendar.evidence,
        evidence.cash_funding.evidence,
        *(item.evidence for item in evidence.bond_masters),
        *(item.evidence for item in evidence.cash_flows),
        *(item.evidence for item in evidence.capacities),
        *(item.evidence for item in evidence.liquidity_capacities),
        *(item.source for item in evidence.liquidity_inputs),
        *(item.source for item in evidence.legs),
    )
    for exact in exact_records:
        blocker = _owner_reason(exact, evaluated_at)
        if blocker is not None:
            blockers.append(blocker)
    selected_topology = next(
        item for item in policy.strategy_topologies if item.strategy_kind is evidence.strategy_kind
    )
    if not _valid_structure(evidence.strategy_kind, evidence.legs) or not _matches_topology(
        evidence.legs,
        selected_topology,
    ):
        blockers.append(
            _blocker(
                CurveRelativeValueBlockerCode.STRUCTURE_INVALID,
                "strategy leg role/side topology is invalid",
            )
        )
    if len({leg.bond_id for leg in evidence.legs}) != len(evidence.legs):
        blockers.append(
            _blocker(
                CurveRelativeValueBlockerCode.INSTRUMENT_DUPLICATE,
                "curve candidate instruments must be distinct",
            )
        )
    masters = {item.bond_id: item for item in evidence.bond_masters}
    cash_flows = {item.bond_id: item for item in evidence.cash_flows}
    capacities = {(item.bond_id, item.side): item for item in evidence.capacities}
    liquidity_caps = {(item.bond_id, item.side): item for item in evidence.liquidity_capacities}
    liquidity_inputs = {item.subject_id: item for item in evidence.liquidity_inputs}
    liquidity_results = {
        subject_id: evaluate_liquidity_premium(
            liquidity_input,
            policy=liquidity_policy,
            evaluated_at=evaluated_at,
        )
        for subject_id, liquidity_input in liquidity_inputs.items()
    }
    allowed_pairs = {(item.curve_role, item.curve_kind) for item in policy.allowed_curve_pairs}
    completed_legs: list[CurveLegAssessment] = []
    for leg in evidence.legs:
        master = masters.get(leg.bond_id)
        cash_flow = cash_flows.get(leg.bond_id)
        capacity = capacities.get((leg.bond_id, leg.side))
        liquidity_cap = liquidity_caps.get((leg.bond_id, leg.side))
        liquidity_input = liquidity_inputs.get(leg.bond_id)
        liquidity_result = liquidity_results.get(leg.bond_id)
        if master is None:
            blockers.append(
                _blocker(CurveRelativeValueBlockerCode.BOND_MASTER_MISSING, "master missing")
            )
        if cash_flow is None:
            blockers.append(
                _blocker(CurveRelativeValueBlockerCode.CASH_FLOW_MISSING, "cash flow missing")
            )
        if capacity is None:
            blockers.append(
                _blocker(CurveRelativeValueBlockerCode.CAPACITY_MISSING, "capacity missing")
            )
            if leg.side is CurveLegSide.SHORT:
                blockers.append(
                    _blocker(
                        CurveRelativeValueBlockerCode.SHORTABILITY_MISSING,
                        "SHORT borrow capacity missing",
                    )
                )
        if liquidity_cap is None:
            blockers.append(
                _blocker(
                    CurveRelativeValueBlockerCode.LIQUIDITY_GATE_MISSING,
                    "liquidity capacity missing",
                )
            )
        if liquidity_result is None:
            blockers.append(
                _blocker(
                    CurveRelativeValueBlockerCode.LIQUIDITY_ASSESSMENT_MISSING,
                    "unique liquidity cost ledger missing",
                )
            )
        if any(
            item is None
            for item in (
                master,
                cash_flow,
                capacity,
                liquidity_cap,
                liquidity_input,
                liquidity_result,
            )
        ):
            continue
        assert master is not None
        assert cash_flow is not None
        assert capacity is not None
        assert liquidity_cap is not None
        assert liquidity_input is not None
        assert liquidity_result is not None
        if (
            master.master_hash != leg.bond_master_hash
            or cash_flow.schedule_hash != leg.cash_flow_hash
            or liquidity_input.evidence_hash != leg.liquidity_evidence_hash
            or liquidity_result.output_hash != liquidity_result.calculated_output_hash
            or liquidity_result.status is not LiquidityPremiumStatus.AVAILABLE
            or liquidity_result.total_deductible_cost_bp is None
            or liquidity_result.evaluated_at != evaluated_at
            or liquidity_result.gross_included_cost_roles
        ):
            blockers.append(
                _blocker(
                    CurveRelativeValueBlockerCode.LIQUIDITY_ASSESSMENT_MISSING,
                    "leg owner/cost ledger hash or availability mismatch",
                )
            )
            continue
        if (
            leg.currency != evidence.currency
            or master.currency != evidence.currency
            or cash_flow.currency != evidence.currency
            or capacity.currency != evidence.currency
            or liquidity_cap.currency != evidence.currency
            or liquidity_result.currency != evidence.currency
        ):
            blockers.append(
                _blocker(
                    CurveRelativeValueBlockerCode.CURRENCY_MISMATCH,
                    "leg evidence currencies differ",
                )
            )
        leg_is_authorized = True
        if (leg.curve_role, leg.curve_kind) not in allowed_pairs:
            leg_is_authorized = False
            blockers.append(
                _blocker(
                    CurveRelativeValueBlockerCode.CURVE_PAIR_MISMATCH,
                    "curve role/kind pair is not policy-authorized",
                )
            )
        if master.instrument_kind not in policy.allowed_instrument_kinds:
            leg_is_authorized = False
            blockers.append(
                _blocker(
                    CurveRelativeValueBlockerCode.INSTRUMENT_KIND_MISMATCH,
                    "instrument kind is not policy-authorized",
                )
            )
        if not leg_is_authorized:
            continue
        calendar = evidence.trading_calendar
        leg_calendar_matches = not (
            leg.calendar_hash != calendar.calendar_hash
            or leg.settlement_at != calendar.settlement_at
            or leg.holding_horizon_days != calendar.holding_horizon_days
        )
        if not leg_calendar_matches:
            blockers.append(
                _blocker(
                    CurveRelativeValueBlockerCode.SETTLEMENT_HORIZON_MISMATCH,
                    "leg/calendar settlement or horizon differs",
                )
            )
            continue
        if evidence.cash_funding.settlement_at != calendar.settlement_at:
            blockers.append(
                _blocker(
                    CurveRelativeValueBlockerCode.SETTLEMENT_HORIZON_MISMATCH,
                    "cash funding settlement differs from calendar",
                )
            )
        if capacity.side is CurveLegSide.SHORT and (
            capacity.borrow_cost_bp is None
            or capacity.borrow_cost_horizon_days != leg.holding_horizon_days
        ):
            blockers.append(
                _blocker(
                    CurveRelativeValueBlockerCode.BORROW_COST_MISSING,
                    "SHORT borrow cost or horizon is missing",
                )
            )
            continue
        if any(
            entry.cost_basis is not LiquidityCostBasis.GROSS_TRADED_NOTIONAL
            or entry.applied_horizon_days != leg.holding_horizon_days
            for entry in liquidity_result.cost_entries
        ):
            blockers.append(
                _blocker(
                    CurveRelativeValueBlockerCode.COST_LEDGER_HORIZON_MISMATCH,
                    "liquidity cost basis/horizon differs from leg",
                )
            )
            continue
        risk_identities_hold = True
        if (
            abs(leg.dirty_price_per_100 - leg.clean_price_per_100 - leg.accrued_interest_per_100)
            > policy.price_identity_tolerance
            or abs(leg.accrued_interest_per_100 - cash_flow.accrued_interest_per_100)
            > policy.price_identity_tolerance
        ):
            blockers.append(
                _blocker(
                    CurveRelativeValueBlockerCode.PRICE_IDENTITY_FAILED,
                    "dirty/clean/accrued identity failed",
                )
            )
        if leg.analytics_notional != leg.notional:
            blockers.append(
                _blocker(
                    CurveRelativeValueBlockerCode.ANALYTICS_NOTIONAL_MISMATCH,
                    "analytics notional differs from trade notional",
                )
            )
        key_rate_universe_matches = (
            tuple(node.tenor for node in leg.key_rate_analytics) == policy.required_key_rate_tenors
        )
        if not key_rate_universe_matches:
            blockers.append(
                _blocker(
                    CurveRelativeValueBlockerCode.KEY_RATE_UNIVERSE_MISMATCH,
                    "key-rate universe is incomplete",
                )
            )
            continue
        if (
            abs(sum((node.dv01 for node in leg.key_rate_analytics), start=Decimal("0")) - leg.dv01)
            > policy.risk_identity_tolerance
        ):
            risk_identities_hold = False
            blockers.append(
                _blocker(
                    CurveRelativeValueBlockerCode.KEY_RATE_DV01_IDENTITY_FAILED,
                    "key-rate DV01 does not sum to leg DV01",
                )
            )
        if (
            abs(
                sum((node.convexity for node in leg.key_rate_analytics), start=Decimal("0"))
                - leg.convexity
            )
            > policy.risk_identity_tolerance
        ):
            risk_identities_hold = False
            blockers.append(
                _blocker(
                    CurveRelativeValueBlockerCode.KEY_RATE_CONVEXITY_IDENTITY_FAILED,
                    "key-rate convexity does not sum to leg convexity",
                )
            )
        if not risk_identities_hold:
            continue
        participation = min(
            capacity.owner_max_participation,
            policy.policy_max_participation,
        )
        capacity_limit = min(
            capacity.available_notional * participation,
            master.issue_size * participation,
        )
        liquidity_limit = liquidity_cap.liquidatable_notional
        effective_limit = min(capacity_limit, liquidity_limit)
        if leg.notional > capacity_limit:
            blockers.append(
                _blocker(
                    CurveRelativeValueBlockerCode.CAPACITY_EXCEEDED,
                    "leg exceeds owner-derived capacity",
                )
            )
        liquidity_horizon_invalid = (
            liquidity_cap.horizon_days > policy.maximum_liquidation_horizon_days
            or liquidity_cap.horizon_days > leg.holding_horizon_days
        )
        if leg.notional > liquidity_limit or liquidity_horizon_invalid:
            blockers.append(
                _blocker(
                    CurveRelativeValueBlockerCode.LIQUIDITY_EXCEEDED,
                    "leg exceeds liquidity amount or horizon",
                )
            )
        if liquidity_horizon_invalid:
            continue
        sign = leg.side.exposure_sign
        dirty_market_value = leg.notional * leg.dirty_price_per_100 / Decimal("100")
        borrow_cost = capacity.borrow_cost_bp
        curve_liquidity_cost_bp = sum(
            (entry.applied_cost_bp for entry in liquidity_result.cost_entries),
            start=Decimal("0"),
        )
        gross_cost = leg.notional * (curve_liquidity_cost_bp + (borrow_cost or Decimal("0"))) * _BP
        completed_legs.append(
            CurveLegAssessment(
                leg_id=leg.leg_id,
                leg_role=leg.leg_role,
                bond_id=leg.bond_id,
                instrument_kind=master.instrument_kind,
                curve_role=leg.curve_role,
                curve_kind=leg.curve_kind,
                side=leg.side,
                notional=leg.notional,
                holding_horizon_days=leg.holding_horizon_days,
                liquidation_horizon_days=liquidity_cap.horizon_days,
                dirty_price_per_100=leg.dirty_price_per_100,
                long_key_rate_analytics=leg.key_rate_analytics,
                long_dv01=leg.dv01,
                long_cs01=leg.cs01,
                long_convexity=leg.convexity,
                long_carry_cash=leg.carry_cash,
                long_roll_down_cash=leg.roll_down_cash,
                liquidity_cost_bp=curve_liquidity_cost_bp,
                borrow_cost_bp=borrow_cost,
                issue_size=master.issue_size,
                available_notional=capacity.available_notional,
                owner_max_participation=capacity.owner_max_participation,
                policy_max_participation=policy.policy_max_participation,
                liquidatable_notional=liquidity_cap.liquidatable_notional,
                risk_identity_tolerance=policy.risk_identity_tolerance,
                dirty_market_value=dirty_market_value,
                signed_trade_cash=-sign * dirty_market_value,
                signed_dv01=sign * leg.dv01,
                plus_one_bp_pnl=-(sign * leg.dv01),
                signed_cs01=sign * leg.cs01,
                signed_convexity=sign * leg.convexity,
                signed_carry_cash=sign * leg.carry_cash,
                signed_roll_down_cash=sign * leg.roll_down_cash,
                gross_cost_cash=gross_cost,
                capacity_limit=capacity_limit,
                liquidity_limit=liquidity_limit,
                effective_trade_limit=effective_limit,
                evidence_hash=leg.leg_hash,
            )
        )
    completed = tuple(sorted(completed_legs, key=lambda item: item.leg_id))
    key_rates = tuple(
        SignedKeyRateExposure(
            tenor=tolerance.tenor,
            signed_dv01=sum(
                (
                    leg.side.exposure_sign
                    * next(
                        node.dv01
                        for node in leg.long_key_rate_analytics
                        if node.tenor == tolerance.tenor
                    )
                    for leg in completed
                ),
                start=Decimal("0"),
            ),
            signed_convexity=sum(
                (
                    leg.side.exposure_sign
                    * next(
                        node.convexity
                        for node in leg.long_key_rate_analytics
                        if node.tenor == tolerance.tenor
                    )
                    for leg in completed
                ),
                start=Decimal("0"),
            ),
            plus_one_bp_pnl=-sum(
                (
                    leg.side.exposure_sign
                    * next(
                        node.dv01
                        for node in leg.long_key_rate_analytics
                        if node.tenor == tolerance.tenor
                    )
                    for leg in completed
                ),
                start=Decimal("0"),
            ),
        )
        for tolerance in policy.key_rate_tolerances
    )
    signed_dv01 = sum((leg.signed_dv01 for leg in completed), start=Decimal("0"))
    signed_cs01 = sum((leg.signed_cs01 for leg in completed), start=Decimal("0"))
    signed_convexity = sum((leg.signed_convexity for leg in completed), start=Decimal("0"))
    if abs(signed_dv01) > policy.absolute_dv01_tolerance:
        blockers.append(
            _blocker(CurveRelativeValueBlockerCode.DV01_NEUTRALITY_BREACHED, "DV01 gate")
        )
    if abs(signed_cs01) > policy.absolute_cs01_tolerance:
        blockers.append(
            _blocker(CurveRelativeValueBlockerCode.CS01_NEUTRALITY_BREACHED, "CS01 gate")
        )
    if abs(signed_convexity) > policy.absolute_convexity_tolerance:
        blockers.append(
            _blocker(
                CurveRelativeValueBlockerCode.CONVEXITY_NEUTRALITY_BREACHED,
                "convexity gate",
            )
        )
    if any(
        abs(exposure.signed_dv01) > tolerance.absolute_dv01
        for exposure, tolerance in zip(key_rates, policy.key_rate_tolerances, strict=True)
    ):
        blockers.append(
            _blocker(
                CurveRelativeValueBlockerCode.KEY_RATE_NEUTRALITY_BREACHED,
                "key-rate gate",
            )
        )
    trade_cash = sum((leg.signed_trade_cash for leg in completed), start=Decimal("0"))
    funding = evidence.cash_funding
    if abs(trade_cash + funding.financing_cash + funding.residual_cash) > policy.cash_tolerance:
        blockers.append(
            _blocker(CurveRelativeValueBlockerCode.CASH_IDENTITY_FAILED, "cash identity")
        )
    if abs(funding.residual_cash) > min(
        funding.owner_maximum_absolute_residual_cash,
        policy.maximum_absolute_residual_cash,
    ):
        blockers.append(
            _blocker(
                CurveRelativeValueBlockerCode.RESIDUAL_CASH_EXCEEDED,
                "residual cash gate",
            )
        )
    unique_blockers = tuple(sorted(set(blockers), key=lambda item: (item.code.value, item.detail)))
    return _make_assessment(
        status=(
            CurveRelativeValueStatus.BLOCKED
            if unique_blockers
            else CurveRelativeValueStatus.AVAILABLE
        ),
        evidence=evidence,
        policy=policy,
        liquidity_policy=liquidity_policy,
        evaluated_at=evaluated_at,
        input_hash=input_hash,
        liquidity_results=tuple(
            sorted(liquidity_results.values(), key=lambda item: item.subject_id)
        ),
        legs=completed,
        key_rates=key_rates,
        blockers=unique_blockers,
    )
