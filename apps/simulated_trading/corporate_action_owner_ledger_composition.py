"""Read accepted owner corporate-action balances from complete original Audit pairs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, localcontext

from django.db import DEFAULT_DB_ALIAS, connections

from apps.account.domain.simulated_corporate_action_write_capabilities import (
    SimulatedCorporateActionWriteCapability as Capability,
)
from apps.account.domain.simulated_corporate_action_write_grant import (
    SimulatedCorporateActionWriteGrant,
    SimulatedCorporateActionWriteGrantRecord,
)
from apps.account.simulated_corporate_action_grant_history_composition import (
    read_simulated_corporate_action_grant_scope_records,
)
from apps.audit.corporate_action_tax_assessment_composition import (
    build_tax_assessment_audit_coordinator,
)
from apps.audit.domain.system_audit_event import JSONValue, SystemAuditEvent
from apps.audit.retained_system_audit_pair_composition import read_retained_system_audit_pair
from apps.simulated_trading.application.corporate_action_posting import (
    CorporateActionPostingReceipt,
)
from apps.simulated_trading.audited_corporate_action_posting_composition import (
    DjangoAuditedCorporateActionPostingRepository,
    _event_id,
    _ledger_row_matches_request,
    _stream_id,
)
from apps.simulated_trading.domain.corporate_action_owner_revision import (
    OwnerCorporateActionRevisionEntry,
)
from apps.simulated_trading.domain.corporate_action_posting import (
    CorporateActionEntryKind,
    CorporateActionInputValidationError,
    CorporateActionKind,
    CorporateActionLedgerDelta,
    CorporateActionStageRequest,
)
from apps.simulated_trading.infrastructure.corporate_action_posting_models import (
    CorporateActionPostingModel,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_payment_basis_reader import (
    _request_from_row,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    SimulatedAccountModel,
)
from core.exceptions import BusinessLogicError

_MAX_READ_ROWS = 10_000
_LABELS = {
    "cash_entitlement": "登记模拟现金权益",
    "cash_payment": "模拟分红到账",
    "share_entitlement": "登记送转权益",
    "share_delivery": "送转记入模拟持仓",
    "share_sellable_release": "释放模拟可用股份",
    "rights_not_exercised": "模拟未参与配股",
}


def _blocked() -> BusinessLogicError:
    return BusinessLogicError(
        "公司行动原始账本与审计回执无法完整核对。",
        code="CORPORATE_ACTION_ORIGINAL_LEDGER_UNVERIFIED",
    )


@dataclass(frozen=True, slots=True)
class OwnerCorporateActionPostingState:
    """Verified local totals and stage entries, without source-window or price qualification."""

    dividend_receivable: Decimal
    share_receivables: tuple[tuple[str, Decimal], ...]
    audit_receipts: tuple[dict[str, JSONValue], ...]
    revision_entries: tuple[OwnerCorporateActionRevisionEntry, ...] = ()


def _verified_original_grant(
    request: CorporateActionStageRequest,
    event: SystemAuditEvent,
    records: tuple[SimulatedCorporateActionWriteGrantRecord, ...],
    *,
    canonical_account_id: str,
    required_capability: Capability,
) -> SimulatedCorporateActionWriteGrant:
    """Validate historical scope at the original clock, without current permission semantics."""
    refs = tuple(
        ref
        for ref in event.evidence_refs
        if ref.owner == "account" and ref.artifact_type == "simulated_corporate_action_write_grant"
    )
    if len(refs) != 1 or type(required_capability) is not Capability or event.scope is None:
        raise _blocked()
    for record in records:
        if type(record) is not SimulatedCorporateActionWriteGrantRecord:
            raise _blocked()
        record.__post_init__()
    reference = refs[0]
    candidates = tuple(
        record
        for record in records
        if (
            record.grant.grant_id == reference.artifact_id
            and record.grant.grant_version == reference.artifact_version
            and record.grant.content_hash == reference.content_hash
        )
    )
    if len(candidates) != 1:
        raise _blocked()
    record = candidates[0]
    grant, binding = record.grant, record.grant.binding
    if (
        binding.account_namespace != "simulated"
        or binding.account_id != canonical_account_id
        or binding.owner_user_id != request.owner_user_id
        or binding.tenant_id != event.scope.tenant_id
        or binding.owner_id != event.scope.owner_id
        or not grant.is_active_at(event.recorded_at)
        or not grant.supports_capability(required_capability)
        or (record.revocation is not None and record.revocation.recorded_at <= event.recorded_at)
        or any(
            other.grant != grant
            and other.grant.grant_id == grant.grant_id
            and grant.recorded_at <= other.grant.recorded_at <= event.recorded_at
            for other in records
        )
    ):
        raise _blocked()
    return grant


def _capability(request: CorporateActionStageRequest) -> Capability:
    if request.action_kind is CorporateActionKind.CASH_DIVIDEND:
        return Capability.CASH_STAGE_WRITE
    if request.action_kind is CorporateActionKind.SHARE_DISTRIBUTION:
        return Capability.SHARE_STAGE_WRITE
    if request.action_kind is CorporateActionKind.RIGHTS_ISSUE:
        return Capability.RIGHTS_NOT_EXERCISED
    raise _blocked()


def read_locked_owner_corporate_action_posting_state(
    *,
    account: SimulatedAccountModel,
    canonical_account_id: str,
    as_of: datetime,
    using: str = DEFAULT_DB_ALIAS,
) -> OwnerCorporateActionPostingState:
    """Reconcile all original ledger rows under the caller's actual owned-account transaction.

    The caller authenticates the current owner before passing the concrete row.
    Historical grant, Audit and Outbox reads issue no new financial authority;
    current-window completeness and independent raw marks remain separate.
    """
    connection = connections[using]
    if (
        not connection.in_atomic_block
        or connection.get_autocommit()
        or type(account.pk) is not int
        or type(account.user_id) is not int
        or account.account_type != "simulated"
        or account._state.db != using
        or type(canonical_account_id) is not str
        or not canonical_account_id
        or type(as_of) is not datetime
        or as_of.tzinfo is None
        or as_of.utcoffset() is None
    ):
        raise _blocked()
    physical = (
        SimulatedAccountModel._base_manager.using(using).select_for_update().get(pk=account.pk)
    )
    if (
        physical.user_id != account.user_id
        or physical.account_type != "simulated"
        or physical.updated_at != account.updated_at
        or physical.updated_at > as_of
    ):
        raise _blocked()
    rows = tuple(
        CorporateActionPostingModel._base_manager.using(using)
        .select_for_update()
        .filter(account_id=account.pk)
        .order_by("account_revision")[: _MAX_READ_ROWS + 1]
    )
    if len(rows) > _MAX_READ_ROWS:
        raise _blocked()
    if not rows:
        return OwnerCorporateActionPostingState(Decimal("0"), (), ())
    requests = tuple(_request_from_row(row, owner_user_id=account.user_id) for row in rows)
    by_id = {row.pk: row for row in rows}
    audit = build_tax_assessment_audit_coordinator(using=using)
    winners: list[SystemAuditEvent] = []
    with audit.caller_owned_readonly():
        audit.lock_streams(tuple(sorted({_stream_id(request) for request in requests})))
        for revision, (row, request) in enumerate(zip(rows, requests, strict=True), 1):
            target = (
                by_id.get(request.reversal_of_entry_id)
                if request.reversal_of_entry_id is not None
                else None
            )
            if (
                row.account_revision != revision
                or row.created_at > as_of
                or not _ledger_row_matches_request(row, request, reversal_target=target)
            ):
                raise _blocked()
            winner = audit.get_winner_targeted(
                event_id=_event_id(request), event_version="1", as_of=as_of, lock=True
            )
            if winner is None:
                raise _blocked()
            winners.append(winner)
    receipts: list[dict[str, JSONValue]] = []
    revision_entries: list[OwnerCorporateActionRevisionEntry] = []
    shares: dict[str, Decimal] = {}
    cash_by_asset: dict[str, Decimal] = {}
    heads: dict[str, SystemAuditEvent] = {}
    with localcontext() as context:
        context.prec = 96
        for row, request, winner in zip(rows, requests, winners, strict=True):
            if winner.scope is None:
                raise _blocked()
            pair = read_retained_system_audit_pair(
                event_id=winner.event_id,
                event_version=winner.event_version,
                stream_id=_stream_id(request),
                scope=winner.scope,
                using=using,
                as_of=as_of,
            )
            if pair.event != winner:
                raise _blocked()
            records = read_simulated_corporate_action_grant_scope_records(
                account_namespace="simulated",
                account_id=canonical_account_id,
                using=using,
                as_of=winner.recorded_at,
            )
            grant = _verified_original_grant(
                request,
                winner,
                records,
                canonical_account_id=canonical_account_id,
                required_capability=_capability(request),
            )
            if type(row.pk) is not int:
                raise _blocked()
            try:
                revision_entries.append(
                    OwnerCorporateActionRevisionEntry(
                        entry_id=row.pk,
                        account_revision=row.account_revision,
                        request=request,
                        delta=CorporateActionLedgerDelta(
                            cash=row.cash_delta,
                            cash_receivable=row.cash_receivable_delta,
                            shares=row.share_delta,
                            share_receivable=row.share_receivable_delta,
                            available_shares=row.available_share_delta,
                        ),
                    )
                )
            except (CorporateActionInputValidationError, TypeError, ValueError) as error:
                raise _blocked() from error
            receipt = CorporateActionPostingReceipt(
                row.pk, row.account_revision, request.stage_key, request.payload_sha256, False
            )
            if not DjangoAuditedCorporateActionPostingRepository._matches_winner(
                winner, request, receipt, winner.scope, owner_grant=grant
            ):
                raise _blocked()
            previous = heads.get(winner.stream_id)
            if previous is not None and (
                winner.sequence_no != previous.sequence_no + 1
                or winner.predecessor_hash != previous.content_hash
            ):
                raise _blocked()
            if previous is None and winner.sequence_no != 1:
                raise _blocked()
            heads[winner.stream_id] = winner
            cash_by_asset[row.asset_code] = (
                cash_by_asset.get(row.asset_code, Decimal(0)) + row.cash_receivable_delta
            )
            shares[row.asset_code] = (
                shares.get(row.asset_code, Decimal(0)) + row.share_receivable_delta
            )
            receipts.append(
                {
                    "receipt_id": winner.event_id,
                    "recorded_at": winner.recorded_at.isoformat(),
                    "asset_code": row.asset_code,
                    "stage_label": (
                        "冲正：" if request.entry_kind is CorporateActionEntryKind.REVERSAL else ""
                    )
                    + _LABELS.get(row.stage, "历史公司行动"),
                    "cash_delta": format(row.cash_delta, "f"),
                    "share_delta": format(row.share_delta, "f"),
                    "summary": "原始账本、分项授权与审计回执已核对。",
                }
            )
        if any(value < 0 for value in (*cash_by_asset.values(), *shares.values())):
            raise _blocked()
        dividend_receivable = sum(cash_by_asset.values(), Decimal(0))
    with audit.caller_owned_readonly():
        for stream, expected in sorted(heads.items()):
            if (
                audit.get_current_head_targeted(
                    stream_id=stream, as_of=as_of, scope=expected.scope, lock=True
                )
                != expected
            ):
                raise _blocked()
    return OwnerCorporateActionPostingState(
        dividend_receivable,
        tuple(sorted(shares.items())),
        tuple(reversed(receipts)),
        tuple(revision_entries),
    )


def read_locked_owner_corporate_action_revision_history(
    *,
    account: SimulatedAccountModel,
    canonical_account_id: str,
    source_namespace: str,
    source_event_id: str,
    as_of: datetime,
    using: str = DEFAULT_DB_ALIAS,
) -> tuple[OwnerCorporateActionRevisionEntry, ...]:
    """Return one event's entries only after every account row and receipt verifies.

    The complete account ledger is reconciled first, including all original grants,
    Audit/Outbox pairs, account revisions, and per-stream heads. Filtering is limited
    to the exact logical source namespace/event pair; asset or action identity is
    deliberately left for the Domain revision validator to compare across every row.
    """
    if (
        type(source_namespace) is not str
        or not source_namespace
        or source_namespace != source_namespace.strip()
        or type(source_event_id) is not str
        or not source_event_id
        or source_event_id != source_event_id.strip()
    ):
        raise _blocked()
    state = read_locked_owner_corporate_action_posting_state(
        account=account,
        canonical_account_id=canonical_account_id,
        as_of=as_of,
        using=using,
    )
    if (
        type(state) is not OwnerCorporateActionPostingState
        or type(state.revision_entries) is not tuple
        or any(
            type(entry) is not OwnerCorporateActionRevisionEntry for entry in state.revision_entries
        )
    ):
        raise _blocked()
    entries = tuple(
        entry
        for entry in state.revision_entries
        if entry.request.source_namespace == source_namespace
        and entry.request.source_event_id == source_event_id
    )
    if not entries:
        raise _blocked()
    return entries
