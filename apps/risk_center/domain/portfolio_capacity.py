"""Source-qualified, gross portfolio capacity rules for simulated trading."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from fractions import Fraction
from typing import Literal

from apps.risk_center.domain.portfolio_risk_sources import (
    CoverageStatus,
    PortfolioRiskSourceEvidence,
    SourceObservationPrecision,
    qualify_portfolio_risk_source,
)

CapacityMeasure = Literal["volume", "amount"]
CapacityWindowKind = Literal["session_cumulative", "rolling_sessions"]
CapacityBasis = Literal["session_total", "average_per_session"]
CapacityUsageScope = Literal["account_security_session"]
CapacityUsageDateBasis = Literal["execution_session"]
CapacityDecisionStatus = Literal["allowed", "partial", "blocked", "unknown"]
OrderSide = Literal["buy", "sell"]


@dataclass(frozen=True, slots=True)
class CapacityValue:
    """One exact nonnegative amount and its explicit canonical unit, or unknown."""

    value: Decimal | None
    unit: str | None

    def __post_init__(self) -> None:
        """Reject floats, negative capacity and values without a unit."""

        if (self.value is None) != (self.unit is None):
            raise ValueError("capacity value and unit must both be present or both be absent")
        if self.value is not None:
            if type(self.value) is not Decimal or not self.value.is_finite() or self.value < 0:
                raise ValueError("capacity value must be an exact nonnegative Decimal")
            if type(self.unit) is not str or not self.unit or self.unit.strip() != self.unit:
                raise ValueError("capacity unit must be an explicit canonical token")
            if any(character.isspace() for character in self.unit):
                raise ValueError("capacity unit cannot contain whitespace")


@dataclass(frozen=True, slots=True)
class CapacityWindowObservation:
    """One source-bound liquidity observation over an explicit market lookback."""

    asset_code: str
    security_id: str
    window_kind: CapacityWindowKind
    window_start: date
    window_end: date
    window_sessions: int
    volume: CapacityValue
    amount: CapacityValue
    execution_session_suspended: bool | None
    execution_session_state_date: date | None
    execution_session_state_evidence: PortfolioRiskSourceEvidence | None
    source_evidence: PortfolioRiskSourceEvidence

    def __post_init__(self) -> None:
        """Validate identities, exact date bounds and window semantics."""

        _require_token(self.asset_code, "asset_code")
        _require_token(self.security_id, "security_id")
        _require_date(self.window_start, "window_start")
        _require_date(self.window_end, "window_end")
        if self.window_end < self.window_start:
            raise ValueError("capacity window end cannot precede start")
        if type(self.window_sessions) is not int or self.window_sessions < 1:
            raise ValueError("window_sessions must be a positive exact integer")
        if self.window_kind == "session_cumulative":
            if self.window_sessions != 1 or self.window_start != self.window_end:
                raise ValueError("session_cumulative must identify exactly one session date")
        elif self.window_kind == "rolling_sessions":
            if self.window_sessions < 2:
                raise ValueError("rolling_sessions must contain at least two sessions")
        else:
            raise ValueError("window_kind must be a supported capacity window")
        if type(self.volume) is not CapacityValue or type(self.amount) is not CapacityValue:
            raise TypeError("volume and amount must be CapacityValue instances")
        if (
            self.execution_session_suspended is not None
            and type(self.execution_session_suspended) is not bool
        ):
            raise TypeError("execution_session_suspended must be a boolean or None")
        if self.execution_session_state_date is not None:
            _require_date(self.execution_session_state_date, "execution_session_state_date")
        if (
            self.execution_session_state_evidence is not None
            and type(self.execution_session_state_evidence) is not PortfolioRiskSourceEvidence
        ):
            raise TypeError(
                "execution_session_state_evidence must be PortfolioRiskSourceEvidence or None"
            )
        if type(self.source_evidence) is not PortfolioRiskSourceEvidence:
            raise TypeError("source_evidence must be PortfolioRiskSourceEvidence")


@dataclass(frozen=True, slots=True)
class CapacityParticipationPolicy:
    """Versioned participation limit and explicit source-window policy."""

    policy_id: str
    version: str
    content_hash: str
    measure: CapacityMeasure
    unit: str
    capacity_basis: CapacityBasis
    usage_scope: CapacityUsageScope
    usage_date_basis: CapacityUsageDateBasis
    max_participation: Decimal
    capacity_increment: Decimal
    window_kind: CapacityWindowKind
    window_sessions: int
    effective_from: datetime
    effective_until: datetime | None
    known_at: datetime
    allowed_observation_precisions: tuple[SourceObservationPrecision, ...]
    date_precision_purposes: tuple[str, ...]
    allowed_source_restrictions: tuple[str, ...]

    def __post_init__(self) -> None:
        """Require a hashed, current policy with exact units and source precision."""

        for field_name, value in (
            ("policy_id", self.policy_id),
            ("version", self.version),
            ("unit", self.unit),
        ):
            _require_token(value, field_name)
        if len(self.content_hash) != 64 or any(
            character not in "0123456789abcdef" for character in self.content_hash
        ):
            raise ValueError("content_hash must be a lowercase SHA-256 digest")
        if self.measure not in ("volume", "amount"):
            raise ValueError("measure must be volume or amount")
        if self.capacity_basis not in ("session_total", "average_per_session"):
            raise ValueError("capacity_basis must be explicitly supported")
        if self.usage_scope != "account_security_session":
            raise ValueError("usage_scope must be account_security_session")
        if self.usage_date_basis != "execution_session":
            raise ValueError("usage_date_basis must be execution_session")
        _require_fraction(self.max_participation, "max_participation")
        if (
            type(self.capacity_increment) is not Decimal
            or not self.capacity_increment.is_finite()
            or self.capacity_increment <= 0
        ):
            raise ValueError("capacity_increment must be a positive exact Decimal")
        if self.window_kind not in ("session_cumulative", "rolling_sessions"):
            raise ValueError("window_kind must be a supported capacity window")
        if type(self.window_sessions) is not int or self.window_sessions < 1:
            raise ValueError("window_sessions must be a positive exact integer")
        if self.window_kind == "session_cumulative" and self.window_sessions != 1:
            raise ValueError("session_cumulative policy must declare one session")
        if self.window_kind == "rolling_sessions" and self.window_sessions < 2:
            raise ValueError("rolling_sessions policy must declare at least two sessions")
        if self.window_kind == "session_cumulative" and self.capacity_basis != "session_total":
            raise ValueError("session_cumulative requires the session_total capacity basis")
        if self.window_kind == "rolling_sessions" and self.capacity_basis != "average_per_session":
            raise ValueError("rolling_sessions requires average_per_session capacity basis")
        _require_aware(self.effective_from, "effective_from")
        _require_aware(self.known_at, "known_at")
        if self.effective_until is not None:
            _require_aware(self.effective_until, "effective_until")
            if self.effective_until < self.effective_from:
                raise ValueError("effective_until cannot precede effective_from")
        if type(self.allowed_observation_precisions) is not tuple or not (
            self.allowed_observation_precisions
        ):
            raise ValueError("allowed_observation_precisions must be a nonempty tuple")
        if any(
            not isinstance(precision, SourceObservationPrecision)
            for precision in self.allowed_observation_precisions
        ):
            raise TypeError("allowed_observation_precisions contains an invalid precision")
        if type(self.date_precision_purposes) is not tuple:
            raise TypeError("date_precision_purposes must be a tuple")
        if len(self.date_precision_purposes) != len(set(self.date_precision_purposes)):
            raise ValueError("date_precision_purposes cannot contain duplicate tokens")
        for purpose in self.date_precision_purposes:
            _require_token(purpose, "date_precision_purposes")
        if type(self.allowed_source_restrictions) is not tuple:
            raise TypeError("allowed_source_restrictions must be a tuple")
        if len(self.allowed_source_restrictions) != len(set(self.allowed_source_restrictions)):
            raise ValueError("allowed_source_restrictions cannot contain duplicate tokens")
        for restriction in self.allowed_source_restrictions:
            _require_token(restriction, "allowed_source_restrictions")
            if _is_unconditionally_prohibited_restriction(restriction):
                raise ValueError("policy cannot allow an unconditional source prohibition")


@dataclass(frozen=True, slots=True)
class CapacityOrderUsage:
    """One order's remaining or proposed gross use in both supported measures."""

    order_id: str
    account_id: int
    asset_code: str
    security_id: str
    side: OrderSide
    volume: CapacityValue
    amount: CapacityValue

    def __post_init__(self) -> None:
        """Validate order identity and explicit remaining/proposed measures."""

        _require_token(self.order_id, "order_id")
        if type(self.account_id) is not int or self.account_id < 1:
            raise ValueError("account_id must be a positive exact integer")
        _require_token(self.asset_code, "asset_code")
        _require_token(self.security_id, "security_id")
        if self.side not in ("buy", "sell"):
            raise ValueError("side must be buy or sell")
        if type(self.volume) is not CapacityValue or type(self.amount) is not CapacityValue:
            raise TypeError("order measures must be CapacityValue instances")


