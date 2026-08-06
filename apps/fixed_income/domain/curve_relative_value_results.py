"""Result contracts and structural validation for curve-relative-value research."""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import datetime
from decimal import Decimal

from apps.fixed_income.domain.curve_relative_value_contracts import (
    CurveLegRole,
    CurveLegSide,
    CurveRelativeValueBlocker,
    CurveRelativeValueLeg,
    CurveRelativeValueStatus,
    CurveRoleKindPair,
    CurveStrategyKind,
    CurveStrategyTopology,
    KeyRateAnalytics,
    KeyRateNeutralityTolerance,
)
from apps.fixed_income.domain.entities import CurveKind
from apps.fixed_income.domain.evidence import (
    canonical_hash,
    require_aware,
    require_finite,
    require_sha256,
    require_token,
)
from apps.fixed_income.domain.liquidity_premium import (
    LiquidityPremiumAssessment,
    LiquidityPremiumStatus,
)

_BP = Decimal("0.0001")


@dataclass(frozen=True)
class SignedKeyRateExposure:
    """Portfolio signed key-rate DV01/convexity and +1bp P&L."""

    tenor: str
    signed_dv01: Decimal
    signed_convexity: Decimal
    plus_one_bp_pnl: Decimal

    def __post_init__(self) -> None:
        require_token(self.tenor, "SignedKeyRateExposure.tenor")
        for name in ("signed_dv01", "signed_convexity", "plus_one_bp_pnl"):
            require_finite(getattr(self, name), f"SignedKeyRateExposure.{name}")
        if self.plus_one_bp_pnl != -self.signed_dv01:
            raise ValueError("key-rate +1bp P&L must equal negative signed DV01")


@dataclass(frozen=True)
class CurveLiquidityResultSeal:
    """Fresh per-subject liquidity result consumed by the curve calculation."""

    subject_id: str
    evaluated_at: datetime
    input_hash: str
    output_hash: str
    policy_hash: str
    status: LiquidityPremiumStatus
    applied_cost_bp: Decimal
    blocker_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        require_token(self.subject_id, "CurveLiquidityResultSeal.subject_id")
        require_aware(self.evaluated_at, "CurveLiquidityResultSeal.evaluated_at")
        for name in ("input_hash", "output_hash", "policy_hash"):
            require_sha256(
                str(getattr(self, name)),
                f"CurveLiquidityResultSeal.{name}",
            )
        if not isinstance(self.status, LiquidityPremiumStatus):
            raise ValueError("curve liquidity result status is invalid")
        require_finite(
            self.applied_cost_bp,
            "CurveLiquidityResultSeal.applied_cost_bp",
        )
        if self.applied_cost_bp < 0:
            raise ValueError("curve liquidity applied cost cannot be negative")
        if self.blocker_codes != tuple(sorted(set(self.blocker_codes))):
            raise ValueError("curve liquidity blocker codes must be canonical")
        if self.status is LiquidityPremiumStatus.AVAILABLE and self.blocker_codes:
            raise ValueError("available curve liquidity result cannot have blockers")


def seal_curve_liquidity_results(
    results: tuple[LiquidityPremiumAssessment, ...],
) -> tuple[CurveLiquidityResultSeal, ...]:
    """Return canonical fresh result seals shared with the composite assessment."""

    seals = tuple(
        CurveLiquidityResultSeal(
            subject_id=result.subject_id,
            evaluated_at=result.evaluated_at,
            input_hash=result.input_hash,
            output_hash=result.output_hash,
            policy_hash=result.policy_hash,
            status=result.status,
            applied_cost_bp=sum(
                (entry.applied_cost_bp for entry in result.cost_entries),
                start=Decimal("0"),
            ),
            blocker_codes=tuple(item.code.value for item in result.blockers),
        )
        for result in sorted(results, key=lambda item: item.subject_id)
    )
    subjects = tuple(item.subject_id for item in seals)
    if subjects != tuple(sorted(set(subjects))):
        raise ValueError("curve liquidity result subjects must be unique and canonical")
    return seals


