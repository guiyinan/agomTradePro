"""Signed curve-relative-value portfolio contracts for R5 research."""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum

from apps.fixed_income.domain.entities import CurveKind
from apps.fixed_income.domain.evidence import (
    EvidenceRole,
    ExactEvidence,
    canonical_hash,
    require_aware,
    require_finite,
    require_sha256,
    require_token,
)
from apps.fixed_income.domain.liquidity_premium import (
    LiquidityCostBasis,
    LiquidityPremiumAssessment,
    LiquidityPremiumEvidence,
    LiquidityPremiumPolicy,
    LiquidityPremiumStatus,
    evaluate_liquidity_premium,
)

_BP = Decimal("0.0001")


class CurveStrategyKind(str, Enum):
    """Supported curve and credit relative-value structures."""

    KEY_RATE = "key_rate"
    STEEPENER = "steepener"
    FLATTENING = "flattening"
    BUTTERFLY = "butterfly"
    CREDIT_SPREAD = "credit_spread"


class CurveLegSide(str, Enum):
    """Single sign convention for strictly positive notional."""

    LONG = "long"
    SHORT = "short"

    @property
    def exposure_sign(self) -> Decimal:
        """Return +1 for LONG exposure and -1 for SHORT exposure."""

        return Decimal("1") if self is CurveLegSide.LONG else Decimal("-1")


class CurveLegRole(str, Enum):
    """Topology role inside a curve structure."""

    FRONT_END = "front_end"
    BACK_END = "back_end"
    BELLY = "belly"
    LEFT_WING = "left_wing"
    RIGHT_WING = "right_wing"
    CREDIT = "credit"
    HEDGE = "hedge"


class CurveRelativeValueStatus(str, Enum):
    """Availability state of one research-only candidate."""

    AVAILABLE = "available"
    BLOCKED = "blocked"


class CurveCarryCostSemantics(str, Enum):
    """Whether leg carry/roll values already include costs."""

    GROSS_BEFORE_LIQUIDITY_AND_BORROW_COSTS = "gross_before_liquidity_and_borrow_costs"


class CurveRelativeValueBlockerCode(str, Enum):
    """Stable evidence, identity, neutrality, and tradability blockers."""

    INPUT_HASH_MISMATCH = "fixed_income.curve_rv.input.hash_mismatch"
    POLICY_INACTIVE = "fixed_income.curve_rv.policy.inactive"
    EVIDENCE_FROM_FUTURE = "fixed_income.curve_rv.evidence.from_future"
    EVIDENCE_STALE = "fixed_income.curve_rv.evidence.stale"
    BOND_MASTER_MISSING = "fixed_income.curve_rv.bond_master.missing"
    CASH_FLOW_MISSING = "fixed_income.curve_rv.cash_flow.missing"
    CALENDAR_MISSING = "fixed_income.curve_rv.calendar.missing"
    CASH_FUNDING_MISSING = "fixed_income.curve_rv.cash_funding.missing"
    LIQUIDITY_ASSESSMENT_MISSING = "fixed_income.curve_rv.liquidity_assessment.missing"
    CAPACITY_MISSING = "fixed_income.curve_rv.capacity.missing"
    LIQUIDITY_GATE_MISSING = "fixed_income.curve_rv.liquidity_gate.missing"
    SHORTABILITY_MISSING = "fixed_income.curve_rv.shortability.missing"
    CURRENCY_MISMATCH = "fixed_income.curve_rv.currency.mismatch"
    CURVE_PAIR_MISMATCH = "fixed_income.curve_rv.curve_pair.mismatch"
    INSTRUMENT_KIND_MISMATCH = "fixed_income.curve_rv.instrument_kind.mismatch"
    INSTRUMENT_DUPLICATE = "fixed_income.curve_rv.instrument.duplicate"
    STRUCTURE_INVALID = "fixed_income.curve_rv.structure.invalid"
    SETTLEMENT_HORIZON_MISMATCH = "fixed_income.curve_rv.settlement_horizon.mismatch"
    PRICE_IDENTITY_FAILED = "fixed_income.curve_rv.identity.dirty_price"
    ANALYTICS_NOTIONAL_MISMATCH = "fixed_income.curve_rv.analytics.notional_mismatch"
    KEY_RATE_UNIVERSE_MISMATCH = "fixed_income.curve_rv.key_rate.universe"
    KEY_RATE_DV01_IDENTITY_FAILED = "fixed_income.curve_rv.identity.key_rate_dv01"
    KEY_RATE_CONVEXITY_IDENTITY_FAILED = "fixed_income.curve_rv.identity.key_rate_convexity"
    DV01_NEUTRALITY_BREACHED = "fixed_income.curve_rv.neutrality.dv01"
    CS01_NEUTRALITY_BREACHED = "fixed_income.curve_rv.neutrality.cs01"
    CONVEXITY_NEUTRALITY_BREACHED = "fixed_income.curve_rv.neutrality.convexity"
    KEY_RATE_NEUTRALITY_BREACHED = "fixed_income.curve_rv.neutrality.key_rate"
    CASH_IDENTITY_FAILED = "fixed_income.curve_rv.identity.cash"
    RESIDUAL_CASH_EXCEEDED = "fixed_income.curve_rv.cash.residual_exceeded"
    CAPACITY_EXCEEDED = "fixed_income.curve_rv.capacity.exceeded"
    LIQUIDITY_EXCEEDED = "fixed_income.curve_rv.liquidity.exceeded"
    BORROW_COST_MISSING = "fixed_income.curve_rv.borrow_cost.missing"
    COST_LEDGER_HORIZON_MISMATCH = "fixed_income.curve_rv.cost_ledger.horizon"