@dataclass(frozen=True, slots=True)
class CapacityUsageSnapshot:
    """Actual current-session use plus active holds and proposed orders for one scope."""

    account_id: int
    security_id: str
    asset_code: str
    capacity_date: date
    snapshot_read_at: datetime
    volume: CapacityValue
    amount: CapacityValue
    executed_usage_complete: bool
    active_orders_complete: bool
    active_orders: tuple[CapacityOrderUsage, ...]
    proposed_orders: tuple[CapacityOrderUsage, ...]

    def __post_init__(self) -> None:
        """Bind use to one account/security/session without supplying missing zeroes."""

        if type(self.account_id) is not int or self.account_id < 1:
            raise ValueError("account_id must be a positive exact integer")
        _require_token(self.security_id, "security_id")
        _require_token(self.asset_code, "asset_code")
        _require_date(self.capacity_date, "capacity_date")
        _require_aware(self.snapshot_read_at, "snapshot_read_at")
        if type(self.volume) is not CapacityValue or type(self.amount) is not CapacityValue:
            raise TypeError("executed volume and amount must be CapacityValue instances")
        if type(self.executed_usage_complete) is not bool:
            raise TypeError("executed_usage_complete must be a boolean")
        if type(self.active_orders_complete) is not bool:
            raise TypeError("active_orders_complete must be a boolean")
        if type(self.active_orders) is not tuple or type(self.proposed_orders) is not tuple:
            raise TypeError("active_orders and proposed_orders must be tuples")
        all_orders = (*self.active_orders, *self.proposed_orders)
        if any(type(order) is not CapacityOrderUsage for order in all_orders):
            raise TypeError("order collections must contain CapacityOrderUsage values")


