"""Exact simulated balance projections including unpaid disposition tax.

Gross cash, unpaid liabilities and existing order reservations remain distinct.
Unknown facts never become zero, and recognition/collection cannot expense the
same tax twice. This module grants no source qualification or write authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, localcontext
from enum import StrEnum

from apps.simulated_trading.domain.corporate_action_deferred_tax import (
    DeferredDividendTaxValidationError,
)
from apps.simulated_trading.domain.corporate_action_tax_liability import (
    _money,
    _positive_quantum,
    _require_quantized,
)
from apps.simulated_trading.domain.simulated_dividend_tax_policy_scope import (
    SimulatedDividendTaxCurrency,
)


class TaxBalanceBlockReason(StrEnum):
    """Stable reasons why a financial snapshot cannot support a decision."""

    SOURCE_INCOMPLETE = "TAX_BALANCE_SOURCE_INCOMPLETE"
    CASH_BALANCE_UNKNOWN = "CASH_BALANCE_UNKNOWN"
    POSITION_VALUATION_UNKNOWN = "POSITION_VALUATION_UNKNOWN"
    DIVIDEND_RECEIVABLE_UNKNOWN = "DIVIDEND_RECEIVABLE_UNKNOWN"
    TAX_PAYABLE_UNKNOWN = "TAX_PAYABLE_UNKNOWN"
    ORDER_CASH_RESERVATION_UNKNOWN = "ORDER_CASH_RESERVATION_UNKNOWN"
    TAX_ASSESSMENT_NOT_APPLIED = "TAX_ASSESSMENT_NOT_APPLIED"
    TAX_EVIDENCE_UNAVAILABLE = "TAX_EVIDENCE_UNAVAILABLE"
    TAX_LEDGER_CORRUPT = "TAX_LEDGER_CORRUPT"


@dataclass(frozen=True, slots=True)
class CorporateActionTaxBalance:
    """Known original balance facts and exact debt-adjusted projections.

    Callers independently verify complete assessment/journal/Audit provenance,
    the real account owner, current holds and the raw-price position marks.
    A declared blocker or incomplete evidence prevents both projections.
    """

    currency: SimulatedDividendTaxCurrency
    currency_quantum: Decimal
    book_cash: Decimal | None
    marked_assets: Decimal | None
    dividend_receivable: Decimal | None
    tax_payable: Decimal | None
    order_cash_reserved: Decimal | None
    source_complete: bool
    declared_blockers: tuple[TaxBalanceBlockReason, ...]

    def __post_init__(self) -> None:
        """Require explicit exact currency values and reconciled existing reservations."""
        if (
            type(self.currency) is not SimulatedDividendTaxCurrency
            or self.currency is not SimulatedDividendTaxCurrency.CNY
            or type(self.source_complete) is not bool
            or type(self.declared_blockers) is not tuple
            or any(type(reason) is not TaxBalanceBlockReason for reason in self.declared_blockers)
            or len(set(self.declared_blockers)) != len(self.declared_blockers)
        ):
            raise DeferredDividendTaxValidationError(
                "tax balance scope or evidence state is invalid"
            )
        quantum = _positive_quantum(self.currency_quantum)
        for name, value in (
            ("book_cash", self.book_cash),
            ("marked_assets", self.marked_assets),
            ("dividend_receivable", self.dividend_receivable),
            ("tax_payable", self.tax_payable),
            ("order_cash_reserved", self.order_cash_reserved),
        ):
            if value is not None:
                amount = _money(value, name)
                _require_quantized(amount, quantum, name)
        if (
            self.book_cash is not None
            and self.order_cash_reserved is not None
            and self.order_cash_reserved > self.book_cash
        ):
            raise DeferredDividendTaxValidationError(
                "active order cash exceeds the actual book balance"
            )

    @property
    def blocking_reasons(self) -> tuple[TaxBalanceBlockReason, ...]:
        """Publish declared and derived missing-data reasons in stable unique order."""
        reasons = set(self.declared_blockers)
        if not self.source_complete:
            reasons.add(TaxBalanceBlockReason.SOURCE_INCOMPLETE)
        for amount, reason in (
            (self.book_cash, TaxBalanceBlockReason.CASH_BALANCE_UNKNOWN),
            (self.marked_assets, TaxBalanceBlockReason.POSITION_VALUATION_UNKNOWN),
            (self.dividend_receivable, TaxBalanceBlockReason.DIVIDEND_RECEIVABLE_UNKNOWN),
            (self.tax_payable, TaxBalanceBlockReason.TAX_PAYABLE_UNKNOWN),
            (self.order_cash_reserved, TaxBalanceBlockReason.ORDER_CASH_RESERVATION_UNKNOWN),
        ):
            if amount is None:
                reasons.add(reason)
        return tuple(sorted(reasons, key=lambda item: item.value))

    @property
    def must_not_use_for_decision(self) -> bool:
        """Mark the full snapshot unusable while any required fact is unresolved."""
        return bool(self.blocking_reasons)

    @property
    def net_asset_value(self) -> Decimal | None:
        """Subtract unpaid tax once from cash, raw-price assets and dividend receivables."""
        if self.must_not_use_for_decision:
            return None
        cash, assets, receivable, debt = (
            self.book_cash,
            self.marked_assets,
            self.dividend_receivable,
            self.tax_payable,
        )
        if cash is None or assets is None or receivable is None or debt is None:
            return None
        # Each validated input has at most68 integer and12 fractional places.
        # Summing three such values needs at most81 significant digits.
        with localcontext() as context:
            context.prec = 96
            return cash + assets + receivable - debt

    @property
    def spendable_cash(self) -> Decimal | None:
        """Protect both existing order holds and unpaid tax from new spending."""
        if not self.source_complete or self.declared_blockers:
            return None
        cash, holds, debt = self.book_cash, self.order_cash_reserved, self.tax_payable
        if cash is None or holds is None or debt is None:
            return None
        with localcontext() as context:
            context.prec = 96
            return max(Decimal("0"), cash - holds - debt)


__all__ = ["CorporateActionTaxBalance", "TaxBalanceBlockReason"]