@dataclass(frozen=True)
class CurveRelativeValueBlocker:
    """Stable blocker with bounded diagnostic detail."""

    code: CurveRelativeValueBlockerCode
    detail: str

    def __post_init__(self) -> None:
        if not isinstance(self.code, CurveRelativeValueBlockerCode):
            raise ValueError("CurveRelativeValueBlocker.code is invalid")
        require_token(
            self.detail.replace(" ", "_"),
            "CurveRelativeValueBlocker.detail",
            maximum=240,
        )


def _record_bound(record_hash: str, evidence: ExactEvidence) -> bool:
    return record_hash == evidence.content_hash or record_hash in evidence.upstream_hashes


@dataclass(frozen=True)
class BondMasterEvidence:
    """Exact owner bond master including instrument kind and issue size."""

    bond_id: str
    currency: str
    instrument_kind: str
    issue_size: Decimal
    record_hash: str
    evidence: ExactEvidence

    def __post_init__(self) -> None:
        require_token(self.bond_id, "BondMasterEvidence.bond_id")
        require_token(self.currency, "BondMasterEvidence.currency", maximum=12)
        require_token(self.instrument_kind, "BondMasterEvidence.instrument_kind")
        require_finite(self.issue_size, "BondMasterEvidence.issue_size")
        require_sha256(self.record_hash, "BondMasterEvidence.record_hash")
        if self.issue_size <= 0:
            raise ValueError("bond issue size must be positive")
        if self.evidence.role is not EvidenceRole.BOND_MASTER:
            raise ValueError("bond master requires BondMaster owner evidence")
        if (
            self.evidence.subject_id != self.bond_id
            or self.evidence.currency != self.currency
            or self.evidence.curve_role != "bond_master"
            or not _record_bound(self.record_hash, self.evidence)
        ):
            raise ValueError("bond master values are not bound by exact owner evidence")

    @property
    def master_hash(self) -> str:
        """Hash all master values and owner provenance."""

        return canonical_hash(
            {
                "bond_id": self.bond_id,
                "currency": self.currency,
                "instrument_kind": self.instrument_kind,
                "issue_size": self.issue_size,
                "record_hash": self.record_hash,
                "evidence_hash": self.evidence.seal_hash,
            }
        )


@dataclass(frozen=True)
class CashFlowEvidence:
    """Exact owner schedule and accrued-interest values."""

    schedule_id: str
    bond_id: str
    currency: str
    face_value: Decimal
    accrued_interest_per_100: Decimal
    record_hash: str
    evidence: ExactEvidence

    def __post_init__(self) -> None:
        for name in ("schedule_id", "bond_id", "currency"):
            require_token(str(getattr(self, name)), f"CashFlowEvidence.{name}")
        require_finite(self.face_value, "CashFlowEvidence.face_value")
        require_finite(self.accrued_interest_per_100, "accrued_interest_per_100")
        require_sha256(self.record_hash, "CashFlowEvidence.record_hash")
        if self.face_value <= 0 or self.accrued_interest_per_100 < 0:
            raise ValueError("cash-flow face/accrued values are invalid")
        if self.evidence.role is not EvidenceRole.CASH_FLOW:
            raise ValueError("cash flow requires CashFlow owner evidence")
        if (
            self.evidence.subject_id != self.bond_id
            or self.evidence.currency != self.currency
            or self.evidence.curve_role != "cash_flow"
            or not _record_bound(self.record_hash, self.evidence)
        ):
            raise ValueError("cash-flow values are not bound by exact owner evidence")

    @property
    def schedule_hash(self) -> str:
        """Hash all cash-flow identity/value and provenance fields."""

        return canonical_hash(
            {
                "schedule_id": self.schedule_id,
                "bond_id": self.bond_id,
                "currency": self.currency,
                "face_value": self.face_value,
                "accrued_interest_per_100": self.accrued_interest_per_100,
                "record_hash": self.record_hash,
                "evidence_hash": self.evidence.seal_hash,
            }
        )


