"""Input contracts for signed curve-relative-value research portfolios."""

from __future__ import annotations

from dataclasses import dataclass
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
    LiquidityPremiumEvidence,
)


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
