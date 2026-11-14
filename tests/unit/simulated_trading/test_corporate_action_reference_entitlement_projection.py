"""Pure projection-reference contracts for verified current action coverage.

Source documents and unsaved posting rows are synthetic. They exercise the
existing current-entitlement validation and do not grant financial authority.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from apps.data_center.domain.security_disclosure_event import (
    SecurityDisclosureEvent,
    SecurityDisclosureEventType,
    SecurityDisclosureExchange,
    SecurityDisclosureSource,
    SzseDistributionTerms,
)
from apps.simulated_trading import corporate_action_current_entitlement_coverage as coverage
from apps.simulated_trading.domain.corporate_action_ownership_history import (
    RecordDateOwnershipProof,
)
from apps.simulated_trading.domain.corporate_action_performance_projection import (
    RestatementEntitlement,
)
from apps.simulated_trading.domain.corporate_action_posting import (
    CorporateActionEntryKind,
    CorporateActionKind,
    CorporateActionLedgerDelta,
    CorporateActionStage,
    CorporateActionStageRequest,
    calculate_corporate_action_delta,
)
from apps.simulated_trading.infrastructure.corporate_action_posting_models import (
    CorporateActionPostingModel,
)
from apps.simulated_trading.infrastructure.corporate_action_posting_repository import (
    DjangoCorporateActionPostingRepository,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    SimulatedAccountModel,
)
from apps.simulated_trading.official_disclosure_action_composition import (
    szse_action_qualification_sha256,
)

_ASSET = "000001.SZ"
_ACCOUNT_ID = 4101
_OWNER_ID = 8101
_LOGICAL_EVENT_ID = "fca1e323-1c2e-44c8-8c5c-1b73c1699000"
_SOURCE_EVENT_ID = "fca1e323-1c2e-44c8-8c5c-1b73c1699001"
_RECORD_DATE = date(2026, 10, 30)
_EX_DATE = date(2026, 10, 31)
_PAYMENT_DATE = date(2026, 11, 5)
_DELIVERY_DATE = date(2026, 11, 3)
_SELLABLE_DATE = date(2026, 11, 5)
_SOURCE_SEEN = datetime(2026, 10, 20, 1, 0, tzinfo=UTC)
_PROOF_OBSERVED = datetime(2026, 11, 1, 1, 0, tzinfo=UTC)
_RECORD_DATE_END = datetime(2026, 10, 31, 0, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def _event(
    *,
    event_type: SecurityDisclosureEventType = SecurityDisclosureEventType.CASH_DIVIDEND,
    source_event_id: str = _SOURCE_EVENT_ID,
    first_seen_at: datetime = _SOURCE_SEEN,
    prior: SecurityDisclosureEvent | None = None,
) -> SecurityDisclosureEvent:
    """Build an explicitly synthetic official-shaped source revision."""
    body = f"synthetic current source:{source_event_id}:{event_type.value}".encode("ascii")
    revision = f"sha256:{hashlib.sha256(body).hexdigest()}"
    return SecurityDisclosureEvent.from_source_document(
        source=SecurityDisclosureSource.SZSE_OFFICIAL,
        exchange=SecurityDisclosureExchange.SZSE,
        asset_code=_ASSET,
        source_security_code=_ASSET[:6],
        source_event_id=source_event_id,
        source_revision_id=revision,
        raw_event_type=event_type.value,
        event_type=event_type,
        source_url=f"https://disc.static.szse.cn/synthetic/{source_event_id}.PDF",
        source_document_body=body,
        first_seen_at=first_seen_at,
        effective_at=_EX_DATE,
        supersedes_source_event_id=prior.source_event_id if prior is not None else None,
        supersedes_source_revision_id=prior.source_revision_id if prior is not None else None,
    )


def _terms(
    *,
    event_type: SecurityDisclosureEventType = SecurityDisclosureEventType.CASH_DIVIDEND,
    cash_per_ten: Decimal = Decimal("1.23"),
) -> SzseDistributionTerms:
    """Return exact synthetic cash or stock terms without guessed rounding."""
    is_cash = event_type is SecurityDisclosureEventType.CASH_DIVIDEND
    return SzseDistributionTerms(
        record_date=_RECORD_DATE,
        ex_date=_EX_DATE,
        payment_date=_PAYMENT_DATE if is_cash else None,
        cash_per_ten=cash_per_ten if is_cash else None,
        shares_per_ten=None if is_cash else Decimal("1.00"),
        tax_treatment="deferred_withholding" if is_cash else "not_applicable",
        share_delivery_date=None if is_cash else _DELIVERY_DATE,
        share_sellable_date=None if is_cash else _SELLABLE_DATE,
    )


def _proof(
    *,
    observed_at: datetime = _PROOF_OBSERVED,
    quantity: Decimal = Decimal("100.000000"),
) -> RecordDateOwnershipProof:
    """Return one synthetic complete closed-date proof for unit-level replay."""
    return RecordDateOwnershipProof(
        account_id=_ACCOUNT_ID,
        owner_user_id=_OWNER_ID,
        security_id=_ASSET,
        asset_code=_ASSET,
        record_date=_RECORD_DATE,
        ownership_snapshot_as_of_date=_RECORD_DATE,
        record_date_end_exclusive=_RECORD_DATE_END,
        exchange="SZSE",
        exchange_timezone_name="Asia/Shanghai",
        cutoff_policy_id="synthetic-exchange-timezone-policy",
        cutoff_policy_sha256="a" * 64,
        eligible_quantity=quantity,
        ownership_snapshot_id="synthetic-record-date-snapshot",
        ownership_snapshot_sha256="b" * 64,
        ownership_snapshot_observed_at=observed_at,
    )


def _request(
    *,
    event: SecurityDisclosureEvent,
    terms: SzseDistributionTerms,
    proof: RecordDateOwnershipProof,
    stage: CorporateActionStage,
    amount: Decimal,
    posted_at: datetime,
    qualified_at: datetime = _PROOF_OBSERVED,
    entry_kind: CorporateActionEntryKind = CorporateActionEntryKind.POSTING,
    supersedes_revision_id: str | None = None,
    reversal_of_entry_id: int | None = None,
) -> CorporateActionStageRequest:
    """Build one real Domain request with stage-local clocks and terms."""
    event_type = event.event_type
    is_cash = event_type is SecurityDisclosureEventType.CASH_DIVIDEND
    is_entitlement = stage in {
        CorporateActionStage.CASH_ENTITLEMENT,
        CorporateActionStage.SHARE_ENTITLEMENT,
    }
    is_reversal = entry_kind is CorporateActionEntryKind.REVERSAL
    if stage is CorporateActionStage.CASH_ENTITLEMENT:
        stage_date = terms.record_date
    elif stage is CorporateActionStage.CASH_PAYMENT:
        stage_date = terms.payment_date
    elif stage is CorporateActionStage.SHARE_ENTITLEMENT:
        stage_date = terms.record_date
    elif stage is CorporateActionStage.SHARE_DELIVERY:
        stage_date = terms.share_delivery_date
    else:
        stage_date = terms.share_sellable_date
    if type(stage_date) is not date:
        raise AssertionError("synthetic stage date is incomplete")
    cash_amount = amount if is_cash and not is_reversal else None
    share_amount = amount if not is_cash and not is_reversal else None
    return CorporateActionStageRequest(
        account_id=_ACCOUNT_ID,
        owner_user_id=_OWNER_ID,
        security_id=_ASSET,
        asset_code=_ASSET,
        asset_name="Synthetic test security",
        source_namespace="exchange_official_disclosure",
        source_record_id=event.source_event_id,
        source_event_id=_LOGICAL_EVENT_ID,
        source_revision_id=event.source_revision_id,
        source_payload_sha256=event.source_body_sha256,
        qualification_sha256=szse_action_qualification_sha256(event, terms),
        qualifier_identity="szse_official_pdf.v1",
        source_observed_at=event.first_seen_at,
        qualified_at=qualified_at,
        posted_at=posted_at,
        action_kind=(
            CorporateActionKind.CASH_DIVIDEND if is_cash else CorporateActionKind.SHARE_DISTRIBUTION
        ),
        stage=stage,
        entry_kind=entry_kind,
        record_date=terms.record_date,
        effective_date=terms.ex_date,
        stage_date=stage_date,
        cash_amount=cash_amount,
        share_amount=share_amount,
        payment_date=terms.payment_date if stage is CorporateActionStage.CASH_PAYMENT else None,
        sellable_date=(
            terms.share_sellable_date
            if stage
            in {
                CorporateActionStage.SHARE_DELIVERY,
                CorporateActionStage.SHARE_SELLABLE_RELEASE,
            }
            else None
        ),
        tax_treatment=None if is_reversal else terms.tax_treatment,
        ownership_snapshot_id=(
            proof.ownership_snapshot_id if is_entitlement and not is_reversal else None
        ),
        ownership_snapshot_sha256=(
            proof.ownership_snapshot_sha256 if is_entitlement and not is_reversal else None
        ),
        ownership_snapshot_as_of_date=(
            proof.ownership_snapshot_as_of_date if is_entitlement and not is_reversal else None
        ),
        ownership_snapshot_observed_at=(
            proof.ownership_snapshot_observed_at if is_entitlement and not is_reversal else None
        ),
        eligible_quantity=(proof.eligible_quantity if is_entitlement and not is_reversal else None),
        entitlement_calculation_sha256=("e" * 64 if is_entitlement and not is_reversal else None),
        odd_lot_policy=None if is_cash else "whole_shares",
        supersedes_revision_id=supersedes_revision_id,
        reversal_of_entry_id=reversal_of_entry_id,
    )


def _row(
    request: CorporateActionStageRequest,
    *,
    entry_id: int,
    account_revision: int,
    created_at: datetime | None,
    reversal_target: CorporateActionPostingModel | None = None,
    delta: CorporateActionLedgerDelta | None = None,
) -> CorporateActionPostingModel:
    """Map a real request to an unsaved posting model row with retained clocks."""
    account = SimulatedAccountModel(pk=_ACCOUNT_ID, user_id=_OWNER_ID)
    row = DjangoCorporateActionPostingRepository._make_row(
        request=request,
        account=account,
        account_revision=account_revision,
        delta=delta or calculate_corporate_action_delta(request),
        reverses=reversal_target,
    )
    row.pk = entry_id
    row.created_at = created_at
    return row


def _inverse(delta: CorporateActionLedgerDelta) -> CorporateActionLedgerDelta:
    """Return the exact signed reversal for one synthetic original posting."""
    return CorporateActionLedgerDelta(
        cash=delta.cash.copy_negate(),
        cash_receivable=delta.cash_receivable.copy_negate(),
        shares=delta.shares.copy_negate(),
        share_receivable=delta.share_receivable.copy_negate(),
        available_shares=delta.available_shares.copy_negate(),
    )


def _inspect(
    *,
    event: SecurityDisclosureEvent,
    terms: SzseDistributionTerms,
    proof: RecordDateOwnershipProof,
    rows: tuple[CorporateActionPostingModel, ...],
) -> coverage.CurrentAssetEntitlementCoverage:
    """Call the real read-only current entitlement validator on synthetic rows."""
    return coverage.inspect_current_distribution_entitlement(
        event=event,
        terms=terms,
        logical_source_event_id=_LOGICAL_EVENT_ID,
        proof=proof,
        rows=rows,
    )


def test_cash_reference_uses_all_verified_reversal_and_late_payment_rows() -> None:
    """Retain original transfer signs and use posted-at local dates, never stage dates."""
    old_event = _event()
    old_terms = _terms(cash_per_ten=Decimal("1.00"))
    old_proof = _proof()
    old_qualified = datetime(2026, 11, 1, 2, 0, tzinfo=UTC)
    old_entitlement_request = _request(
        event=old_event,
        terms=old_terms,
        proof=old_proof,
        stage=CorporateActionStage.CASH_ENTITLEMENT,
        amount=Decimal("10.00"),
        posted_at=datetime(2026, 11, 1, 2, 1, tzinfo=UTC),
        qualified_at=old_qualified,
    )
    old_entitlement = _row(
        old_entitlement_request,
        entry_id=101,
        account_revision=1,
        created_at=datetime(2026, 11, 1, 2, 2, tzinfo=UTC),
    )
    old_payment_request = _request(
        event=old_event,
        terms=old_terms,
        proof=old_proof,
        stage=CorporateActionStage.CASH_PAYMENT,
        amount=Decimal("10.00"),
        posted_at=datetime(2026, 11, 8, 1, 0, tzinfo=UTC),
        qualified_at=old_qualified,
    )
    old_payment = _row(
        old_payment_request,
        entry_id=102,
        account_revision=2,
        created_at=datetime(2026, 11, 8, 1, 1, tzinfo=UTC),
    )

    current_event = _event(
        source_event_id="fca1e323-1c2e-44c8-8c5c-1b73c1699002",
        first_seen_at=datetime(2026, 11, 9, 0, 0, tzinfo=UTC),
        prior=old_event,
    )
    current_terms = _terms(cash_per_ten=Decimal("1.23"))
    current_proof = _proof(observed_at=datetime(2026, 11, 9, 0, 30, tzinfo=UTC))
    qualified_at = datetime(2026, 11, 9, 0, 45, tzinfo=UTC)
    correction_posted_at = datetime(2026, 11, 9, 1, 0, tzinfo=UTC)
    reversal_payment_request = _request(
        event=current_event,
        terms=current_terms,
        proof=current_proof,
        stage=CorporateActionStage.CASH_PAYMENT,
        amount=Decimal("0.00"),
        posted_at=correction_posted_at,
        qualified_at=qualified_at,
        entry_kind=CorporateActionEntryKind.REVERSAL,
        supersedes_revision_id=old_event.source_revision_id,
        reversal_of_entry_id=old_payment.pk,
    )
    reversal_payment = _row(
        reversal_payment_request,
        entry_id=103,
        account_revision=3,
        created_at=datetime(2026, 11, 9, 1, 1, tzinfo=UTC),
        reversal_target=old_payment,
        delta=_inverse(
            CorporateActionLedgerDelta(
                cash=old_payment.cash_delta,
                cash_receivable=old_payment.cash_receivable_delta,
                shares=old_payment.share_delta,
                share_receivable=old_payment.share_receivable_delta,
                available_shares=old_payment.available_share_delta,
            )
        ),
    )
    reversal_entitlement_request = _request(
        event=current_event,
        terms=current_terms,
        proof=current_proof,
        stage=CorporateActionStage.CASH_ENTITLEMENT,
        amount=Decimal("0.00"),
        posted_at=correction_posted_at,
        qualified_at=qualified_at,
        entry_kind=CorporateActionEntryKind.REVERSAL,
        supersedes_revision_id=old_event.source_revision_id,
        reversal_of_entry_id=old_entitlement.pk,
    )
    reversal_entitlement = _row(
        reversal_entitlement_request,
        entry_id=104,
        account_revision=4,
        created_at=datetime(2026, 11, 9, 1, 3, tzinfo=UTC),
        reversal_target=old_entitlement,
        delta=_inverse(
            CorporateActionLedgerDelta(
                cash=old_entitlement.cash_delta,
                cash_receivable=old_entitlement.cash_receivable_delta,
                shares=old_entitlement.share_delta,
                share_receivable=old_entitlement.share_receivable_delta,
                available_shares=old_entitlement.available_share_delta,
            )
        ),
    )
    current_entitlement_request = _request(
        event=current_event,
        terms=current_terms,
        proof=current_proof,
        stage=CorporateActionStage.CASH_ENTITLEMENT,
        amount=Decimal("12.30"),
        posted_at=correction_posted_at,
        qualified_at=qualified_at,
        entry_kind=CorporateActionEntryKind.SUCCESSOR,
        supersedes_revision_id=old_event.source_revision_id,
    )
    current_entitlement = _row(
        current_entitlement_request,
        entry_id=105,
        account_revision=5,
        created_at=datetime(2026, 11, 9, 1, 3, tzinfo=UTC),
    )
    current_payment_request = _request(
        event=current_event,
        terms=current_terms,
        proof=current_proof,
        stage=CorporateActionStage.CASH_PAYMENT,
        amount=Decimal("12.30"),
        posted_at=correction_posted_at,
        qualified_at=qualified_at,
        entry_kind=CorporateActionEntryKind.SUCCESSOR,
        supersedes_revision_id=old_event.source_revision_id,
    )
    current_payment = _row(
        current_payment_request,
        entry_id=106,
        account_revision=6,
        created_at=datetime(2026, 11, 9, 1, 4, tzinfo=UTC),
    )
    rows = (
        old_entitlement,
        old_payment,
        reversal_payment,
        reversal_entitlement,
        current_entitlement,
        current_payment,
    )

    result = _inspect(event=current_event, terms=current_terms, proof=current_proof, rows=rows)

    assert result.cash_complete is True
    references = result.current_entitlement_references
    assert references is not None and len(references) == 1
    reference = references[0]
    assert reference.record_date == _RECORD_DATE
    assert reference.reference_quantity == Decimal("100.000000")
    assert reference.exchange_timezone_name == "Asia/Shanghai"
    assert reference.source_event_id == current_event.source_event_id
    assert reference.logical_source_event_id == _LOGICAL_EVENT_ID
    assert reference.source_revision_id == current_event.source_revision_id
    assert reference.source_body_sha256 == current_event.source_body_sha256
    assert reference.event_content_sha256 == current_event.content_hash
    entitlement = reference.restatement_entitlement
    assert type(entitlement) is RestatementEntitlement
    assert entitlement.action_id == _LOGICAL_EVENT_ID
    assert entitlement.effective_on == _EX_DATE
    assert entitlement.gross_cash == Decimal("12.30")
    assert entitlement.gross_shares == Decimal("0")
    assert tuple(item.amount for item in entitlement.cash_transfers) == (
        Decimal("10.00"),
        Decimal("-10.00"),
        Decimal("12.30"),
    )
    assert tuple(item.entry_id for item in entitlement.cash_transfers) == (
        "102",
        "103",
        "106",
    )
    local = ZoneInfo("Asia/Shanghai")
    assert tuple(item.accounting_on for item in entitlement.cash_transfers) == tuple(
        row.posted_at.astimezone(local).date()
        for row in (old_payment, reversal_payment, current_payment)
    )
    assert entitlement.cash_transfers[-1].accounting_on != current_payment.stage_date
    assert entitlement.cash_transfers[-1].recorded_at == current_payment.created_at
    assert entitlement.known_at == current_payment.created_at


def test_share_projection_uses_delivery_transfer_not_scheduled_dates_or_release() -> None:
    """Use exact share delivery delta at its original posted-at exchange-local date."""
    event = _event(event_type=SecurityDisclosureEventType.STOCK_DIVIDEND)
    terms = _terms(event_type=SecurityDisclosureEventType.STOCK_DIVIDEND)
    proof = _proof()
    qualified_at = datetime(2026, 11, 1, 2, 0, tzinfo=UTC)
    entitlement_request = _request(
        event=event,
        terms=terms,
        proof=proof,
        stage=CorporateActionStage.SHARE_ENTITLEMENT,
        amount=Decimal("10.000000"),
        posted_at=datetime(2026, 11, 1, 2, 1, tzinfo=UTC),
        qualified_at=qualified_at,
    )
    entitlement_row = _row(
        entitlement_request,
        entry_id=201,
        account_revision=1,
        created_at=datetime(2026, 11, 1, 2, 2, tzinfo=UTC),
    )
    delivery_row = _row(
        _request(
            event=event,
            terms=terms,
            proof=proof,
            stage=CorporateActionStage.SHARE_DELIVERY,
            amount=Decimal("10.000000"),
            posted_at=datetime(2026, 11, 9, 1, 0, tzinfo=UTC),
            qualified_at=qualified_at,
        ),
        entry_id=202,
        account_revision=2,
        created_at=datetime(2026, 11, 9, 1, 1, tzinfo=UTC),
    )
    release_row = _row(
        _request(
            event=event,
            terms=terms,
            proof=proof,
            stage=CorporateActionStage.SHARE_SELLABLE_RELEASE,
            amount=Decimal("10.000000"),
            posted_at=datetime(2026, 11, 12, 1, 0, tzinfo=UTC),
            qualified_at=qualified_at,
        ),
        entry_id=203,
        account_revision=3,
        created_at=datetime(2026, 11, 12, 1, 1, tzinfo=UTC),
    )

    result = _inspect(
        event=event, terms=terms, proof=proof, rows=(entitlement_row, delivery_row, release_row)
    )

    assert result.shares_complete is True
    references = result.current_entitlement_references
    assert references is not None and len(references) == 1
    entitlement = references[0].restatement_entitlement
    assert entitlement.gross_cash == Decimal("0")
    assert entitlement.gross_shares == Decimal("10.000000")
    assert entitlement.cash_transfers == ()
    assert len(entitlement.share_transfers) == 1
    transfer = entitlement.share_transfers[0]
    assert transfer.entry_id == "202"
    assert transfer.amount == Decimal("10.000000")
    assert (
        transfer.accounting_on
        == delivery_row.posted_at.astimezone(ZoneInfo("Asia/Shanghai")).date()
    )
    assert transfer.accounting_on != delivery_row.stage_date
    assert transfer.recorded_at == delivery_row.created_at


def test_missing_storage_clock_keeps_existing_complete_flag_but_no_reference() -> None:
    """An absent ORM creation clock leaves the new projection unknown only."""
    event = _event()
    terms = _terms()
    proof = _proof()
    request = _request(
        event=event,
        terms=terms,
        proof=proof,
        stage=CorporateActionStage.CASH_ENTITLEMENT,
        amount=Decimal("12.30"),
        posted_at=datetime(2026, 11, 1, 2, 1, tzinfo=UTC),
        qualified_at=datetime(2026, 11, 1, 2, 0, tzinfo=UTC),
    )
    row = _row(
        request,
        entry_id=301,
        account_revision=1,
        created_at=None,
    )

    result = _inspect(event=event, terms=terms, proof=proof, rows=(row,))

    assert result.cash_complete is True
    assert result.current_entitlement_references is None

    row.created_at = datetime(2026, 11, 1, 2, 2, tzinfo=UTC)
    with_clock = _inspect(event=event, terms=terms, proof=proof, rows=(row,))
    assert with_clock.cash_complete is True
    assert with_clock.current_entitlement_references is not None
    assert with_clock.evidence_sha256 == result.evidence_sha256


def test_legacy_tax_withholding_is_never_projected_as_dividend_principal() -> None:
    """An unsupported withholding stage cannot become a cash transfer reference."""
    event = _event()
    terms = _terms()
    proof = _proof()
    qualified_at = datetime(2026, 11, 1, 2, 0, tzinfo=UTC)
    entitlement_request = _request(
        event=event,
        terms=terms,
        proof=proof,
        stage=CorporateActionStage.CASH_ENTITLEMENT,
        amount=Decimal("12.30"),
        posted_at=datetime(2026, 11, 1, 2, 1, tzinfo=UTC),
        qualified_at=qualified_at,
    )
    entitlement_row = _row(
        entitlement_request,
        entry_id=351,
        account_revision=1,
        created_at=datetime(2026, 11, 1, 2, 2, tzinfo=UTC),
    )
    withholding_request = replace(
        entitlement_request,
        stage=CorporateActionStage.TAX_WITHHOLDING,
        stage_date=_PAYMENT_DATE,
        cash_amount=Decimal("2.30"),
        tax_rule_id="synthetic-tax-rule",
        tax_rule_sha256="c" * 64,
        tax_basis_record_id="synthetic-assessment",
        tax_basis_sha256="d" * 64,
        ownership_snapshot_id=None,
        ownership_snapshot_sha256=None,
        ownership_snapshot_as_of_date=None,
        ownership_snapshot_observed_at=None,
        eligible_quantity=None,
        entitlement_calculation_sha256=None,
    )
    withholding_row = _row(
        withholding_request,
        entry_id=352,
        account_revision=2,
        created_at=datetime(2026, 11, 5, 2, 2, tzinfo=UTC),
    )

    result = _inspect(
        event=event,
        terms=terms,
        proof=proof,
        rows=(entitlement_row, withholding_row),
    )

    assert result.cash_complete is False
    assert result.current_entitlement_references is None


def test_combine_preserves_unknown_projection_and_certifies_empty_projection() -> None:
    """Only all-known event references flatten; a verified empty window is empty tuple."""
    empty = coverage.combine_current_entitlement_coverage(
        asset_code=_ASSET,
        window_sha256="d" * 64,
        events=(),
    )
    assert empty.cash_complete is True
    assert empty.shares_complete is True
    assert empty.current_entitlement_references == ()

    event = _event()
    terms = _terms()
    proof = _proof()
    request = _request(
        event=event,
        terms=terms,
        proof=proof,
        stage=CorporateActionStage.CASH_ENTITLEMENT,
        amount=Decimal("12.30"),
        posted_at=datetime(2026, 11, 1, 2, 1, tzinfo=UTC),
        qualified_at=datetime(2026, 11, 1, 2, 0, tzinfo=UTC),
    )
    complete_event = _inspect(
        event=event,
        terms=terms,
        proof=proof,
        rows=(
            _row(
                request,
                entry_id=401,
                account_revision=1,
                created_at=datetime(2026, 11, 1, 2, 2, tzinfo=UTC),
            ),
        ),
    )
    unknown_event = replace(complete_event, current_entitlement_references=None)

    merged = coverage.combine_current_entitlement_coverage(
        asset_code=_ASSET,
        window_sha256="e" * 64,
        events=(complete_event,),
    )
    mixed = coverage.combine_current_entitlement_coverage(
        asset_code=_ASSET,
        window_sha256="f" * 64,
        events=(complete_event, unknown_event),
    )

    assert merged.current_entitlement_references == complete_event.current_entitlement_references
    assert mixed.current_entitlement_references is None
    assert mixed.cash_complete is True
    assert mixed.shares_complete is True
