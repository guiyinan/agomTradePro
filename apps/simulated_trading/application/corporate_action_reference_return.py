"""Gross fixed-reference holding wealth; account performance is a separate contract."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from apps.data_center.application.retained_historical_price_source import (
    RetainedHistoricalPriceEvidence,
)
from apps.simulated_trading.application.corporate_action_nav_mark import (
    SimulatedCorporateActionNavRawMarkProof,
)
from apps.simulated_trading.domain.corporate_action_performance_projection import (
    ReferenceCorporateActionWealthComparison,
    RestatementEntitlement,
    RestatementRawMark,
    project_reference_corporate_action_wealth,
)
from core.exceptions import BusinessLogicError


def _blocked(reason: str) -> BusinessLogicError:
    return BusinessLogicError("登记日参考持仓权益回报尚不能完整核对。", code=reason)


@dataclass(frozen=True, slots=True)
class CorporateActionReferenceReturnInputs:
    """Sources supplied by independently verified owner/current-entitlement compositions."""

    record_date: date
    reference_quantity: Decimal
    entitlement: RestatementEntitlement
    current_mark: SimulatedCorporateActionNavRawMarkProof
    opening_source: RetainedHistoricalPriceEvidence
    closing_source: RetainedHistoricalPriceEvidence
    currency_quantum: Decimal
    quantity_quantum: Decimal
    knowledge_cutoff: datetime
    source_scope_valid_until: datetime


@dataclass(frozen=True, slots=True)
class CorporateActionReferenceReturnReport:
    """An exact gross two-session comparison without account cash or debt claims."""

    asset_code: str
    record_date: date
    comparison: ReferenceCorporateActionWealthComparison
    opening_source: RetainedHistoricalPriceEvidence
    closing_source: RetainedHistoricalPriceEvidence
    knowledge_cutoff: datetime
    valid_until: datetime
    knowledge_semantics: Literal["currently_known_reference_holding"] = (
        "currently_known_reference_holding"
    )
    return_basis: Literal["gross_unreinvested_record_date_holding"] = (
        "gross_unreinvested_record_date_holding"
    )
    must_not_use_for_decision: Literal[True] = True


def build_corporate_action_reference_return(
    inputs: CorporateActionReferenceReturnInputs,
) -> CorporateActionReferenceReturnReport:
    """Bracket one verified ex-date with raw prices and count economic rights once.

    The composition separately verifies actual owner/record-date entitlement,
    current source lease, complete original financial transfers and exact
    retained source proofs. This use case adds no financial capability and
    never reads or reconstructs an account cash-flow-adjusted return.
    """
    if type(inputs) is not CorporateActionReferenceReturnInputs:
        raise _blocked("REFERENCE_RETURN_INPUT_INVALID")
    cutoff = inputs.knowledge_cutoff
    deadline = inputs.source_scope_valid_until
    if (
        type(cutoff) is not datetime
        or cutoff.tzinfo is None
        or cutoff.utcoffset() is None
        or type(deadline) is not datetime
        or deadline.tzinfo is None
        or deadline.utcoffset() is None
        or not cutoff < deadline
        or type(inputs.record_date) is not date
        or type(inputs.entitlement) is not RestatementEntitlement
        or type(inputs.current_mark) is not SimulatedCorporateActionNavRawMarkProof
    ):
        raise _blocked("REFERENCE_RETURN_SCOPE_INVALID")
    current = inputs.current_mark
    current.verify_for(current.query, as_of=cutoff)
    current.calendar.validate_for(cutoff)
    action = inputs.entitlement
    action.__post_init__()
    if inputs.record_date >= action.effective_on or action.asset_code != current.query.asset_code:
        raise _blocked("REFERENCE_RETURN_ENTITLEMENT_SCOPE_INVALID")
    open_days = tuple(day.calendar_date for day in current.calendar.snapshot.days if day.is_open)
    before = tuple(day for day in open_days if day < action.effective_on)
    if (
        not before
        or action.effective_on not in open_days
        or action.effective_on > current.trade_date
    ):
        raise _blocked("REFERENCE_RETURN_EX_DATE_NOT_CLOSED")
    expected_dates = (max(before), action.effective_on)
    sources = (inputs.opening_source, inputs.closing_source)
    marks: list[RestatementRawMark] = []
    for expected, source in zip(expected_dates, sources, strict=True):
        if (
            type(source) is not RetainedHistoricalPriceEvidence
            or source.knowledge_semantics != "currently_known_historical"
            or source.must_not_use_for_decision is not True
            or source.knowledge_cutoff != cutoff
            or source.price.asset_code != action.asset_code
            or source.price.trade_date != expected
            or source.price.amount_unit != current.policy_binding.policy.currency
            or source.price.publication_key != current.policy_binding.policy.publication_key
            or source.price.adjustment.value != "none"
            or source.price.source_observed_at is not None
        ):
            raise _blocked("REFERENCE_RETURN_RAW_PRICE_SCOPE_INVALID")
        source.activation.pair.verify_at_cutoff(as_of=cutoff)
        marks.append(
            RestatementRawMark(
                day=source.price.trade_date,
                asset_code=source.price.asset_code,
                money_unit=source.price.amount_unit,
                quantity_unit=source.price.volume_unit,
                price=source.price.values.close,
                adjustment=source.price.adjustment.value,
                interval_end_at=source.price.interval_end_at,
                local_known_at=source.price.source_available_at,
                publication_recorded_at=source.price.publication_published_at,
                source_observed_at=source.price.source_observed_at,
            )
        )
    comparison = project_reference_corporate_action_wealth(
        reference_quantity=inputs.reference_quantity,
        entitlement=action,
        marks=(marks[0], marks[1]),
        money_quantum=inputs.currency_quantum,
        quantity_quantum=inputs.quantity_quantum,
        knowledge_cutoff=cutoff,
        decision_day=current.trade_date,
    )
    return CorporateActionReferenceReturnReport(
        action.asset_code,
        inputs.record_date,
        comparison,
        inputs.opening_source,
        inputs.closing_source,
        cutoff,
        min(deadline, current.valid_until),
    )