@dataclass(frozen=True)
class CurveTradingCalendarEvidence:
    """Exact settlement and holding-horizon calendar evidence."""

    calendar_id: str
    calendar_version: str
    settlement_at: datetime
    horizon_ends_at: datetime
    holding_horizon_days: int
    record_hash: str
    evidence: ExactEvidence

    def __post_init__(self) -> None:
        require_token(self.calendar_id, "CurveTradingCalendarEvidence.calendar_id")
        require_token(self.calendar_version, "CurveTradingCalendarEvidence.calendar_version")
        require_aware(self.settlement_at, "CurveTradingCalendarEvidence.settlement_at")
        require_aware(self.horizon_ends_at, "CurveTradingCalendarEvidence.horizon_ends_at")
        require_sha256(self.record_hash, "CurveTradingCalendarEvidence.record_hash")
        if self.holding_horizon_days <= 0 or self.horizon_ends_at != (
            self.settlement_at + timedelta(days=self.holding_horizon_days)
        ):
            raise ValueError("calendar holding horizon is not exact")
        if self.evidence.role is not EvidenceRole.CALENDAR:
            raise ValueError("curve calendar requires Calendar owner evidence")
        if (
            self.evidence.evidence_id != self.calendar_id
            or self.evidence.version != self.calendar_version
            or self.evidence.subject_id != self.calendar_id
            or self.evidence.curve_role != "curve_trading_calendar"
            or not _record_bound(self.record_hash, self.evidence)
        ):
            raise ValueError("curve calendar is not bound by exact owner evidence")

    @property
    def calendar_hash(self) -> str:
        """Hash exact settlement, horizon, record, and owner evidence."""

        return canonical_hash(
            {
                "calendar_id": self.calendar_id,
                "calendar_version": self.calendar_version,
                "settlement_at": self.settlement_at,
                "horizon_ends_at": self.horizon_ends_at,
                "holding_horizon_days": self.holding_horizon_days,
                "record_hash": self.record_hash,
                "evidence_hash": self.evidence.seal_hash,
            }
        )


@dataclass(frozen=True)
class CurveCashFundingEvidence:
    """Owner-supplied funding and bounded residual cash; never a caller plug."""

    candidate_id: str
    currency: str
    settlement_at: datetime
    financing_cash: Decimal
    residual_cash: Decimal
    owner_maximum_absolute_residual_cash: Decimal
    record_hash: str
    evidence: ExactEvidence

    def __post_init__(self) -> None:
        require_token(self.candidate_id, "CurveCashFundingEvidence.candidate_id")
        require_token(self.currency, "CurveCashFundingEvidence.currency", maximum=12)
        require_aware(self.settlement_at, "CurveCashFundingEvidence.settlement_at")
        for name in (
            "financing_cash",
            "residual_cash",
            "owner_maximum_absolute_residual_cash",
        ):
            require_finite(getattr(self, name), f"CurveCashFundingEvidence.{name}")
        if self.owner_maximum_absolute_residual_cash < 0:
            raise ValueError("owner residual cash limit cannot be negative")
        require_sha256(self.record_hash, "CurveCashFundingEvidence.record_hash")
        if self.evidence.role is not EvidenceRole.PORTFOLIO_INPUT:
            raise ValueError("cash funding requires exact Portfolio owner evidence")
        if (
            self.evidence.subject_id != self.candidate_id
            or self.evidence.currency != self.currency
            or self.evidence.curve_role != "curve_cash_funding"
            or not _record_bound(self.record_hash, self.evidence)
        ):
            raise ValueError("cash/funding values are not bound by owner evidence")

    @property
    def funding_hash(self) -> str:
        """Hash funding, residual, limit, settlement, and owner provenance."""

        return canonical_hash(
            {
                "candidate_id": self.candidate_id,
                "currency": self.currency,
                "settlement_at": self.settlement_at,
                "financing_cash": self.financing_cash,
                "residual_cash": self.residual_cash,
                "owner_maximum_absolute_residual_cash": (self.owner_maximum_absolute_residual_cash),
                "record_hash": self.record_hash,
                "evidence_hash": self.evidence.seal_hash,
            }
        )


@dataclass(frozen=True)
class KeyRateAnalytics:
    """Long-side key-rate DV01 and convexity at one required tenor."""

    tenor: str
    dv01: Decimal
    convexity: Decimal

    def __post_init__(self) -> None:
        require_token(self.tenor, "KeyRateAnalytics.tenor")
        require_finite(self.dv01, "KeyRateAnalytics.dv01")
        require_finite(self.convexity, "KeyRateAnalytics.convexity")