@dataclass(frozen=True)
class CurveLegAssessment:
    """Fully recomputable signed leg risk, cash, cost, and owner-derived limits."""

    leg_id: str
    leg_role: CurveLegRole
    bond_id: str
    instrument_kind: str
    curve_role: str
    curve_kind: CurveKind
    side: CurveLegSide
    notional: Decimal
    holding_horizon_days: int
    liquidation_horizon_days: int
    dirty_price_per_100: Decimal
    long_key_rate_analytics: tuple[KeyRateAnalytics, ...]
    long_dv01: Decimal
    long_cs01: Decimal
    long_convexity: Decimal
    long_carry_cash: Decimal
    long_roll_down_cash: Decimal
    liquidity_cost_bp: Decimal
    borrow_cost_bp: Decimal | None
    issue_size: Decimal
    available_notional: Decimal
    owner_max_participation: Decimal
    policy_max_participation: Decimal
    liquidatable_notional: Decimal
    risk_identity_tolerance: Decimal
    dirty_market_value: Decimal
    signed_trade_cash: Decimal
    signed_dv01: Decimal
    plus_one_bp_pnl: Decimal
    signed_cs01: Decimal
    signed_convexity: Decimal
    signed_carry_cash: Decimal
    signed_roll_down_cash: Decimal
    gross_cost_cash: Decimal
    capacity_limit: Decimal
    liquidity_limit: Decimal
    effective_trade_limit: Decimal
    evidence_hash: str

    def __post_init__(self) -> None:
        for name in ("leg_id", "bond_id", "instrument_kind", "curve_role"):
            require_token(str(getattr(self, name)), f"CurveLegAssessment.{name}")
        if (
            not isinstance(self.leg_role, CurveLegRole)
            or not isinstance(
                self.side,
                CurveLegSide,
            )
            or not isinstance(self.curve_kind, CurveKind)
        ):
            raise ValueError("curve leg assessment enums are invalid")
        for name in (
            "notional",
            "dirty_price_per_100",
            "long_dv01",
            "long_cs01",
            "long_convexity",
            "long_carry_cash",
            "long_roll_down_cash",
            "liquidity_cost_bp",
            "issue_size",
            "available_notional",
            "owner_max_participation",
            "policy_max_participation",
            "liquidatable_notional",
            "risk_identity_tolerance",
            "dirty_market_value",
            "signed_trade_cash",
            "signed_dv01",
            "plus_one_bp_pnl",
            "signed_cs01",
            "signed_convexity",
            "signed_carry_cash",
            "signed_roll_down_cash",
            "gross_cost_cash",
            "capacity_limit",
            "liquidity_limit",
            "effective_trade_limit",
        ):
            require_finite(getattr(self, name), f"CurveLegAssessment.{name}")
        if self.borrow_cost_bp is not None:
            require_finite(self.borrow_cost_bp, "CurveLegAssessment.borrow_cost_bp")
        if (
            self.notional <= 0
            or self.holding_horizon_days <= 0
            or self.liquidation_horizon_days <= 0
            or self.liquidation_horizon_days > self.holding_horizon_days
            or self.dirty_price_per_100 <= 0
            or self.long_dv01 < 0
            or self.long_cs01 < 0
            or self.liquidity_cost_bp < 0
            or (self.borrow_cost_bp is not None and self.borrow_cost_bp < 0)
            or self.issue_size <= 0
            or self.available_notional < 0
            or self.liquidatable_notional < 0
            or self.risk_identity_tolerance < 0
            or not Decimal("0") < self.owner_max_participation <= Decimal("1")
            or not Decimal("0") < self.policy_max_participation <= Decimal("1")
        ):
            raise ValueError("curve leg assessment contains invalid raw values")
        key_rate_tenors = tuple(node.tenor for node in self.long_key_rate_analytics)
        if not key_rate_tenors or key_rate_tenors != tuple(sorted(set(key_rate_tenors))):
            raise ValueError("curve leg assessment key-rate universe is invalid")
        if (
            abs(
                sum(
                    (node.dv01 for node in self.long_key_rate_analytics),
                    start=Decimal("0"),
                )
                - self.long_dv01
            )
            > self.risk_identity_tolerance
        ):
            raise ValueError("curve leg assessment key-rate DV01 identity failed")
        if (
            abs(
                sum(
                    (node.convexity for node in self.long_key_rate_analytics),
                    start=Decimal("0"),
                )
                - self.long_convexity
            )
            > self.risk_identity_tolerance
        ):
            raise ValueError("curve leg assessment key-rate convexity identity failed")
        require_sha256(self.evidence_hash, "CurveLegAssessment.evidence_hash")
        sign = self.side.exposure_sign
        if self.dirty_market_value != self.notional * self.dirty_price_per_100 / Decimal("100"):
            raise ValueError("leg dirty market value is not recomputable")
        if self.signed_trade_cash != -sign * self.dirty_market_value:
            raise ValueError("leg signed cash is not recomputable")
        if (
            self.signed_dv01 != sign * self.long_dv01
            or self.plus_one_bp_pnl != -self.signed_dv01
            or self.signed_cs01 != sign * self.long_cs01
            or self.signed_convexity != sign * self.long_convexity
            or self.signed_carry_cash != sign * self.long_carry_cash
            or self.signed_roll_down_cash != sign * self.long_roll_down_cash
        ):
            raise ValueError("leg signed risk/carry identities failed")
        borrow = self.borrow_cost_bp or Decimal("0")
        if self.side is CurveLegSide.SHORT and self.borrow_cost_bp is None:
            raise ValueError("SHORT leg assessment requires borrow cost")
        if self.side is CurveLegSide.LONG and self.borrow_cost_bp is not None:
            raise ValueError("LONG leg assessment cannot carry borrow cost")
        if self.gross_cost_cash != self.notional * (self.liquidity_cost_bp + borrow) * _BP:
            raise ValueError("leg gross cost is not recomputable")
        participation = min(
            self.owner_max_participation,
            self.policy_max_participation,
        )
        if self.capacity_limit != min(
            self.available_notional * participation,
            self.issue_size * participation,
        ):
            raise ValueError("leg capacity is not owner-derived")
        if self.liquidity_limit != self.liquidatable_notional or (
            self.effective_trade_limit != min(self.capacity_limit, self.liquidity_limit)
        ):
            raise ValueError("leg effective trade limit is not owner-derived")


