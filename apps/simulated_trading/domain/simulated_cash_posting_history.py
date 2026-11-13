"""Pure replay checks for immutable simulated cash-action ledger rows."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, localcontext

from apps.simulated_trading.domain.corporate_action_posting import (
    CorporateActionEntryKind,
    CorporateActionKind,
    CorporateActionLedgerDelta,
    CorporateActionStage,
    CorporateActionStageRequest,
    calculate_corporate_action_delta,
)

_MAX_HISTORY_STEPS = 10_000
_ZERO = Decimal("0")
_CASH_STAGES = frozenset(
    {
        CorporateActionStage.CASH_ENTITLEMENT,
        CorporateActionStage.CASH_PAYMENT,
        CorporateActionStage.TAX_WITHHOLDING,
    }
)
_CASH_ENTRY_KINDS = frozenset(
    {
        CorporateActionEntryKind.POSTING,
        CorporateActionEntryKind.REVERSAL,
        CorporateActionEntryKind.SUCCESSOR,
    }
)


class SimulatedCashPostingHistoryValidationError(ValueError):
    """A persisted cash event cannot be replayed without breaking ledger rules."""


@dataclass(frozen=True, slots=True)
class SimulatedCashPostingHistoryStep:
    """One stored event row in its account-revision order."""

    account_revision: int
    request: CorporateActionStageRequest
    delta: CorporateActionLedgerDelta


def _supported_cash_decimal(value: Decimal) -> bool:
    """Accept one exact row amount within the persisted fifteen-digit cent schema."""

    if type(value) is not Decimal or not value.is_finite():
        return False
    parts = value.as_tuple()
    exponent = parts.exponent
    if type(exponent) is not int or exponent < -2 or len(parts.digits) > 15:
        return False
    integer_digits = max(len(parts.digits) + exponent, 0)
    return integer_digits <= 13


def validate_simulated_cash_posting_history(
    steps: tuple[SimulatedCashPostingHistoryStep, ...],
) -> None:
    """Replay one audited cash-dividend event and reject impossible intermediate balances.

    The caller supplies rows already ordered by their strictly increasing account
    revision. Revision gaps are allowed because unrelated account activity can occur
    between stages. Correction completeness and each reversal's exact target remain
    the caller's responsibility.
    """

    if type(steps) is not tuple or not steps or len(steps) > _MAX_HISTORY_STEPS:
        raise SimulatedCashPostingHistoryValidationError(
            "cash event history is empty, unbounded, or not an immutable sequence"
        )

    identity: tuple[int, str, str, CorporateActionKind, str, str] | None = None
    previous_revision = 0
    event_cash_receivable = _ZERO
    event_cash_paid = _ZERO
    event_tax_withheld = _ZERO

    with localcontext() as context:
        context.prec = 80
        for step in steps:
            if type(step) is not SimulatedCashPostingHistoryStep:
                raise SimulatedCashPostingHistoryValidationError(
                    "cash event history step is invalid"
                )
            if type(step.account_revision) is not int or step.account_revision <= previous_revision:
                raise SimulatedCashPostingHistoryValidationError(
                    "account revisions must be strictly increasing"
                )
            if (
                type(step.request) is not CorporateActionStageRequest
                or type(step.delta) is not CorporateActionLedgerDelta
            ):
                raise SimulatedCashPostingHistoryValidationError(
                    "cash event history step is invalid"
                )
            previous_revision = step.account_revision
            request = step.request
            delta = step.delta
            if (
                type(request.action_kind) is not CorporateActionKind
                or type(request.stage) is not CorporateActionStage
                or type(request.entry_kind) is not CorporateActionEntryKind
                or request.action_kind is not CorporateActionKind.CASH_DIVIDEND
                or request.stage not in _CASH_STAGES
                or request.entry_kind not in _CASH_ENTRY_KINDS
            ):
                raise SimulatedCashPostingHistoryValidationError(
                    "cash event history contains an unsupported action or stage"
                )
            current_identity = (
                request.account_id,
                request.source_namespace,
                request.source_event_id,
                request.action_kind,
                request.asset_code,
                request.security_id,
            )
            if identity is None:
                identity = current_identity
            elif current_identity != identity:
                raise SimulatedCashPostingHistoryValidationError(
                    "asset identity changed across source revisions"
                )

            if not all(
                _supported_cash_decimal(value) for value in (delta.cash, delta.cash_receivable)
            ):
                raise SimulatedCashPostingHistoryValidationError(
                    "cash event row contains an unsupported persisted amount"
                )
            share_deltas = (delta.shares, delta.share_receivable, delta.available_shares)
            if any(
                type(value) is not Decimal or not value.is_finite() or not value.is_zero()
                for value in share_deltas
            ):
                raise SimulatedCashPostingHistoryValidationError(
                    "cash event row contains an unrelated or unsupported share delta"
                )
            if request.entry_kind is not CorporateActionEntryKind.REVERSAL:
                if delta != calculate_corporate_action_delta(request):
                    raise SimulatedCashPostingHistoryValidationError(
                        "posting delta differs from its cash stage"
                    )

            if request.stage is CorporateActionStage.CASH_PAYMENT:
                if request.entry_kind is not CorporateActionEntryKind.REVERSAL:
                    if event_cash_receivable != -delta.cash_receivable:
                        raise SimulatedCashPostingHistoryValidationError(
                            "cash payment does not settle the full outstanding receivable"
                        )
                if event_cash_receivable < -delta.cash_receivable:
                    raise SimulatedCashPostingHistoryValidationError(
                        "cash payment exceeds its event receivable"
                    )
            if request.stage is CorporateActionStage.TAX_WITHHOLDING:
                if event_cash_paid - event_tax_withheld < -delta.cash:
                    raise SimulatedCashPostingHistoryValidationError(
                        "withholding exceeds the event's paid gross proceeds"
                    )

            event_cash_receivable += delta.cash_receivable
            if event_cash_receivable < _ZERO:
                raise SimulatedCashPostingHistoryValidationError(
                    "cash receivable becomes negative during event replay"
                )
            if request.stage is CorporateActionStage.CASH_PAYMENT:
                event_cash_paid += delta.cash
            if request.stage is CorporateActionStage.TAX_WITHHOLDING:
                event_tax_withheld -= delta.cash
            if event_tax_withheld < _ZERO or event_tax_withheld > event_cash_paid:
                raise SimulatedCashPostingHistoryValidationError(
                    "event withholding exceeds paid proceeds during replay"
                )


__all__ = (
    "SimulatedCashPostingHistoryStep",
    "SimulatedCashPostingHistoryValidationError",
    "validate_simulated_cash_posting_history",
)
