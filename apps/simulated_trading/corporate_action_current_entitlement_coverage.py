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
from apps.simulated_trading.domain.corporate_action_posting import (
    CorporateActionEntryKind,
    CorporateActionKind,
    CorporateActionLedgerDelta,
    CorporateActionStage,
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


@dataclass(frozen=True, slots=True)
class CurrentAssetEntitlementCoverage:
    """Read-only recognized rights; its owning source witness supplies the original finite lease."""

    asset_code: str
    cash_complete: bool
    shares_complete: bool
    minimum_mark_date: date | None
    evidence_sha256: str

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
        ):
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
    return CurrentAssetEntitlementCoverage(
        event.asset_code,
        complete if kind is CorporateActionKind.CASH_DIVIDEND else True,
        complete if kind is CorporateActionKind.SHARE_DISTRIBUTION else True,
        terms.ex_date,
        digest,
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
    )
