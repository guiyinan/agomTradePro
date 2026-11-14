"""Synthetic unit contracts for complete owner correction previews."""

from __future__ import annotations

from dataclasses import fields, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256

import pytest

from apps.simulated_trading.application.corporate_action_owner_revision_preview import (
    OwnerCorporateActionRevisionPreview,
    build_owner_corporate_action_revision_preview,
)
from apps.simulated_trading.corporate_action_owner_event_support import (
    PreparedOwnerOfficialAction,
)
from apps.simulated_trading.domain.corporate_action_owner_revision import (
    OwnerCorporateActionRevisionEntry,
    PreparedOwnerCorporateActionRevision,
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

_ACCOUNT_ID = 41
_OWNER_ID = 83
_ASSET = "000001.SZ"
_EVENT_ID = "event-ash05-preview"
_RECORD_DATE = date(2026, 10, 30)
_EX_DATE = date(2026, 10, 31)
_PAYMENT_DATE = date(2026, 11, 5)
_DELIVERY_DATE = date(2026, 11, 6)
_SELLABLE_DATE = date(2026, 11, 10)
_AS_OF_DATE = date(2026, 11, 14)
_OLD_REVISION = "revision-old"
_NEW_REVISION = "revision-new"


def _digest(value: str) -> str:
    """Return one deterministic synthetic digest for a source-fixture component."""

    return sha256(value.encode("utf-8")).hexdigest()


def _request(
    *,
    action_kind: CorporateActionKind,
    stage: CorporateActionStage,
    amount: Decimal,
    source_revision_id: str,
    source_record_id: str,
    entry_kind: CorporateActionEntryKind = CorporateActionEntryKind.POSTING,
) -> CorporateActionStageRequest:
    """Construct a valid synthetic original or current-source stage request."""

    source_clock = datetime(
        2026,
        11,
        13 if source_revision_id == _OLD_REVISION else 14,
        2,
        0,
        tzinfo=UTC,
    )
    kwargs: dict[str, object] = {
        "account_id": _ACCOUNT_ID,
        "owner_user_id": _OWNER_ID,
        "security_id": _ASSET,
        "asset_code": _ASSET,
        "asset_name": "Synthetic preview security",
        "source_namespace": "exchange_official_disclosure",
        "source_record_id": source_record_id,
        "source_event_id": _EVENT_ID,
        "source_revision_id": source_revision_id,
        "source_payload_sha256": _digest(source_record_id),
        "qualification_sha256": _digest("qualification-" + source_revision_id),
        "qualifier_identity": "synthetic-preview-source",
        "source_observed_at": source_clock,
        "qualified_at": source_clock + timedelta(minutes=1),
        "posted_at": source_clock + timedelta(minutes=2),
        "action_kind": action_kind,
        "stage": stage,
        "entry_kind": entry_kind,
        "record_date": _RECORD_DATE,
        "effective_date": _EX_DATE,
        "stage_date": _RECORD_DATE,
        "tax_treatment": (
            "deferred_withholding"
            if action_kind is CorporateActionKind.CASH_DIVIDEND
            else "not_applicable"
        ),
    }
    if action_kind is CorporateActionKind.CASH_DIVIDEND:
        kwargs["cash_amount"] = amount
        if stage is CorporateActionStage.CASH_ENTITLEMENT:
            kwargs.update(
                {
                    "ownership_snapshot_id": "synthetic-owner-proof-" + source_revision_id,
                    "ownership_snapshot_sha256": _digest("owner-proof-" + source_revision_id),
                    "ownership_snapshot_as_of_date": _RECORD_DATE,
                    "ownership_snapshot_observed_at": source_clock,
                    "eligible_quantity": Decimal("100"),
                    "entitlement_calculation_sha256": _digest(
                        "cash-entitlement-" + source_revision_id
                    ),
                }
            )
        else:
            kwargs["stage_date"] = _PAYMENT_DATE
            kwargs["payment_date"] = _PAYMENT_DATE
    else:
        kwargs["share_amount"] = amount
        kwargs["odd_lot_policy"] = "whole_shares"
        if stage is CorporateActionStage.SHARE_ENTITLEMENT:
            kwargs.update(
                {
                    "ownership_snapshot_id": "synthetic-owner-proof-" + source_revision_id,
                    "ownership_snapshot_sha256": _digest("owner-proof-" + source_revision_id),
                    "ownership_snapshot_as_of_date": _RECORD_DATE,
                    "ownership_snapshot_observed_at": source_clock,
                    "eligible_quantity": Decimal("100"),
                    "entitlement_calculation_sha256": _digest(
                        "share-entitlement-" + source_revision_id
                    ),
                }
            )
        elif stage is CorporateActionStage.SHARE_DELIVERY:
            kwargs["stage_date"] = _DELIVERY_DATE
            kwargs["sellable_date"] = _SELLABLE_DATE
        else:
            kwargs["stage_date"] = _SELLABLE_DATE
            kwargs["sellable_date"] = _SELLABLE_DATE
    return CorporateActionStageRequest(**kwargs)  # type: ignore[arg-type]


def _history(
    action_kind: CorporateActionKind,
) -> tuple[OwnerCorporateActionRevisionEntry, ...]:
    """Build the complete synthetic active ledger history for one family."""

    if action_kind is CorporateActionKind.CASH_DIVIDEND:
        stages = (
            CorporateActionStage.CASH_ENTITLEMENT,
            CorporateActionStage.CASH_PAYMENT,
        )
    else:
        stages = (
            CorporateActionStage.SHARE_ENTITLEMENT,
            CorporateActionStage.SHARE_DELIVERY,
            CorporateActionStage.SHARE_SELLABLE_RELEASE,
        )
    amount = Decimal("10.00") if action_kind is CorporateActionKind.CASH_DIVIDEND else Decimal("20")
    return tuple(
        OwnerCorporateActionRevisionEntry(
            entry_id=100 + index,
            account_revision=index,
            request=_request(
                action_kind=action_kind,
                stage=stage,
                amount=amount,
                source_revision_id=_OLD_REVISION,
                source_record_id="source-record-old",
            ),
            delta=calculate_corporate_action_delta(
                _request(
                    action_kind=action_kind,
                    stage=stage,
                    amount=amount,
                    source_revision_id=_OLD_REVISION,
                    source_record_id="source-record-old",
                )
            ),
        )
        for index, stage in enumerate(stages, 1)
    )


def _prepared(
    action_kind: CorporateActionKind,
) -> tuple[
    PreparedOwnerCorporateActionRevision,
    tuple[OwnerCorporateActionRevisionEntry, ...],
]:
    """Build a complete synthetic current-source correction and its verified head."""

    history = _history(action_kind)
    if action_kind is CorporateActionKind.CASH_DIVIDEND:
        stages = (
            CorporateActionStage.CASH_ENTITLEMENT,
            CorporateActionStage.CASH_PAYMENT,
        )
        amount = Decimal("12.00")
    else:
        stages = (
            CorporateActionStage.SHARE_ENTITLEMENT,
            CorporateActionStage.SHARE_DELIVERY,
            CorporateActionStage.SHARE_SELLABLE_RELEASE,
        )
        amount = Decimal("25")
    replacements = tuple(
        _request(
            action_kind=action_kind,
            stage=stage,
            amount=amount,
            source_revision_id=_NEW_REVISION,
            source_record_id="source-record-new",
        )
        for stage in stages
    )
    batch = prepare_owner_corporate_action_revision(
        history=history,
        expected_head_revision_id=_OLD_REVISION,
        replacement_requests=replacements,
        as_of_date=_AS_OF_DATE,
    )
    active = read_owner_corporate_action_revision_head(
        history, expected_head_revision_id=_OLD_REVISION
    )
    return batch, active


def _inverse(delta: CorporateActionLedgerDelta) -> CorporateActionLedgerDelta:
    """Return the exact signed inverse of one retained active stage."""

    return CorporateActionLedgerDelta(
        cash=-delta.cash,
        cash_receivable=-delta.cash_receivable,
        shares=-delta.shares,
        share_receivable=-delta.share_receivable,
        available_shares=-delta.available_shares,
    )


def test_cash_preview_pairs_exact_inverse_and_current_source_deltas() -> None:
    batch, active = _prepared(CorporateActionKind.CASH_DIVIDEND)

    preview = build_owner_corporate_action_revision_preview(
        prepared_batch=batch,
        active_entries=active,
    )

    assert type(preview) is OwnerCorporateActionRevisionPreview
    assert preview.previous_source_revision_id == _OLD_REVISION
    assert preview.current_source_revision_id == _NEW_REVISION
    assert [(row.entry_kind, row.stage) for row in preview.rows] == [
        (CorporateActionEntryKind.REVERSAL, CorporateActionStage.CASH_PAYMENT),
        (CorporateActionEntryKind.REVERSAL, CorporateActionStage.CASH_ENTITLEMENT),
        (CorporateActionEntryKind.SUCCESSOR, CorporateActionStage.CASH_ENTITLEMENT),
        (CorporateActionEntryKind.SUCCESSOR, CorporateActionStage.CASH_PAYMENT),
    ]
    assert [row.reverses_entry_id for row in preview.rows] == [102, 101, None, None]
    assert [row.previous_source_revision_id for row in preview.rows] == [_OLD_REVISION] * 4
    assert [row.source_revision_id for row in preview.rows] == [_NEW_REVISION] * 4
    assert [row.signed_delta for row in preview.rows] == [
        _inverse(active[1].delta),
        _inverse(active[0].delta),
        CorporateActionLedgerDelta(cash_receivable=Decimal("12.00")),
        CorporateActionLedgerDelta(cash=Decimal("12.00"), cash_receivable=Decimal("-12.00")),
    ]


def test_share_preview_shows_full_reverse_and_replacement_stage_effects() -> None:
    batch, active = _prepared(CorporateActionKind.SHARE_DISTRIBUTION)

    preview = build_owner_corporate_action_revision_preview(
        prepared_batch=batch,
        active_entries=active,
    )

    assert [(row.entry_kind, row.stage) for row in preview.rows] == [
        (CorporateActionEntryKind.REVERSAL, CorporateActionStage.SHARE_SELLABLE_RELEASE),
        (CorporateActionEntryKind.REVERSAL, CorporateActionStage.SHARE_DELIVERY),
        (CorporateActionEntryKind.REVERSAL, CorporateActionStage.SHARE_ENTITLEMENT),
        (CorporateActionEntryKind.SUCCESSOR, CorporateActionStage.SHARE_ENTITLEMENT),
        (CorporateActionEntryKind.SUCCESSOR, CorporateActionStage.SHARE_DELIVERY),
        (CorporateActionEntryKind.SUCCESSOR, CorporateActionStage.SHARE_SELLABLE_RELEASE),
    ]
    assert [row.reverses_entry_id for row in preview.rows] == [103, 102, 101, None, None, None]
    assert [row.signed_delta for row in preview.rows] == [
        _inverse(active[2].delta),
        _inverse(active[1].delta),
        _inverse(active[0].delta),
        CorporateActionLedgerDelta(share_receivable=Decimal("25")),
        CorporateActionLedgerDelta(shares=Decimal("25"), share_receivable=Decimal("-25")),
        CorporateActionLedgerDelta(available_shares=Decimal("25")),
    ]


def test_preview_rejects_a_reversal_target_outside_the_verified_active_head() -> None:
    batch, active = _prepared(CorporateActionKind.CASH_DIVIDEND)
    tampered_reversal = replace(batch.requests[0], reversal_of_entry_id=999)
    tampered_batch = replace(batch, requests=(tampered_reversal, *batch.requests[1:]))

    with pytest.raises(CorporateActionInputValidationError):
        build_owner_corporate_action_revision_preview(
            prepared_batch=tampered_batch,
            active_entries=active,
        )


def test_preview_rejects_an_incomplete_active_stage_set() -> None:
    batch, active = _prepared(CorporateActionKind.SHARE_DISTRIBUTION)

    with pytest.raises(CorporateActionInputValidationError):
        build_owner_corporate_action_revision_preview(
            prepared_batch=batch,
            active_entries=active[:-1],
        )


def test_preview_rejects_a_cross_account_active_target() -> None:
    batch, active = _prepared(CorporateActionKind.CASH_DIVIDEND)
    foreign_request = replace(active[0].request, account_id=_ACCOUNT_ID + 1)
    foreign_entry = replace(
        active[0],
        request=foreign_request,
        delta=calculate_corporate_action_delta(foreign_request),
    )

    with pytest.raises(CorporateActionInputValidationError):
        build_owner_corporate_action_revision_preview(
            prepared_batch=batch,
            active_entries=(foreign_entry, *active[1:]),
        )


def test_preview_rejects_a_noncanonical_batch_order() -> None:
    batch, active = _prepared(CorporateActionKind.SHARE_DISTRIBUTION)
    reordered = (batch.requests[1], batch.requests[0], *batch.requests[2:])

    with pytest.raises(CorporateActionInputValidationError):
        tampered_batch = replace(batch, requests=reordered)
        build_owner_corporate_action_revision_preview(
            prepared_batch=tampered_batch,
            active_entries=active,
        )


def test_preview_rejects_a_tampered_active_ledger_delta() -> None:
    batch, active = _prepared(CorporateActionKind.CASH_DIVIDEND)
    tampered_entry = replace(
        active[0],
        delta=CorporateActionLedgerDelta(cash_receivable=Decimal("10.01")),
    )

    with pytest.raises(CorporateActionInputValidationError):
        build_owner_corporate_action_revision_preview(
            prepared_batch=batch,
            active_entries=(tampered_entry, *active[1:]),
        )


def test_preview_rejects_a_replaced_reversal_row_with_a_finite_but_wrong_delta() -> None:
    batch, active = _prepared(CorporateActionKind.CASH_DIVIDEND)
    preview = build_owner_corporate_action_revision_preview(
        prepared_batch=batch,
        active_entries=active,
    )
    tampered_row = replace(
        preview.rows[0],
        signed_delta=CorporateActionLedgerDelta(cash=Decimal("1.00")),
    )

    with pytest.raises(CorporateActionInputValidationError):
        replace(preview, rows=(tampered_row, *preview.rows[1:]))


def test_preview_row_rejects_string_values_that_compare_equal_to_enums() -> None:
    batch, active = _prepared(CorporateActionKind.CASH_DIVIDEND)
    preview = build_owner_corporate_action_revision_preview(
        prepared_batch=batch,
        active_entries=active,
    )

    with pytest.raises(CorporateActionInputValidationError):
        replace(preview.rows[0], entry_kind="reversal")
    with pytest.raises(CorporateActionInputValidationError):
        replace(preview.rows[0], action_kind="cash_dividend")


@pytest.mark.parametrize("target_id", [-1, False, 0, 1])
def test_successor_preview_row_requires_reversal_target_to_be_none(target_id: object) -> None:
    batch, active = _prepared(CorporateActionKind.CASH_DIVIDEND)
    preview = build_owner_corporate_action_revision_preview(
        prepared_batch=batch,
        active_entries=active,
    )

    with pytest.raises(CorporateActionInputValidationError):
        replace(preview.rows[-1], reverses_entry_id=target_id)


def test_prepared_action_keeps_revision_preview_optional_for_old_callers() -> None:
    names = {field.name: field for field in fields(PreparedOwnerOfficialAction)}

    assert names["revision_preview"].default is None
