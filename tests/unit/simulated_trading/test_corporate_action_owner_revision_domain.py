"""Pure synthetic contracts for complete owner correction preparation."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, localcontext
from unittest.mock import patch

import pytest

from apps.simulated_trading.domain.corporate_action_owner_revision import (
    OwnerCorporateActionRevisionEntry,
    PreparedOwnerCorporateActionRevision,
    _canonical_stage_order,
    _supported_persisted_decimal,
    _validate_share_history,
    prepare_owner_corporate_action_revision,
    read_owner_corporate_action_revision_head,
)
from apps.simulated_trading.domain.corporate_action_posting import (
    CorporateActionEntryKind,
    CorporateActionInputValidationError,
    CorporateActionKind,
    CorporateActionLedgerDelta,
    CorporateActionStage,
    CorporateActionStageRequest,
    calculate_corporate_action_delta,
)

_ACCOUNT_ID = 1101
_OWNER_ID = 2101
_ASSET = "000001.SZ"
_LOGICAL_EVENT = "synthetic-logical-action"
_RECORD = date(2026, 10, 30)
_EX_DATE = date(2026, 10, 31)
_PAYMENT_DATE = date(2026, 11, 5)
_DELIVERY_DATE = date(2026, 11, 6)
_SELLABLE_DATE = date(2026, 11, 10)
_AS_OF_DATE = date(2026, 11, 14)
_SOURCE_SEEN = datetime(2026, 10, 20, 1, 0, tzinfo=UTC)
_QUALIFIED = datetime(2026, 11, 1, 1, 0, tzinfo=UTC)
_REVISION_QUALIFIED = datetime(2026, 11, 14, 9, 0, tzinfo=UTC)
_REVISION_POSTED = datetime(2026, 11, 14, 11, 0, tzinfo=UTC)


def _stage_clocks(stage_date: date) -> tuple[datetime, datetime]:
    """Return a plausible qualification and posting time on or after this stage date."""

    stage_morning = datetime.combine(stage_date, time(9, 0), tzinfo=UTC)
    qualified_at = max(_QUALIFIED, stage_morning)
    return qualified_at, qualified_at + timedelta(minutes=5)


def _request(
    *,
    action_kind: CorporateActionKind,
    stage: CorporateActionStage,
    revision: str,
    record_id: str,
    amount: Decimal,
    payment_date: date | None = None,
    delivery_date: date | None = None,
    sellable_date: date | None = None,
    source_event: str = _LOGICAL_EVENT,
    account_id: int = _ACCOUNT_ID,
    owner_user_id: int = _OWNER_ID,
    asset_code: str = _ASSET,
    security_id: str = _ASSET,
    asset_name: str = "Synthetic test asset",
    qualified_at: datetime | None = None,
    posted_at: datetime | None = None,
    entry_kind: CorporateActionEntryKind = CorporateActionEntryKind.POSTING,
    supersedes_revision_id: str | None = None,
) -> CorporateActionStageRequest:
    """Create one fully validated synthetic current-source stage request."""

    is_cash = action_kind is CorporateActionKind.CASH_DIVIDEND
    is_entitlement = stage in {
        CorporateActionStage.CASH_ENTITLEMENT,
        CorporateActionStage.SHARE_ENTITLEMENT,
    }
    stage_date = (
        _RECORD
        if is_entitlement
        else (
            payment_date
            if stage is CorporateActionStage.CASH_PAYMENT
            else delivery_date if stage is CorporateActionStage.SHARE_DELIVERY else sellable_date
        )
    )
    if stage_date is None:
        raise AssertionError("test stage requires its explicit date")
    default_qualified_at, default_posted_at = _stage_clocks(stage_date)
    actual_qualified_at = qualified_at if qualified_at is not None else default_qualified_at
    actual_posted_at = posted_at if posted_at is not None else default_posted_at
    return CorporateActionStageRequest(
        account_id=account_id,
        owner_user_id=owner_user_id,
        security_id=security_id,
        asset_code=asset_code,
        asset_name=asset_name,
        source_namespace="exchange_official_disclosure",
        source_record_id=record_id,
        source_event_id=source_event,
        source_revision_id=revision,
        source_payload_sha256="a" * 64,
        qualification_sha256="b" * 64,
        qualifier_identity="synthetic-source-qualifier.v1",
        source_observed_at=_SOURCE_SEEN,
        qualified_at=actual_qualified_at,
        posted_at=actual_posted_at,
        action_kind=action_kind,
        stage=stage,
        entry_kind=entry_kind,
        record_date=_RECORD,
        effective_date=_EX_DATE,
        stage_date=stage_date,
        cash_amount=amount if is_cash else None,
        share_amount=None if is_cash else amount,
        payment_date=(payment_date if stage is CorporateActionStage.CASH_PAYMENT else None),
        sellable_date=(
            sellable_date
            if stage
            in {
                CorporateActionStage.SHARE_DELIVERY,
                CorporateActionStage.SHARE_SELLABLE_RELEASE,
            }
            else None
        ),
        tax_treatment="deferred_withholding" if is_cash else "not_applicable",
        ownership_snapshot_id=("synthetic-record-date-proof" if is_entitlement else None),
        ownership_snapshot_sha256=("c" * 64 if is_entitlement else None),
        ownership_snapshot_as_of_date=(_RECORD if is_entitlement else None),
        ownership_snapshot_observed_at=(
            min(_QUALIFIED, actual_qualified_at) if is_entitlement else None
        ),
        eligible_quantity=(Decimal("100.000000") if is_entitlement else None),
        entitlement_calculation_sha256=("d" * 64 if is_entitlement else None),
        odd_lot_policy=None if is_cash else "whole_shares",
        supersedes_revision_id=supersedes_revision_id,
    )


def _entry(
    entry_id: int,
    revision: int,
    request: CorporateActionStageRequest,
    *,
    delta: CorporateActionLedgerDelta | None = None,
) -> OwnerCorporateActionRevisionEntry:
    """Wrap one exact synthetic ledger stage and its persisted signed delta."""

    return OwnerCorporateActionRevisionEntry(
        entry_id=entry_id,
        account_revision=revision,
        request=request,
        delta=delta or calculate_corporate_action_delta(request),
    )


def _history(
    *requests: CorporateActionStageRequest,
) -> tuple[OwnerCorporateActionRevisionEntry, ...]:
    """Create one account-ordered initial active revision for the synthetic event."""

    entries: list[OwnerCorporateActionRevisionEntry] = []
    for index, request in enumerate(requests):
        if request.entry_kind is CorporateActionEntryKind.POSTING:
            qualified_at, posted_at = _stage_clocks(request.stage_date)
            request = replace(request, qualified_at=qualified_at, posted_at=posted_at)
        entries.append(_entry(301 + index, 1 + index, request))
    return tuple(entries)


def _cash_correction_history() -> tuple[OwnerCorporateActionRevisionEntry, ...]:
    """Return one complete paid cash correction with two exact revision stages."""

    original = _history(*_cash_replacements(revision="revision-1"))
    replacements = _cash_replacements(revision="revision-2")
    payment_reversal = _reversal_for(
        replacements[1], target=original[1], predecessor_revision="revision-1"
    )
    entitlement_reversal = _reversal_for(
        replacements[0], target=original[0], predecessor_revision="revision-1"
    )
    return original + (
        _entry(
            303,
            3,
            payment_reversal,
            delta=_inverse_delta(original[1].delta),
        ),
        _entry(
            304,
            4,
            entitlement_reversal,
            delta=_inverse_delta(original[0].delta),
        ),
        _entry(
            305,
            5,
            replace(
                replacements[0],
                entry_kind=CorporateActionEntryKind.SUCCESSOR,
                supersedes_revision_id="revision-1",
            ),
        ),
        _entry(
            306,
            6,
            replace(
                replacements[1],
                entry_kind=CorporateActionEntryKind.SUCCESSOR,
                supersedes_revision_id="revision-1",
            ),
        ),
    )


def _cash_replacements(revision: str = "revision-2") -> tuple[CorporateActionStageRequest, ...]:
    """Return a full source-qualified synthetic cash entitlement/payment pair."""

    requests = (
        _request(
            action_kind=CorporateActionKind.CASH_DIVIDEND,
            stage=CorporateActionStage.CASH_ENTITLEMENT,
            revision=revision,
            record_id="source-record-2",
            amount=Decimal("120.00"),
        ),
        _request(
            action_kind=CorporateActionKind.CASH_DIVIDEND,
            stage=CorporateActionStage.CASH_PAYMENT,
            revision=revision,
            record_id="source-record-2",
            amount=Decimal("120.00"),
            payment_date=_PAYMENT_DATE,
        ),
    )
    return tuple(
        replace(request, qualified_at=_REVISION_QUALIFIED, posted_at=_REVISION_POSTED)
        for request in requests
    )


def _share_replacements(
    revision: str = "revision-2",
    *,
    delivery_date: date = _DELIVERY_DATE,
    sellable_date: date = _SELLABLE_DATE,
) -> tuple[CorporateActionStageRequest, ...]:
    """Return all three distinct source-dated synthetic share stages."""

    requests = (
        _request(
            action_kind=CorporateActionKind.SHARE_DISTRIBUTION,
            stage=CorporateActionStage.SHARE_ENTITLEMENT,
            revision=revision,
            record_id="source-record-2",
            amount=Decimal("100.000000"),
        ),
        _request(
            action_kind=CorporateActionKind.SHARE_DISTRIBUTION,
            stage=CorporateActionStage.SHARE_DELIVERY,
            revision=revision,
            record_id="source-record-2",
            amount=Decimal("100.000000"),
            delivery_date=delivery_date,
            sellable_date=sellable_date,
        ),
        _request(
            action_kind=CorporateActionKind.SHARE_DISTRIBUTION,
            stage=CorporateActionStage.SHARE_SELLABLE_RELEASE,
            revision=revision,
            record_id="source-record-2",
            amount=Decimal("100.000000"),
            sellable_date=sellable_date,
        ),
    )
    return tuple(
        replace(request, qualified_at=_REVISION_QUALIFIED, posted_at=_REVISION_POSTED)
        for request in requests
    )


def _rights_no_effect_request() -> CorporateActionStageRequest:
    """Create one explicit synthetic rights no-exercise stage for a boundary test."""

    entitlement = _request(
        action_kind=CorporateActionKind.SHARE_DISTRIBUTION,
        stage=CorporateActionStage.SHARE_ENTITLEMENT,
        revision="revision-1",
        record_id="source-record-1",
        amount=Decimal("100.000000"),
    )
    return replace(
        entitlement,
        action_kind=CorporateActionKind.RIGHTS_ISSUE,
        stage=CorporateActionStage.RIGHTS_NOT_EXERCISED,
        entry_kind=CorporateActionEntryKind.NO_EFFECT,
        stage_date=_PAYMENT_DATE,
        share_amount=None,
        tax_treatment=None,
        odd_lot_policy=None,
        rights_terms_sha256="e" * 64,
        rights_election="not_exercised",
    )


def _reversal_for(
    replacement: CorporateActionStageRequest,
    *,
    target: OwnerCorporateActionRevisionEntry,
    predecessor_revision: str,
) -> CorporateActionStageRequest:
    """Build a synthetic exact predecessor reversal using the current source identity."""

    return replace(
        replacement,
        entry_kind=CorporateActionEntryKind.REVERSAL,
        cash_amount=None,
        share_amount=None,
        tax_treatment=None,
        ownership_snapshot_id=None,
        ownership_snapshot_sha256=None,
        ownership_snapshot_as_of_date=None,
        ownership_snapshot_observed_at=None,
        eligible_quantity=None,
        entitlement_calculation_sha256=None,
        odd_lot_policy=None,
        supersedes_revision_id=predecessor_revision,
        reversal_of_entry_id=target.entry_id,
    )


def _inverse_delta(delta: CorporateActionLedgerDelta) -> CorporateActionLedgerDelta:
    """Return an exact context-independent inverse for a synthetic ledger row."""

    return CorporateActionLedgerDelta(
        cash=delta.cash.copy_negate(),
        cash_receivable=delta.cash_receivable.copy_negate(),
        shares=delta.shares.copy_negate(),
        share_receivable=delta.share_receivable.copy_negate(),
        available_shares=delta.available_shares.copy_negate(),
    )


def test_cash_revision_reverses_payment_before_entitlement_then_replaces_both() -> None:
    """Cash correction preserves the full active pair and safe receivable sequence."""

    old_entitlement = _request(
        action_kind=CorporateActionKind.CASH_DIVIDEND,
        stage=CorporateActionStage.CASH_ENTITLEMENT,
        revision="revision-1",
        record_id="source-record-1",
        amount=Decimal("100.00"),
    )
    old_payment = _request(
        action_kind=CorporateActionKind.CASH_DIVIDEND,
        stage=CorporateActionStage.CASH_PAYMENT,
        revision="revision-1",
        record_id="source-record-1",
        amount=Decimal("100.00"),
        payment_date=_PAYMENT_DATE,
    )
    history = _history(old_entitlement, old_payment)

    result = prepare_owner_corporate_action_revision(
        history=history,
        expected_head_revision_id="revision-1",
        replacement_requests=_cash_replacements(),
        as_of_date=_AS_OF_DATE,
    )

    assert tuple((item.entry_kind, item.stage) for item in result.requests) == (
        (CorporateActionEntryKind.REVERSAL, CorporateActionStage.CASH_PAYMENT),
        (CorporateActionEntryKind.REVERSAL, CorporateActionStage.CASH_ENTITLEMENT),
        (CorporateActionEntryKind.SUCCESSOR, CorporateActionStage.CASH_ENTITLEMENT),
        (CorporateActionEntryKind.SUCCESSOR, CorporateActionStage.CASH_PAYMENT),
    )
    assert tuple(item.reversal_of_entry_id for item in result.requests[:2]) == (302, 301)
    assert result.gate_anchor is result.requests[2]


def test_share_revision_uses_reverse_then_forward_stage_order_and_full_quantity() -> None:
    """Share correction keeps delivery and sellable dates independent and quantity whole."""

    old_stages = _share_replacements(revision="revision-1")
    history = _history(*old_stages)

    result = prepare_owner_corporate_action_revision(
        history=history,
        expected_head_revision_id="revision-1",
        replacement_requests=_share_replacements(),
        as_of_date=_AS_OF_DATE,
    )

    assert tuple(item.stage for item in result.requests) == (
        CorporateActionStage.SHARE_SELLABLE_RELEASE,
        CorporateActionStage.SHARE_DELIVERY,
        CorporateActionStage.SHARE_ENTITLEMENT,
        CorporateActionStage.SHARE_ENTITLEMENT,
        CorporateActionStage.SHARE_DELIVERY,
        CorporateActionStage.SHARE_SELLABLE_RELEASE,
    )
    delivery = result.requests[4]
    release = result.requests[5]
    assert delivery.stage_date == _DELIVERY_DATE
    assert delivery.sellable_date == _SELLABLE_DATE
    assert release.stage_date == _SELLABLE_DATE
    assert {item.share_amount for item in result.requests if item.share_amount is not None} == {
        Decimal("100.000000")
    }


def test_rejects_replacement_that_omits_an_active_cash_payment() -> None:
    """Every active immediate-predecessor stage must have one current successor."""

    history = _history(*_cash_replacements(revision="revision-1"))
    only_entitlement = (_cash_replacements()[0],)

    with pytest.raises(CorporateActionInputValidationError):
        prepare_owner_corporate_action_revision(
            history=history,
            expected_head_revision_id="revision-1",
            replacement_requests=only_entitlement,
            as_of_date=_AS_OF_DATE,
        )


def test_rejects_partial_prior_correction_history() -> None:
    """A prior correction with only one reversal cannot be called the complete head."""

    initial = _history(*_cash_replacements(revision="revision-1"))
    replacements = _cash_replacements(revision="revision-2")
    active_by_stage = {entry.request.stage: entry for entry in initial}
    partial_reversal = _reversal_for(
        replacements[0],
        target=active_by_stage[CorporateActionStage.CASH_ENTITLEMENT],
        predecessor_revision="revision-1",
    )
    partial_successor = replace(
        replacements[0],
        entry_kind=CorporateActionEntryKind.SUCCESSOR,
        supersedes_revision_id="revision-1",
    )
    incomplete_history = initial + (
        _entry(
            303,
            3,
            partial_reversal,
            delta=CorporateActionLedgerDelta(cash_receivable=Decimal("-100.00")),
        ),
        _entry(304, 4, partial_successor),
    )

    with pytest.raises(CorporateActionInputValidationError):
        prepare_owner_corporate_action_revision(
            history=incomplete_history,
            expected_head_revision_id="revision-2",
            replacement_requests=_cash_replacements(revision="revision-3"),
            as_of_date=_AS_OF_DATE,
        )


def test_rejects_cross_scope_or_wrong_head() -> None:
    """A forked source or stale expected head cannot receive a correction batch."""

    old_entitlement = _request(
        action_kind=CorporateActionKind.CASH_DIVIDEND,
        stage=CorporateActionStage.CASH_ENTITLEMENT,
        revision="revision-1",
        record_id="source-record-1",
        amount=Decimal("100.00"),
    )
    history = _history(old_entitlement)

    with pytest.raises(CorporateActionInputValidationError):
        prepare_owner_corporate_action_revision(
            history=history,
            expected_head_revision_id="not-the-head",
            replacement_requests=_cash_replacements()[0:1],
            as_of_date=_AS_OF_DATE,
        )

    cross_account = replace(_cash_replacements()[0], account_id=_ACCOUNT_ID + 1)
    with pytest.raises(CorporateActionInputValidationError):
        prepare_owner_corporate_action_revision(
            history=history,
            expected_head_revision_id="revision-1",
            replacement_requests=(cross_account,),
            as_of_date=_AS_OF_DATE,
        )


def test_rejects_legacy_tax_withholding_in_history() -> None:
    """Legacy standalone withholding cannot be folded into this source revision helper."""

    entitlement = _request(
        action_kind=CorporateActionKind.CASH_DIVIDEND,
        stage=CorporateActionStage.CASH_ENTITLEMENT,
        revision="revision-1",
        record_id="source-record-1",
        amount=Decimal("100.00"),
    )
    withholding = replace(
        entitlement,
        stage=CorporateActionStage.TAX_WITHHOLDING,
        stage_date=_PAYMENT_DATE,
        cash_amount=Decimal("3.00"),
        payment_date=None,
        ownership_snapshot_id=None,
        ownership_snapshot_sha256=None,
        ownership_snapshot_as_of_date=None,
        ownership_snapshot_observed_at=None,
        eligible_quantity=None,
        entitlement_calculation_sha256=None,
        tax_rule_id="synthetic-legacy-rule",
        tax_rule_sha256="e" * 64,
        tax_basis_record_id="synthetic-legacy-basis",
        tax_basis_sha256="f" * 64,
    )
    history = (
        _entry(301, 1, entitlement),
        _entry(
            302,
            2,
            withholding,
            delta=CorporateActionLedgerDelta(cash=Decimal("-3.00")),
        ),
    )

    with pytest.raises(CorporateActionInputValidationError):
        prepare_owner_corporate_action_revision(
            history=history,
            expected_head_revision_id="revision-1",
            replacement_requests=_cash_replacements(),
            as_of_date=_AS_OF_DATE,
        )


def test_rejects_future_share_delivery_stage() -> None:
    """A correction batch cannot create a delivery or release before its source date."""

    history = _history(*_share_replacements(revision="revision-1"))
    future = _share_replacements(
        delivery_date=_AS_OF_DATE + timedelta(days=1),
        sellable_date=_AS_OF_DATE + timedelta(days=4),
    )

    with pytest.raises(CorporateActionInputValidationError):
        prepare_owner_corporate_action_revision(
            history=history,
            expected_head_revision_id="revision-1",
            replacement_requests=future,
            as_of_date=_AS_OF_DATE,
        )


def test_rejects_partial_share_quantity_replacement() -> None:
    """Entitlement, delivery, and release successors must preserve one full quantity."""

    history = _history(*_share_replacements(revision="revision-1"))
    requests = list(_share_replacements())
    requests[1] = replace(requests[1], share_amount=Decimal("99.000000"))

    with pytest.raises(CorporateActionInputValidationError):
        prepare_owner_corporate_action_revision(
            history=history,
            expected_head_revision_id="revision-1",
            replacement_requests=tuple(requests),
            as_of_date=_AS_OF_DATE,
        )


def test_read_revision_head_accepts_later_payment_on_corrected_entitlement() -> None:
    """Readback returns the active corrected pair after a later head posting."""

    original_entitlement = _request(
        action_kind=CorporateActionKind.CASH_DIVIDEND,
        stage=CorporateActionStage.CASH_ENTITLEMENT,
        revision="revision-1",
        record_id="source-record-1",
        amount=Decimal("100.00"),
    )
    corrected_entitlement, corrected_payment = _cash_replacements()
    reversal = _reversal_for(
        corrected_entitlement,
        target=_entry(301, 1, original_entitlement),
        predecessor_revision="revision-1",
    )
    history = (
        _entry(301, 1, original_entitlement),
        _entry(
            302,
            2,
            reversal,
            delta=CorporateActionLedgerDelta(cash_receivable=Decimal("-100.00")),
        ),
        _entry(
            303,
            3,
            replace(
                corrected_entitlement,
                entry_kind=CorporateActionEntryKind.SUCCESSOR,
                supersedes_revision_id="revision-1",
            ),
        ),
        _entry(304, 4, corrected_payment),
    )

    active = read_owner_corporate_action_revision_head(history, "revision-2")

    assert tuple(entry.entry_id for entry in active) == (303, 304)
    assert tuple(entry.request.stage for entry in active) == (
        CorporateActionStage.CASH_ENTITLEMENT,
        CorporateActionStage.CASH_PAYMENT,
    )


def test_one_source_revision_accepts_stage_specific_posting_clocks_and_names() -> None:
    """Later real-stage posting and display-name changes do not fork source facts."""

    entitlement = _request(
        action_kind=CorporateActionKind.CASH_DIVIDEND,
        stage=CorporateActionStage.CASH_ENTITLEMENT,
        revision="revision-1",
        record_id="source-record-1",
        amount=Decimal("100.00"),
        asset_name="Earlier disclosed title",
    )
    payment = _request(
        action_kind=CorporateActionKind.CASH_DIVIDEND,
        stage=CorporateActionStage.CASH_PAYMENT,
        revision="revision-1",
        record_id="source-record-1",
        amount=Decimal("100.00"),
        payment_date=_PAYMENT_DATE,
        asset_name="Later canonical title",
    )
    assert entitlement.qualified_at < payment.qualified_at
    assert entitlement.posted_at < payment.posted_at

    active = read_owner_corporate_action_revision_head(
        (_entry(301, 1, entitlement), _entry(302, 2, payment)),
        "revision-1",
    )

    assert tuple(entry.request.stage for entry in active) == (
        CorporateActionStage.CASH_ENTITLEMENT,
        CorporateActionStage.CASH_PAYMENT,
    )


def test_corrected_entitlement_accepts_later_ordinary_payment_with_new_clocks() -> None:
    """A later payment keeps the current revision after a full entitlement correction."""

    original_entitlement = _request(
        action_kind=CorporateActionKind.CASH_DIVIDEND,
        stage=CorporateActionStage.CASH_ENTITLEMENT,
        revision="revision-1",
        record_id="source-record-1",
        amount=Decimal("100.00"),
    )
    old_entry = _entry(301, 1, original_entitlement)
    corrected_entitlement = _request(
        action_kind=CorporateActionKind.CASH_DIVIDEND,
        stage=CorporateActionStage.CASH_ENTITLEMENT,
        revision="revision-2",
        record_id="source-record-2",
        amount=Decimal("120.00"),
        qualified_at=datetime(2026, 11, 3, 9, 0, tzinfo=UTC),
        posted_at=datetime(2026, 11, 3, 9, 5, tzinfo=UTC),
    )
    reversal = _reversal_for(
        corrected_entitlement,
        target=old_entry,
        predecessor_revision="revision-1",
    )
    successor = replace(
        corrected_entitlement,
        entry_kind=CorporateActionEntryKind.SUCCESSOR,
        supersedes_revision_id="revision-1",
    )
    later_payment = _request(
        action_kind=CorporateActionKind.CASH_DIVIDEND,
        stage=CorporateActionStage.CASH_PAYMENT,
        revision="revision-2",
        record_id="source-record-2",
        amount=Decimal("120.00"),
        payment_date=_PAYMENT_DATE,
        asset_name="Updated canonical title",
    )
    history = (
        old_entry,
        _entry(
            302,
            2,
            reversal,
            delta=CorporateActionLedgerDelta(cash_receivable=Decimal("-100.00")),
        ),
        _entry(303, 3, successor),
        _entry(304, 4, later_payment),
    )

    active = read_owner_corporate_action_revision_head(history, "revision-2")

    assert tuple(entry.entry_id for entry in active) == (303, 304)
    assert successor.posted_at < later_payment.posted_at
    assert later_payment.stage_date == _PAYMENT_DATE


def test_share_history_rejects_partial_delivery_at_the_intermediate_step() -> None:
    """A later exact correction cannot hide a historical partial delivery."""

    original = _share_replacements(revision="revision-1")
    partial_delivery = replace(original[1], share_amount=Decimal("99.000000"))
    first_entries = (_entry(301, 1, original[0]), _entry(302, 2, partial_delivery))
    replacement = _share_replacements(revision="revision-2")[:2]
    reversal_delivery = _reversal_for(
        replacement[1], target=first_entries[1], predecessor_revision="revision-1"
    )
    reversal_entitlement = _reversal_for(
        replacement[0], target=first_entries[0], predecessor_revision="revision-1"
    )
    history = first_entries + (
        _entry(
            303,
            3,
            reversal_delivery,
            delta=CorporateActionLedgerDelta(
                shares=Decimal("-99.000000"),
                share_receivable=Decimal("99.000000"),
            ),
        ),
        _entry(
            304,
            4,
            reversal_entitlement,
            delta=CorporateActionLedgerDelta(share_receivable=Decimal("-100.000000")),
        ),
        _entry(
            305,
            5,
            replace(
                replacement[0],
                entry_kind=CorporateActionEntryKind.SUCCESSOR,
                supersedes_revision_id="revision-1",
            ),
        ),
        _entry(
            306,
            6,
            replace(
                replacement[1],
                entry_kind=CorporateActionEntryKind.SUCCESSOR,
                supersedes_revision_id="revision-1",
            ),
        ),
    )

    with pytest.raises(CorporateActionInputValidationError):
        read_owner_corporate_action_revision_head(history, "revision-2")


def test_share_history_rejects_partial_release_at_the_intermediate_step() -> None:
    """A later exact correction cannot hide a historical partial release."""

    original = _share_replacements(revision="revision-1")
    partial_release = replace(original[2], share_amount=Decimal("99.000000"))
    first_entries = tuple(
        _entry(301 + index, 1 + index, request)
        for index, request in enumerate((*original[:2], partial_release))
    )
    replacement = _share_replacements(revision="revision-2")
    reversals = tuple(
        _reversal_for(
            template,
            target=target,
            predecessor_revision="revision-1",
        )
        for template, target in zip(reversed(replacement), reversed(first_entries), strict=False)
    )
    # The stage-specific reversal targets must follow the canonical release, delivery,
    # entitlement order, which is also the reverse of the active stage rows.
    successor_rows = tuple(
        replace(
            request,
            entry_kind=CorporateActionEntryKind.SUCCESSOR,
            supersedes_revision_id="revision-1",
        )
        for request in replacement
    )
    history = (
        first_entries
        + tuple(
            _entry(304 + index, 4 + index, request, delta=_inverse_delta(target.delta))
            for index, (request, target) in enumerate(
                zip(reversals, reversed(first_entries), strict=False)
            )
        )
        + tuple(
            _entry(307 + index, 7 + index, request) for index, request in enumerate(successor_rows)
        )
    )

    with pytest.raises(CorporateActionInputValidationError):
        read_owner_corporate_action_revision_head(history, "revision-2")


def test_share_history_rejects_delivery_without_a_full_prior_entitlement() -> None:
    """A delivery stage cannot create shares without the full event receivable."""

    delivery = _request(
        action_kind=CorporateActionKind.SHARE_DISTRIBUTION,
        stage=CorporateActionStage.SHARE_DELIVERY,
        revision="revision-1",
        record_id="source-record-1",
        amount=Decimal("100.000000"),
        delivery_date=_DELIVERY_DATE,
        sellable_date=_SELLABLE_DATE,
    )

    with pytest.raises(CorporateActionInputValidationError):
        read_owner_corporate_action_revision_head(_history(delivery), "revision-1")


def test_share_replay_and_inverse_are_exact_under_hostile_decimal_context() -> None:
    """Large six-place quantities replay and invert without ambient rounding."""

    old_quantity = Decimal("12345678901234.000000")
    new_quantity = Decimal("12345678901235.000000")
    old_requests = tuple(
        replace(request, share_amount=old_quantity)
        for request in _share_replacements(revision="revision-1")
    )
    replacement_requests = tuple(
        replace(request, share_amount=new_quantity)
        for request in _share_replacements(revision="revision-2")
    )
    history = _history(*old_requests)

    with localcontext() as context:
        context.prec = 2
        active = read_owner_corporate_action_revision_head(history, "revision-1")
        prepared = prepare_owner_corporate_action_revision(
            history=history,
            expected_head_revision_id="revision-1",
            replacement_requests=replacement_requests,
            as_of_date=_AS_OF_DATE,
        )

    assert len(active) == 3
    assert prepared.requests[0].stage is CorporateActionStage.SHARE_SELLABLE_RELEASE
    assert prepared.requests[0].reversal_of_entry_id == history[2].entry_id
    assert prepared.requests[0].share_amount is None
    assert prepared.requests[3].share_amount == new_quantity


def test_revision_head_rejects_ambiguous_same_revision_source_facts() -> None:
    """Rows sharing a revision id must agree on record-date source facts."""

    entitlement, payment = _cash_replacements(revision="revision-1")
    different_record_date = replace(
        payment,
        record_date=_RECORD - timedelta(days=1),
    )

    with pytest.raises(CorporateActionInputValidationError):
        read_owner_corporate_action_revision_head(
            _history(entitlement, different_record_date),
            "revision-1",
        )


def test_revision_entry_rejects_malformed_nested_request() -> None:
    """Nested history facts are checked at immutable Domain construction time."""

    with pytest.raises(CorporateActionInputValidationError):
        OwnerCorporateActionRevisionEntry(
            entry_id=1,
            account_revision=1,
            request=None,  # type: ignore[arg-type]
            delta=CorporateActionLedgerDelta(),
        )


def test_prepared_revision_rejects_forged_receipt_identity_or_gate_anchor() -> None:
    """Prepared results cannot pair stage receipts with a different batch."""

    result = prepare_owner_corporate_action_revision(
        history=_history(*_share_replacements(revision="revision-1")),
        expected_head_revision_id="revision-1",
        replacement_requests=_share_replacements(),
        as_of_date=_AS_OF_DATE,
    )

    assert isinstance(result, PreparedOwnerCorporateActionRevision)
    with pytest.raises(CorporateActionInputValidationError):
        replace(result, caller_stage_keys=("posting:share_entitlement",))
    with pytest.raises(CorporateActionInputValidationError):
        replace(result, gate_anchor=result.requests[0])


@pytest.mark.parametrize(
    ("value", "max_digits", "decimal_places", "expected"),
    (
        (Decimal("1.000000"), 20, 6, True),
        (0, 20, 6, False),
        (Decimal("NaN"), 20, 6, False),
        (Decimal("0.0000001"), 20, 6, False),
        (Decimal("123456789012345678901.00"), 20, 2, False),
        (Decimal("10000000000000.00"), 15, 2, False),
    ),
)
def test_persisted_decimal_schema_boundary(
    value: object,
    max_digits: int,
    decimal_places: int,
    expected: bool,
) -> None:
    """Fixed-scale fields reject malformed scale and values outside storage bounds."""

    assert (
        _supported_persisted_decimal(
            value,  # type: ignore[arg-type]
            max_digits=max_digits,
            decimal_places=decimal_places,
        )
        is expected
    )


def test_revision_history_rejects_malformed_identity_and_account_order() -> None:
    """The history reader requires a bounded tuple and strict account revisions."""

    request = _cash_replacements(revision="revision-1")[0]
    valid_entry = _entry(301, 1, request)
    invalid_inputs: tuple[tuple[object, object], ...] = (
        ((), "revision-1"),
        ([], "revision-1"),
        (("not-an-entry",), "revision-1"),
        ((valid_entry,), ""),
        ((valid_entry, _entry(301, 2, request)), "revision-1"),
        ((valid_entry, _entry(302, 1, request)), "revision-1"),
    )
    for history, expected_head in invalid_inputs:
        with pytest.raises(CorporateActionInputValidationError):
            read_owner_corporate_action_revision_head(
                history,  # type: ignore[arg-type]
                expected_head,  # type: ignore[arg-type]
            )


def test_history_rejects_unsupported_family_stage_and_crossed_scope() -> None:
    """Only one supported event family and exact owner/account scope are replayed."""

    with pytest.raises(CorporateActionInputValidationError):
        read_owner_corporate_action_revision_head(
            _history(_rights_no_effect_request()), "revision-1"
        )

    cash_entitlement = _cash_replacements(revision="revision-1")[0]
    invalid_stage = _entry(301, 1, cash_entitlement)
    object.__setattr__(invalid_stage.request, "stage", CorporateActionStage.SHARE_ENTITLEMENT)
    with pytest.raises(CorporateActionInputValidationError):
        read_owner_corporate_action_revision_head((invalid_stage,), "revision-1")

    entitlement, payment = _cash_replacements(revision="revision-1")
    crossed_payment = replace(payment, account_id=_ACCOUNT_ID + 1)
    with pytest.raises(CorporateActionInputValidationError):
        read_owner_corporate_action_revision_head(
            _history(entitlement, crossed_payment), "revision-1"
        )


def test_history_rejects_bad_posting_head_duplicate_stage_and_signed_delta() -> None:
    """Ordinary rows cannot fork, repeat a stage, or disagree with Domain economics."""

    entitlement, payment = _cash_replacements(revision="revision-1")
    first = _entry(301, 1, entitlement)

    with pytest.raises(CorporateActionInputValidationError):
        read_owner_corporate_action_revision_head(
            (first, _entry(302, 2, replace(payment, source_revision_id="revision-2"))),
            "revision-1",
        )
    with pytest.raises(CorporateActionInputValidationError):
        read_owner_corporate_action_revision_head(
            (first, _entry(302, 2, entitlement)), "revision-1"
        )
    with pytest.raises(CorporateActionInputValidationError):
        read_owner_corporate_action_revision_head(
            (
                _entry(
                    301,
                    1,
                    entitlement,
                    delta=CorporateActionLedgerDelta(cash_receivable=Decimal("99.00")),
                ),
            ),
            "revision-1",
        )

    initial_with_predecessor = _entry(303, 1, entitlement)
    object.__setattr__(initial_with_predecessor.request, "supersedes_revision_id", "revision-0")
    with pytest.raises(CorporateActionInputValidationError):
        read_owner_corporate_action_revision_head((initial_with_predecessor,), "revision-1")

    unsupported_entry = _entry(304, 1, _cash_replacements(revision="revision-1")[0])
    object.__setattr__(unsupported_entry.request, "entry_kind", CorporateActionEntryKind.NO_EFFECT)
    with pytest.raises(CorporateActionInputValidationError):
        read_owner_corporate_action_revision_head((unsupported_entry,), "revision-1")


def test_cash_history_replay_wraps_an_unsettled_payment_as_domain_conflict() -> None:
    """A cash payment without its receivable is rejected by the reused cash replay."""

    payment = _cash_replacements(revision="revision-1")[1]

    with pytest.raises(CorporateActionInputValidationError):
        read_owner_corporate_action_revision_head(_history(payment), "revision-1")


def test_share_history_rejects_noncanonical_and_unpersistable_deltas() -> None:
    """Share rows must match both Domain arithmetic and stored Decimal precision."""

    entitlement = _share_replacements(revision="revision-1")[0]
    with pytest.raises(CorporateActionInputValidationError):
        read_owner_corporate_action_revision_head(
            (
                _entry(
                    301,
                    1,
                    entitlement,
                    delta=CorporateActionLedgerDelta(share_receivable=Decimal("99.000000")),
                ),
            ),
            "revision-1",
        )

    oversized = replace(entitlement, share_amount=Decimal("123456789012345.000000"))
    with pytest.raises(CorporateActionInputValidationError):
        read_owner_corporate_action_revision_head(_history(oversized), "revision-1")
    with pytest.raises(CorporateActionInputValidationError):
        _validate_share_history(
            (
                _entry(
                    302,
                    2,
                    entitlement,
                    delta=CorporateActionLedgerDelta(share_receivable=Decimal("99.000000")),
                ),
            )
        )


def test_internal_share_replay_rejects_corrupt_signed_balance_and_cash_effect() -> None:
    """The balance replay remains defensive if corrupted rows bypass full-history checks."""

    entitlement = _share_replacements(revision="revision-1")[0]
    reversal = _reversal_for(
        _share_replacements(revision="revision-2")[0],
        target=_entry(301, 1, entitlement),
        predecessor_revision="revision-1",
    )
    with pytest.raises(CorporateActionInputValidationError):
        _validate_share_history(
            (
                _entry(
                    302,
                    2,
                    reversal,
                    delta=CorporateActionLedgerDelta(share_receivable=Decimal("-1.000000")),
                ),
            )
        )

    with pytest.raises(CorporateActionInputValidationError):
        _validate_share_history(
            (
                _entry(
                    302,
                    2,
                    reversal,
                    delta=CorporateActionLedgerDelta(cash=Decimal("1.00")),
                ),
            )
        )


def test_revision_history_rejects_a_complete_correction_with_wrong_predecessor() -> None:
    """Every correction row must name the actual immediately preceding revision."""

    original = _history(_cash_replacements(revision="revision-1")[0])
    replacement = _cash_replacements(revision="revision-2")[0]
    reversal = _reversal_for(replacement, target=original[0], predecessor_revision="other-revision")
    successor = replace(
        replacement,
        entry_kind=CorporateActionEntryKind.SUCCESSOR,
        supersedes_revision_id="other-revision",
    )
    history = original + (
        _entry(302, 2, reversal, delta=_inverse_delta(original[0].delta)),
        _entry(303, 3, successor),
    )

    with pytest.raises(CorporateActionInputValidationError):
        read_owner_corporate_action_revision_head(history, "revision-2")


def test_revision_history_rejects_noncontiguous_or_mixed_correction_batches() -> None:
    """A correction is one contiguous account write with one direct predecessor."""

    original = _history(_cash_replacements(revision="revision-1")[0])
    replacement = _cash_replacements(revision="revision-2")[0]
    reversal = _reversal_for(replacement, target=original[0], predecessor_revision="revision-1")
    successor = replace(
        replacement,
        entry_kind=CorporateActionEntryKind.SUCCESSOR,
        supersedes_revision_id="revision-1",
    )
    with pytest.raises(CorporateActionInputValidationError):
        read_owner_corporate_action_revision_head(
            original
            + (
                _entry(302, 2, reversal, delta=_inverse_delta(original[0].delta)),
                _entry(303, 4, successor),
            ),
            "revision-2",
        )

    mixed_successor = replace(successor, supersedes_revision_id="other-revision")
    with pytest.raises(CorporateActionInputValidationError):
        read_owner_corporate_action_revision_head(
            original
            + (
                _entry(302, 2, reversal, delta=_inverse_delta(original[0].delta)),
                _entry(303, 3, mixed_successor),
            ),
            "revision-2",
        )


def test_correction_rejects_missing_successor_and_wrong_reversal_target() -> None:
    """Every active stage is replaced once and each reversal names its own stage."""

    original = _history(*_cash_replacements(revision="revision-1"))
    replacement = _cash_replacements(revision="revision-2")
    reverse_payment = _reversal_for(
        replacement[1], target=original[1], predecessor_revision="revision-1"
    )
    reverse_entitlement = _reversal_for(
        replacement[0], target=original[0], predecessor_revision="revision-1"
    )
    successor_entitlement = replace(
        replacement[0],
        entry_kind=CorporateActionEntryKind.SUCCESSOR,
        supersedes_revision_id="revision-1",
    )
    with pytest.raises(CorporateActionInputValidationError):
        read_owner_corporate_action_revision_head(
            original
            + (
                _entry(303, 3, reverse_payment, delta=_inverse_delta(original[1].delta)),
                _entry(304, 4, reverse_entitlement, delta=_inverse_delta(original[0].delta)),
                _entry(305, 5, successor_entitlement),
            ),
            "revision-2",
        )

    wrong_payment_target = _reversal_for(
        replacement[1], target=original[0], predecessor_revision="revision-1"
    )
    wrong_entitlement_target = _reversal_for(
        replacement[0], target=original[1], predecessor_revision="revision-1"
    )
    successor_payment = replace(
        replacement[1],
        entry_kind=CorporateActionEntryKind.SUCCESSOR,
        supersedes_revision_id="revision-1",
    )
    with pytest.raises(CorporateActionInputValidationError):
        read_owner_corporate_action_revision_head(
            original
            + (
                _entry(303, 3, wrong_payment_target, delta=_inverse_delta(original[0].delta)),
                _entry(304, 4, wrong_entitlement_target, delta=_inverse_delta(original[1].delta)),
                _entry(305, 5, successor_entitlement),
                _entry(306, 6, successor_payment),
            ),
            "revision-2",
        )


def test_correction_rejects_successor_delta_and_share_write_order_errors() -> None:
    """Successor deltas and recorded share correction ordering are replayed exactly."""

    original = _history(_cash_replacements(revision="revision-1")[0])
    replacement = _cash_replacements(revision="revision-2")[0]
    reversal = _reversal_for(replacement, target=original[0], predecessor_revision="revision-1")
    successor = replace(
        replacement,
        entry_kind=CorporateActionEntryKind.SUCCESSOR,
        supersedes_revision_id="revision-1",
    )
    with pytest.raises(CorporateActionInputValidationError):
        read_owner_corporate_action_revision_head(
            original
            + (
                _entry(302, 2, reversal, delta=_inverse_delta(original[0].delta)),
                _entry(
                    303,
                    3,
                    successor,
                    delta=CorporateActionLedgerDelta(cash_receivable=Decimal("120.01")),
                ),
            ),
            "revision-2",
        )

    old_share = _share_replacements(revision="revision-1")
    old_entries = _history(*old_share)
    new_share = _share_replacements(revision="revision-2")
    reverse_rows = tuple(
        _reversal_for(
            template,
            target=target,
            predecessor_revision="revision-1",
        )
        for template, target in zip(reversed(new_share), reversed(old_entries), strict=False)
    )
    successor_rows = tuple(
        replace(
            request,
            entry_kind=CorporateActionEntryKind.SUCCESSOR,
            supersedes_revision_id="revision-1",
        )
        for request in new_share
    )
    noncanonical = (
        reverse_rows[1],
        reverse_rows[0],
        reverse_rows[2],
        *successor_rows,
    )
    assert tuple(item.stage for item in noncanonical[:3]) != tuple(
        item.stage for item in reverse_rows
    )
    active_by_id = {entry.entry_id: entry for entry in old_entries}
    malformed_rows = tuple(
        _entry(
            304 + index,
            4 + index,
            request,
            delta=(
                _inverse_delta(active_by_id[request.reversal_of_entry_id].delta)
                if request.entry_kind is CorporateActionEntryKind.REVERSAL
                and request.reversal_of_entry_id is not None
                else None
            ),
        )
        for index, request in enumerate(noncanonical)
    )
    with pytest.raises(CorporateActionInputValidationError):
        read_owner_corporate_action_revision_head(old_entries + malformed_rows, "revision-2")


def test_replacement_validation_rejects_bad_types_dates_and_scopes() -> None:
    """New source templates must be reached, supported, and exactly same-scope."""

    history = _history(*_cash_replacements(revision="revision-1"))
    valid = _cash_replacements(revision="revision-2")
    invalid_cases: tuple[tuple[object, object], ...] = (
        ((), _AS_OF_DATE),
        (valid, datetime(2026, 11, 14, tzinfo=UTC)),
        ((None,), _AS_OF_DATE),
        ((valid[0], None), _AS_OF_DATE),
    )
    for requests, as_of in invalid_cases:
        with pytest.raises(CorporateActionInputValidationError):
            prepare_owner_corporate_action_revision(
                history=history,
                expected_head_revision_id="revision-1",
                replacement_requests=requests,  # type: ignore[arg-type]
                as_of_date=as_of,  # type: ignore[arg-type]
            )

    other_family = _request(
        action_kind=CorporateActionKind.SHARE_DISTRIBUTION,
        stage=CorporateActionStage.SHARE_ENTITLEMENT,
        revision="revision-2",
        record_id="source-record-2",
        amount=Decimal("100.000000"),
    )
    with pytest.raises(CorporateActionInputValidationError):
        prepare_owner_corporate_action_revision(
            history=history,
            expected_head_revision_id="revision-1",
            replacement_requests=(other_family,),
            as_of_date=_AS_OF_DATE,
        )

    other_scope = replace(valid[0], owner_user_id=_OWNER_ID + 1)
    with pytest.raises(CorporateActionInputValidationError):
        prepare_owner_corporate_action_revision(
            history=history,
            expected_head_revision_id="revision-1",
            replacement_requests=(other_scope, valid[1]),
            as_of_date=_AS_OF_DATE,
        )

    mixed_revision_facts = replace(valid[1], source_record_id="different-source-record")
    with pytest.raises(CorporateActionInputValidationError):
        prepare_owner_corporate_action_revision(
            history=history,
            expected_head_revision_id="revision-1",
            replacement_requests=(valid[0], mixed_revision_facts),
            as_of_date=_AS_OF_DATE,
        )

    withholding = replace(
        valid[0],
        stage=CorporateActionStage.TAX_WITHHOLDING,
        stage_date=_PAYMENT_DATE,
        cash_amount=Decimal("3.00"),
        ownership_snapshot_id=None,
        ownership_snapshot_sha256=None,
        ownership_snapshot_as_of_date=None,
        ownership_snapshot_observed_at=None,
        eligible_quantity=None,
        entitlement_calculation_sha256=None,
        tax_rule_id="synthetic-rule",
        tax_rule_sha256="e" * 64,
        tax_basis_record_id="synthetic-basis",
        tax_basis_sha256="f" * 64,
    )
    with pytest.raises(CorporateActionInputValidationError):
        prepare_owner_corporate_action_revision(
            history=history,
            expected_head_revision_id="revision-1",
            replacement_requests=(withholding,),
            as_of_date=_AS_OF_DATE,
        )


def test_replacement_validation_rejects_reused_duplicate_and_unpersistable_values() -> None:
    """A correction cannot reuse an old source revision or exceed ledger precision."""

    original = _history(_cash_replacements(revision="revision-1")[0])
    replacement = _cash_replacements(revision="revision-2")[0]
    reversal = _reversal_for(replacement, target=original[0], predecessor_revision="revision-1")
    successor = replace(
        replacement,
        entry_kind=CorporateActionEntryKind.SUCCESSOR,
        supersedes_revision_id="revision-1",
    )
    corrected_history = original + (
        _entry(302, 2, reversal, delta=_inverse_delta(original[0].delta)),
        _entry(303, 3, successor),
    )
    with pytest.raises(CorporateActionInputValidationError):
        prepare_owner_corporate_action_revision(
            history=corrected_history,
            expected_head_revision_id="revision-2",
            replacement_requests=_cash_replacements(revision="revision-1")[:1],
            as_of_date=_AS_OF_DATE,
        )

    two_stages = _cash_replacements(revision="revision-2")
    with pytest.raises(CorporateActionInputValidationError):
        prepare_owner_corporate_action_revision(
            history=_history(*_cash_replacements(revision="revision-1")),
            expected_head_revision_id="revision-1",
            replacement_requests=(two_stages[0], two_stages[0]),
            as_of_date=_AS_OF_DATE,
        )

    oversized_cash = tuple(
        replace(request, cash_amount=Decimal("10000000000000.00")) for request in two_stages
    )
    with pytest.raises(CorporateActionInputValidationError):
        prepare_owner_corporate_action_revision(
            history=_history(*_cash_replacements(revision="revision-1")),
            expected_head_revision_id="revision-1",
            replacement_requests=oversized_cash,
            as_of_date=_AS_OF_DATE,
        )

    oversized_shares = tuple(
        replace(request, share_amount=Decimal("123456789012345.000000"))
        for request in _share_replacements()
    )
    with pytest.raises(CorporateActionInputValidationError):
        prepare_owner_corporate_action_revision(
            history=_history(*_share_replacements(revision="revision-1")),
            expected_head_revision_id="revision-1",
            replacement_requests=oversized_shares,
            as_of_date=_AS_OF_DATE,
        )


def test_correction_batch_keeps_shared_qualification_posting_and_name_identity() -> None:
    """The correction batch still obeys the planner's one-revision identity contract."""

    history = _history(*_cash_replacements(revision="revision-1"))
    requests = _cash_replacements(revision="revision-2")
    variants = (
        replace(
            requests[1],
            qualified_at=datetime(2026, 11, 14, 9, 30, tzinfo=UTC),
            posted_at=datetime(2026, 11, 14, 11, 30, tzinfo=UTC),
        ),
        replace(requests[1], asset_name="A different current display name"),
    )
    for payment in variants:
        with pytest.raises(CorporateActionInputValidationError):
            prepare_owner_corporate_action_revision(
                history=history,
                expected_head_revision_id="revision-1",
                replacement_requests=(requests[0], payment),
                as_of_date=_AS_OF_DATE,
            )


