"""Pure record-date ownership replay for an anchored simulated account."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from apps.simulated_trading.domain.corporate_action_ownership_history import (
    CorporateActionOwnershipEvidence,
    OwnershipAnchorKind,
    OwnershipEvidenceError,
    OwnershipFillFact,
    OwnershipFillSide,
    OwnershipOpeningAnchor,
    OwnershipReplayRequest,
    replay_record_date_ownership,
)
from apps.simulated_trading.domain.corporate_action_posting import (
    CorporateActionEntryKind,
    CorporateActionKind,
    CorporateActionStage,
)

_ACCOUNT_ID = 7
_OWNER_ID = 11
_SECURITY_ID = "security:002727.SZ"
_ASSET_CODE = "002727.SZ"
_RECORD_DATE = date(2026, 9, 23)
_RECORD_DATE_END_EXCLUSIVE = datetime(2026, 9, 23, 16, 0, tzinfo=UTC)
_EVIDENCE_CUTOFF = datetime(2026, 9, 25, 0, 0, tzinfo=UTC)
_ANCHOR_AT = datetime(2026, 9, 1, 1, 0, tzinfo=UTC)


def _anchor() -> OwnershipOpeningAnchor:
    """Return a source-sealed synthetic zero-quantity account creation anchor."""

    return OwnershipOpeningAnchor(
        account_id=_ACCOUNT_ID,
        owner_user_id=_OWNER_ID,
        anchor_id=f"simulated-account-zero-origin:{_ACCOUNT_ID}",
        anchor_kind=OwnershipAnchorKind.ZERO_ORIGIN,
        quantity=Decimal("0.000000"),
        effective_at=_ANCHOR_AT,
        observed_at=_ANCHOR_AT,
        evidence_sha256="a" * 64,
    )


def _fill(
    *,
    trade_id: int,
    side: OwnershipFillSide,
    quantity: Decimal,
    occurred_at: datetime = datetime(2026, 9, 20, 1, 0, tzinfo=UTC),
    recorded_at: datetime = datetime(2026, 9, 20, 1, 1, tzinfo=UTC),
    binding_version: int = 4,
    receipt_version: int = 1,
) -> OwnershipFillFact:
    """Return one synthetic receipt-backed fill fact."""

    return OwnershipFillFact(
        account_id=_ACCOUNT_ID,
        owner_user_id=_OWNER_ID,
        security_id=_SECURITY_ID,
        asset_code=_ASSET_CODE,
        trade_id=trade_id,
        reservation_id=trade_id + 100,
        fill_sequence=1,
        side=side,
        quantity=quantity,
        execution_date=occurred_at.astimezone(ZoneInfo("Asia/Shanghai")).date(),
        occurred_at=occurred_at,
        recorded_at=recorded_at,
        binding_version=binding_version,
        receipt_version=receipt_version,
        receipt_sha256=f"{trade_id:064x}",
    )


def _action(
    *,
    entry_id: int,
    event_id: str,
    revision_id: str,
    stage: CorporateActionStage,
    share_delta: Decimal,
    share_receivable_delta: Decimal | None = None,
    entry_kind: CorporateActionEntryKind = CorporateActionEntryKind.POSTING,
    supersedes_revision_id: str | None = None,
    reversal_of_entry_id: int | None = None,
    stage_date: date = date(2026, 9, 10),
    posted_at: datetime = datetime(2026, 9, 10, 1, 0, tzinfo=UTC),
    recorded_at: datetime | None = None,
    action_kind: CorporateActionKind = CorporateActionKind.SHARE_DISTRIBUTION,
) -> CorporateActionOwnershipEvidence:
    """Return one synthetic immutable action-stage effect."""

    if share_receivable_delta is None:
        share_receivable_delta = (
            -share_delta if stage is CorporateActionStage.SHARE_DELIVERY else Decimal("0.000000")
        )
    if recorded_at is None:
        recorded_at = posted_at + timedelta(minutes=1)
    return CorporateActionOwnershipEvidence(
        account_id=_ACCOUNT_ID,
        owner_user_id=_OWNER_ID,
        security_id=_SECURITY_ID,
        asset_code=_ASSET_CODE,
        account_revision=entry_id,
        entry_id=entry_id,
        source_event_id=event_id,
        source_revision_id=revision_id,
        supersedes_revision_id=supersedes_revision_id,
        action_kind=action_kind,
        stage_key=f"{entry_kind.value}:{stage.value}",
        stage=stage,
        entry_kind=entry_kind,
        stage_date=stage_date,
        posted_at=posted_at,
        recorded_at=recorded_at,
        share_delta=share_delta,
        share_receivable_delta=share_receivable_delta,
        reversal_of_entry_id=reversal_of_entry_id,
        evidence_sha256=f"{entry_id:064x}",
    )


def _query(
    *,
    anchor: OwnershipOpeningAnchor | None = None,
    include_anchor: bool = True,
    fills: tuple[OwnershipFillFact, ...] = (),
    actions: tuple[CorporateActionOwnershipEvidence, ...] = (),
    record_date: date = _RECORD_DATE,
    evidence_cutoff_at: datetime = _EVIDENCE_CUTOFF,
) -> OwnershipReplayRequest:
    """Bind exact identity, the immutable anchor, and replay inputs."""

    return OwnershipReplayRequest(
        account_id=_ACCOUNT_ID,
        owner_user_id=_OWNER_ID,
        security_id=_SECURITY_ID,
        asset_code=_ASSET_CODE,
        record_date=record_date,
        record_date_end_exclusive=_RECORD_DATE_END_EXCLUSIVE,
        exchange="SZSE",
        exchange_timezone_name="Asia/Shanghai",
        cutoff_policy_id="exchange-timezone-map:v1",
        cutoff_policy_sha256="c" * 64,
        evidence_cutoff_at=evidence_cutoff_at,
        opening_anchor=(_anchor() if anchor is None else anchor) if include_anchor else None,
        fills=fills,
        corporate_actions=actions,
    )


def test_replays_anchor_complete_receipt_prefix_and_company_action_delta() -> None:
    """Use exact identity and stable evidence references for the closing quantity."""

    request = _query(
        fills=(
            _fill(
                trade_id=1,
                side=OwnershipFillSide.BUY,
                quantity=Decimal("50.000000"),
                occurred_at=datetime(2026, 9, 20, 1, 0, tzinfo=UTC),
                recorded_at=datetime(2026, 9, 20, 1, 1, tzinfo=UTC),
            ),
            _fill(
                trade_id=2,
                side=OwnershipFillSide.SELL,
                quantity=Decimal("20.000000"),
                occurred_at=datetime(2026, 9, 21, 1, 0, tzinfo=UTC),
                recorded_at=datetime(2026, 9, 21, 1, 1, tzinfo=UTC),
            ),
        ),
        actions=(
            _action(
                entry_id=3,
                event_id="SZSE:share-action-1",
                revision_id="revision-1",
                stage=CorporateActionStage.SHARE_ENTITLEMENT,
                share_delta=Decimal("0.000000"),
                share_receivable_delta=Decimal("10.000000"),
                stage_date=date(2026, 9, 10),
            ),
            _action(
                entry_id=4,
                event_id="SZSE:share-action-1",
                revision_id="revision-1",
                stage=CorporateActionStage.SHARE_DELIVERY,
                share_delta=Decimal("10.000000"),
                stage_date=date(2026, 9, 15),
            ),
        ),
    )

    proof = replay_record_date_ownership(request)

    assert proof.eligible_quantity == Decimal("40.000000")
    assert proof.ownership_snapshot_as_of_date == _RECORD_DATE
    assert len(proof.ownership_snapshot_sha256) == 64
    assert proof.ownership_snapshot_id.endswith(proof.ownership_snapshot_sha256)


def test_replay_uses_successor_revision_and_validates_its_reversal() -> None:
    """A corrected active action replaces its predecessor's economic effect."""

    request = _query(
        actions=(
            _action(
                entry_id=10,
                event_id="SZSE:share-action-2",
                revision_id="revision-1",
                stage=CorporateActionStage.SHARE_ENTITLEMENT,
                share_delta=Decimal("0.000000"),
                share_receivable_delta=Decimal("10.000000"),
            ),
            _action(
                entry_id=11,
                event_id="SZSE:share-action-2",
                revision_id="revision-2",
                stage=CorporateActionStage.SHARE_ENTITLEMENT,
                share_delta=Decimal("0.000000"),
                share_receivable_delta=Decimal("-10.000000"),
                entry_kind=CorporateActionEntryKind.REVERSAL,
                supersedes_revision_id="revision-1",
                reversal_of_entry_id=10,
                stage_date=date(2026, 9, 11),
                posted_at=datetime(2026, 9, 12, 1, 0, tzinfo=UTC),
            ),
            _action(
                entry_id=12,
                event_id="SZSE:share-action-2",
                revision_id="revision-1",
                stage=CorporateActionStage.SHARE_DELIVERY,
                share_delta=Decimal("10.000000"),
                stage_date=date(2026, 9, 11),
            ),
            _action(
                entry_id=13,
                event_id="SZSE:share-action-2",
                revision_id="revision-2",
                stage=CorporateActionStage.SHARE_DELIVERY,
                share_delta=Decimal("-10.000000"),
                entry_kind=CorporateActionEntryKind.REVERSAL,
                supersedes_revision_id="revision-1",
                reversal_of_entry_id=12,
                stage_date=date(2026, 9, 11),
                posted_at=datetime(2026, 9, 12, 1, 0, tzinfo=UTC),
            ),
            _action(
                entry_id=14,
                event_id="SZSE:share-action-2",
                revision_id="revision-2",
                stage=CorporateActionStage.SHARE_ENTITLEMENT,
                share_delta=Decimal("0.000000"),
                share_receivable_delta=Decimal("8.000000"),
                entry_kind=CorporateActionEntryKind.SUCCESSOR,
                supersedes_revision_id="revision-1",
                stage_date=date(2026, 9, 10),
                posted_at=datetime(2026, 9, 12, 1, 0, tzinfo=UTC),
            ),
            _action(
                entry_id=15,
                event_id="SZSE:share-action-2",
                revision_id="revision-2",
                stage=CorporateActionStage.SHARE_DELIVERY,
                share_delta=Decimal("8.000000"),
                entry_kind=CorporateActionEntryKind.SUCCESSOR,
                supersedes_revision_id="revision-1",
                stage_date=date(2026, 9, 11),
                posted_at=datetime(2026, 9, 12, 1, 0, tzinfo=UTC),
            ),
        ),
    )

    proof = replay_record_date_ownership(request)

    assert proof.eligible_quantity == Decimal("8.000000")


