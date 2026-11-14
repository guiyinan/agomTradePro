"""Exact restatement arithmetic; source qualification and account authority stay outside.

The caller must independently verify complete current-knowledge source, account,
trade, flow, tax, fee and original financial/Audit histories. This module cannot
turn caller-supplied hashes or arithmetic values into qualified financial facts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, DecimalException, Inexact, localcontext


class CorporateActionRestatementInvalid(ValueError):
    """Identify unsupported or inconsistent arithmetic without partial valuations."""

    def __init__(self, reason_code: str) -> None:
        """Retain only a stable reason; never print account or source payloads."""
        self.reason_code = reason_code
        super().__init__(reason_code)


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise CorporateActionRestatementInvalid(reason)


def _day(value: date) -> None:
    _require(type(value) is date, "RESTATEMENT_DATE_INVALID")


def _aware(value: datetime) -> None:
    _require(
        type(value) is datetime and value.tzinfo is not None and value.utcoffset() is not None,
        "RESTATEMENT_CLOCK_INVALID",
    )


def _decimal(value: Decimal) -> None:
    _require(type(value) is Decimal and value.is_finite(), "RESTATEMENT_AMOUNT_INVALID")


def _token(value: str) -> None:
    _require(
        type(value) is str and bool(value) and value.strip() == value, "RESTATEMENT_ID_INVALID"
    )


def _power_of_ten(value: Decimal) -> bool:
    digits = value.as_tuple().digits
    return value > 0 and digits[0] == 1 and all(digit == 0 for digit in digits[1:])


@dataclass(frozen=True, slots=True)
class RestatementTransfer:
    """One original signed financial effect at its actual accounting date."""

    entry_id: str
    accounting_on: date
    amount: Decimal
    recorded_at: datetime

    def __post_init__(self) -> None:
        """Reject ambiguous dates, unknown amounts and missing original identities."""
        _token(self.entry_id)
        _day(self.accounting_on)
        _decimal(self.amount)
        _aware(self.recorded_at)
        _require(self.amount != 0, "RESTATEMENT_ZERO_TRANSFER_INVALID")


@dataclass(frozen=True, slots=True)
class RestatementEntitlement:
    """Current source terms and complete original transfers for one logical family.

    The economic entitlement starts on the verified source effective date.
    Transfers keep their actual accounting dates; late simulated payment is
    never moved back to a scheduled or source observation date.
    """

    action_id: str
    asset_code: str
    effective_on: date
    gross_cash: Decimal
    gross_shares: Decimal
    known_at: datetime
    cash_transfers: tuple[RestatementTransfer, ...]
    share_transfers: tuple[RestatementTransfer, ...]

    def __post_init__(self) -> None:
        """Require exact nonnegative rights, without inventing allocation rules."""
        _token(self.action_id)
        _token(self.asset_code)
        _day(self.effective_on)
        _aware(self.known_at)
        _decimal(self.gross_cash)
        _decimal(self.gross_shares)
        _require(
            self.gross_cash >= 0
            and self.gross_shares >= 0
            and (self.gross_cash > 0 or self.gross_shares > 0),
            "RESTATEMENT_ENTITLEMENT_INVALID",
        )
        for rows in (self.cash_transfers, self.share_transfers):
            _require(type(rows) is tuple, "RESTATEMENT_TRANSFERS_INVALID")
            for row in rows:
                _require(type(row) is RestatementTransfer, "RESTATEMENT_TRANSFERS_INVALID")
                row.__post_init__()


@dataclass(frozen=True, slots=True)
class RestatementRawMark:
    """Exact raw interval price and its separate original local knowledge clocks."""

    day: date
    asset_code: str
    money_unit: str
    quantity_unit: str
    price: Decimal
    adjustment: str
    interval_end_at: datetime
    local_known_at: datetime
    publication_recorded_at: datetime
    source_observed_at: datetime | None

    def __post_init__(self) -> None:
        """Reject adjusted prices and future/contradictory retained evidence clocks."""
        _day(self.day)
        for value in (self.asset_code, self.money_unit, self.quantity_unit):
            _token(value)
        _decimal(self.price)
        _require(self.price > 0 and self.adjustment == "none", "RESTATEMENT_RAW_MARK_REQUIRED")
        for clock in (self.interval_end_at, self.local_known_at, self.publication_recorded_at):
            _aware(clock)
        _require(
            self.interval_end_at <= self.local_known_at <= self.publication_recorded_at,
            "RESTATEMENT_MARK_CLOCK_ORDER_INVALID",
        )
        if self.source_observed_at is not None:
            _aware(self.source_observed_at)
            _require(
                self.source_observed_at <= self.local_known_at, "RESTATEMENT_SOURCE_CLOCK_INVALID"
            )


@dataclass(frozen=True, slots=True)
class CorporateActionRestatementInput:
    """A verified single-asset stable-trade interval, valued with current knowledge.

    ``unmodeled_event_dates`` must include every ordinary trade, capital flow,
    fee correction and tax operation. Anything in or after the first session
    is unsupported here because the current balance cannot safely undo it.
    This input is arithmetic data, not proof that those histories are complete.
    """

    asset_code: str
    money_unit: str
    quantity_unit: str
    money_quantum: Decimal
    quantity_quantum: Decimal
    knowledge_cutoff: datetime
    decision_day: date
    session_days: tuple[date, ...]
    current_cash: Decimal
    current_position_quantity: Decimal
    current_tax_payable: Decimal
    marks: tuple[RestatementRawMark, ...]
    entitlements: tuple[RestatementEntitlement, ...]
    unmodeled_event_dates: tuple[date, ...]


@dataclass(frozen=True, slots=True)
class RestatedCorporateActionValue:
    """One exact arithmetic point without any source or execution eligibility flag."""

    day: date
    cash: Decimal
    physical_shares: Decimal
    share_receivable: Decimal
    market_value: Decimal
    dividend_receivable: Decimal
    tax_payable: Decimal
    total_value: Decimal


def _sum_transfers(rows: tuple[RestatementTransfer, ...], day: date | None = None) -> Decimal:
    return sum((row.amount for row in rows if day is None or row.accounting_on <= day), Decimal(0))


def project_corporate_action_restatement(
    data: CorporateActionRestatementInput,
) -> tuple[RestatedCorporateActionValue, ...]:
    """Project exact raw-price NAV once per entitlement, retaining late transfers.

    No source is fetched, no ledger is written and no historical information
    availability is inferred. Unsupported cases return no partial result.
    """
    _require(type(data) is CorporateActionRestatementInput, "RESTATEMENT_INPUT_INVALID")
    _aware(data.knowledge_cutoff)
    _day(data.decision_day)
    for text in (data.asset_code, data.money_unit, data.quantity_unit):
        _token(text)
    for value in (
        data.money_quantum,
        data.quantity_quantum,
        data.current_cash,
        data.current_position_quantity,
        data.current_tax_payable,
    ):
        _decimal(value)
    _require(
        _power_of_ten(data.money_quantum) and _power_of_ten(data.quantity_quantum),
        "RESTATEMENT_QUANTUM_INVALID",
    )
    _require(
        data.current_cash >= 0
        and data.current_position_quantity >= 0
        and data.current_tax_payable >= 0,
        "RESTATEMENT_CURRENT_BALANCE_INVALID",
    )
    _require(
        type(data.session_days) is tuple and len(data.session_days) >= 2,
        "RESTATEMENT_SESSIONS_MISSING",
    )
    for day in data.session_days:
        _day(day)
    _require(
        tuple(sorted(set(data.session_days))) == data.session_days
        and data.session_days[-1] <= data.decision_day,
        "RESTATEMENT_SESSIONS_INVALID",
    )
    _require(type(data.unmodeled_event_dates) is tuple, "RESTATEMENT_HISTORY_INVALID")
    for day in data.unmodeled_event_dates:
        _day(day)
        _require(day < data.session_days[0], "RESTATEMENT_INTERVENING_HISTORY_UNSUPPORTED")
    _require(
        type(data.marks) is tuple and all(type(mark) is RestatementRawMark for mark in data.marks),
        "RESTATEMENT_MARKS_INVALID",
    )
    _require(
        tuple(mark.day for mark in data.marks) == data.session_days,
        "RESTATEMENT_MARK_COVERAGE_INCOMPLETE",
    )
    for mark in data.marks:
        mark.__post_init__()
        _require(
            (mark.asset_code, mark.money_unit, mark.quantity_unit)
            == (data.asset_code, data.money_unit, data.quantity_unit)
            and mark.publication_recorded_at <= data.knowledge_cutoff,
            "RESTATEMENT_MARK_SCOPE_OR_KNOWLEDGE_INVALID",
        )
    _require(
        type(data.entitlements) is tuple and bool(data.entitlements),
        "RESTATEMENT_ENTITLEMENTS_MISSING",
    )
    ids: set[str] = set()
    entries: set[str] = set()
    for action in data.entitlements:
        _require(type(action) is RestatementEntitlement, "RESTATEMENT_ENTITLEMENT_INVALID")
        action.__post_init__()
        _require(action.action_id not in ids, "RESTATEMENT_DUPLICATE_ACTION")
        ids.add(action.action_id)
        _require(
            action.asset_code == data.asset_code and action.known_at <= data.knowledge_cutoff,
            "RESTATEMENT_ACTION_SCOPE_OR_KNOWLEDGE_INVALID",
        )
        for row in (*action.cash_transfers, *action.share_transfers):
            _require(row.entry_id not in entries, "RESTATEMENT_DUPLICATE_TRANSFER")
            entries.add(row.entry_id)
            _require(
                action.effective_on <= row.accounting_on <= data.decision_day
                and row.recorded_at <= data.knowledge_cutoff,
                "RESTATEMENT_TRANSFER_SCOPE_OR_KNOWLEDGE_INVALID",
            )
    try:
        with localcontext() as context:
            context.prec = 96
            context.traps[Inexact] = True
            return _project_exact(data)
    except DecimalException as error:
        raise CorporateActionRestatementInvalid("RESTATEMENT_ARITHMETIC_INVALID") from error


def _project_exact(
    data: CorporateActionRestatementInput,
) -> tuple[RestatedCorporateActionValue, ...]:
    money = [data.current_cash, data.current_tax_payable]
    quantities = [data.current_position_quantity]
    for action in data.entitlements:
        money.extend((action.gross_cash, *(row.amount for row in action.cash_transfers)))
        quantities.extend((action.gross_shares, *(row.amount for row in action.share_transfers)))
    _require(
        all(amount.quantize(data.money_quantum) == amount for amount in money),
        "RESTATEMENT_CASH_PRECISION_INVALID",
    )
    _require(
        all(amount.quantize(data.quantity_quantum) == amount for amount in quantities),
        "RESTATEMENT_SHARE_PRECISION_INVALID",
    )
    base_cash = data.current_cash - sum(
        (_sum_transfers(action.cash_transfers) for action in data.entitlements), Decimal(0)
    )
    base_quantity = data.current_position_quantity - sum(
        (_sum_transfers(action.share_transfers) for action in data.entitlements), Decimal(0)
    )
    output: list[RestatedCorporateActionValue] = []
    for mark in data.marks:
        cash, physical, pending_cash, pending_shares = (
            base_cash,
            base_quantity,
            Decimal(0),
            Decimal(0),
        )
        for action in data.entitlements:
            paid = _sum_transfers(action.cash_transfers, mark.day)
            delivered = _sum_transfers(action.share_transfers, mark.day)
            entitled_cash = action.gross_cash if action.effective_on <= mark.day else Decimal(0)
            entitled_shares = action.gross_shares if action.effective_on <= mark.day else Decimal(0)
            _require(
                Decimal(0) <= paid <= entitled_cash and Decimal(0) <= delivered <= entitled_shares,
                "RESTATEMENT_TRANSFER_PREFIX_UNSUPPORTED",
            )
            cash += paid
            physical += delivered
            pending_cash += entitled_cash - paid
            pending_shares += entitled_shares - delivered
        _require(cash >= 0 and physical >= 0, "RESTATEMENT_NEGATIVE_PROJECTED_BALANCE")
        for amount in (cash, pending_cash, data.current_tax_payable):
            _require(
                amount.quantize(data.money_quantum) == amount, "RESTATEMENT_CASH_PRECISION_INVALID"
            )
        for quantity in (physical, pending_shares):
            _require(
                quantity.quantize(data.quantity_quantum) == quantity,
                "RESTATEMENT_SHARE_PRECISION_INVALID",
            )
        market = (physical + pending_shares) * mark.price
        total = cash + market + pending_cash - data.current_tax_payable
        _require(total >= 0, "RESTATEMENT_NEGATIVE_TOTAL")
        output.append(
            RestatedCorporateActionValue(
                mark.day,
                cash,
                physical,
                pending_shares,
                market,
                pending_cash,
                data.current_tax_payable,
                total,
            )
        )
    return tuple(output)