def test_revision_entities_reject_invalid_nested_domain_facts() -> None:
    """Immutable wrappers revalidate nested requests at the construction boundary."""

    malformed = _cash_replacements(revision="revision-1")[0]
    object.__setattr__(malformed, "asset_name", "")
    with pytest.raises(CorporateActionInputValidationError):
        OwnerCorporateActionRevisionEntry(
            entry_id=301,
            account_revision=1,
            request=malformed,
            delta=CorporateActionLedgerDelta(),
        )


def test_prepared_revision_rejects_tampered_scope_order_and_shape() -> None:
    """The public immutable result validates its canonical correction receipt."""

    def prepared() -> PreparedOwnerCorporateActionRevision:
        return prepare_owner_corporate_action_revision(
            history=_history(*_share_replacements(revision="revision-1")),
            expected_head_revision_id="revision-1",
            replacement_requests=_share_replacements(),
            as_of_date=_AS_OF_DATE,
        )

    result = prepared()
    with pytest.raises(CorporateActionInputValidationError):
        replace(result, requests=())
    with pytest.raises(CorporateActionInputValidationError):
        replace(result, previous_revision_id=" ")
    with pytest.raises(CorporateActionInputValidationError):
        replace(result, current_revision_id="revision-1")

    result = prepared()
    with pytest.raises(CorporateActionInputValidationError):
        replace(result, requests=(*result.requests[3:], *result.requests[:3]))

    result = prepared()
    duplicate_reversal = result.requests[0]
    with pytest.raises(CorporateActionInputValidationError):
        replace(
            result,
            requests=(duplicate_reversal, duplicate_reversal, *result.requests[2:]),
        )

    result = prepared()
    with pytest.raises(CorporateActionInputValidationError):
        replace(
            result,
            requests=(result.requests[1], result.requests[0], *result.requests[2:]),
        )

    result = prepared()
    object.__setattr__(result.requests[0], "asset_code", "999999.SZ")
    with pytest.raises(CorporateActionInputValidationError):
        replace(result, gate_anchor=result.gate_anchor)

    result = prepared()
    with pytest.raises(CorporateActionInputValidationError):
        replace(
            result,
            caller_stage_keys=(
                "posting:cash_entitlement",
                "posting:cash_payment",
                "posting:unknown",
            ),
        )

    result = prepared()
    object.__setattr__(result.requests[0], "asset_name", "")
    with pytest.raises(CorporateActionInputValidationError):
        replace(result, gate_anchor=result.gate_anchor)

    result = prepared()
    with patch.object(
        CorporateActionStageRequest,
        "__post_init__",
        side_effect=AttributeError("malformed nested request"),
    ):
        with pytest.raises(CorporateActionInputValidationError):
            replace(result, gate_anchor=result.gate_anchor)


def test_canonical_order_helper_rejects_unrelated_action_family() -> None:
    """Revision ordering is defined only for cash and share-distribution events."""

    with pytest.raises(CorporateActionInputValidationError):
        _canonical_stage_order(CorporateActionKind.RIGHTS_ISSUE)
