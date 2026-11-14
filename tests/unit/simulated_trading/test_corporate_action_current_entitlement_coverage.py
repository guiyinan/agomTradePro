"""Synthetic unit contracts for separately recognized corporate-action rights.

These tests exercise only the read-only entitlement contract. Synthetic source
bytes are not evidence of current official disclosure acceptance; callers remain
responsible for the current window, owner lock, historical Audit, and Outbox.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

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
_LOGICAL_EVENT_ID = "fca1e323-1c2e-44c8-8c5c-1b73c1699001"
_RECORD_DATE = date(2026, 10, 30)
_EX_DATE = date(2026, 10, 31)
_SOURCE_SEEN = datetime(2026, 10, 20, 1, 0, tzinfo=UTC)
_QUALIFIED_AT = datetime(2026, 11, 1, 1, 0, tzinfo=UTC)
_POSTED_AT = datetime(2026, 11, 1, 1, 1, tzinfo=UTC)
_RECORD_DATE_END = datetime(2026, 10, 31, 0, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def _event(
    *,
    event_id: str = _LOGICAL_EVENT_ID,
    body: bytes | None = None,
    prior: SecurityDisclosureEvent | None = None,
) -> SecurityDisclosureEvent:
    """Return one explicitly synthetic source revision with optional predecessor."""

    body_bytes = body or f"synthetic-only:{event_id}".encode("ascii")
    return SecurityDisclosureEvent.from_source_document(
        source=SecurityDisclosureSource.SZSE_OFFICIAL,
        exchange=SecurityDisclosureExchange.SZSE,
        asset_code=_ASSET,
        source_security_code=_ASSET[:6],
        source_event_id=event_id,
        source_revision_id=f"sha256:{hashlib.sha256(body_bytes).hexdigest()}",
        raw_event_type=SecurityDisclosureEventType.CASH_DIVIDEND.value,
        event_type=SecurityDisclosureEventType.CASH_DIVIDEND,
        source_url=f"https://disc.static.szse.cn/synthetic/{event_id}.PDF",
        source_document_body=body_bytes,
        first_seen_at=_SOURCE_SEEN + (timedelta(days=1) if prior is not None else timedelta()),
        effective_at=_EX_DATE,
        supersedes_source_event_id=prior.source_event_id if prior is not None else None,
        supersedes_source_revision_id=prior.source_revision_id if prior is not None else None,
    )


def _terms(cash_per_ten: Decimal = Decimal("1.23")) -> SzseDistributionTerms:
    """Return exact synthetic terms with distinct record and ex-dates."""

    return SzseDistributionTerms(
        record_date=_RECORD_DATE,
        ex_date=_EX_DATE,
        payment_date=date(2026, 11, 5),
        cash_per_ten=cash_per_ten,
        shares_per_ten=None,
        tax_treatment="deferred_withholding",
    )


def _proof(
    quantity: Decimal = Decimal("100.000000"),
    *,
    account_id: int = _ACCOUNT_ID,
    owner_user_id: int = _OWNER_ID,
    snapshot_id: str = "synthetic-record-date-snapshot",
    snapshot_sha256: str = "b" * 64,
    observed_at: datetime = _QUALIFIED_AT,
    record_date_end_exclusive: datetime = _RECORD_DATE_END,
) -> RecordDateOwnershipProof:
    """Return a complete-shaped synthetic proof for the closed record-date boundary."""

    return RecordDateOwnershipProof(
        account_id=account_id,
        owner_user_id=owner_user_id,
        security_id=_ASSET,
        asset_code=_ASSET,
        record_date=_RECORD_DATE,
        ownership_snapshot_as_of_date=_RECORD_DATE,
        record_date_end_exclusive=record_date_end_exclusive,
        exchange="SZSE",
        exchange_timezone_name="Asia/Shanghai",
        cutoff_policy_id="synthetic-exchange-timezone-policy",
        cutoff_policy_sha256="a" * 64,
        eligible_quantity=quantity,
        ownership_snapshot_id=snapshot_id,
        ownership_snapshot_sha256=snapshot_sha256,
        ownership_snapshot_observed_at=observed_at,
    )


def _request(
    event: SecurityDisclosureEvent,
    terms: SzseDistributionTerms,
    proof: RecordDateOwnershipProof,
    *,
    amount: Decimal | None = None,
    entry_kind: CorporateActionEntryKind = CorporateActionEntryKind.POSTING,
    supersedes_revision_id: str | None = None,
    reversal_of_entry_id: int | None = None,
    account_id: int = _ACCOUNT_ID,
    source_record_id: str | None = None,
    source_event_id: str = _LOGICAL_EVENT_ID,
    source_revision_id: str | None = None,
    source_payload_sha256: str | None = None,
    asset_code: str = _ASSET,
    security_id: str = _ASSET,
) -> CorporateActionStageRequest:
    """Build one real Domain request for an initial, reversal, or successor row."""

    is_reversal = entry_kind is CorporateActionEntryKind.REVERSAL
    return CorporateActionStageRequest(
        account_id=account_id,
        owner_user_id=proof.owner_user_id,
        security_id=security_id,
        asset_code=asset_code,
        asset_name="Synthetic test security",
        source_namespace="exchange_official_disclosure",
        source_record_id=source_record_id or event.source_event_id,
        source_event_id=source_event_id,
        source_revision_id=source_revision_id or event.source_revision_id,
        source_payload_sha256=source_payload_sha256 or event.source_body_sha256,
        qualification_sha256=szse_action_qualification_sha256(event, terms),
        qualifier_identity="szse_official_pdf.v1",
        source_observed_at=event.first_seen_at,
        qualified_at=_QUALIFIED_AT,
        posted_at=_POSTED_AT,
        action_kind=CorporateActionKind.CASH_DIVIDEND,
        stage=CorporateActionStage.CASH_ENTITLEMENT,
        entry_kind=entry_kind,
        record_date=terms.record_date,
        effective_date=terms.ex_date,
        stage_date=terms.record_date,
        cash_amount=None if is_reversal else (amount or Decimal("12.30")),
        tax_treatment=None if is_reversal else terms.tax_treatment,
        ownership_snapshot_id=None if is_reversal else proof.ownership_snapshot_id,
        ownership_snapshot_sha256=None if is_reversal else proof.ownership_snapshot_sha256,
        ownership_snapshot_as_of_date=None if is_reversal else proof.ownership_snapshot_as_of_date,
        ownership_snapshot_observed_at=(
            None if is_reversal else proof.ownership_snapshot_observed_at
        ),
        eligible_quantity=None if is_reversal else proof.eligible_quantity,
        entitlement_calculation_sha256=None if is_reversal else "e" * 64,
        supersedes_revision_id=supersedes_revision_id,
        reversal_of_entry_id=reversal_of_entry_id,
    )


def _row(
    request: CorporateActionStageRequest,
    *,
    account_user_id: int = _OWNER_ID,
    account_revision: int = 1,
    primary_key: int = 101,
    reversal_target: CorporateActionPostingModel | None = None,
    delta: CorporateActionLedgerDelta | None = None,
) -> CorporateActionPostingModel:
    """Map a real Domain request into an unsaved posting model row."""

    account = SimulatedAccountModel(pk=request.account_id, user_id=account_user_id)
    row = DjangoCorporateActionPostingRepository._make_row(
        request=request,
        account=account,
        account_revision=account_revision,
        delta=delta or calculate_corporate_action_delta(request),
        reverses=reversal_target,
    )
    row.pk = primary_key
    return row


def _inspect(
    *,
    event: SecurityDisclosureEvent | None = None,
    terms: SzseDistributionTerms | None = None,
    proof: RecordDateOwnershipProof | None = None,
    rows: tuple[CorporateActionPostingModel, ...] = (),
) -> coverage.CurrentAssetEntitlementCoverage:
    """Inspect one synthetic current cash event through the registered public API."""

    selected_event = event or _event()
    selected_terms = terms or _terms()
    selected_proof = proof or _proof()
    return coverage.inspect_current_distribution_entitlement(
        event=selected_event,
        terms=selected_terms,
        logical_source_event_id=_LOGICAL_EVENT_ID,
        proof=selected_proof,
        rows=rows,
    )


def test_missing_cash_entitlement_is_unknown_not_complete_zero() -> None:
    """Source facts and a positive record-date proof cannot synthesize a receivable."""

    result = _inspect(proof=_proof())

    assert result.cash_complete is False
    assert result.minimum_mark_date == _EX_DATE


def test_exact_current_source_and_closed_record_date_entitlement_are_complete() -> None:
    """An exact current body, owner, closed proof, quantity, and gross match is recognized."""

    event = _event()
    terms = _terms()
    proof = _proof()
    request = _request(event, terms, proof)
    row = _row(request)

    result = _inspect(event=event, terms=terms, proof=proof, rows=(row,))

    assert result.cash_complete is True
    assert result.minimum_mark_date == terms.ex_date


@pytest.mark.parametrize(
    "mismatch",
    ("account", "owner", "security", "source_record", "source_body", "revision", "gross"),
)
def test_mismatched_owner_source_or_gross_cannot_cover_receivable(mismatch: str) -> None:
    """Every current entitlement must bind to the exact physical/source/economic scope."""

    event = _event()
    terms = _terms()
    proof = _proof()
    changes: dict[str, object] = {}
    account_user_id = _OWNER_ID
    if mismatch == "account":
        changes["account_id"] = _ACCOUNT_ID + 1
    elif mismatch == "owner":
        account_user_id = _OWNER_ID + 1
    elif mismatch == "security":
        changes["asset_code"] = "000002.SZ"
        changes["security_id"] = "000002.SZ"
    elif mismatch == "source_record":
        changes["source_record_id"] = "another-source-record"
    elif mismatch == "source_body":
        changes["source_payload_sha256"] = "f" * 64
    elif mismatch == "revision":
        changes["source_revision_id"] = f"sha256:{'f' * 64}"
    else:
        changes["amount"] = Decimal("12.31")
    request = _request(event, terms, proof, **changes)
    row = _row(request, account_user_id=account_user_id)

    result = _inspect(event=event, terms=terms, proof=proof, rows=(row,))

    assert result.cash_complete is False


def test_open_record_date_boundary_cannot_cover_entitlement() -> None:
    """A proof cutoff before the next exchange-local midnight is not a closed snapshot."""

    event = _event()
    terms = _terms()
    open_proof = _proof(
        record_date_end_exclusive=datetime(2026, 10, 30, 23, 59, tzinfo=ZoneInfo("Asia/Shanghai"))
    )
    row = _row(_request(event, terms, open_proof))

    result = _inspect(event=event, terms=terms, proof=open_proof, rows=(row,))

    assert result.cash_complete is False


def test_incomplete_correction_does_not_treat_one_successor_as_complete() -> None:
    """A successor cannot stand alone when it has not reversed the active predecessor."""

    proof = _proof()
    old_event = _event()
    old_terms = _terms(Decimal("1.00"))
    old_request = _request(old_event, old_terms, proof, amount=Decimal("10.00"))
    old_row = _row(old_request, primary_key=101, account_revision=1)
    current_event = _event(event_id="fca1e323-1c2e-44c8-8c5c-1b73c1699002", prior=old_event)
    current_terms = _terms(Decimal("1.23"))
    successor_request = _request(
        current_event,
        current_terms,
        proof,
        amount=Decimal("12.30"),
        entry_kind=CorporateActionEntryKind.SUCCESSOR,
        supersedes_revision_id=old_event.source_revision_id,
    )
    successor_row = _row(successor_request, primary_key=103, account_revision=3)

    result = _inspect(
        event=current_event,
        terms=current_terms,
        proof=proof,
        rows=(old_row, successor_row),
    )

    assert result.cash_complete is False


def test_complete_reversal_and_successor_chain_covers_current_entitlement() -> None:
    """Only a full exact correction batch plus the current successor covers the right."""

    proof = _proof()
    old_event = _event()
    old_terms = _terms(Decimal("1.00"))
    old_request = _request(old_event, old_terms, proof, amount=Decimal("10.00"))
    old_row = _row(old_request, primary_key=101, account_revision=1)
    current_event = _event(event_id="fca1e323-1c2e-44c8-8c5c-1b73c1699003", prior=old_event)
    current_terms = _terms(Decimal("1.23"))
    reversal_request = _request(
        current_event,
        current_terms,
        proof,
        entry_kind=CorporateActionEntryKind.REVERSAL,
        supersedes_revision_id=old_event.source_revision_id,
        reversal_of_entry_id=old_row.pk,
    )
    reversal_row = _row(
        reversal_request,
        primary_key=102,
        account_revision=2,
        reversal_target=old_row,
        delta=CorporateActionLedgerDelta(cash_receivable=-old_row.cash_receivable_delta),
    )
    successor_request = _request(
        current_event,
        current_terms,
        proof,
        amount=Decimal("12.30"),
        entry_kind=CorporateActionEntryKind.SUCCESSOR,
        supersedes_revision_id=old_event.source_revision_id,
    )
    successor_row = _row(successor_request, primary_key=103, account_revision=3)

    result = _inspect(
        event=current_event,
        terms=current_terms,
        proof=proof,
        rows=(old_row, reversal_row, successor_row),
    )

    assert result.cash_complete is True
    assert result.minimum_mark_date == current_terms.ex_date


def test_observation_only_proof_refresh_preserves_recognition_identity() -> None:
    """A new snapshot observation with the same closed quantity does not change the right."""

    event = _event()
    terms = _terms()
    original_proof = _proof()
    row = _row(_request(event, terms, original_proof))
    original = _inspect(event=event, terms=terms, proof=original_proof, rows=(row,))
    refreshed_proof = _proof(
        original_proof.eligible_quantity,
        snapshot_id="synthetic-refreshed-observation",
        snapshot_sha256="c" * 64,
        observed_at=_QUALIFIED_AT + timedelta(hours=1),
    )

    refreshed = _inspect(event=event, terms=terms, proof=refreshed_proof, rows=(row,))

    assert original.cash_complete is True
    assert refreshed.cash_complete is True
    assert refreshed.evidence_sha256 == original.evidence_sha256


def test_empty_current_window_can_be_complete_without_mark_floor() -> None:
    """A caller-verified complete empty window has no rights and no ex-date mark floor."""

    result = coverage.combine_current_entitlement_coverage(
        asset_code=_ASSET,
        window_sha256="d" * 64,
        events=(),
    )

    assert result.cash_complete is True
    assert result.shares_complete is True
    assert result.minimum_mark_date is None