@dataclass(frozen=True, slots=True)
class PortfolioCapacityDecision:
    """A decision and the exact source, policy, account and capacity basis used."""

    status: CapacityDecisionStatus
    reason_codes: tuple[str, ...]
    account_id: int
    asset_code: str
    security_id: str
    business_date: date
    capacity_date: date
    snapshot_read_at: datetime
    executed_usage_complete: bool
    active_orders_complete: bool
    source_id: str
    source_record_id: str
    source_payload_sha256: str | None
    source_observation_precision: SourceObservationPrecision
    source_observed_at: datetime | None
    source_observed_on: date | None
    source_available_at: datetime | None
    source_known_at: datetime | None
    source_decision_cutoff: datetime
    source_decision_date_cutoff: date | None
    source_valid_until: datetime | None
    source_effective_on: date | None
    source_effective_until: date | None
    source_purpose: str
    source_allowed_purposes: tuple[str, ...]
    source_restrictions: tuple[str, ...]
    source_must_not_use_for_decision: bool
    source_coverage_status: CoverageStatus
    source_coverage_precision_basis: str
    source_coverage_reported_weight_fraction: Decimal | None
    source_coverage_expected_item_count: int | None
    source_coverage_observed_item_count: int | None
    execution_session_state_date: date | None
    execution_session_suspended: bool | None
    execution_session_state_evidence: PortfolioRiskSourceEvidence | None
    decision_as_of: datetime
    source_window_start: date
    source_window_end: date
    source_window_sessions: int
    policy_id: str | None
    policy_version: str | None
    policy_content_hash: str | None
    measure: CapacityMeasure | None
    unit: str | None
    capacity_basis: CapacityBasis | None
    usage_scope: CapacityUsageScope | None
    usage_date_basis: CapacityUsageDateBasis | None
    policy_date_precision_purposes: tuple[str, ...] | None
    policy_allowed_source_restrictions: tuple[str, ...] | None
    window_capacity: Decimal | None
    used_capacity: Decimal | None
    reserved_buy_capacity: Decimal | None
    reserved_sell_capacity: Decimal | None
    proposed_capacity: Decimal | None
    remaining_capacity: Decimal | None
    allowed_new_capacity: Decimal | None

    def __post_init__(self) -> None:
        """Require stable blockers and keep all published numeric values exact."""

        if self.status not in ("allowed", "partial", "blocked", "unknown"):
            raise ValueError("status must be a supported capacity result")
        if type(self.reason_codes) is not tuple or any(
            type(reason) is not str or not reason.strip() for reason in self.reason_codes
        ):
            raise ValueError("reason_codes must be a tuple of stable nonempty codes")
        if (
            self.execution_session_state_date is not None
            and type(self.execution_session_state_date) is not date
        ):
            raise TypeError("execution_session_state_date must be a date or None")
        if (
            self.execution_session_suspended is not None
            and type(self.execution_session_suspended) is not bool
        ):
            raise TypeError("execution_session_suspended must be a boolean or None")
        if (
            self.execution_session_state_evidence is not None
            and type(self.execution_session_state_evidence) is not PortfolioRiskSourceEvidence
        ):
            raise TypeError(
                "execution_session_state_evidence must be PortfolioRiskSourceEvidence or None"
            )
        for field_name in (
            "window_capacity",
            "used_capacity",
            "reserved_buy_capacity",
            "reserved_sell_capacity",
            "proposed_capacity",
            "remaining_capacity",
            "allowed_new_capacity",
        ):
            value = getattr(self, field_name)
            if value is not None and (type(value) is not Decimal or not value.is_finite()):
                raise ValueError(f"{field_name} must be an exact Decimal or None")