@dataclass(frozen=True)
class CurveRelativeValueLeg:
    """Positive-notional leg whose long analytics are bound to that notional.

    Long ``dv01`` is positive and the +1bp first-order P&L is ``-dv01``.
    ``cs01`` is mandatory and can be an exact, sealed zero.
    """

    leg_id: str
    leg_role: CurveLegRole
    bond_id: str
    side: CurveLegSide
    notional: Decimal
    analytics_notional: Decimal
    currency: str
    curve_kind: CurveKind
    curve_role: str
    settlement_at: datetime
    holding_horizon_days: int
    calendar_hash: str
    clean_price_per_100: Decimal
    accrued_interest_per_100: Decimal
    dirty_price_per_100: Decimal
    key_rate_analytics: tuple[KeyRateAnalytics, ...]
    dv01: Decimal
    cs01: Decimal
    convexity: Decimal
    carry_cash: Decimal
    roll_down_cash: Decimal
    carry_cost_semantics: CurveCarryCostSemantics
    carry_cost_manifest_hash: str
    bond_master_hash: str
    cash_flow_hash: str
    liquidity_evidence_hash: str
    analytics_record_hash: str
    source: ExactEvidence

    def __post_init__(self) -> None:
        for name in ("leg_id", "bond_id", "currency", "curve_role"):
            require_token(str(getattr(self, name)), f"CurveRelativeValueLeg.{name}")
        if not isinstance(self.leg_role, CurveLegRole) or not isinstance(self.side, CurveLegSide):
            raise ValueError("curve leg role/side is invalid")
        if not isinstance(self.curve_kind, CurveKind):
            raise ValueError("curve kind is invalid")
        require_aware(self.settlement_at, "CurveRelativeValueLeg.settlement_at")
        for name in (
            "notional",
            "analytics_notional",
            "clean_price_per_100",
            "accrued_interest_per_100",
            "dirty_price_per_100",
            "dv01",
            "cs01",
            "convexity",
            "carry_cash",
            "roll_down_cash",
        ):
            require_finite(getattr(self, name), f"CurveRelativeValueLeg.{name}")
        if self.notional <= 0 or self.analytics_notional != self.notional:
            raise ValueError("leg analytics must be bound to exact positive notional")
        if (
            self.clean_price_per_100 <= 0
            or self.dirty_price_per_100 <= 0
            or self.accrued_interest_per_100 < 0
            or self.dv01 < 0
            or self.cs01 < 0
        ):
            raise ValueError("leg price/accrued/DV01/CS01 values are invalid")
        if self.holding_horizon_days <= 0:
            raise ValueError("leg holding horizon must be positive")
        for name in (
            "calendar_hash",
            "bond_master_hash",
            "cash_flow_hash",
            "liquidity_evidence_hash",
            "analytics_record_hash",
            "carry_cost_manifest_hash",
        ):
            require_sha256(str(getattr(self, name)), f"CurveRelativeValueLeg.{name}")
        tenors = tuple(node.tenor for node in self.key_rate_analytics)
        if not tenors or tenors != tuple(sorted(set(tenors))):
            raise ValueError("leg key-rate universe must be non-empty and canonical")
        if self.source.role is not EvidenceRole.FIXED_INCOME_ANALYTICS:
            raise ValueError("curve leg requires fixed-income analytics evidence")
        if (
            self.carry_cost_semantics
            is not CurveCarryCostSemantics.GROSS_BEFORE_LIQUIDITY_AND_BORROW_COSTS
        ):
            raise ValueError("curve carry must be gross before unique cost ledgers")
        expected_carry_manifest = canonical_hash(
            {
                "analytics_record_hash": self.analytics_record_hash,
                "notional": self.notional,
                "holding_horizon_days": self.holding_horizon_days,
                "carry_cash": self.carry_cash,
                "roll_down_cash": self.roll_down_cash,
                "cost_semantics": self.carry_cost_semantics,
            }
        )
        if (
            self.carry_cost_manifest_hash != expected_carry_manifest
            or self.carry_cost_manifest_hash not in self.source.upstream_hashes
        ):
            raise ValueError("leg source must attest gross carry cost-inclusion manifest")
        if (
            self.source.subject_id != self.bond_id
            or self.source.currency != self.currency
            or self.source.curve_role != self.curve_role
            or not _record_bound(self.analytics_record_hash, self.source)
        ):
            raise ValueError("leg analytics are not bound by exact PIT evidence")

    @property
    def leg_hash(self) -> str:
        """Hash raw owner analytics plus the exact liquidity-evidence link."""

        return canonical_hash(
            {
                "raw_leg_hash": self.raw_leg_hash,
                "liquidity_evidence_hash": self.liquidity_evidence_hash,
            }
        )

    @property
    def raw_leg_hash(self) -> str:
        """Hash raw multi-owner leg inputs without derived result hashes."""

        return canonical_hash(
            {
                name: getattr(self, name) if name != "source" else self.source.seal_hash
                for name in self.__dataclass_fields__
                if name != "liquidity_evidence_hash"
            }
        )


