"""Contracts for replaying persisted simulated cash event balances."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import cast

import pytest

from apps.simulated_trading.domain.corporate_action_posting import (
    CorporateActionEntryKind,
    CorporateActionKind,
    CorporateActionLedgerDelta,
    CorporateActionStage,
    CorporateActionStageRequest,
    calculate_corporate_action_delta,
)
from apps.simulated_trading.domain.simulated_cash_posting_history import (
    SimulatedCashPostingHistoryStep,
    SimulatedCashPostingHistoryValidationError,
    validate_simulated_cash_posting_history,
)

_RECORD_DATE = date(2026, 11, 11)
_PAYMENT_DATE = date(2026, 11, 12)
_OBSERVED = datetime(2026, 11, 12, 3, 0, tzinfo=UTC)
_QUALIFIED = datetime(2026, 11, 12, 3, 1, tzinfo=UTC)
_POSTED = datetime(2026, 11, 12, 3, 2, tzinfo=UTC)


def _request(
    stage: CorporateActionStage,
    *,
    entry_kind: CorporateActionEntryKind = CorporateActionEntryKind.POSTING,
    revision_id: str = "revision-1",
    supersedes_revision_id: str | None = None,
    reversal_of_entry_id: int | None = None,
    amount: Decimal = Decimal("35.00"),
) -> CorporateActionStageRequest:
    """Build a structurally complete cash dividend stage for replay tests."""

    reversal = entry_kind is CorporateActionEntryKind.REVERSAL
    entitlement = stage is CorporateActionStage.CASH_ENTITLEMENT and not reversal
    payment = stage is CorporateActionStage.CASH_PAYMENT and not reversal
    withholding = stage is CorporateActionStage.TAX_WITHHOLDING and not reversal
    return CorporateActionStageRequest(
        account_id=7,
        owner_user_id=11,
        security_id="600000.SH",
        asset_code="equity-cn",
        asset_name="Synthetic Equity",
        source_namespace="exchange_official_disclosure",
        source_record_id="source-record-1",
        source_event_id="source-event-1",
        source_revision_id=revision_id,
        source_payload_sha256="a" * 64,
        qualification_sha256="b" * 64,
        qualifier_identity="szse_official_pdf.v1",
        source_observed_at=_OBSERVED,
        qualified_at=_QUALIFIED,
        posted_at=_POSTED,
        action_kind=CorporateActionKind.CASH_DIVIDEND,
        stage=stage,
        entry_kind=entry_kind,
        record_date=_RECORD_DATE,
        effective_date=_PAYMENT_DATE,
        stage_date=_RECORD_DATE if entitlement else _PAYMENT_DATE,
        cash_amount=None if reversal else amount,
        payment_date=_PAYMENT_DATE if payment else None,
        tax_treatment=None if reversal else "deferred_withholding",
        tax_rule_id="tax-rule-1" if withholding else None,
        tax_rule_sha256="c" * 64 if withholding else None,
        tax_basis_record_id="basis-1" if withholding else None,
        tax_basis_sha256="d" * 64 if withholding else None,
        ownership_snapshot_id="snapshot-1" if entitlement else None,
        ownership_snapshot_sha256="e" * 64 if entitlement else None,
        ownership_snapshot_as_of_date=_RECORD_DATE if entitlement else None,
        ownership_snapshot_observed_at=_QUALIFIED if entitlement else None,
        eligible_quantity=Decimal("70.000000") if entitlement else None,
        entitlement_calculation_sha256="f" * 64 if entitlement else None,
        supersedes_revision_id=supersedes_revision_id,
        reversal_of_entry_id=reversal_of_entry_id,
    )


def _step(
    account_revision: int,
    request: CorporateActionStageRequest,
    *,
    delta: CorporateActionLedgerDelta | None = None,
) -> SimulatedCashPostingHistoryStep:
    """Build one revision step, defaulting to the canonical posting delta."""

    return SimulatedCashPostingHistoryStep(
        account_revision=account_revision,
        request=request,
        delta=delta if delta is not None else calculate_corporate_action_delta(request),
    )


def _reversal_step(
    account_revision: int,
    request: CorporateActionStageRequest,
    original: SimulatedCashPostingHistoryStep,
) -> SimulatedCashPostingHistoryStep:
    """Build an exact inverse of one preceding cash stage."""

    return _step(
        account_revision,
        request,
        delta=CorporateActionLedgerDelta(
            cash=-original.delta.cash,
            cash_receivable=-original.delta.cash_receivable,
            shares=-original.delta.shares,
            share_receivable=-original.delta.share_receivable,
            available_shares=-original.delta.available_shares,
        ),
    )


def test_replays_full_payment_and_withholding_with_account_revision_gaps() -> None:
    entitlement = _step(4, _request(CorporateActionStage.CASH_ENTITLEMENT))
    payment = _step(9, _request(CorporateActionStage.CASH_PAYMENT))
    tax = _step(13, _request(CorporateActionStage.TAX_WITHHOLDING, amount=Decimal("5.25")))

    validate_simulated_cash_posting_history((entitlement, payment, tax))


def test_replays_orm_scale_zero_share_deltas_on_cash_rows() -> None:
    entitlement_request = _request(CorporateActionStage.CASH_ENTITLEMENT)
    payment_request = _request(CorporateActionStage.CASH_PAYMENT)
    zero_shares = Decimal("0.000000")
    entitlement = _step(
        4,
        entitlement_request,
        delta=CorporateActionLedgerDelta(
            cash_receivable=Decimal("35.00"),
            shares=zero_shares,
            share_receivable=zero_shares,
            available_shares=zero_shares,
        ),
    )
    payment = _step(
        9,
        payment_request,
        delta=CorporateActionLedgerDelta(
            cash=Decimal("35.00"),
            cash_receivable=Decimal("-35.00"),
            shares=zero_shares,
            share_receivable=zero_shares,
            available_shares=zero_shares,
        ),
    )

    validate_simulated_cash_posting_history((entitlement, payment))


def test_replays_cent_exact_money_with_legal_decimal_representation() -> None:
    amount = Decimal("3500E-2")
    entitlement = _step(
        1,
        _request(CorporateActionStage.CASH_ENTITLEMENT, amount=amount),
    )
    payment = _step(2, _request(CorporateActionStage.CASH_PAYMENT, amount=amount))

    validate_simulated_cash_posting_history((entitlement, payment))


def test_replays_complete_correction_then_late_payment_on_current_head() -> None:
    original_entitlement = _step(2, _request(CorporateActionStage.CASH_ENTITLEMENT))
    original_payment = _step(3, _request(CorporateActionStage.CASH_PAYMENT))
    original_tax = _step(
        4,
        _request(CorporateActionStage.TAX_WITHHOLDING, amount=Decimal("5.25")),
    )
    reverse_tax = _reversal_step(
        8,
        _request(
            CorporateActionStage.TAX_WITHHOLDING,
            entry_kind=CorporateActionEntryKind.REVERSAL,
            revision_id="revision-2",
            supersedes_revision_id="revision-1",
            reversal_of_entry_id=103,
        ),
        original_tax,
    )
    reverse_payment = _reversal_step(
        9,
        _request(
            CorporateActionStage.CASH_PAYMENT,
            entry_kind=CorporateActionEntryKind.REVERSAL,
            revision_id="revision-2",
            supersedes_revision_id="revision-1",
            reversal_of_entry_id=102,
        ),
        original_payment,
    )
    reverse_entitlement = _reversal_step(
        10,
        _request(
            CorporateActionStage.CASH_ENTITLEMENT,
            entry_kind=CorporateActionEntryKind.REVERSAL,
            revision_id="revision-2",
            supersedes_revision_id="revision-1",
            reversal_of_entry_id=101,
        ),
        original_entitlement,
    )
    successor_entitlement = _step(
        11,
        _request(
            CorporateActionStage.CASH_ENTITLEMENT,
            entry_kind=CorporateActionEntryKind.SUCCESSOR,
            revision_id="revision-2",
            supersedes_revision_id="revision-1",
        ),
    )
    late_payment = _step(
        17,
        _request(CorporateActionStage.CASH_PAYMENT, revision_id="revision-2"),
    )

    validate_simulated_cash_posting_history(
        (
            original_entitlement,
            original_payment,
            original_tax,
            reverse_tax,
            reverse_payment,
            reverse_entitlement,
            successor_entitlement,
            late_payment,
        )
    )


def test_rejects_reversing_payment_before_its_withholding() -> None:
    entitlement = _step(1, _request(CorporateActionStage.CASH_ENTITLEMENT))
    payment = _step(2, _request(CorporateActionStage.CASH_PAYMENT))
    tax = _step(3, _request(CorporateActionStage.TAX_WITHHOLDING, amount=Decimal("5.00")))
    reverse_payment = _reversal_step(
        4,
        _request(
            CorporateActionStage.CASH_PAYMENT,
            entry_kind=CorporateActionEntryKind.REVERSAL,
            revision_id="revision-2",
            supersedes_revision_id="revision-1",
            reversal_of_entry_id=102,
        ),
        payment,
    )
    reverse_tax = _reversal_step(
        5,
        _request(
            CorporateActionStage.TAX_WITHHOLDING,
            entry_kind=CorporateActionEntryKind.REVERSAL,
            revision_id="revision-2",
            supersedes_revision_id="revision-1",
            reversal_of_entry_id=103,
        ),
        tax,
    )

    with pytest.raises(
        SimulatedCashPostingHistoryValidationError,
        match="event withholding exceeds paid proceeds during replay",
    ):
        validate_simulated_cash_posting_history(
            (entitlement, payment, tax, reverse_payment, reverse_tax)
        )


@pytest.mark.parametrize(
    ("steps", "message"),
    (
        (
            (_step(1, _request(CorporateActionStage.CASH_PAYMENT)),),
            "cash payment does not settle the full outstanding receivable",
        ),
        (
            (
                _step(1, _request(CorporateActionStage.CASH_ENTITLEMENT)),
                _step(
                    2,
                    _request(CorporateActionStage.CASH_PAYMENT, amount=Decimal("20.00")),
                ),
            ),
            "cash payment does not settle the full outstanding receivable",
        ),
        (
            (
                _step(1, _request(CorporateActionStage.CASH_ENTITLEMENT)),
                _step(2, _request(CorporateActionStage.CASH_PAYMENT)),
                _step(
                    3,
                    _request(CorporateActionStage.TAX_WITHHOLDING, amount=Decimal("35.01")),
                ),
            ),
            "withholding exceeds the event's paid gross proceeds",
        ),
    ),
)
def test_rejects_payment_or_tax_that_exceeds_recorded_event_basis(
    steps: tuple[SimulatedCashPostingHistoryStep, ...],
    message: str,
) -> None:
    with pytest.raises(SimulatedCashPostingHistoryValidationError, match=message):
        validate_simulated_cash_posting_history(steps)


def test_rejects_reversing_entitlement_before_its_payment() -> None:
    entitlement = _step(1, _request(CorporateActionStage.CASH_ENTITLEMENT))
    payment = _step(2, _request(CorporateActionStage.CASH_PAYMENT))
    reverse_entitlement = _reversal_step(
        3,
        _request(
            CorporateActionStage.CASH_ENTITLEMENT,
            entry_kind=CorporateActionEntryKind.REVERSAL,
            revision_id="revision-2",
            supersedes_revision_id="revision-1",
            reversal_of_entry_id=101,
        ),
        entitlement,
    )

    with pytest.raises(
        SimulatedCashPostingHistoryValidationError,
        match="cash receivable becomes negative during event replay",
    ):
        validate_simulated_cash_posting_history((entitlement, payment, reverse_entitlement))


def test_rejects_asset_identity_change_between_source_revisions() -> None:
    entitlement = _request(CorporateActionStage.CASH_ENTITLEMENT)
    successor = replace(
        entitlement,
        entry_kind=CorporateActionEntryKind.SUCCESSOR,
        source_revision_id="revision-2",
        supersedes_revision_id="revision-1",
        asset_code="000001.SZ",
        security_id="000001.SZ",
    )

    with pytest.raises(
        SimulatedCashPostingHistoryValidationError,
        match="asset identity changed across source revisions",
    ):
        validate_simulated_cash_posting_history((_step(1, entitlement), _step(2, successor)))


def test_rejects_non_increasing_account_revision_without_requiring_contiguity() -> None:
    entitlement = _step(2, _request(CorporateActionStage.CASH_ENTITLEMENT))
    payment = _step(2, _request(CorporateActionStage.CASH_PAYMENT))

    with pytest.raises(
        SimulatedCashPostingHistoryValidationError,
        match="account revisions must be strictly increasing",
    ):
        validate_simulated_cash_posting_history((entitlement, payment))

    bool_revision = SimulatedCashPostingHistoryStep(
        account_revision=True,
        request=_request(CorporateActionStage.CASH_ENTITLEMENT),
        delta=calculate_corporate_action_delta(_request(CorporateActionStage.CASH_ENTITLEMENT)),
    )
    with pytest.raises(
        SimulatedCashPostingHistoryValidationError,
        match="account revisions must be strictly increasing",
    ):
        validate_simulated_cash_posting_history((bool_revision,))


@pytest.mark.parametrize(
    "step",
    (
        SimulatedCashPostingHistoryStep(
            account_revision=1,
            request=cast(CorporateActionStageRequest, None),
            delta=CorporateActionLedgerDelta(),
        ),
        SimulatedCashPostingHistoryStep(
            account_revision=1,
            request=cast(CorporateActionStageRequest, None),
            delta=cast(CorporateActionLedgerDelta, None),
        ),
    ),
)
def test_rejects_step_without_typed_request_and_delta(
    step: SimulatedCashPostingHistoryStep,
) -> None:
    with pytest.raises(
        SimulatedCashPostingHistoryValidationError,
        match="cash event history step is invalid",
    ):
        validate_simulated_cash_posting_history((step,))


def test_rejects_posting_delta_that_disagrees_with_its_stage() -> None:
    entitlement = _request(CorporateActionStage.CASH_ENTITLEMENT)
    bad_delta = CorporateActionLedgerDelta(cash=Decimal("1.00"))

    with pytest.raises(
        SimulatedCashPostingHistoryValidationError,
        match="posting delta differs from its cash stage",
    ):
        validate_simulated_cash_posting_history((_step(1, entitlement, delta=bad_delta),))


@pytest.mark.parametrize(
    "bad_amount",
    (
        Decimal("NaN"),
        Decimal("0.001"),
        Decimal("1E+19"),
        Decimal("1234567890123456"),
    ),
)
def test_rejects_nonfinite_or_unrepresentable_persisted_amounts(bad_amount: Decimal) -> None:
    entitlement = _request(CorporateActionStage.CASH_ENTITLEMENT)
    bad_delta = CorporateActionLedgerDelta(cash_receivable=bad_amount)

    with pytest.raises(
        SimulatedCashPostingHistoryValidationError,
        match="unsupported persisted amount",
    ):
        validate_simulated_cash_posting_history((_step(1, entitlement, delta=bad_delta),))


def test_rejects_history_without_bounded_immutable_steps() -> None:
    with pytest.raises(
        SimulatedCashPostingHistoryValidationError,
        match="history is empty, unbounded, or not an immutable sequence",
    ):
        validate_simulated_cash_posting_history(())

    entitlement = _step(1, _request(CorporateActionStage.CASH_ENTITLEMENT))
    with pytest.raises(
        SimulatedCashPostingHistoryValidationError,
        match="history is empty, unbounded, or not an immutable sequence",
    ):
        validate_simulated_cash_posting_history(
            cast(tuple[SimulatedCashPostingHistoryStep, ...], [entitlement])
        )

    with pytest.raises(
        SimulatedCashPostingHistoryValidationError,
        match="history step is invalid",
    ):
        validate_simulated_cash_posting_history(
            cast(tuple[SimulatedCashPostingHistoryStep, ...], (None,))
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("action_kind", CorporateActionKind.SHARE_DISTRIBUTION),
        ("stage", CorporateActionStage.SHARE_DELIVERY),
        ("entry_kind", CorporateActionEntryKind.NO_EFFECT),
    ),
)
def test_rejects_unsupported_cash_action_stage_or_entry_kind(
    field: str,
    value: object,
) -> None:
    request = _request(CorporateActionStage.CASH_ENTITLEMENT)
    object.__setattr__(request, field, value)

    with pytest.raises(
        SimulatedCashPostingHistoryValidationError,
        match="unsupported action or stage",
    ):
        validate_simulated_cash_posting_history(
            (_step(1, request, delta=CorporateActionLedgerDelta()),)
        )


def test_rejects_share_delta_in_cash_history() -> None:
    entitlement = _request(CorporateActionStage.CASH_ENTITLEMENT)
    bad_delta = CorporateActionLedgerDelta(
        cash_receivable=Decimal("35.00"),
        shares=Decimal("1.00"),
    )

    with pytest.raises(
        SimulatedCashPostingHistoryValidationError,
        match="unrelated or unsupported share delta",
    ):
        validate_simulated_cash_posting_history((_step(1, entitlement, delta=bad_delta),))


@pytest.mark.parametrize(
    "share_delta",
    (Decimal("NaN"), Decimal("1.000000")),
)
def test_rejects_nonfinite_or_nonzero_share_delta(share_delta: Decimal) -> None:
    entitlement = _request(CorporateActionStage.CASH_ENTITLEMENT)
    bad_delta = CorporateActionLedgerDelta(
        cash_receivable=Decimal("35.00"),
        shares=share_delta,
    )

    with pytest.raises(
        SimulatedCashPostingHistoryValidationError,
        match="share delta",
    ):
        validate_simulated_cash_posting_history((_step(1, entitlement, delta=bad_delta),))


def test_rejects_payment_reversal_exceeding_current_event_receivable() -> None:
    entitlement = _step(
        1,
        _request(CorporateActionStage.CASH_ENTITLEMENT, amount=Decimal("20.00")),
    )
    reversed_payment = _request(
        CorporateActionStage.CASH_PAYMENT,
        entry_kind=CorporateActionEntryKind.REVERSAL,
        revision_id="revision-2",
        supersedes_revision_id="revision-1",
        reversal_of_entry_id=102,
    )
    bad_reversal = _step(
        2,
        reversed_payment,
        delta=CorporateActionLedgerDelta(
            cash=Decimal("-35.00"),
            cash_receivable=Decimal("-35.00"),
        ),
    )

    with pytest.raises(
        SimulatedCashPostingHistoryValidationError,
        match="cash payment exceeds its event receivable",
    ):
        validate_simulated_cash_posting_history((entitlement, bad_reversal))