def _valid_structure(
    strategy: CurveStrategyKind,
    legs: tuple[CurveRelativeValueLeg, ...],
) -> bool:
    by_role = {leg.leg_role: leg for leg in legs}
    if len(by_role) != len(legs):
        return False
    if strategy in {
        CurveStrategyKind.KEY_RATE,
        CurveStrategyKind.STEEPENER,
        CurveStrategyKind.FLATTENING,
    }:
        if set(by_role) != {CurveLegRole.FRONT_END, CurveLegRole.BACK_END}:
            return False
        front = by_role[CurveLegRole.FRONT_END]
        back = by_role[CurveLegRole.BACK_END]
        if strategy is CurveStrategyKind.STEEPENER:
            return front.side is CurveLegSide.LONG and back.side is CurveLegSide.SHORT
        if strategy is CurveStrategyKind.FLATTENING:
            return front.side is CurveLegSide.SHORT and back.side is CurveLegSide.LONG
        return front.side is not back.side
    if strategy is CurveStrategyKind.BUTTERFLY:
        if set(by_role) != {
            CurveLegRole.LEFT_WING,
            CurveLegRole.BELLY,
            CurveLegRole.RIGHT_WING,
        }:
            return False
        left = by_role[CurveLegRole.LEFT_WING]
        belly = by_role[CurveLegRole.BELLY]
        right = by_role[CurveLegRole.RIGHT_WING]
        return left.side is right.side and belly.side is not left.side
    if set(by_role) != {CurveLegRole.CREDIT, CurveLegRole.HEDGE}:
        return False
    return by_role[CurveLegRole.CREDIT].side is not by_role[CurveLegRole.HEDGE].side


def _matches_topology(
    legs: tuple[CurveRelativeValueLeg, ...],
    topology: CurveStrategyTopology,
) -> bool:
    actual = {
        (
            leg.leg_role,
            leg.side,
            leg.curve_role,
            leg.curve_kind,
        )
        for leg in legs
    }
    expected = {
        (
            leg.leg_role,
            leg.side,
            leg.curve_pair.curve_role,
            leg.curve_pair.curve_kind,
        )
        for leg in topology.legs
    }
    return len(actual) == len(legs) == len(topology.legs) and actual == expected