@dataclass(frozen=True)
class DirectionalCapacityEvidence:
    """Exact side-specific availability and mandatory SHORT borrow evidence."""

    bond_id: str
    currency: str
    side: CurveLegSide
    available_notional: Decimal
    owner_max_participation: Decimal
    borrow_cost_bp: Decimal | None
    borrow_cost_basis: LiquidityCostBasis | None
    borrow_cost_horizon_days: int | None
    record_hash: str
    evidence: ExactEvidence

    def __post_init__(self) -> None:
        require_token(self.bond_id, "DirectionalCapacityEvidence.bond_id")
        require_token(self.currency, "DirectionalCapacityEvidence.currency", maximum=12)
        if not isinstance(self.side, CurveLegSide):
            raise ValueError("directional capacity side is invalid")
        require_finite(self.available_notional, "available_notional")
        require_finite(self.owner_max_participation, "owner_max_participation")
        if self.available_notional < 0 or not Decimal(
            "0"
        ) < self.owner_max_participation <= Decimal("1"):
            raise ValueError("directional capacity amount/participation is invalid")
        if self.side is CurveLegSide.SHORT:
            if (
                self.borrow_cost_bp is None
                or self.borrow_cost_basis is not LiquidityCostBasis.GROSS_TRADED_NOTIONAL
                or self.borrow_cost_horizon_days is None
                or self.borrow_cost_horizon_days <= 0
            ):
                raise ValueError("SHORT requires exact borrow cost basis and horizon")
            require_finite(self.borrow_cost_bp, "borrow_cost_bp")
            if self.borrow_cost_bp < 0:
                raise ValueError("borrow cost cannot be negative")
        elif any(
            value is not None
            for value in (
                self.borrow_cost_bp,
                self.borrow_cost_basis,
                self.borrow_cost_horizon_days,
            )
        ):
            raise ValueError("LONG capacity cannot carry synthetic borrow evidence")
        require_sha256(self.record_hash, "DirectionalCapacityEvidence.record_hash")
        if self.evidence.role is not EvidenceRole.PUBLICATION:
            raise ValueError("directional capacity requires Publication evidence")
        if (
            self.evidence.subject_id != self.bond_id
            or self.evidence.currency != self.currency
            or self.evidence.curve_role != f"capacity:{self.side.value}"
            or not _record_bound(self.record_hash, self.evidence)
        ):
            raise ValueError("capacity/borrow values are not owner-bound")

    @property
    def capacity_hash(self) -> str:
        """Hash side, capacity, participation, borrow, and owner evidence."""

        return canonical_hash(
            {
                name: getattr(self, name) if name != "evidence" else self.evidence.seal_hash
                for name in self.__dataclass_fields__
            }
        )


@dataclass(frozen=True)
class LiquidityCapacityEvidence:
    """Exact side-specific liquidatable amount over a fixed horizon."""

    bond_id: str
    currency: str
    side: CurveLegSide
    liquidatable_notional: Decimal
    horizon_days: int
    record_hash: str
    evidence: ExactEvidence

    def __post_init__(self) -> None:
        require_token(self.bond_id, "LiquidityCapacityEvidence.bond_id")
        require_token(self.currency, "LiquidityCapacityEvidence.currency", maximum=12)
        if not isinstance(self.side, CurveLegSide):
            raise ValueError("liquidity capacity side is invalid")
        require_finite(self.liquidatable_notional, "liquidatable_notional")
        if self.liquidatable_notional < 0 or self.horizon_days <= 0:
            raise ValueError("liquidity capacity amount/horizon is invalid")
        require_sha256(self.record_hash, "LiquidityCapacityEvidence.record_hash")
        if self.evidence.role is not EvidenceRole.PUBLICATION:
            raise ValueError("liquidity capacity requires Publication evidence")
        if (
            self.evidence.subject_id != self.bond_id
            or self.evidence.currency != self.currency
            or self.evidence.curve_role != f"liquidity_capacity:{self.side.value}"
            or not _record_bound(self.record_hash, self.evidence)
        ):
            raise ValueError("liquidity capacity is not owner-bound")

    @property
    def liquidity_hash(self) -> str:
        """Hash side-specific amount, horizon, and exact owner evidence."""

        return canonical_hash(
            {
                name: getattr(self, name) if name != "evidence" else self.evidence.seal_hash
                for name in self.__dataclass_fields__
            }
        )


@dataclass(frozen=True)
class CurveRoleKindPair:
    """One versioned legal curve-role/curve-kind combination."""

    curve_role: str
    curve_kind: CurveKind

    def __post_init__(self) -> None:
        require_token(self.curve_role, "CurveRoleKindPair.curve_role")
        if not isinstance(self.curve_kind, CurveKind):
            raise ValueError("CurveRoleKindPair.curve_kind is invalid")