@pytest.mark.parametrize(
    ("field", "value", "code"),
    (
        ("binding_version", 3, "CORPORATE_ACTION_OWNERSHIP_RECEIPT_UNSUPPORTED"),
        ("receipt_version", 9, "CORPORATE_ACTION_OWNERSHIP_RECEIPT_UNSUPPORTED"),
        ("owner_user_id", 12, "CORPORATE_ACTION_OWNERSHIP_SCOPE_INVALID"),
        ("asset_code", "002728.SZ", "CORPORATE_ACTION_OWNERSHIP_SCOPE_INVALID"),
    ),
)
def test_replay_rejects_untrusted_or_misaligned_fill_facts(
    field: str, value: object, code: str
) -> None:
    """Reject legacy versions and every cross-owner/security/asset fact."""

    fill = replace(
        _fill(
            trade_id=1,
            side=OwnershipFillSide.BUY,
            quantity=Decimal("5.000000"),
        ),
        **{field: value},
    )
    with pytest.raises(OwnershipEvidenceError) as blocked:
        replay_record_date_ownership(_query(fills=(fill,)))

    assert blocked.value.code == code


def test_replay_blocks_any_trade_on_record_date_and_requires_complete_day() -> None:
    """Same-date trades cannot be classified, and evidence must cover record-date close."""

    same_day_fill = _fill(
        trade_id=1,
        side=OwnershipFillSide.BUY,
        quantity=Decimal("5.000000"),
        occurred_at=datetime(2026, 9, 23, 1, 0, tzinfo=UTC),
        recorded_at=datetime(2026, 9, 23, 1, 1, tzinfo=UTC),
    )
    with pytest.raises(OwnershipEvidenceError) as same_day:
        replay_record_date_ownership(_query(fills=(same_day_fill,)))
    assert same_day.value.code == "CORPORATE_ACTION_OWNERSHIP_SAME_DAY_AMBIGUOUS"

    before_close = datetime(2026, 9, 23, 15, 59, 59, tzinfo=UTC)
    with pytest.raises(OwnershipEvidenceError) as incomplete_day:
        replay_record_date_ownership(_query(evidence_cutoff_at=before_close))
    assert incomplete_day.value.code == "CORPORATE_ACTION_OWNERSHIP_RECORD_DATE_OPEN"


