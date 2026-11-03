"""Pure capacity-window calculations for simulated portfolio exit pressure."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, localcontext
from fractions import Fraction

from apps.risk_center.domain.portfolio_capacity import (
    CapacityWindowObservation,
    PortfolioCapacityDecision,
)
from apps.risk_center.domain.portfolio_exit_pressure import ExitCapacityWindow
from apps.risk_center.domain.portfolio_risk_snapshot import AccountSnapshot, exact_decimal_sum
from apps.risk_center.domain.portfolio_risk_sources import PortfolioRiskSourceEvidence
from apps.risk_center.domain.scenarios import (
    ParametricShock,
    ParametricShockParameters,
    PortfolioExposure,
    ScenarioRevision,
    ShockUnit,
    scenario_exposure_loading,
)


def calculate_current_exit_capacity_window(
    *,
    account_snapshot: AccountSnapshot,
    asset_code: str,
    security_id: str | None,
    held_quantity: Decimal,
    available_quantity: Decimal | None,
    quantity_unit: str,
    price: Decimal | None,
    price_unit: str | None,
    money_unit: str | None,
    capacity_observation: CapacityWindowObservation | None,
    decisions: tuple[PortfolioCapacityDecision, ...],
    evidence_by_id: dict[str, PortfolioRiskSourceEvidence],
    business_date: date,
) -> tuple[ExitCapacityWindow, Decimal | None, tuple[str, ...], tuple[str, ...]]:
    """Use an exact same-session usage-only decision and actual sellable balance."""

    quantity_unit_value = quantity_unit
    current_date = account_snapshot.execution_session
    candidates = tuple(item for item in decisions if item.asset_code == asset_code)
    source_ids: tuple[str, ...] = ()
    reasons: list[str] = []
    if len(candidates) != 1 or capacity_observation is None:
        reasons.append("PORTFOLIO_PRESSURE_CAPACITY_DECISION_MISSING")
        return _unknown_window(current_date, quantity_unit_value, reasons), None, (), tuple(reasons)
    decision = candidates[0]
    evidence = capacity_observation.source_evidence
    state_evidence = capacity_observation.execution_session_state_evidence
    possible_ids = [f"{evidence.source_id}:{evidence.source_record_id}"]
    if state_evidence is not None:
        possible_ids.append(f"{state_evidence.source_id}:{state_evidence.source_record_id}")
    references = (evidence, state_evidence) if state_evidence is not None else (evidence,)
    if any(
        evidence_by_id.get(f"{item.source_id}:{item.source_record_id}") != item
        for item in references
    ):
        reasons.append("PORTFOLIO_PRESSURE_CAPACITY_SOURCE_UNBOUND")
        return _unknown_window(current_date, quantity_unit_value, reasons), None, (), tuple(reasons)
    source_ids = _ordered_unique(tuple(possible_ids))
    if (
        decision.account_id != account_snapshot.account_id
        or decision.security_id != security_id
        or decision.business_date != business_date
        or decision.capacity_date != current_date
        or decision.snapshot_read_at != account_snapshot.read_at
        or decision.executed_usage_complete != account_snapshot.executed_usage_complete
        or decision.active_orders_complete != account_snapshot.active_orders_complete
        or decision.usage_scope != "account_security_session"
        or decision.usage_date_basis != "execution_session"
        or decision.proposed_capacity not in (None, Decimal("0"))
        or decision.allowed_new_capacity not in (None, Decimal("0"))
        or decision.decision_as_of != evidence.decision_cutoff
        or decision.source_id != evidence.source_id
        or decision.source_record_id != evidence.source_record_id
        or decision.source_payload_sha256 != evidence.original_payload_sha256
        or decision.source_observation_precision is not evidence.observation_precision
        or decision.source_observed_at != evidence.observed_at
        or decision.source_observed_on != evidence.observed_on
        or decision.source_available_at != evidence.available_at
        or decision.source_known_at != evidence.known_at
        or decision.source_decision_cutoff != evidence.decision_cutoff
        or decision.source_decision_date_cutoff != evidence.decision_date_cutoff
        or decision.source_valid_until != evidence.valid_until
        or decision.source_effective_on != evidence.effective_on
        or decision.source_effective_until != evidence.effective_until
        or decision.source_purpose != evidence.source_purpose
        or decision.source_allowed_purposes != evidence.allowed_purposes
        or decision.source_restrictions != evidence.restrictions
        or decision.source_must_not_use_for_decision != evidence.must_not_use_for_decision
        or decision.source_coverage_status != evidence.coverage.status
        or decision.source_coverage_precision_basis != evidence.coverage.precision_basis
        or decision.source_coverage_reported_weight_fraction
        != evidence.coverage.reported_weight_fraction
        or decision.source_coverage_expected_item_count != evidence.coverage.expected_item_count
        or decision.source_coverage_observed_item_count != evidence.coverage.observed_item_count
        or decision.source_window_start != capacity_observation.window_start
        or decision.source_window_end != capacity_observation.window_end
        or decision.source_window_sessions != capacity_observation.window_sessions
        or decision.execution_session_state_evidence != state_evidence
        or decision.execution_session_state_date
        != capacity_observation.execution_session_state_date
        or decision.execution_session_suspended != capacity_observation.execution_session_suspended
    ):
        reasons.append("PORTFOLIO_PRESSURE_CAPACITY_DECISION_SCOPE_MISMATCH")
        return _unknown_window(current_date, quantity_unit_value, reasons), None, (), tuple(reasons)
    if (
        decision.status == "unknown"
        or decision.window_capacity is None
        or decision.remaining_capacity is None
        or decision.measure is None
        or decision.unit is None
        or decision.source_must_not_use_for_decision
        or any(code.startswith("RISK_SOURCE_") for code in decision.reason_codes)
    ):
        reasons.extend(decision.reason_codes)
        reasons.append("PORTFOLIO_PRESSURE_CAPACITY_UNKNOWN")
        usable_ids = _usable_capacity_source_ids(decision, source_ids)
        return (
            _unknown_window(current_date, quantity_unit_value, reasons, usable_ids),
            None,
            usable_ids,
            tuple(reasons),
        )
    if decision.status == "blocked":
        usable_ids = _usable_capacity_source_ids(decision, source_ids)
        known_zero = bool(usable_ids) and (
            decision.execution_session_suspended is True
            or decision.remaining_capacity == Decimal("0")
        )
        if not known_zero:
            reasons.extend(decision.reason_codes)
            reasons.append("PORTFOLIO_PRESSURE_CAPACITY_DECISION_BLOCKED")
            return (
                _unknown_window(current_date, quantity_unit_value, reasons, usable_ids),
                None,
                usable_ids,
                _ordered_unique(tuple(reasons)),
            )
        reasons.extend(decision.reason_codes)
    market_quantity = _remaining_capacity_quantity(
        decision=decision,
        quantity_unit=quantity_unit_value,
        price=price,
        price_unit=price_unit,
        money_unit=money_unit,
    )
    if decision.execution_session_suspended is True:
        reasons.append("CURRENT_SESSION_TRADING_SUSPENDED")
        return (
            ExitCapacityWindow(
                session_date=current_date,
                exitable_quantity=Decimal("0"),
                quantity_unit=quantity_unit_value,
                reason_codes=_ordered_unique(tuple(reasons)),
                source_evidence_ids=source_ids,
            ),
            market_quantity,
            source_ids,
            _ordered_unique(tuple(reasons)),
        )
    if available_quantity == Decimal("0"):
        reasons.append("CURRENT_POSITION_AVAILABLE_QUANTITY_ZERO")
        return (
            ExitCapacityWindow(
                session_date=current_date,
                exitable_quantity=Decimal("0"),
                quantity_unit=quantity_unit_value,
                reason_codes=_ordered_unique(tuple(reasons)),
                source_evidence_ids=source_ids,
            ),
            market_quantity,
            source_ids,
            _ordered_unique(tuple(reasons)),
        )
    if available_quantity is None:
        reasons.append("PORTFOLIO_PRESSURE_AVAILABLE_QUANTITY_UNKNOWN")
        return (
            _unknown_window(current_date, quantity_unit_value, reasons, source_ids),
            market_quantity,
            source_ids,
            _ordered_unique(tuple(reasons)),
        )
    if market_quantity is None:
        reasons.append("PORTFOLIO_PRESSURE_CAPACITY_UNIT_OR_PRICE_UNKNOWN")
        return (
            _unknown_window(current_date, quantity_unit_value, reasons, source_ids),
            None,
            source_ids,
            tuple(reasons),
        )
    quantity = market_quantity
    if available_quantity < held_quantity:
        quantity = min(quantity, available_quantity)
        reasons.append("PORTFOLIO_PRESSURE_AVAILABLE_QUANTITY_LIMITED")
    if quantity == 0 and not reasons:
        reasons.append("PORTFOLIO_PRESSURE_NO_REMAINING_CAPACITY")
    return (
        ExitCapacityWindow(
            session_date=current_date,
            exitable_quantity=quantity,
            quantity_unit=quantity_unit_value,
            reason_codes=_ordered_unique(tuple(reasons)),
            source_evidence_ids=source_ids,
        ),
        quantity,
        source_ids,
        _ordered_unique(tuple(reasons)),
    )


def matching_exit_pressure_shocks(
    revision: ScenarioRevision,
    exposure: PortfolioExposure,
) -> tuple[ParametricShock, ...]:
    """Select only supported explicit exit assumptions matching one asset."""

    if not isinstance(revision.parameters, ParametricShockParameters):
        return ()
    return tuple(
        shock
        for shock in revision.parameters.shocks
        if shock.shock_kind in {"exit_liquidity_change", "exit_halt", "exit_limit_down_lock"}
        and scenario_exposure_loading(exposure, shock.target_kind, shock.target) > 0
    )


def calculate_future_exit_capacity_window(
    *,
    session_date: date,
    quantity_unit: str,
    base_quantity: Decimal | None,
    held_quantity: Decimal,
    available_quantity: Decimal | None,
    source_evidence_ids: tuple[str, ...],
    shocks: tuple[ParametricShock, ...],
) -> ExitCapacityWindow:
    """Apply only explicit downside exit assumptions to one real calendar date."""

    reasons = ["PORTFOLIO_PRESSURE_CAPACITY_BY_APPROVED_SCENARIO_ASSUMPTION"]
    if not shocks:
        reasons.append("PORTFOLIO_PRESSURE_EXIT_ASSUMPTION_MISSING")
        return _unknown_window(session_date, quantity_unit, reasons, source_evidence_ids)
    if any(not _exit_assumption_is_valid(shock) for shock in shocks):
        reasons.append("PORTFOLIO_PRESSURE_EXIT_ASSUMPTION_INVALID")
        return _unknown_window(session_date, quantity_unit, reasons, source_evidence_ids)
    if not source_evidence_ids:
        reasons.append("PORTFOLIO_PRESSURE_CAPACITY_SOURCE_MISSING")
        return _unknown_window(session_date, quantity_unit, reasons)
    locks = tuple(
        shock for shock in shocks if shock.shock_kind in {"exit_halt", "exit_limit_down_lock"}
    )
    if locks:
        reasons.extend(
            (
                "SCENARIO_EXIT_HALT_ASSUMED"
                if shock.shock_kind == "exit_halt"
                else "SCENARIO_EXIT_LIMIT_DOWN_LOCK_ASSUMED"
            )
            for shock in locks
        )
        return ExitCapacityWindow(
            session_date=session_date,
            exitable_quantity=Decimal("0"),
            quantity_unit=quantity_unit,
            reason_codes=_ordered_unique(tuple(reasons)),
            source_evidence_ids=source_evidence_ids,
        )
    if available_quantity is None or available_quantity < held_quantity:
        reasons.append("PORTFOLIO_PRESSURE_FUTURE_AVAILABLE_QUANTITY_UNKNOWN")
        return _unknown_window(session_date, quantity_unit, reasons, source_evidence_ids)
    if base_quantity is None:
        reasons.append("PORTFOLIO_PRESSURE_BASE_CAPACITY_UNKNOWN")
        return _unknown_window(session_date, quantity_unit, reasons, source_evidence_ids)
    factor = Decimal("1")
    for shock in shocks:
        if shock.shock_kind == "exit_liquidity_change":
            factor *= Decimal("1") + shock.magnitude
            reasons.append("SCENARIO_EXIT_LIQUIDITY_CHANGE_ASSUMED")
            if shock.target_kind == "factor":
                reasons.append("PORTFOLIO_PRESSURE_FACTOR_EXIT_ASSUMPTION_APPLIED_TO_FULL_ASSET")
    quantity = base_quantity * factor
    if quantity == 0:
        reasons.append("SCENARIO_EXIT_LIQUIDITY_REDUCED_TO_ZERO")
    return ExitCapacityWindow(
        session_date=session_date,
        exitable_quantity=quantity,
        quantity_unit=quantity_unit,
        reason_codes=_ordered_unique(tuple(reasons)),
        source_evidence_ids=source_evidence_ids,
    )


def pending_exit_order_quantity(
    account_snapshot: AccountSnapshot,
    asset_code: str,
) -> tuple[Decimal, bool]:
    """Return exact active SELL reservations and whether their quantity is incomplete."""

    orders = tuple(
        item
        for item in account_snapshot.active_orders
        if item.asset_code == asset_code and item.side == "sell"
    )
    unknown = not account_snapshot.active_orders_complete or any(
        item.remaining_quantity is None for item in orders
    )
    known = exact_decimal_sum(
        tuple(item.remaining_quantity for item in orders if item.remaining_quantity is not None)
    )
    return known, unknown


def _remaining_capacity_quantity(
    *,
    decision: PortfolioCapacityDecision,
    quantity_unit: str,
    price: Decimal | None,
    price_unit: str | None,
    money_unit: str | None,
) -> Decimal | None:
    """Convert amount capacity only with the same currency and a qualified price."""

    remaining = decision.remaining_capacity
    if remaining is None or remaining < 0:
        return None
    if decision.measure == "volume":
        return remaining if decision.unit == quantity_unit else None
    if (
        decision.measure != "amount"
        or decision.unit != money_unit
        or price_unit != money_unit
        or price is None
        or price <= 0
    ):
        return None
    exact_ratio = Fraction(remaining) / Fraction(price)
    with localcontext() as context:
        context.prec = 50
        converted = remaining / price
        while Fraction(converted) > exact_ratio:
            converted = converted.next_minus(context)
    return max(Decimal("0"), converted)


def _exit_assumption_is_valid(shock: ParametricShock) -> bool:
    """Require a bounded explicit downside exit assumption before projecting."""

    if shock.horizon_days > 3650:
        return False
    if shock.shock_kind == "exit_liquidity_change":
        return shock.unit is ShockUnit.PERCENT and Decimal("-1") <= shock.magnitude <= Decimal("0")
    if shock.shock_kind in {"exit_halt", "exit_limit_down_lock"}:
        return shock.unit is ShockUnit.PERCENT and shock.magnitude == Decimal("-1")
    return False


def _usable_capacity_source_ids(
    decision: PortfolioCapacityDecision,
    source_ids: tuple[str, ...],
) -> tuple[str, ...]:
    """Keep assumption references only when capacity and policy sources are usable."""

    unusable_prefixes = (
        "RISK_SOURCE_",
        "CAPACITY_POLICY_",
        "CAPACITY_WINDOW_",
        "CAPACITY_SOURCE_",
    )
    if (
        decision.policy_id is None
        or decision.policy_version is None
        or decision.policy_content_hash is None
        or decision.source_must_not_use_for_decision
        or any(code.startswith(unusable_prefixes) for code in decision.reason_codes)
    ):
        return ()
    return source_ids


def _unknown_window(
    session_date: date,
    quantity_unit: str,
    reason_codes: list[str],
    source_evidence_ids: tuple[str, ...] = (),
) -> ExitCapacityWindow:
    """Preserve missing capacity as unknown, never as zero."""

    return ExitCapacityWindow(
        session_date=session_date,
        exitable_quantity=None,
        quantity_unit=quantity_unit,
        reason_codes=_ordered_unique(tuple(reason_codes)),
        source_evidence_ids=source_evidence_ids,
    )


def _ordered_unique(values: tuple[str, ...]) -> tuple[str, ...]:
    """Retain stable reason-code order while removing duplicates."""

    return tuple(dict.fromkeys(values))


__all__ = (
    "calculate_current_exit_capacity_window",
    "calculate_future_exit_capacity_window",
    "matching_exit_pressure_shocks",
    "pending_exit_order_quantity",
)