def evaluate_portfolio_capacity(
    *,
    observation: CapacityWindowObservation,
    policy: CapacityParticipationPolicy | None,
    usage: CapacityUsageSnapshot,
    requested_purpose: str,
    business_date: date,
    as_of: datetime,
) -> PortfolioCapacityDecision:
    """Evaluate one security's per-session gross use against a source-bound cap.

    Rolling source liquidity is averaged across the explicitly reported number of
    sessions. Current-session executed use, active remaining BUY/SELL orders, and
    proposed orders are then added gross. The function never nets sides, infers
    missing usage as zero, or treats a preview expiration as an order release.
    The lookback's market source never doubles as execution-session trading-state
    evidence; the latter has its own source clocks and effective session date.
    Date-precision source cutoffs bind to the caller's business date, while usage
    remains scoped to the separately declared execution session.
    Its capacity values describe market throughput only; they do not alter account
    cash, withdrawable cash, securities settlement, or T+1 treatment.
    """

    _require_aware(as_of, "as_of")
    _require_date(business_date, "business_date")
    blockers: list[str] = []
    source = observation.source_evidence
    qualification = None
    if policy is None:
        blockers.append("CAPACITY_POLICY_UNCONFIGURED")
    else:
        qualification = qualify_portfolio_risk_source(
            evidence=source,
            requested_purpose=requested_purpose,
            allowed_observation_precisions=policy.allowed_observation_precisions,
            as_of=as_of,
            allowed_restrictions=policy.allowed_source_restrictions,
        )
        blockers.extend(qualification.reason_codes)
        if as_of < policy.effective_from or policy.known_at > as_of:
            blockers.append("CAPACITY_POLICY_NOT_CURRENT_AT_CUTOFF")
        if policy.effective_until is not None and as_of >= policy.effective_until:
            blockers.append("CAPACITY_POLICY_EXPIRED")
        if (
            policy.window_kind != observation.window_kind
            or policy.window_sessions != observation.window_sessions
        ):
            blockers.append("CAPACITY_WINDOW_POLICY_MISMATCH")
        if source.observation_precision is SourceObservationPrecision.DATE:
            if requested_purpose not in policy.date_precision_purposes:
                blockers.append("CAPACITY_DATE_PRECISION_PURPOSE_NOT_ALLOWED")
            if source.decision_date_cutoff != business_date:
                blockers.append("CAPACITY_DATE_CUTOFF_MISMATCH")
        state_evidence = observation.execution_session_state_evidence
        state_date = observation.execution_session_state_date
        if state_evidence is None or state_date is None:
            blockers.append("CAPACITY_TRADING_STATUS_EVIDENCE_MISSING")
        else:
            state_qualification = qualify_portfolio_risk_source(
                evidence=state_evidence,
                requested_purpose=requested_purpose,
                allowed_observation_precisions=policy.allowed_observation_precisions,
                as_of=as_of,
                allowed_restrictions=policy.allowed_source_restrictions,
            )
            blockers.extend(state_qualification.reason_codes)
            if state_date != usage.capacity_date:
                blockers.append("CAPACITY_TRADING_STATUS_SESSION_DATE_MISMATCH")
            if state_date > business_date:
                blockers.append("CAPACITY_TRADING_STATUS_FUTURE_SESSION")
            if state_evidence.effective_on != state_date:
                blockers.append("CAPACITY_TRADING_STATUS_EFFECTIVE_DATE_MISMATCH")
            if state_evidence.coverage.status is not CoverageStatus.COMPLETE:
                blockers.append("CAPACITY_TRADING_STATUS_COVERAGE_INCOMPLETE")
            if state_evidence.observation_precision is SourceObservationPrecision.DATE:
                if requested_purpose not in policy.date_precision_purposes:
                    blockers.append("CAPACITY_TRADING_STATUS_DATE_PRECISION_NOT_ALLOWED")
                if state_evidence.observed_on != state_date:
                    blockers.append("CAPACITY_TRADING_STATUS_OBSERVATION_DATE_MISMATCH")
                if state_evidence.decision_date_cutoff != business_date:
                    blockers.append("CAPACITY_TRADING_STATUS_DATE_CUTOFF_MISMATCH")

    if observation.source_evidence.effective_on is not None:
        if observation.source_evidence.effective_on != observation.window_end:
            blockers.append("CAPACITY_SOURCE_EFFECTIVE_DATE_MISMATCH")
    if (
        source.observation_precision is SourceObservationPrecision.DATE
        and source.observed_on != observation.window_end
    ):
        blockers.append("CAPACITY_SOURCE_OBSERVATION_DATE_MISMATCH")
    if observation.source_evidence.effective_until is not None:
        if observation.source_evidence.effective_until < observation.window_end:
            blockers.append("CAPACITY_SOURCE_EFFECTIVE_DATE_MISMATCH")
    if observation.window_kind == "rolling_sessions":
        if observation.window_end >= usage.capacity_date:
            blockers.append("CAPACITY_LOOKBACK_NOT_BEFORE_EXECUTION_SESSION")
    elif observation.window_start != usage.capacity_date:
        blockers.append("CAPACITY_SESSION_SOURCE_DATE_MISMATCH")
    if observation.source_evidence.coverage.status.value != "complete":
        blockers.append("CAPACITY_WINDOW_COVERAGE_INCOMPLETE")
    if usage.security_id != observation.security_id or usage.asset_code != observation.asset_code:
        blockers.append("CAPACITY_USAGE_SCOPE_MISMATCH")
    if usage.snapshot_read_at > as_of:
        blockers.append("CAPACITY_USAGE_AFTER_CUTOFF")
    if not usage.executed_usage_complete:
        blockers.append("CAPACITY_EXECUTED_USAGE_INCOMPLETE")
    if not usage.active_orders_complete:
        blockers.append("CAPACITY_ACTIVE_ORDER_SNAPSHOT_INCOMPLETE")
    if (
        observation.execution_session_state_evidence is None
        or observation.execution_session_state_date is None
        or observation.execution_session_suspended is None
    ):
        blockers.append("CAPACITY_TRADING_STATUS_UNKNOWN")
    elif observation.execution_session_suspended:
        blockers.append("CAPACITY_TRADING_SUSPENDED")

    measure: CapacityMeasure | None = policy.measure if policy is not None else None
    unit: str | None = policy.unit if policy is not None else None
    market_value = _value_for_measure(observation, measure)
    if market_value.value is None or market_value.unit is None:
        blockers.append(f"CAPACITY_{(measure or 'MEASURE').upper()}_UNKNOWN")
    elif unit is not None and market_value.unit != unit:
        blockers.append("CAPACITY_SOURCE_UNIT_MISMATCH")
    elif market_value.value == 0:
        blockers.append(f"CAPACITY_ZERO_{(measure or 'MEASURE').upper()}")

    used_value = _value_for_measure(usage, measure)
    if used_value.value is None or used_value.unit is None:
        blockers.append("CAPACITY_USED_UNKNOWN")
    elif unit is not None and used_value.unit != unit:
        blockers.append("CAPACITY_USED_UNIT_MISMATCH")

    reserved_buy_values: list[Decimal] = []
    reserved_sell_values: list[Decimal] = []
    proposed_values: list[Decimal] = []
    seen_order_ids: set[str] = set()
    for is_active, orders in (
        (True, usage.active_orders),
        (False, usage.proposed_orders),
    ):
        for order in orders:
            if order.order_id in seen_order_ids:
                blockers.append("CAPACITY_DUPLICATE_ORDER_ID")
            seen_order_ids.add(order.order_id)
            if (
                order.account_id != usage.account_id
                or order.security_id != usage.security_id
                or order.asset_code != usage.asset_code
            ):
                blockers.append("CAPACITY_ORDER_SCOPE_MISMATCH")
            order_value = _value_for_measure(order, measure)
            if order_value.value is None or order_value.unit is None:
                blockers.append(
                    "CAPACITY_ACTIVE_ORDER_USE_UNKNOWN"
                    if is_active
                    else "CAPACITY_PROPOSED_ORDER_USE_UNKNOWN"
                )
                continue
            if unit is not None and order_value.unit != unit:
                blockers.append("CAPACITY_ORDER_UNIT_MISMATCH")
                continue
            if not is_active:
                proposed_values.append(order_value.value)
            elif order.side == "buy":
                reserved_buy_values.append(order_value.value)
            else:
                reserved_sell_values.append(order_value.value)
    reserved_buy = _sum_exact_decimals(tuple(reserved_buy_values))
    reserved_sell = _sum_exact_decimals(tuple(reserved_sell_values))
    proposed = _sum_exact_decimals(tuple(proposed_values))

    source_basis_blockers = {
        "CAPACITY_POLICY_UNCONFIGURED",
        "CAPACITY_POLICY_NOT_CURRENT_AT_CUTOFF",
        "CAPACITY_POLICY_EXPIRED",
        "CAPACITY_WINDOW_POLICY_MISMATCH",
        "CAPACITY_SOURCE_EFFECTIVE_DATE_MISMATCH",
        "CAPACITY_SOURCE_OBSERVATION_DATE_MISMATCH",
        "CAPACITY_DATE_PRECISION_PURPOSE_NOT_ALLOWED",
        "CAPACITY_DATE_CUTOFF_MISMATCH",
        "CAPACITY_LOOKBACK_NOT_BEFORE_EXECUTION_SESSION",
        "CAPACITY_SESSION_SOURCE_DATE_MISMATCH",
        "CAPACITY_WINDOW_COVERAGE_INCOMPLETE",
        "CAPACITY_SOURCE_UNIT_MISMATCH",
        "CAPACITY_VOLUME_UNKNOWN",
        "CAPACITY_AMOUNT_UNKNOWN",
        "CAPACITY_TRADING_STATUS_EVIDENCE_MISSING",
        "CAPACITY_TRADING_STATUS_UNKNOWN",
        "CAPACITY_TRADING_STATUS_SESSION_DATE_MISMATCH",
        "CAPACITY_TRADING_STATUS_FUTURE_SESSION",
        "CAPACITY_TRADING_STATUS_EFFECTIVE_DATE_MISMATCH",
        "CAPACITY_TRADING_STATUS_COVERAGE_INCOMPLETE",
        "CAPACITY_TRADING_STATUS_DATE_PRECISION_NOT_ALLOWED",
        "CAPACITY_TRADING_STATUS_OBSERVATION_DATE_MISMATCH",
        "CAPACITY_TRADING_STATUS_DATE_CUTOFF_MISMATCH",
    }
    source_basis_valid = not any(
        code.startswith("RISK_SOURCE_") or code in source_basis_blockers for code in blockers
    )
    window_capacity: Decimal | None = None
    remaining_capacity: Decimal | None = None
    allowed_new_capacity: Decimal | None = None
    used_amount = (
        used_value.value if used_value.value is not None and used_value.unit == unit else None
    )
    if (
        policy is not None
        and source_basis_valid
        and market_value.value is not None
        and market_value.unit == unit
    ):
        window_capacity = _floor_capacity_to_increment(
            market_value.value,
            sessions=observation.window_sessions,
            basis=policy.capacity_basis,
            participation=policy.max_participation,
            increment=policy.capacity_increment,
        )
        if window_capacity == 0:
            blockers.append("CAPACITY_PARTICIPATION_BUDGET_ZERO")
    unique_blockers = tuple(dict.fromkeys(blockers))
    usage_blocker_prefixes = (
        "CAPACITY_USED_",
        "CAPACITY_EXECUTED_USAGE_",
        "CAPACITY_ORDER_",
        "CAPACITY_ACTIVE_ORDER_",
        "CAPACITY_ACTIVE_ORDER_SNAPSHOT_",
        "CAPACITY_PROPOSED_ORDER_",
        "CAPACITY_DUPLICATE_ORDER_",
        "CAPACITY_USAGE_",
    )
    usage_inputs_valid = not any(
        code.startswith(usage_blocker_prefixes) for code in unique_blockers
    )
    if (
        window_capacity is not None
        and usage_inputs_valid
        and used_amount is not None
        and "CAPACITY_TRADING_STATUS_UNKNOWN" not in unique_blockers
    ):
        remaining_fraction = max(
            Fraction(0),
            Fraction(window_capacity)
            - Fraction(used_amount)
            - Fraction(reserved_buy)
            - Fraction(reserved_sell),
        )
        remaining_capacity = _fraction_to_decimal(remaining_fraction)
        allowed_new_capacity = (
            Decimal("0")
            if "CAPACITY_TRADING_SUSPENDED" in unique_blockers
            else min(proposed, remaining_capacity)
        )
    fatal_unknown = any(
        code.startswith(("RISK_SOURCE_", "CAPACITY_"))
        and code
        not in (
            "CAPACITY_TRADING_SUSPENDED",
            "CAPACITY_ZERO_VOLUME",
            "CAPACITY_ZERO_AMOUNT",
            "CAPACITY_PARTICIPATION_BUDGET_ZERO",
            "CAPACITY_POLICY_EXPIRED",
            "RISK_SOURCE_PROHIBITED_FOR_DECISION",
            "RISK_SOURCE_PROHIBITED_PURPOSE",
            "RISK_SOURCE_PROHIBITED_RESTRICTION",
        )
        for code in unique_blockers
    )
    if fatal_unknown:
        status: CapacityDecisionStatus = "unknown"
    elif unique_blockers:
        status = "blocked"
    elif proposed > (remaining_capacity or Decimal("0")):
        status = (
            "partial" if remaining_capacity is not None and remaining_capacity > 0 else "blocked"
        )
        if status == "partial":
            unique_blockers = (*unique_blockers, "CAPACITY_PROPOSAL_EXCEEDS_REMAINDER")
        else:
            unique_blockers = (*unique_blockers, "CAPACITY_REMAINDER_EXHAUSTED")
    else:
        status = "allowed"

    return PortfolioCapacityDecision(
        status=status,
        reason_codes=unique_blockers,
        account_id=usage.account_id,
        asset_code=observation.asset_code,
        security_id=observation.security_id,
        business_date=business_date,
        capacity_date=usage.capacity_date,
        snapshot_read_at=usage.snapshot_read_at,
        executed_usage_complete=usage.executed_usage_complete,
        active_orders_complete=usage.active_orders_complete,
        source_id=source.source_id,
        source_record_id=source.source_record_id,
        source_payload_sha256=source.original_payload_sha256,
        source_observation_precision=source.observation_precision,
        source_observed_at=source.observed_at,
        source_observed_on=source.observed_on,
        source_available_at=source.available_at,
        source_known_at=source.known_at,
        source_decision_cutoff=source.decision_cutoff,
        source_decision_date_cutoff=source.decision_date_cutoff,
        source_valid_until=source.valid_until,
        source_effective_on=source.effective_on,
        source_effective_until=source.effective_until,
        source_purpose=source.source_purpose,
        source_allowed_purposes=source.allowed_purposes,
        source_restrictions=source.restrictions,
        source_must_not_use_for_decision=source.must_not_use_for_decision,
        source_coverage_status=source.coverage.status,
        source_coverage_precision_basis=source.coverage.precision_basis,
        source_coverage_reported_weight_fraction=source.coverage.reported_weight_fraction,
        source_coverage_expected_item_count=source.coverage.expected_item_count,
        source_coverage_observed_item_count=source.coverage.observed_item_count,
        execution_session_state_date=observation.execution_session_state_date,
        execution_session_suspended=observation.execution_session_suspended,
        execution_session_state_evidence=observation.execution_session_state_evidence,
        decision_as_of=as_of,
        source_window_start=observation.window_start,
        source_window_end=observation.window_end,
        source_window_sessions=observation.window_sessions,
        policy_id=policy.policy_id if policy is not None else None,
        policy_version=policy.version if policy is not None else None,
        policy_content_hash=policy.content_hash if policy is not None else None,
        measure=measure,
        unit=unit,
        capacity_basis=policy.capacity_basis if policy is not None else None,
        usage_scope=policy.usage_scope if policy is not None else None,
        usage_date_basis=policy.usage_date_basis if policy is not None else None,
        policy_date_precision_purposes=(
            policy.date_precision_purposes if policy is not None else None
        ),
        policy_allowed_source_restrictions=(
            policy.allowed_source_restrictions if policy is not None else None
        ),
        window_capacity=window_capacity,
        used_capacity=used_amount,
        reserved_buy_capacity=reserved_buy if usage_inputs_valid else None,
        reserved_sell_capacity=reserved_sell if usage_inputs_valid else None,
        proposed_capacity=proposed if usage_inputs_valid else None,
        remaining_capacity=remaining_capacity,
        allowed_new_capacity=allowed_new_capacity,
    )