@dataclass(frozen=True)
class CurveTopologyLegSpec:
    """One exact topology leg role, side, and legal curve pair."""

    leg_role: CurveLegRole
    side: CurveLegSide
    curve_pair: CurveRoleKindPair

    def __post_init__(self) -> None:
        if not isinstance(self.leg_role, CurveLegRole) or not isinstance(self.side, CurveLegSide):
            raise ValueError("curve topology leg role/side is invalid")


@dataclass(frozen=True)
class CurveStrategyTopology:
    """Versioned exact leg topology for one strategy kind."""

    strategy_kind: CurveStrategyKind
    legs: tuple[CurveTopologyLegSpec, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.strategy_kind, CurveStrategyKind):
            raise ValueError("curve topology strategy kind is invalid")
        expected_roles: set[CurveLegRole]
        if self.strategy_kind in {
            CurveStrategyKind.KEY_RATE,
            CurveStrategyKind.STEEPENER,
            CurveStrategyKind.FLATTENING,
        }:
            expected_roles = {CurveLegRole.FRONT_END, CurveLegRole.BACK_END}
        elif self.strategy_kind is CurveStrategyKind.BUTTERFLY:
            expected_roles = {
                CurveLegRole.LEFT_WING,
                CurveLegRole.BELLY,
                CurveLegRole.RIGHT_WING,
            }
        else:
            expected_roles = {CurveLegRole.CREDIT, CurveLegRole.HEDGE}
        roles = {leg.leg_role for leg in self.legs}
        if roles != expected_roles or len(self.legs) != len(expected_roles):
            raise ValueError("curve topology must exactly cover strategy leg roles")
        if self.legs != tuple(sorted(self.legs, key=lambda leg: leg.leg_role.value)):
            raise ValueError("curve topology legs must use canonical role order")
        sides = {leg.side for leg in self.legs}
        if sides != {CurveLegSide.LONG, CurveLegSide.SHORT}:
            raise ValueError("curve topology requires both LONG and SHORT")
        by_role = {leg.leg_role: leg for leg in self.legs}
        if self.strategy_kind is CurveStrategyKind.STEEPENER and not (
            by_role[CurveLegRole.FRONT_END].side is CurveLegSide.LONG
            and by_role[CurveLegRole.BACK_END].side is CurveLegSide.SHORT
        ):
            raise ValueError("steepener topology side convention is invalid")
        if self.strategy_kind is CurveStrategyKind.FLATTENING and not (
            by_role[CurveLegRole.FRONT_END].side is CurveLegSide.SHORT
            and by_role[CurveLegRole.BACK_END].side is CurveLegSide.LONG
        ):
            raise ValueError("flattening topology side convention is invalid")
        if self.strategy_kind is CurveStrategyKind.BUTTERFLY and not (
            by_role[CurveLegRole.LEFT_WING].side is by_role[CurveLegRole.RIGHT_WING].side
            and by_role[CurveLegRole.BELLY].side is not by_role[CurveLegRole.LEFT_WING].side
        ):
            raise ValueError("butterfly topology side convention is invalid")
        if self.strategy_kind is CurveStrategyKind.CREDIT_SPREAD and (
            by_role[CurveLegRole.CREDIT].curve_pair == by_role[CurveLegRole.HEDGE].curve_pair
        ):
            raise ValueError("credit-spread topology requires distinct curve pairs")


@dataclass(frozen=True)
class KeyRateNeutralityTolerance:
    """Absolute signed key-rate DV01 tolerance for one required tenor."""

    tenor: str
    absolute_dv01: Decimal

    def __post_init__(self) -> None:
        require_token(self.tenor, "KeyRateNeutralityTolerance.tenor")
        require_finite(self.absolute_dv01, "absolute_dv01")
        if self.absolute_dv01 < 0:
            raise ValueError("key-rate tolerance cannot be negative")