def test_replay_blocks_action_reversal_mismatch_and_open_receivable() -> None:
    """Only fully matched revisions with no unresolved share receivable are usable."""

    predecessor = _action(
        entry_id=20,
        event_id="SZSE:share-action-3",
        revision_id="revision-1",
        stage=CorporateActionStage.SHARE_DELIVERY,
        share_delta=Decimal("10.000000"),
    )
    mismatched_reversal = _action(
        entry_id=21,
        event_id="SZSE:share-action-3",
        revision_id="revision-2",
        stage=CorporateActionStage.SHARE_DELIVERY,
        share_delta=Decimal("-9.000000"),
        entry_kind=CorporateActionEntryKind.REVERSAL,
        supersedes_revision_id="revision-1",
        reversal_of_entry_id=20,
        stage_date=date(2026, 9, 11),
        posted_at=datetime(2026, 9, 12, 1, 0, tzinfo=UTC),
    )
    with pytest.raises(OwnershipEvidenceError) as reversal:
        replay_record_date_ownership(_query(actions=(predecessor, mismatched_reversal)))
    assert reversal.value.code == "CORPORATE_ACTION_OWNERSHIP_ACTION_REVERSAL_INVALID"

    open_receivable = _action(
        entry_id=22,
        event_id="SZSE:share-action-4",
        revision_id="revision-1",
        stage=CorporateActionStage.SHARE_ENTITLEMENT,
        share_delta=Decimal("0.000000"),
        share_receivable_delta=Decimal("10.000000"),
        stage_date=date(2026, 9, 10),
    )
    with pytest.raises(OwnershipEvidenceError) as receivable:
        replay_record_date_ownership(_query(actions=(open_receivable,)))
    assert receivable.value.code == "CORPORATE_ACTION_OWNERSHIP_ACTION_RECEIVABLE_OPEN"


