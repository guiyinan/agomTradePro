"""Separate current recognized rights from complete simulated tax exposure."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from apps.data_center.domain.security_disclosure_event import (
    SecurityDisclosureEvent,
    SecurityDisclosureEventType,
    SzseDistributionTerms,
)
from apps.simulated_trading.application.corporate_action_official_window_evidence import _is_sha256
from apps.simulated_trading.audited_corporate_action_posting_composition import (
    _ledger_row_matches_request,
)
from apps.simulated_trading.corporate_action_owner_event_requests import (
    _cash_gross,
    _whole_share_gross,
)
from apps.simulated_trading.corporate_action_owner_event_support import _OFFICIAL_NAMESPACE
from apps.simulated_trading.domain.corporate_action_owner_revision import (
    OwnerCorporateActionRevisionEntry,
    read_owner_corporate_action_revision_head,
)
from apps.simulated_trading.domain.corporate_action_ownership_history import (
    RecordDateOwnershipProof,
)
from apps.simulated_trading.domain.corporate_action_performance_projection import (
    RestatementEntitlement,
    RestatementTransfer,
)
from apps.simulated_trading.domain.corporate_action_posting import (
    CorporateActionEntryKind,
    CorporateActionKind,
    CorporateActionLedgerDelta,
    CorporateActionStage,
    CorporateActionStageRequest,
)
from apps.simulated_trading.infrastructure.corporate_action_posting_models import (
    CorporateActionPostingModel,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_payment_basis_reader import (
    _request_from_row,
)
from apps.simulated_trading.official_disclosure_action_composition import (
    _PARSER_ID,
    szse_action_qualification_sha256,
)
from core.exceptions import BusinessLogicError


def _blocked() -> BusinessLogicError:
    return BusinessLogicError(
        "尚未完整登记本账户的当前公司行动权益。",
        code="CORPORATE_ACTION_ENTITLEMENT_COVERAGE_UNVERIFIED",
    )


def _digest(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    ).hexdigest()


def _aware(value: object) -> bool:
    """Return whether a retained datetime is exact and timezone-aware."""
    return type(value) is datetime and value.tzinfo is not None and value.utcoffset() is not None


@dataclass(frozen=True, slots=True)
class CurrentEntitlementReference:
    """Current source entitlement plus original signed transfer facts for restatement.

    This value is an optional projection of an independently verified current
    entitlement and full ledger history. It is not account NAV, tax authority,
    or permission to post any ledger stage. The source-body digest and canonical
    event digest remain separate; local ownership-proof observation is not a
    source-knowledge clock.
    """

    record_date: date
    reference_quantity: Decimal
    exchange_timezone_name: str
    source_event_id: str
    logical_source_event_id: str
    source_revision_id: str
    source_body_sha256: str
    event_content_sha256: str
    restatement_entitlement: RestatementEntitlement

    def __post_init__(self) -> None:
        """Keep source, record-date, and restatement identities distinct and exact."""
        if (
            type(self.record_date) is not date
            or type(self.reference_quantity) is not Decimal
            or not self.reference_quantity.is_finite()
            or self.reference_quantity <= 0
            or type(self.exchange_timezone_name) is not str
            or not self.exchange_timezone_name
            or self.exchange_timezone_name != self.exchange_timezone_name.strip()
            or type(self.source_event_id) is not str
            or not self.source_event_id
            or self.source_event_id != self.source_event_id.strip()
            or type(self.logical_source_event_id) is not str
            or not self.logical_source_event_id
            or self.logical_source_event_id != self.logical_source_event_id.strip()
            or type(self.source_revision_id) is not str
            or not self.source_revision_id
            or self.source_revision_id != self.source_revision_id.strip()
            or not _is_sha256(self.source_body_sha256)
            or not _is_sha256(self.event_content_sha256)
            or type(self.restatement_entitlement) is not RestatementEntitlement
        ):
            raise _blocked()
        try:
            ZoneInfo(self.exchange_timezone_name)
            self.restatement_entitlement.__post_init__()
        except (KeyError, TypeError, ValueError) as error:
            raise _blocked() from error
        if (
            self.restatement_entitlement.action_id != self.logical_source_event_id
            or self.restatement_entitlement.effective_on < self.record_date
        ):
            raise _blocked()


def _current_entitlement_reference(
    *,
    event: SecurityDisclosureEvent,
    terms: SzseDistributionTerms,
    logical_source_event_id: str,
    proof: RecordDateOwnershipProof,
    kind: CorporateActionKind,
    gross: Decimal,
    history: tuple[CorporateActionPostingModel, ...],
    requests: dict[int, CorporateActionStageRequest],
) -> CurrentEntitlementReference | None:
    """Project verified current rights and original principal transfers when clocks allow.

    Retained source, qualification, posting, and storage clocks bound current
    knowledge. The ownership proof's local reconstruction clock is excluded.
    """
    try:
        zone = ZoneInfo(proof.exchange_timezone_name)
    except (KeyError, TypeError, ValueError):
        return None
    if not _aware(event.first_seen_at):
        return None
    known_clocks = [event.first_seen_at]
    cash_transfers: list[RestatementTransfer] = []
    share_transfers: list[RestatementTransfer] = []
    for row in history:
        request = requests.get(row.pk)
        if request is None:
            return None
        created_at: object = getattr(row, "created_at", None)
        if (
            request.action_kind is not kind
            or request.stage is CorporateActionStage.TAX_WITHHOLDING
            or type(row.pk) is not int
            or row.pk <= 0
            or not _aware(created_at)
            or not all(
                _aware(clock)
                for clock in (
                    request.source_observed_at,
                    request.qualified_at,
                    request.posted_at,
                )
            )
        ):
            return None
        if type(created_at) is not datetime:
            return None
        known_clocks.extend(
            (
                request.source_observed_at,
                request.qualified_at,
                request.posted_at,
                created_at,
            )
        )
        cash = row.cash_delta
        cash_receivable = row.cash_receivable_delta
        shares = row.share_delta
        share_receivable = row.share_receivable_delta
        available_shares = row.available_share_delta
        if any(
            type(value) is not Decimal or not value.is_finite()
            for value in (cash, cash_receivable, shares, share_receivable, available_shares)
        ):
            return None
        if kind is CorporateActionKind.CASH_DIVIDEND:
            if shares != 0 or share_receivable != 0 or available_shares != 0:
                return None
            if request.stage is CorporateActionStage.CASH_PAYMENT:
                if cash != cash_receivable.copy_negate():
                    return None
                if cash != 0:
                    cash_transfers.append(
                        RestatementTransfer(
                            entry_id=str(row.pk),
                            accounting_on=request.posted_at.astimezone(zone).date(),
                            amount=cash,
                            recorded_at=created_at,
                        )
                    )
            elif cash != 0:
                return None
        else:
            if cash != 0 or cash_receivable != 0:
                return None
            if request.stage is CorporateActionStage.SHARE_DELIVERY:
                if shares != share_receivable.copy_negate():
                    return None
                if shares != 0:
                    share_transfers.append(
                        RestatementTransfer(
                            entry_id=str(row.pk),
                            accounting_on=request.posted_at.astimezone(zone).date(),
                            amount=shares,
                            recorded_at=created_at,
                        )
                    )
            elif shares != 0:
                return None
    try:
        entitlement = RestatementEntitlement(
            action_id=logical_source_event_id,
            asset_code=event.asset_code,
            effective_on=terms.ex_date,
            gross_cash=gross if kind is CorporateActionKind.CASH_DIVIDEND else Decimal(0),
            gross_shares=gross if kind is CorporateActionKind.SHARE_DISTRIBUTION else Decimal(0),
            known_at=max(known_clocks),
            cash_transfers=tuple(cash_transfers),
            share_transfers=tuple(share_transfers),
        )
        return CurrentEntitlementReference(
            record_date=terms.record_date,
            reference_quantity=proof.eligible_quantity,
            exchange_timezone_name=proof.exchange_timezone_name,
            source_event_id=event.source_event_id,
            logical_source_event_id=logical_source_event_id,
            source_revision_id=event.source_revision_id,
            source_body_sha256=event.source_body_sha256,
            event_content_sha256=event.content_hash,
            restatement_entitlement=entitlement,
        )
    except (KeyError, TypeError, ValueError, ArithmeticError):
        return None


@dataclass(frozen=True, slots=True)
class CurrentAssetEntitlementCoverage:
    """Read-only recognized rights; its owning source witness supplies the original finite lease."""

    asset_code: str
    cash_complete: bool
    shares_complete: bool
    minimum_mark_date: date | None
    evidence_sha256: str
    current_entitlement_references: tuple[CurrentEntitlementReference, ...] | None = None

    def __post_init__(self) -> None:
        """Keep unknown recognition distinct from a genuinely empty certified source window."""
        if (
            type(self.asset_code) is not str
            or not self.asset_code
            or self.asset_code != self.asset_code.strip()
            or type(self.cash_complete) is not bool
            or type(self.shares_complete) is not bool
            or (self.minimum_mark_date is not None and type(self.minimum_mark_date) is not date)
            or type(self.evidence_sha256) is not str
            or len(self.evidence_sha256) != 64
            or any(character not in "0123456789abcdef" for character in self.evidence_sha256)
            or (
                self.current_entitlement_references is not None
                and (
                    type(self.current_entitlement_references) is not tuple
                    or any(
                        type(reference) is not CurrentEntitlementReference
                        for reference in self.current_entitlement_references
                    )
                )
            )
        ):
            raise _blocked()
        if self.current_entitlement_references is not None:
            for reference in self.current_entitlement_references:
                reference.__post_init__()
                if reference.restatement_entitlement.asset_code != self.asset_code:
                    raise _blocked()


def inspect_current_distribution_entitlement(
    *,
    event: SecurityDisclosureEvent,
    terms: SzseDistributionTerms,
    logical_source_event_id: str,
    proof: RecordDateOwnershipProof,
    rows: tuple[CorporateActionPostingModel, ...],
) -> CurrentAssetEntitlementCoverage:
    """Require one original current entitlement matching current body and closed-date quantity.

    The caller independently verifies original Audit/Outbox and grant history,
    and qualifies the complete current official window. No missing receivable
    becomes zero and no stage is posted automatically. An unadjusted mark must
    reach the ex-date even if the ledger legitimately recognized a right earlier.
    """
    if (
        type(event) is not SecurityDisclosureEvent
        or type(terms) is not SzseDistributionTerms
        or type(proof) is not RecordDateOwnershipProof
        or type(proof.account_id) is not int
        or proof.account_id <= 0
        or type(proof.owner_user_id) is not int
        or proof.owner_user_id <= 0
        or type(proof.record_date) is not date
        or proof.ownership_snapshot_as_of_date != proof.record_date
        or type(proof.eligible_quantity) is not Decimal
        or not proof.eligible_quantity.is_finite()
    ):
        raise _blocked()
    event.__post_init__()
    if (
        type(terms.record_date) is not date
        or type(terms.ex_date) is not date
        or terms.ex_date < terms.record_date
        or type(rows) is not tuple
        or len(rows) > 10_000
        or type(logical_source_event_id) is not str
        or not logical_source_event_id
        or logical_source_event_id != logical_source_event_id.strip()
    ):
        raise _blocked()
    for digest in (proof.cutoff_policy_sha256, proof.ownership_snapshot_sha256):
        if (
            type(digest) is not str
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise _blocked()
    for clock in (proof.record_date_end_exclusive, proof.ownership_snapshot_observed_at):
        if type(clock) is not datetime or clock.tzinfo is None or clock.utcoffset() is None:
            raise _blocked()
    boundary = datetime.combine(
        proof.record_date + timedelta(days=1),
        time.min,
        tzinfo=ZoneInfo(proof.exchange_timezone_name),
    )
    closed = (
        proof.record_date_end_exclusive == boundary
        and proof.ownership_snapshot_observed_at >= boundary
    )
    if (
        proof.asset_code != event.asset_code
        or proof.security_id != event.asset_code
        or proof.record_date != terms.record_date
        or proof.eligible_quantity <= 0
    ):
        raise _blocked()
    if event.event_type is SecurityDisclosureEventType.CASH_DIVIDEND:
        if terms.cash_per_ten is None:
            raise _blocked()
        kind, stage = CorporateActionKind.CASH_DIVIDEND, CorporateActionStage.CASH_ENTITLEMENT
        gross = _cash_gross(proof.eligible_quantity, terms.cash_per_ten)
    elif event.event_type is SecurityDisclosureEventType.STOCK_DIVIDEND:
        if terms.shares_per_ten is None:
            raise _blocked()
        kind, stage = CorporateActionKind.SHARE_DISTRIBUTION, CorporateActionStage.SHARE_ENTITLEMENT
        gross = _whole_share_gross(proof.eligible_quantity, terms.shares_per_ten)
    else:
        raise _blocked()
    history = tuple(row for row in rows if row.source_event_id == logical_source_event_id)
    selected = tuple(
        row
        for row in history
        if row.source_revision_id == event.source_revision_id
        and row.stage == stage.value
        and row.entry_kind
        in {CorporateActionEntryKind.POSTING.value, CorporateActionEntryKind.SUCCESSOR.value}
    )
    complete = False
    retained: list[str] = []
    active_ids: set[int] = set()
    requests: dict[int, CorporateActionStageRequest] = {}
    try:
        requests = {
            row.pk: _request_from_row(row, owner_user_id=proof.owner_user_id)
            for row in history
            if type(row.pk) is int
        }
        if len(requests) != len(history):
            raise _blocked()
        row_by_id = {row.pk: row for row in history}
        entries: list[OwnerCorporateActionRevisionEntry] = []
        for row in history:
            request = requests[row.pk]
            cached_account = row._state.fields_cache.get("account")
            if (
                request.account_id != proof.account_id
                or request.payload_sha256 != row.request_payload_sha256
                or (cached_account is not None and cached_account.user_id != proof.owner_user_id)
                or not _ledger_row_matches_request(
                    row, request, reversal_target=row_by_id.get(request.reversal_of_entry_id or 0)
                )
            ):
                raise _blocked()
            entries.append(
                OwnerCorporateActionRevisionEntry(
                    row.pk,
                    row.account_revision,
                    request,
                    CorporateActionLedgerDelta(
                        cash=row.cash_delta,
                        cash_receivable=row.cash_receivable_delta,
                        shares=row.share_delta,
                        share_receivable=row.share_receivable_delta,
                        available_shares=row.available_share_delta,
                    ),
                )
            )
        active_ids = {
            entry.entry_id
            for entry in read_owner_corporate_action_revision_head(
                tuple(entries),
                event.source_revision_id,
            )
        }
    except (BusinessLogicError, AttributeError, ArithmeticError, TypeError, ValueError):
        active_ids = set()
    for row in selected:
        request = _request_from_row(row, owner_user_id=proof.owner_user_id)
        retained.append(request.payload_sha256)
        if len(selected) == 1:
            cached_account = row._state.fields_cache.get("account")
            complete = (
                closed
                and row.pk in active_ids
                and request.payload_sha256 == row.request_payload_sha256
                and (cached_account is None or cached_account.user_id == proof.owner_user_id)
                and _ledger_row_matches_request(row, request, reversal_target=None)
                and request.account_id == proof.account_id
                and request.source_namespace == _OFFICIAL_NAMESPACE
                and request.qualifier_identity == _PARSER_ID
                and request.asset_code == event.asset_code
                and request.security_id == proof.security_id
                and request.source_event_id == logical_source_event_id
                and request.source_record_id == event.source_event_id
                and request.source_payload_sha256 == event.source_body_sha256
                and request.action_kind is kind
                and request.record_date == terms.record_date
                and request.effective_date == terms.ex_date
                and request.qualification_sha256 == szse_action_qualification_sha256(event, terms)
                and request.eligible_quantity == proof.eligible_quantity
                and (
                    request.cash_amount
                    if kind is CorporateActionKind.CASH_DIVIDEND
                    else request.share_amount
                )
                == gross
            )
    digest = _digest(
        {
            "schema": "simulated-current-entitlement-coverage.v1",
            "account_id": proof.account_id,
            "owner_user_id": proof.owner_user_id,
            "asset_code": event.asset_code,
            "source_sha256": event.content_hash,
            "closed_record_date": terms.record_date.isoformat(),
            "ex_date": terms.ex_date.isoformat(),
            "eligible_quantity": format(proof.eligible_quantity, "f"),
            "expected_gross": format(gross, "f"),
            "retained_request_sha256": retained,
            "complete": complete,
        }
    )
    reference = (
        _current_entitlement_reference(
            event=event,
            terms=terms,
            logical_source_event_id=logical_source_event_id,
            proof=proof,
            kind=kind,
            gross=gross,
            history=history,
            requests=requests,
        )
        if complete
        else None
    )
    return CurrentAssetEntitlementCoverage(
        event.asset_code,
        complete if kind is CorporateActionKind.CASH_DIVIDEND else True,
        complete if kind is CorporateActionKind.SHARE_DISTRIBUTION else True,
        terms.ex_date,
        digest,
        (reference,) if reference is not None else None,
    )


def combine_current_entitlement_coverage(
    *,
    asset_code: str,
    window_sha256: str,
    events: tuple[CurrentAssetEntitlementCoverage, ...],
) -> CurrentAssetEntitlementCoverage:
    """Aggregate only independently qualified due rights within one actual complete window."""
    if (
        not _is_sha256(window_sha256)
        or type(events) is not tuple
        or len(events) > 10_000
        or any(type(event) is not CurrentAssetEntitlementCoverage for event in events)
        or any(event.asset_code != asset_code for event in events)
    ):
        raise _blocked()
    for event in events:
        event.__post_init__()
    floors = tuple(
        event.minimum_mark_date for event in events if event.minimum_mark_date is not None
    )
    references = (
        tuple(
            reference
            for event in events
            for reference in event.current_entitlement_references or ()
        )
        if all(event.current_entitlement_references is not None for event in events)
        else None
    )
    return CurrentAssetEntitlementCoverage(
        asset_code,
        all(event.cash_complete for event in events),
        all(event.shares_complete for event in events),
        max(floors) if floors else None,
        _digest(
            {
                "window_sha256": window_sha256,
                "asset_code": asset_code,
                "events": [event.evidence_sha256 for event in events],
            }
        ),
        references,
    )