@dataclass(frozen=True)
class CurveRelativeValuePolicy:
    """Versioned topology, legal instruments, risk, cash, and capacity gates."""

    policy_id: str
    policy_version: str
    required_key_rate_tenors: tuple[str, ...]
    key_rate_tolerances: tuple[KeyRateNeutralityTolerance, ...]
    absolute_dv01_tolerance: Decimal
    absolute_cs01_tolerance: Decimal
    absolute_convexity_tolerance: Decimal
    cash_tolerance: Decimal
    maximum_absolute_residual_cash: Decimal
    price_identity_tolerance: Decimal
    risk_identity_tolerance: Decimal
    policy_max_participation: Decimal
    maximum_liquidation_horizon_days: int
    allowed_curve_pairs: tuple[CurveRoleKindPair, ...]
    allowed_instrument_kinds: tuple[str, ...]
    strategy_topologies: tuple[CurveStrategyTopology, ...]
    evidence: ExactEvidence

    def __post_init__(self) -> None:
        require_token(self.policy_id, "CurveRelativeValuePolicy.policy_id")
        require_token(self.policy_version, "CurveRelativeValuePolicy.policy_version")
        for tenor in self.required_key_rate_tenors:
            require_token(tenor, "required_key_rate_tenor")
        if not self.required_key_rate_tenors or self.required_key_rate_tenors != tuple(
            sorted(set(self.required_key_rate_tenors))
        ):
            raise ValueError("required key-rate universe must be canonical")
        if tuple(item.tenor for item in self.key_rate_tolerances) != (
            self.required_key_rate_tenors
        ):
            raise ValueError("key-rate tolerances must exactly cover required universe")
        for name in (
            "absolute_dv01_tolerance",
            "absolute_cs01_tolerance",
            "absolute_convexity_tolerance",
            "cash_tolerance",
            "maximum_absolute_residual_cash",
            "price_identity_tolerance",
            "risk_identity_tolerance",
            "policy_max_participation",
        ):
            require_finite(getattr(self, name), f"CurveRelativeValuePolicy.{name}")
        if any(
            value < 0
            for value in (
                self.absolute_dv01_tolerance,
                self.absolute_cs01_tolerance,
                self.absolute_convexity_tolerance,
                self.cash_tolerance,
                self.maximum_absolute_residual_cash,
                self.price_identity_tolerance,
                self.risk_identity_tolerance,
            )
        ):
            raise ValueError("curve tolerances/limits cannot be negative")
        if not Decimal("0") < self.policy_max_participation <= Decimal("1"):
            raise ValueError("policy max participation must be in (0, 1]")
        if self.maximum_liquidation_horizon_days <= 0:
            raise ValueError("maximum liquidation horizon must be positive")
        if not self.allowed_curve_pairs or self.allowed_curve_pairs != tuple(
            sorted(
                set(self.allowed_curve_pairs),
                key=lambda item: (item.curve_role, item.curve_kind.value),
            )
        ):
            raise ValueError("allowed curve pairs must be unique and canonical")
        if not self.allowed_instrument_kinds or self.allowed_instrument_kinds != tuple(
            sorted(set(self.allowed_instrument_kinds))
        ):
            raise ValueError("allowed instrument kinds must be unique and canonical")
        topology_kinds = tuple(item.strategy_kind for item in self.strategy_topologies)
        if (
            not topology_kinds
            or len(topology_kinds) != len(set(topology_kinds))
            or topology_kinds != tuple(sorted(topology_kinds, key=lambda kind: kind.value))
            or set(topology_kinds) != set(CurveStrategyKind)
        ):
            raise ValueError("strategy topologies must cover every kind canonically")
        allowed_pair_set = set(self.allowed_curve_pairs)
        if any(
            leg.curve_pair not in allowed_pair_set
            for topology in self.strategy_topologies
            for leg in topology.legs
        ):
            raise ValueError("strategy topology uses a non-authorized curve pair")
        if self.evidence.role is not EvidenceRole.POLICY:
            raise ValueError("curve policy requires Research evidence")
        if (
            self.evidence.evidence_id != self.policy_id
            or self.evidence.version != self.policy_version
            or self.evidence.subject_id != self.policy_id
            or self.evidence.curve_role != "curve_relative_value_policy"
        ):
            raise ValueError("curve policy evidence identity mismatch")

    @property
    def policy_hash(self) -> str:
        """Hash every topology-adjacent legal pair and quantitative gate."""

        return canonical_hash(
            {
                name: getattr(self, name) if name != "evidence" else self.evidence.seal_hash
                for name in self.__dataclass_fields__
            }
        )