@dataclass(frozen=True)
class CurveRelativeValueAssessment:
    """Fully sealed signed curve portfolio with recomputed gates and safety flags."""

    status: CurveRelativeValueStatus
    evaluated_at: datetime
    input_hash: str
    output_hash: str
    policy_hash: str
    curve_policy_hash: str
    liquidity_policy_hash: str
    candidate_id: str
    strategy_kind: CurveStrategyKind
    currency: str
    requested_leg_ids: tuple[str, ...]
    requested_liquidity_subjects: tuple[str, ...]
    liquidity_result_seals: tuple[CurveLiquidityResultSeal, ...]
    required_key_rate_tenors: tuple[str, ...]
    key_rate_tolerances: tuple[KeyRateNeutralityTolerance, ...]
    absolute_dv01_tolerance: Decimal
    absolute_cs01_tolerance: Decimal
    absolute_convexity_tolerance: Decimal
    cash_tolerance: Decimal
    maximum_absolute_residual_cash: Decimal
    policy_max_participation: Decimal
    risk_identity_tolerance: Decimal
    maximum_liquidation_horizon_days: int
    holding_horizon_days: int
    allowed_curve_pairs: tuple[CurveRoleKindPair, ...]
    allowed_instrument_kinds: tuple[str, ...]
    strategy_topology: CurveStrategyTopology
    calendar_hash: str
    funding_hash: str
    leg_assessments: tuple[CurveLegAssessment, ...]
    key_rate_exposures: tuple[SignedKeyRateExposure, ...]
    signed_dv01: Decimal
    plus_one_bp_pnl: Decimal
    signed_cs01: Decimal
    signed_convexity: Decimal
    trade_cash: Decimal
    financing_cash: Decimal
    residual_cash: Decimal
    gross_carry_cash: Decimal
    gross_roll_down_cash: Decimal
    total_cost_cash: Decimal | None
    net_relative_value_cash: Decimal | None
    blockers: tuple[CurveRelativeValueBlocker, ...]
    research_only: bool
    must_not_execute: bool
    must_not_use_for_decision: bool

    def __post_init__(self) -> None:
        require_aware(self.evaluated_at, "CurveRelativeValueAssessment.evaluated_at")
        for name in (
            "input_hash",
            "output_hash",
            "policy_hash",
            "curve_policy_hash",
            "liquidity_policy_hash",
            "calendar_hash",
            "funding_hash",
        ):
            require_sha256(str(getattr(self, name)), f"CurveRelativeValueAssessment.{name}")
        if self.policy_hash != canonical_hash(
            {
                "curve_policy_hash": self.curve_policy_hash,
                "liquidity_policy_hash": self.liquidity_policy_hash,
            }
        ):
            raise ValueError("curve assessment composite policy hash mismatch")
        if not (self.research_only and self.must_not_execute and self.must_not_use_for_decision):
            raise ValueError("curve assessment must remain research-only")
        if self.requested_leg_ids != tuple(sorted(set(self.requested_leg_ids))):
            raise ValueError("requested leg ids must be unique and canonical")
        if self.requested_liquidity_subjects != tuple(
            sorted(set(self.requested_liquidity_subjects))
        ):
            raise ValueError("requested liquidity subjects must be unique and canonical")
        if tuple(item.subject_id for item in self.liquidity_result_seals) != (
            self.requested_liquidity_subjects
        ):
            raise ValueError("curve liquidity result seals must exactly cover requested subjects")
        if any(
            item.evaluated_at != self.evaluated_at or item.policy_hash != self.liquidity_policy_hash
            for item in self.liquidity_result_seals
        ):
            raise ValueError(
                "curve liquidity results must use the curve cutoff and liquidity policy"
            )
        liquidity_seal_by_subject = {item.subject_id: item for item in self.liquidity_result_seals}
        if any(
            leg.bond_id not in liquidity_seal_by_subject
            or leg.liquidity_cost_bp != liquidity_seal_by_subject[leg.bond_id].applied_cost_bp
            for leg in self.leg_assessments
        ):
            raise ValueError("curve leg costs must equal the consumed liquidity result summaries")
        assessment_leg_ids = tuple(leg.leg_id for leg in self.leg_assessments)
        if assessment_leg_ids != tuple(sorted(set(assessment_leg_ids))):
            raise ValueError("assessed leg ids must be unique and canonical")
        if self.strategy_topology.strategy_kind is not self.strategy_kind:
            raise ValueError("assessment topology strategy kind mismatch")
        if self.allowed_curve_pairs != tuple(
            sorted(
                set(self.allowed_curve_pairs),
                key=lambda item: (item.curve_role, item.curve_kind.value),
            )
        ):
            raise ValueError("assessment allowed curve pairs must be canonical")
        if self.allowed_instrument_kinds != tuple(sorted(set(self.allowed_instrument_kinds))):
            raise ValueError("assessment allowed instrument kinds must be canonical")
        topology_projection = tuple(
            sorted(
                (
                    (
                        leg.leg_role,
                        leg.side,
                        leg.curve_role,
                        leg.curve_kind,
                    )
                    for leg in self.leg_assessments
                ),
                key=lambda item: (
                    item[0].value,
                    item[1].value,
                    item[2],
                    item[3].value,
                ),
            )
        )
        expected_topology_projection = tuple(
            sorted(
                (
                    (
                        leg.leg_role,
                        leg.side,
                        leg.curve_pair.curve_role,
                        leg.curve_pair.curve_kind,
                    )
                    for leg in self.strategy_topology.legs
                ),
                key=lambda item: (
                    item[0].value,
                    item[1].value,
                    item[2],
                    item[3].value,
                ),
            )
        )
        if self.status is CurveRelativeValueStatus.AVAILABLE and (
            topology_projection != expected_topology_projection
        ):
            raise ValueError("available assessment does not match versioned topology")
        allowed_pairs = {(pair.curve_role, pair.curve_kind) for pair in self.allowed_curve_pairs}
        if any(
            (leg.curve_role, leg.curve_kind) not in allowed_pairs
            or leg.instrument_kind not in self.allowed_instrument_kinds
            for leg in self.leg_assessments
        ):
            raise ValueError("assessed leg violates curve-pair/instrument policy")
        if tuple(item.tenor for item in self.key_rate_tolerances) != self.required_key_rate_tenors:
            raise ValueError("assessment key-rate policy universe mismatch")
        for name in (
            "absolute_dv01_tolerance",
            "absolute_cs01_tolerance",
            "absolute_convexity_tolerance",
            "cash_tolerance",
            "maximum_absolute_residual_cash",
            "signed_dv01",
            "plus_one_bp_pnl",
            "signed_cs01",
            "signed_convexity",
            "trade_cash",
            "financing_cash",
            "residual_cash",
            "gross_carry_cash",
            "gross_roll_down_cash",
        ):
            require_finite(getattr(self, name), f"CurveRelativeValueAssessment.{name}")
        if (
            not Decimal("0") < self.policy_max_participation <= Decimal("1")
            or self.risk_identity_tolerance < 0
            or self.maximum_liquidation_horizon_days <= 0
            or self.holding_horizon_days <= 0
        ):
            raise ValueError("assessment policy capacity/risk/horizon projection is invalid")
        if any(
            leg.policy_max_participation != self.policy_max_participation
            or leg.risk_identity_tolerance != self.risk_identity_tolerance
            or leg.holding_horizon_days != self.holding_horizon_days
            or leg.liquidation_horizon_days > self.maximum_liquidation_horizon_days
            for leg in self.leg_assessments
        ):
            raise ValueError("leg capacity/risk/horizon differs from policy projection")
        if (
            self.signed_dv01
            != sum((leg.signed_dv01 for leg in self.leg_assessments), start=Decimal("0"))
            or self.signed_cs01
            != sum((leg.signed_cs01 for leg in self.leg_assessments), start=Decimal("0"))
            or self.signed_convexity
            != sum((leg.signed_convexity for leg in self.leg_assessments), start=Decimal("0"))
        ):
            raise ValueError("portfolio risk totals are not recomputable")
        if self.plus_one_bp_pnl != -self.signed_dv01:
            raise ValueError("portfolio +1bp P&L identity failed")
        if self.trade_cash != sum(
            (leg.signed_trade_cash for leg in self.leg_assessments), start=Decimal("0")
        ):
            raise ValueError("portfolio trade cash is not recomputable")
        if self.gross_carry_cash != sum(
            (leg.signed_carry_cash for leg in self.leg_assessments), start=Decimal("0")
        ) or self.gross_roll_down_cash != sum(
            (leg.signed_roll_down_cash for leg in self.leg_assessments), start=Decimal("0")
        ):
            raise ValueError("portfolio carry/roll-down is not recomputable")
        if any(
            tuple(node.tenor for node in leg.long_key_rate_analytics)
            != self.required_key_rate_tenors
            for leg in self.leg_assessments
        ):
            raise ValueError("leg key-rate universe is incomplete")
        expected_key_rates = tuple(
            SignedKeyRateExposure(
                tenor=tenor,
                signed_dv01=sum(
                    (
                        leg.side.exposure_sign
                        * next(
                            node.dv01 for node in leg.long_key_rate_analytics if node.tenor == tenor
                        )
                        for leg in self.leg_assessments
                    ),
                    start=Decimal("0"),
                ),
                signed_convexity=sum(
                    (
                        leg.side.exposure_sign
                        * next(
                            node.convexity
                            for node in leg.long_key_rate_analytics
                            if node.tenor == tenor
                        )
                        for leg in self.leg_assessments
                    ),
                    start=Decimal("0"),
                ),
                plus_one_bp_pnl=-sum(
                    (
                        leg.side.exposure_sign
                        * next(
                            node.dv01 for node in leg.long_key_rate_analytics if node.tenor == tenor
                        )
                        for leg in self.leg_assessments
                    ),
                    start=Decimal("0"),
                ),
            )
            for tenor in self.required_key_rate_tenors
        )
        if self.key_rate_exposures != expected_key_rates:
            raise ValueError("portfolio key-rate vector is not recomputable")
        if self.total_cost_cash is not None and self.total_cost_cash != sum(
            (leg.gross_cost_cash for leg in self.leg_assessments), start=Decimal("0")
        ):
            raise ValueError("portfolio cost is not recomputable")
        if self.net_relative_value_cash is not None and (
            self.total_cost_cash is None
            or self.net_relative_value_cash
            != self.gross_carry_cash + self.gross_roll_down_cash - self.total_cost_cash
        ):
            raise ValueError("portfolio net relative value is not recomputable")
        if self.blockers != tuple(
            sorted(set(self.blockers), key=lambda item: (item.code.value, item.detail))
        ):
            raise ValueError("curve blockers must be unique and canonical")
        if self.status is CurveRelativeValueStatus.AVAILABLE:
            if (
                self.blockers
                or assessment_leg_ids != self.requested_leg_ids
                or any(
                    item.status is not LiquidityPremiumStatus.AVAILABLE
                    for item in self.liquidity_result_seals
                )
                or self.total_cost_cash is None
                or self.net_relative_value_cash is None
                or abs(self.signed_dv01) > self.absolute_dv01_tolerance
                or abs(self.signed_cs01) > self.absolute_cs01_tolerance
                or abs(self.signed_convexity) > self.absolute_convexity_tolerance
                or abs(self.trade_cash + self.financing_cash + self.residual_cash)
                > self.cash_tolerance
                or abs(self.residual_cash) > self.maximum_absolute_residual_cash
                or any(
                    abs(exposure.signed_dv01) > tolerance.absolute_dv01
                    for exposure, tolerance in zip(
                        self.key_rate_exposures,
                        self.key_rate_tolerances,
                        strict=True,
                    )
                )
                or any(leg.notional > leg.effective_trade_limit for leg in self.leg_assessments)
            ):
                raise ValueError("available curve assessment violates a sealed gate")
        elif not self.blockers:
            raise ValueError("blocked curve assessment requires blockers")
        if self.output_hash != self.calculated_output_hash:
            raise ValueError("curve assessment output hash mismatch")

    @property
    def calculated_output_hash(self) -> str:
        """Recompute the complete output, gates, blockers, and safety digest."""

        return canonical_hash(
            {
                field.name: getattr(self, field.name)
                for field in fields(self)
                if field.name != "output_hash"
            }
        )