def test_replay_settles_event_receivable_across_distinct_dates() -> None:
    """Aggregate the event-level entitlement and delivery across effective dates."""

    request = _query(
        actions=(
            _action(
                entry_id=30,
                event_id="SZSE:share-action-settled",
                revision_id="revision-1",
                stage=CorporateActionStage.SHARE_ENTITLEMENT,
                share_delta=Decimal("0.000000"),
                share_receivable_delta=Decimal("10.000000"),
                stage_date=date(2026, 9, 10),
            ),
            _action(
                entry_id=31,
                event_id="SZSE:share-action-settled",
                revision_id="revision-1",
                stage=CorporateActionStage.SHARE_DELIVERY,
                share_delta=Decimal("10.000000"),
                stage_date=date(2026, 9, 11),
            ),
        )
    )

    assert replay_record_date_ownership(request).eligible_quantity == Decimal("10.000000")


def test_replay_rejects_delivery_before_entitlement_even_when_dates_differ() -> None:
    """A final positive receivable cannot hide a negative intermediate balance."""

    request = _query(
        actions=(
            _action(
                entry_id=32,
                event_id="SZSE:share-action-reversed-order",
                revision_id="revision-1",
                stage=CorporateActionStage.SHARE_DELIVERY,
                share_delta=Decimal("10.000000"),
                stage_date=date(2026, 9, 10),
            ),
            _action(
                entry_id=33,
                event_id="SZSE:share-action-reversed-order",
                revision_id="revision-1",
                stage=CorporateActionStage.SHARE_ENTITLEMENT,
                share_delta=Decimal("0.000000"),
                share_receivable_delta=Decimal("10.000000"),
                stage_date=date(2026, 9, 11),
            ),
        )
    )

    with pytest.raises(OwnershipEvidenceError) as blocked:
        replay_record_date_ownership(request)

    assert blocked.value.code == "CORPORATE_ACTION_OWNERSHIP_ACTION_RECEIVABLE_OPEN"