@dataclass(frozen=True)
class CurveRelativeValueEvidence:
    """Exact candidate plus all owner records and unique liquidity cost ledgers."""

    evidence_id: str
    evidence_version: str
    candidate_id: str
    strategy_kind: CurveStrategyKind
    currency: str
    legs: tuple[CurveRelativeValueLeg, ...]
    bond_masters: tuple[BondMasterEvidence, ...]
    cash_flows: tuple[CashFlowEvidence, ...]
    capacities: tuple[DirectionalCapacityEvidence, ...]
    liquidity_capacities: tuple[LiquidityCapacityEvidence, ...]
    liquidity_inputs: tuple[LiquidityPremiumEvidence, ...]
    trading_calendar: CurveTradingCalendarEvidence
    cash_funding: CurveCashFundingEvidence
    source: ExactEvidence

    def __post_init__(self) -> None:
        for name in ("evidence_id", "evidence_version", "candidate_id", "currency"):
            require_token(str(getattr(self, name)), f"CurveRelativeValueEvidence.{name}")
        if not self.legs:
            raise ValueError("curve candidate requires explicit legs")
        if not isinstance(self.strategy_kind, CurveStrategyKind):
            raise ValueError("curve candidate strategy kind is invalid")
        if (
            self.cash_funding.candidate_id != self.candidate_id
            or self.cash_funding.currency != self.currency
        ):
            raise ValueError("cash funding must match candidate id and currency")
        leg_ids = tuple(item.leg_id for item in self.legs)
        master_ids = tuple(item.bond_id for item in self.bond_masters)
        cash_flow_ids = tuple(item.bond_id for item in self.cash_flows)
        capacity_ids = tuple((item.bond_id, item.side.value) for item in self.capacities)
        liquidity_capacity_ids = tuple(
            (item.bond_id, item.side.value) for item in self.liquidity_capacities
        )
        liquidity_input_ids = tuple(item.subject_id for item in self.liquidity_inputs)
        for identities in (
            leg_ids,
            master_ids,
            cash_flow_ids,
            capacity_ids,
            liquidity_capacity_ids,
            liquidity_input_ids,
        ):
            if len(identities) != len(set(identities)):
                raise ValueError("curve evidence collection keys cannot repeat")
            if identities != tuple(sorted(identities)):
                raise ValueError("curve evidence collections must use canonical order")
        expected_liquidity_subjects = tuple(sorted({item.bond_id for item in self.legs}))
        if liquidity_input_ids != expected_liquidity_subjects:
            raise ValueError("curve liquidity inputs must exactly cover the unique leg subjects")
        if self.source.role is not EvidenceRole.FIXED_INCOME_CANDIDATE:
            raise ValueError("curve candidate requires fixed-income candidate evidence")
        if (
            self.source.evidence_id != self.evidence_id
            or self.source.version != self.evidence_version
            or self.source.subject_id != self.candidate_id
            or self.source.currency != self.currency
            or self.source.curve_role != "curve_relative_value"
        ):
            raise ValueError("curve aggregate source identity mismatch")
        required_upstreams = {
            *(leg.raw_leg_hash for leg in self.legs),
            *(item.master_hash for item in self.bond_masters),
            *(item.schedule_hash for item in self.cash_flows),
            *(item.capacity_hash for item in self.capacities),
            *(item.liquidity_hash for item in self.liquidity_capacities),
            *(item.evidence_hash for item in self.liquidity_inputs),
            self.trading_calendar.calendar_hash,
            self.cash_funding.funding_hash,
        }
        if not required_upstreams.issubset(set(self.source.upstream_hashes)):
            raise ValueError("curve aggregate source must attest every child hash")
        if self.source.content_hash != self.raw_manifest_hash:
            raise ValueError("curve aggregate source content hash must equal manifest")

    @property
    def raw_manifest_hash(self) -> str:
        """Hash exact multi-owner children without derived result hashes."""

        return canonical_hash(
            {
                "evidence_id": self.evidence_id,
                "evidence_version": self.evidence_version,
                "candidate_id": self.candidate_id,
                "strategy_kind": self.strategy_kind,
                "currency": self.currency,
                "leg_hashes": tuple(item.raw_leg_hash for item in self.legs),
                "master_hashes": tuple(item.master_hash for item in self.bond_masters),
                "cash_flow_hashes": tuple(item.schedule_hash for item in self.cash_flows),
                "capacity_hashes": tuple(item.capacity_hash for item in self.capacities),
                "liquidity_capacity_hashes": tuple(
                    item.liquidity_hash for item in self.liquidity_capacities
                ),
                "liquidity_input_hashes": tuple(
                    item.evidence_hash for item in self.liquidity_inputs
                ),
                "calendar_hash": self.trading_calendar.calendar_hash,
                "funding_hash": self.cash_funding.funding_hash,
            }
        )

    @property
    def evidence_hash(self) -> str:
        """Hash the raw owner manifest and exact aggregate source seal."""

        return canonical_hash(
            {
                "raw_manifest_hash": self.raw_manifest_hash,
                "source_hash": self.source.seal_hash,
                "leg_hashes": tuple(item.leg_hash for item in self.legs),
            }
        )


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


__all__ = [
    "BondMasterEvidence",
    "CashFlowEvidence",
    "CurveCashFundingEvidence",
    "CurveLegAssessment",
    "CurveLegRole",
    "CurveLegSide",
    "CurveLiquidityResultSeal",
    "CurveRelativeValueAssessment",
    "CurveRelativeValueBlocker",
    "CurveRelativeValueBlockerCode",
    "CurveRelativeValueEvidence",
    "CurveRelativeValueLeg",
    "CurveRelativeValuePolicy",
    "CurveRelativeValueStatus",
    "CurveRoleKindPair",
    "CurveStrategyKind",
    "CurveTradingCalendarEvidence",
    "DirectionalCapacityEvidence",
    "KeyRateAnalytics",
    "KeyRateNeutralityTolerance",
    "LiquidityCapacityEvidence",
    "SignedKeyRateExposure",
    "curve_relative_value_input_hash",
    "evaluate_curve_relative_value",
    "seal_curve_liquidity_results",
]
