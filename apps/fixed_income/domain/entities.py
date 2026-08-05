"""Pure value objects for version-bound fixed-income research."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum


def _require_text(value: str, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} cannot be empty")


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _require_finite(value: Decimal, field_name: str) -> None:
    if not value.is_finite():
        raise ValueError(f"{field_name} must be finite")


def _require_sha256(value: str, field_name: str) -> None:
    if re.fullmatch(r"[0-9a-fA-F]{64}", value) is None:
        raise ValueError(f"{field_name} must be a 64-character hexadecimal SHA-256")


class InputRole(str, Enum):
    """Canonical role of one versioned R5 input."""

    BOND_MASTER = "bond_master"
    CASH_FLOW_SCHEDULE = "cash_flow_schedule"
    TRADING_CALENDAR = "trading_calendar"
    GOVERNMENT_CURVE = "government_curve"
    POLICY_BANK_CURVE = "policy_bank_curve"
    CREDIT_VALUATION = "credit_valuation"
    FUNDING_CURVE = "funding_curve"
    POLICY_RATE = "policy_rate"
    FINANCING_COST = "financing_cost"
    TRANSACTION_COST = "transaction_cost"
    LIQUIDITY_COST = "liquidity_cost"


@dataclass(frozen=True)
class CanonicalPublicationReference:
    """Freshness-bounded reference to one canonical Data Center publication."""

    role: InputRole
    currency: str
    curve_kind: CurveKind | None
    semantic_version: str
    owner: str
    dataset_key: str
    publication_key: str
    publication_id: str
    policy_version: str
    content_hash: str
    observed_at: datetime
    published_at: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        for name in (
            "owner",
            "currency",
            "semantic_version",
            "dataset_key",
            "publication_key",
            "publication_id",
            "policy_version",
            "content_hash",
        ):
            _require_text(str(getattr(self, name)), f"CanonicalPublicationReference.{name}")
        if self.owner != "data_center":
            raise ValueError("canonical fixed-income inputs must be owned by data_center")
        curve_roles = {
            InputRole.GOVERNMENT_CURVE: CurveKind.GOVERNMENT,
            InputRole.POLICY_BANK_CURVE: CurveKind.POLICY_BANK,
            InputRole.CREDIT_VALUATION: CurveKind.CREDIT,
            InputRole.FUNDING_CURVE: CurveKind.FUNDING,
            InputRole.POLICY_RATE: CurveKind.POLICY_RATE,
        }
        expected_curve_kind = curve_roles.get(self.role)
        if self.curve_kind is not expected_curve_kind:
            raise ValueError("canonical publication curve_kind does not match role")
        _require_sha256(self.content_hash, "CanonicalPublicationReference.content_hash")
        _require_aware(self.observed_at, "CanonicalPublicationReference.observed_at")
        _require_aware(self.published_at, "CanonicalPublicationReference.published_at")
        _require_aware(self.valid_until, "CanonicalPublicationReference.valid_until")
        if self.published_at < self.observed_at:
            raise ValueError("published_at cannot precede observed_at")
        if self.valid_until <= self.published_at:
            raise ValueError("valid_until must follow published_at")

    def usability_reason(self, as_of: datetime) -> str | None:
        """Return a stable failure reason, or ``None`` when usable at ``as_of``."""

        _require_aware(as_of, "as_of")
        if self.observed_at > as_of or self.published_at > as_of:
            return "publication_from_future"
        if self.valid_until <= as_of:
            return "publication_stale"
        return None


class DayCountConvention(str, Enum):
    """Supported coupon accrual day-count conventions."""

    ACTUAL_ACTUAL_COUPON = "actual_actual_coupon"
    ACTUAL_365_FIXED = "actual_365_fixed"
    ACTUAL_360 = "actual_360"
    THIRTY_E_360 = "30e_360"


class CashFlowKind(str, Enum):
    """Economic type of a contractual bond cash flow."""

    COUPON = "coupon"
    PRINCIPAL = "principal"
    PRINCIPAL_AND_COUPON = "principal_and_coupon"


@dataclass(frozen=True)
class Bond:
    """Version-bound bond terms without inferred contractual fields."""

    bond_id: str
    currency: str
    face_value: Decimal
    issue_date: date
    maturity_date: date
    annual_coupon_rate: Decimal
    coupon_frequency: int
    day_count_convention: DayCountConvention
    master_reference: CanonicalPublicationReference

    def __post_init__(self) -> None:
        _require_text(self.bond_id, "Bond.bond_id")
        _require_text(self.currency, "Bond.currency")
        _require_finite(self.face_value, "Bond.face_value")
        _require_finite(self.annual_coupon_rate, "Bond.annual_coupon_rate")
        if self.face_value <= 0:
            raise ValueError("Bond.face_value must be positive")
        if self.issue_date >= self.maturity_date:
            raise ValueError("Bond.maturity_date must follow issue_date")
        if self.annual_coupon_rate < 0:
            raise ValueError("Bond.annual_coupon_rate cannot be negative")
        if self.coupon_frequency <= 0:
            raise ValueError("Bond.coupon_frequency must be positive")
        if self.master_reference.role is not InputRole.BOND_MASTER:
            raise ValueError("Bond.master_reference must have bond_master role")


@dataclass(frozen=True)
class CashFlow:
    """One contractual cash flow with an injected settlement time factor."""

    payment_date: date
    amount: Decimal
    time_years: Decimal
    kind: CashFlowKind

    def __post_init__(self) -> None:
        _require_finite(self.amount, "CashFlow.amount")
        _require_finite(self.time_years, "CashFlow.time_years")
        if self.amount <= 0:
            raise ValueError("CashFlow.amount must be positive")
        if self.time_years <= 0:
            raise ValueError("CashFlow.time_years must be positive")


@dataclass(frozen=True)
class AccrualPeriod:
    """Explicit coupon period used to calculate settlement accrued interest."""

    settlement_date: date
    previous_coupon_date: date
    next_coupon_date: date
    coupon_amount: Decimal
    day_count_convention: DayCountConvention

    def __post_init__(self) -> None:
        _require_finite(self.coupon_amount, "AccrualPeriod.coupon_amount")
        if self.previous_coupon_date >= self.next_coupon_date:
            raise ValueError("AccrualPeriod coupon dates are not ordered")
        if not self.previous_coupon_date <= self.settlement_date <= self.next_coupon_date:
            raise ValueError("settlement_date must fall inside the coupon period")
        if self.coupon_amount < 0:
            raise ValueError("AccrualPeriod.coupon_amount cannot be negative")


@dataclass(frozen=True)
class CashFlowSchedule:
    """Settlement-specific cash-flow schedule bound to schedule and calendar versions."""

    bond_id: str
    settlement_date: date
    cash_flows: tuple[CashFlow, ...]
    accrual_period: AccrualPeriod
    schedule_reference: CanonicalPublicationReference
    calendar_reference: CanonicalPublicationReference

    def __post_init__(self) -> None:
        _require_text(self.bond_id, "CashFlowSchedule.bond_id")
        if not self.cash_flows:
            raise ValueError("CashFlowSchedule.cash_flows cannot be empty")
        if self.accrual_period.settlement_date != self.settlement_date:
            raise ValueError("accrual and schedule settlement dates must match")
        if self.schedule_reference.role is not InputRole.CASH_FLOW_SCHEDULE:
            raise ValueError("schedule_reference must have cash_flow_schedule role")
        if self.calendar_reference.role is not InputRole.TRADING_CALENDAR:
            raise ValueError("calendar_reference must have trading_calendar role")
        previous_date: date | None = None
        previous_time: Decimal | None = None
        for cash_flow in self.cash_flows:
            if cash_flow.payment_date <= self.settlement_date:
                raise ValueError("cash flows must follow settlement_date")
            if previous_date is not None and cash_flow.payment_date < previous_date:
                raise ValueError("cash flows must be ordered by payment_date")
            if previous_time is not None and cash_flow.time_years < previous_time:
                raise ValueError("cash-flow time factors must be ordered")
            previous_date = cash_flow.payment_date
            previous_time = cash_flow.time_years


class CurveKind(str, Enum):
    """Fixed-income curve semantics."""

    GOVERNMENT = "government"
    POLICY_BANK = "policy_bank"
    CREDIT = "credit"
    FUNDING = "funding"
    POLICY_RATE = "policy_rate"


class InterpolationMethod(str, Enum):
    """Explicitly selected curve interpolation methodology."""

    LINEAR_ZERO = "linear_zero"


@dataclass(frozen=True)
class CurveNode:
    """One annualized zero-yield observation at a positive tenor."""

    tenor_years: Decimal
    annual_yield: Decimal

    def __post_init__(self) -> None:
        _require_finite(self.tenor_years, "CurveNode.tenor_years")
        _require_finite(self.annual_yield, "CurveNode.annual_yield")
        if self.tenor_years <= 0:
            raise ValueError("CurveNode.tenor_years must be positive")
        if self.annual_yield <= Decimal("-1"):
            raise ValueError("CurveNode.annual_yield must exceed -100%")


_CURVE_INPUT_ROLE: dict[CurveKind, InputRole] = {
    CurveKind.GOVERNMENT: InputRole.GOVERNMENT_CURVE,
    CurveKind.POLICY_BANK: InputRole.POLICY_BANK_CURVE,
    CurveKind.CREDIT: InputRole.CREDIT_VALUATION,
    CurveKind.FUNDING: InputRole.FUNDING_CURVE,
    CurveKind.POLICY_RATE: InputRole.POLICY_RATE,
}


@dataclass(frozen=True)
class YieldCurve:
    """Published yield curve with no implicit interpolation or extrapolation."""

    curve_id: str
    currency: str
    kind: CurveKind
    nodes: tuple[CurveNode, ...]
    interpolation: InterpolationMethod
    reference: CanonicalPublicationReference

    def __post_init__(self) -> None:
        _require_text(self.curve_id, "YieldCurve.curve_id")
        _require_text(self.currency, "YieldCurve.currency")
        if len(self.nodes) < 2:
            raise ValueError("YieldCurve requires at least two nodes")
        if self.reference.role is not _CURVE_INPUT_ROLE[self.kind]:
            raise ValueError("YieldCurve reference role does not match curve kind")
        if self.reference.curve_kind is not self.kind:
            raise ValueError("YieldCurve reference semantic curve kind does not match")
        if self.reference.currency != self.currency:
            raise ValueError("YieldCurve reference currency does not match curve currency")
        tenors = tuple(node.tenor_years for node in self.nodes)
        if tenors != tuple(sorted(tenors)) or len(set(tenors)) != len(tenors):
            raise ValueError("YieldCurve nodes must have unique ascending tenors")


@dataclass(frozen=True)
class YieldSolverSpec:
    """Explicit numerical policy for solving yield from dirty price."""

    lower_bound: Decimal
    upper_bound: Decimal
    price_tolerance: Decimal
    yield_tolerance: Decimal
    max_iterations: int

    def __post_init__(self) -> None:
        for name in (
            "lower_bound",
            "upper_bound",
            "price_tolerance",
            "yield_tolerance",
        ):
            _require_finite(getattr(self, name), f"YieldSolverSpec.{name}")
        if self.lower_bound >= self.upper_bound:
            raise ValueError("yield solver bounds are not ordered")
        if self.price_tolerance <= 0 or self.yield_tolerance <= 0:
            raise ValueError("yield solver tolerances must be positive")
        if self.max_iterations <= 0:
            raise ValueError("yield solver max_iterations must be positive")


@dataclass(frozen=True)
class CarryInputs:
    """All cash and cost inputs needed for a research carry estimate."""

    start_date: date
    end_date: date
    start_dirty_price: Decimal
    coupon_cash_received: Decimal
    start_accrued_interest: Decimal
    end_accrued_interest: Decimal
    financing_cost: Decimal
    transaction_cost: Decimal
    liquidity_cost: Decimal
    financing_reference: CanonicalPublicationReference
    transaction_cost_reference: CanonicalPublicationReference
    liquidity_reference: CanonicalPublicationReference
    calendar_reference: CanonicalPublicationReference

    def __post_init__(self) -> None:
        for name in (
            "start_dirty_price",
            "coupon_cash_received",
            "start_accrued_interest",
            "end_accrued_interest",
            "financing_cost",
            "transaction_cost",
            "liquidity_cost",
        ):
            _require_finite(getattr(self, name), f"CarryInputs.{name}")
        if self.start_date >= self.end_date:
            raise ValueError("carry end_date must follow start_date")
        if self.start_dirty_price <= 0:
            raise ValueError("carry start_dirty_price must be positive")
        for name in (
            "coupon_cash_received",
            "start_accrued_interest",
            "end_accrued_interest",
            "financing_cost",
            "transaction_cost",
            "liquidity_cost",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"CarryInputs.{name} cannot be negative")
        expected_roles = (
            (self.financing_reference, InputRole.FINANCING_COST),
            (self.transaction_cost_reference, InputRole.TRANSACTION_COST),
            (self.liquidity_reference, InputRole.LIQUIDITY_COST),
            (self.calendar_reference, InputRole.TRADING_CALENDAR),
        )
        if any(reference.role is not role for reference, role in expected_roles):
            raise ValueError("carry input reference role mismatch")


@dataclass(frozen=True)
class FixedIncomeResearchInputs:
    """Explicitly optional inputs so Application can report every missing gate."""

    bond: Bond | None
    schedule: CashFlowSchedule | None
    government_curve: YieldCurve | None
    policy_bank_curve: YieldCurve | None
    credit_curve: YieldCurve | None
    carry_inputs: CarryInputs | None
    market_dirty_price: Decimal | None
    roll_down_horizon_years: Decimal | None

    def __post_init__(self) -> None:
        for name in ("market_dirty_price", "roll_down_horizon_years"):
            value = getattr(self, name)
            if value is not None:
                _require_finite(value, f"FixedIncomeResearchInputs.{name}")


@dataclass(frozen=True)
class AnalyticsReconciliationSpec:
    """Versioned manual or third-party golden benchmark and tolerances."""

    benchmark_id: str
    benchmark_version: str
    evidence_hash: str
    expected_dirty_price: Decimal
    expected_macaulay_duration: Decimal
    expected_modified_duration: Decimal
    expected_convexity: Decimal
    price_tolerance: Decimal
    duration_tolerance: Decimal
    convexity_tolerance: Decimal

    def __post_init__(self) -> None:
        for name in ("benchmark_id", "benchmark_version", "evidence_hash"):
            _require_text(str(getattr(self, name)), f"AnalyticsReconciliationSpec.{name}")
        _require_sha256(self.evidence_hash, "AnalyticsReconciliationSpec.evidence_hash")
        for name in (
            "expected_dirty_price",
            "expected_macaulay_duration",
            "expected_modified_duration",
            "expected_convexity",
            "price_tolerance",
            "duration_tolerance",
            "convexity_tolerance",
        ):
            _require_finite(getattr(self, name), f"AnalyticsReconciliationSpec.{name}")
        if self.expected_dirty_price <= 0:
            raise ValueError("expected_dirty_price must be positive")
        if self.expected_macaulay_duration < 0 or self.expected_modified_duration < 0:
            raise ValueError("expected duration cannot be negative")
        if self.expected_convexity < 0:
            raise ValueError("expected convexity cannot be negative")
        for name in ("price_tolerance", "duration_tolerance", "convexity_tolerance"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} cannot be negative")


@dataclass(frozen=True)
class BondAnalytics:
    """Price, yield and interest-rate risk measures for one bond snapshot."""

    dirty_price: Decimal
    accrued_interest: Decimal
    clean_price: Decimal
    annual_yield: Decimal
    macaulay_duration_years: Decimal
    modified_duration_years: Decimal
    convexity_years_squared: Decimal

    def __post_init__(self) -> None:
        for name in (
            "dirty_price",
            "accrued_interest",
            "clean_price",
            "annual_yield",
            "macaulay_duration_years",
            "modified_duration_years",
            "convexity_years_squared",
        ):
            _require_finite(getattr(self, name), f"BondAnalytics.{name}")
        if self.dirty_price <= 0:
            raise ValueError("BondAnalytics.dirty_price must be positive")
        if self.accrued_interest < 0:
            raise ValueError("BondAnalytics.accrued_interest cannot be negative")
        if self.macaulay_duration_years < 0 or self.modified_duration_years < 0:
            raise ValueError("BondAnalytics duration cannot be negative")
        if self.convexity_years_squared < 0:
            raise ValueError("BondAnalytics convexity cannot be negative")


@dataclass(frozen=True)
class CarryEstimate:
    """Research carry after all explicitly supplied costs."""

    carry_amount: Decimal
    carry_return: Decimal

    def __post_init__(self) -> None:
        _require_finite(self.carry_amount, "CarryEstimate.carry_amount")
        _require_finite(self.carry_return, "CarryEstimate.carry_return")


@dataclass(frozen=True)
class RollDownEstimate:
    """Duration-convexity roll-down approximation on one unchanged curve."""

    current_tenor_years: Decimal
    residual_tenor_years: Decimal
    current_yield: Decimal
    residual_yield: Decimal
    yield_change: Decimal
    estimated_price_return: Decimal

    def __post_init__(self) -> None:
        for name in (
            "current_tenor_years",
            "residual_tenor_years",
            "current_yield",
            "residual_yield",
            "yield_change",
            "estimated_price_return",
        ):
            _require_finite(getattr(self, name), f"RollDownEstimate.{name}")
        if self.current_tenor_years <= 0 or self.residual_tenor_years <= 0:
            raise ValueError("RollDownEstimate tenors must be positive")


@dataclass(frozen=True)
class RelativeValueMetrics:
    """Non-prescriptive relative-value metrics for a research preview."""

    credit_spread_bp: Decimal
    policy_bank_spread_bp: Decimal
    government_tenor_spread_bp: Decimal
    carry: CarryEstimate
    roll_down: RollDownEstimate

    def __post_init__(self) -> None:
        _require_finite(self.credit_spread_bp, "RelativeValueMetrics.credit_spread_bp")
        _require_finite(
            self.policy_bank_spread_bp,
            "RelativeValueMetrics.policy_bank_spread_bp",
        )
        _require_finite(
            self.government_tenor_spread_bp,
            "RelativeValueMetrics.government_tenor_spread_bp",
        )


@dataclass(frozen=True)
class AnalyticsReconciliationResult:
    """Field-level comparison with the injected golden benchmark."""

    benchmark_id: str
    benchmark_version: str
    is_reconciled: bool
    failed_fields: tuple[str, ...]


class ResearchPreviewStatus(str, Enum):
    """Stable status of the internal fixed-income research preview."""

    AVAILABLE = "available"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class FixedIncomeResearchPreview:
    """Internal research result that is never an execution instruction."""

    status: ResearchPreviewStatus
    method_version: str
    bond_id: str | None
    valuation_at: datetime
    analytics: BondAnalytics | None
    relative_value: RelativeValueMetrics | None
    reconciliation: AnalyticsReconciliationResult | None
    publication_ids: tuple[str, ...]
    blocked_reasons: tuple[str, ...]
    research_only: bool
    must_not_execute: bool
    must_not_use_for_decision: bool

    def __post_init__(self) -> None:
        _require_text(self.method_version, "FixedIncomeResearchPreview.method_version")
        _require_aware(self.valuation_at, "FixedIncomeResearchPreview.valuation_at")
        if (
            not self.research_only
            or not self.must_not_execute
            or not self.must_not_use_for_decision
        ):
            raise ValueError("fixed-income previews must remain research-only and non-executable")
        if self.status is ResearchPreviewStatus.BLOCKED and not self.blocked_reasons:
            raise ValueError("blocked preview requires blocked_reasons")
        if self.status is ResearchPreviewStatus.AVAILABLE and self.blocked_reasons:
            raise ValueError("available preview cannot contain blocked_reasons")


@dataclass(frozen=True)
class PublicationInputSeal:
    """Minimal immutable identity/hash evidence for one canonical publication."""

    dataset_key: str
    publication_key: str
    publication_id: str
    policy_version: str
    semantic_version: str
    content_hash: str

    def __post_init__(self) -> None:
        for name in (
            "dataset_key",
            "publication_key",
            "publication_id",
            "policy_version",
            "semantic_version",
        ):
            _require_text(str(getattr(self, name)), f"PublicationInputSeal.{name}")
        _require_sha256(self.content_hash, "PublicationInputSeal.content_hash")

    @classmethod
    def from_reference(
        cls,
        reference: CanonicalPublicationReference,
    ) -> PublicationInputSeal:
        """Project the real Data Center publication identity into persistence."""

        return cls(
            dataset_key=reference.dataset_key,
            publication_key=reference.publication_key,
            publication_id=reference.publication_id,
            policy_version=reference.policy_version,
            semantic_version=reference.semantic_version,
            content_hash=reference.content_hash,
        )


@dataclass(frozen=True)
class ImmutableResearchResult:
    """Canonical immutable payload passed from Application to persistence."""

    result_id: str
    bond_id: str
    valuation_at: datetime
    settlement_date: date
    method_version: str
    input_hash: str
    output_hash: str
    status: ResearchPreviewStatus
    payload_json: str
    publication_seals: tuple[PublicationInputSeal, ...]
    blocked_reasons: tuple[str, ...]
    research_only: bool
    must_not_execute: bool
    must_not_use_for_decision: bool

    def __post_init__(self) -> None:
        for name in (
            "result_id",
            "bond_id",
            "method_version",
            "input_hash",
            "output_hash",
            "payload_json",
        ):
            _require_text(str(getattr(self, name)), f"ImmutableResearchResult.{name}")
        _require_aware(self.valuation_at, "ImmutableResearchResult.valuation_at")
        _require_sha256(self.input_hash, "ImmutableResearchResult.input_hash")
        _require_sha256(self.output_hash, "ImmutableResearchResult.output_hash")
        if (
            not self.research_only
            or not self.must_not_execute
            or not self.must_not_use_for_decision
        ):
            raise ValueError("persisted fixed-income results must be non-executable research")
        payload = json.loads(self.payload_json)
        if not isinstance(payload, dict):
            raise ValueError("payload_json must encode an object")
        if not self.publication_seals:
            raise ValueError("persisted result requires publication_seals")
        if len(self.publication_ids) != len(set(self.publication_ids)):
            raise ValueError("publication seals cannot contain duplicate publication ids")
        if self.input_hash.lower() != self.calculated_input_hash:
            raise ValueError("fixed-income research result input_hash mismatch")
        if self.output_hash.lower() != self.calculated_output_hash:
            raise ValueError("fixed-income research result output_hash mismatch")
        if self.status is ResearchPreviewStatus.BLOCKED and not self.blocked_reasons:
            raise ValueError("blocked persisted result requires blocked_reasons")
        if self.status is ResearchPreviewStatus.AVAILABLE and self.blocked_reasons:
            raise ValueError("available persisted result cannot contain blocked_reasons")

    @property
    def publication_ids(self) -> tuple[str, ...]:
        """Return stable publication identities sealed into the input hash."""

        return tuple(seal.publication_id for seal in self.publication_seals)

    @property
    def calculated_input_hash(self) -> str:
        """Recompute the canonical input digest from real publication evidence."""

        return fixed_income_research_input_hash(
            bond_id=self.bond_id,
            valuation_at=self.valuation_at,
            settlement_date=self.settlement_date,
            method_version=self.method_version,
            publication_seals=self.publication_seals,
        )

    @property
    def calculated_output_hash(self) -> str:
        """Recompute the canonical result digest from its complete output payload."""

        return fixed_income_research_output_hash(
            result_id=self.result_id,
            input_hash=self.input_hash,
            status=self.status,
            payload_json=self.payload_json,
            blocked_reasons=self.blocked_reasons,
            research_only=self.research_only,
            must_not_execute=self.must_not_execute,
            must_not_use_for_decision=self.must_not_use_for_decision,
        )

    @classmethod
    def build(
        cls,
        *,
        result_id: str,
        bond_id: str,
        valuation_at: datetime,
        settlement_date: date,
        method_version: str,
        status: ResearchPreviewStatus,
        payload_json: str,
        publication_seals: tuple[PublicationInputSeal, ...],
        blocked_reasons: tuple[str, ...],
    ) -> ImmutableResearchResult:
        """Build a triple-blocked immutable result with canonical hashes."""

        input_hash = fixed_income_research_input_hash(
            bond_id=bond_id,
            valuation_at=valuation_at,
            settlement_date=settlement_date,
            method_version=method_version,
            publication_seals=publication_seals,
        )
        output_hash = fixed_income_research_output_hash(
            result_id=result_id,
            input_hash=input_hash,
            status=status,
            payload_json=payload_json,
            blocked_reasons=blocked_reasons,
            research_only=True,
            must_not_execute=True,
            must_not_use_for_decision=True,
        )
        return cls(
            result_id=result_id,
            bond_id=bond_id,
            valuation_at=valuation_at,
            settlement_date=settlement_date,
            method_version=method_version,
            input_hash=input_hash,
            output_hash=output_hash,
            status=status,
            payload_json=payload_json,
            publication_seals=publication_seals,
            blocked_reasons=blocked_reasons,
            research_only=True,
            must_not_execute=True,
            must_not_use_for_decision=True,
        )


def fixed_income_research_input_hash(
    *,
    bond_id: str,
    valuation_at: datetime,
    settlement_date: date,
    method_version: str,
    publication_seals: tuple[PublicationInputSeal, ...],
) -> str:
    """Hash method/as-of scope and exact canonical publication ids and hashes."""

    publication_payload = [
        {
            "dataset_key": seal.dataset_key,
            "publication_key": seal.publication_key,
            "publication_id": seal.publication_id,
            "policy_version": seal.policy_version,
            "semantic_version": seal.semantic_version,
            "content_hash": seal.content_hash.lower(),
        }
        for seal in sorted(
            publication_seals,
            key=lambda item: (item.dataset_key, item.publication_id),
        )
    ]
    payload = {
        "bond_id": bond_id,
        "valuation_at": valuation_at.isoformat(),
        "settlement_date": settlement_date.isoformat(),
        "method_version": method_version,
        "publications": publication_payload,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def fixed_income_research_output_hash(
    *,
    result_id: str,
    input_hash: str,
    status: ResearchPreviewStatus,
    payload_json: str,
    blocked_reasons: tuple[str, ...],
    research_only: bool,
    must_not_execute: bool,
    must_not_use_for_decision: bool,
) -> str:
    """Hash the canonical result payload and all non-decision safety flags."""

    parsed_payload = json.loads(payload_json)
    if not isinstance(parsed_payload, dict):
        raise ValueError("payload_json must encode an object")
    payload = {
        "result_id": result_id,
        "input_hash": input_hash.lower(),
        "status": status.value,
        "payload": parsed_payload,
        "blocked_reasons": list(blocked_reasons),
        "research_only": research_only,
        "must_not_execute": must_not_execute,
        "must_not_use_for_decision": must_not_use_for_decision,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