def test_replay_checks_fill_solvency_after_each_fill_in_timestamp_order() -> None:
    """A later buy cannot conceal an earlier impossible sell on the same day."""

    sell = _fill(
        trade_id=40,
        side=OwnershipFillSide.SELL,
        quantity=Decimal("1.000000"),
        occurred_at=datetime(2026, 9, 20, 1, 0, tzinfo=UTC),
        recorded_at=datetime(2026, 9, 20, 1, 1, tzinfo=UTC),
    )
    buy = _fill(
        trade_id=41,
        side=OwnershipFillSide.BUY,
        quantity=Decimal("1.000000"),
        occurred_at=datetime(2026, 9, 20, 2, 0, tzinfo=UTC),
        recorded_at=datetime(2026, 9, 20, 2, 1, tzinfo=UTC),
    )

    with pytest.raises(OwnershipEvidenceError) as blocked:
        replay_record_date_ownership(_query(fills=(sell, buy)))

    assert blocked.value.code == "CORPORATE_ACTION_OWNERSHIP_QUANTITY_INVALID"


def test_replay_blocks_share_action_before_zero_origin_anchor() -> None:
    """An immutable action before account creation contradicts a zero origin."""

    action = _action(
        entry_id=50,
        event_id="SZSE:share-action-before-anchor",
        revision_id="revision-1",
        stage=CorporateActionStage.SHARE_ENTITLEMENT,
        share_delta=Decimal("0.000000"),
        share_receivable_delta=Decimal("10.000000"),
        stage_date=date(2026, 8, 31),
        posted_at=datetime(2026, 8, 31, 1, 0, tzinfo=UTC),
    )

    with pytest.raises(OwnershipEvidenceError) as blocked:
        replay_record_date_ownership(_query(actions=(action,)))

    assert blocked.value.code == "CORPORATE_ACTION_OWNERSHIP_ANCHOR_UNAVAILABLE"


def test_replay_requires_cutoff_bound_to_qualified_timezone_policy() -> None:
    """Reject a mismatched exchange timezone or an unqualified policy ID."""

    with pytest.raises(OwnershipEvidenceError):
        replace(_query(), exchange_timezone_name="UTC")
    with pytest.raises(OwnershipEvidenceError):
        replace(_query(), cutoff_policy_id=" ")


def test_zero_origin_anchor_cannot_claim_a_nonzero_opening_quantity() -> None:
    """An anchor created as zero-origin cannot smuggle in opening shares."""

    with pytest.raises(OwnershipEvidenceError) as blocked:
        replace(_anchor(), quantity=Decimal("100.000000"))

    assert blocked.value.code == "CORPORATE_ACTION_OWNERSHIP_ANCHOR_UNAVAILABLE"


def test_replay_requires_zero_origin_anchor_and_blocks_negative_quantity() -> None:
    """Missing anchors and impossible outflows never yield an ownership proof."""

    with pytest.raises(OwnershipEvidenceError) as missing:
        replay_record_date_ownership(_query(include_anchor=False))
    assert missing.value.code == "CORPORATE_ACTION_OWNERSHIP_ANCHOR_UNAVAILABLE"

    with pytest.raises(OwnershipEvidenceError) as negative:
        replay_record_date_ownership(
            _query(
                fills=(
                    _fill(
                        trade_id=1,
                        side=OwnershipFillSide.SELL,
                        quantity=Decimal("101.000000"),
                    ),
                )
            )
        )
    assert negative.value.code == "CORPORATE_ACTION_OWNERSHIP_QUANTITY_INVALID"