def _value_for_measure(
    value: CapacityWindowObservation | CapacityUsageSnapshot | CapacityOrderUsage,
    measure: CapacityMeasure | None,
) -> CapacityValue:
    if measure is None:
        return CapacityValue(None, None)
    return value.volume if measure == "volume" else value.amount


def _floor_capacity_to_increment(
    source_measure: Decimal,
    *,
    sessions: int,
    basis: CapacityBasis,
    participation: Decimal,
    increment: Decimal,
) -> Decimal:
    """Floor the exact rational capacity to a configured increment without rounding up."""

    available = Fraction(source_measure)
    if basis == "average_per_session":
        available /= sessions
    budget = available * Fraction(participation)
    increments = budget / Fraction(increment)
    whole_increments = increments.numerator // increments.denominator
    return _fraction_to_decimal(whole_increments * Fraction(increment))


def _sum_exact_decimals(values: tuple[Decimal, ...]) -> Decimal:
    """Add finite Decimal values by aligning integer coefficients without context rounding."""

    if not values:
        return Decimal("0")
    parts: list[tuple[tuple[int, ...], int]] = []
    for value in values:
        component = value.as_tuple()
        if type(component.exponent) is not int:
            raise ValueError("capacity sum requires finite Decimal values")
        parts.append((component.digits, component.exponent))
    exponent = min(part[1] for part in parts)
    coefficient = sum(
        int("".join(str(digit) for digit in digits)) * (10 ** (part_exponent - exponent))
        for digits, part_exponent in parts
    )
    return _decimal_from_scaled_integer(coefficient, exponent)


def _fraction_to_decimal(value: Fraction) -> Decimal:
    """Convert a finite base-ten Fraction to Decimal exactly."""

    numerator = abs(value.numerator)
    denominator = value.denominator
    twos = 0
    fives = 0
    while denominator % 2 == 0:
        denominator //= 2
        twos += 1
    while denominator % 5 == 0:
        denominator //= 5
        fives += 1
    if denominator != 1:
        raise ValueError("capacity arithmetic produced a non-terminating decimal")
    scale = max(twos, fives)
    coefficient = numerator * (2 ** (scale - twos)) * (5 ** (scale - fives))
    return _decimal_from_scaled_integer(
        -coefficient if value.numerator < 0 else coefficient,
        -scale,
    )


def _decimal_from_scaled_integer(coefficient: int, exponent: int) -> Decimal:
    """Build an exact finite Decimal directly from an integer coefficient and scale."""

    digits = tuple(int(character) for character in str(abs(coefficient)))
    return Decimal((1 if coefficient < 0 else 0, digits, exponent))


def _require_fraction(value: Decimal, field_name: str) -> None:
    if type(value) is not Decimal or not value.is_finite() or not Decimal("0") <= value <= 1:
        raise ValueError(f"{field_name} must be an exact Decimal fraction in [0, 1]")


def _require_token(value: str, field_name: str) -> None:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a nonempty canonical token")


def _is_unconditionally_prohibited_restriction(value: str) -> bool:
    normalized = value.lower()
    return (
        normalized.startswith("must_not_")
        or normalized.startswith("research_only")
        or normalized.startswith("observation_only")
    )


def _require_date(value: date, field_name: str) -> None:
    if type(value) is not date:
        raise TypeError(f"{field_name} must be a date, not datetime")


def _require_aware(value: datetime, field_name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be a timezone-aware datetime")
