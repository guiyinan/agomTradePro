"""Read exact audited simulated dividend payments inside a locked owner transaction."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation, localcontext
from typing import NoReturn

from django.db import DatabaseError, connections
from django.utils.connection import ConnectionDoesNotExist

from apps.account.application.simulated_corporate_action_write_grant import (
    SimulatedCorporateActionWriteGrantUnavailable,
)
from apps.account.domain.simulated_corporate_action_write_capabilities import (
    SimulatedCorporateActionWriteCapability,
)
from apps.account.domain.simulated_corporate_action_write_grant import (
    SimulatedCorporateActionWriteGrant,
)
from apps.account.simulated_corporate_action_grant_history_composition import (
    read_simulated_corporate_action_grant_scope_records,
)
from apps.audit.application.retained_system_audit_pair import RetainedSystemAuditPair
from apps.audit.application.system_audit_event_outbox import (
    SystemAuditEventOutboxCorruption,
    SystemAuditEventOutboxUnavailable,
)
from apps.audit.domain.system_audit_event import AuditScopeRef, SystemAuditEvent
from apps.audit.retained_system_audit_pair_composition import (
    read_retained_system_audit_pair,
)
from apps.simulated_trading.application.corporate_action_posting import (
    CorporateActionPostingReceipt,
)
from apps.simulated_trading.application.corporate_action_tax_payment_basis import (
    SimulatedDividendPaymentBasis,
)
from apps.simulated_trading.audited_corporate_action_posting_composition import (
    DjangoAuditedCorporateActionPostingRepository,
    _event_id,
    _ledger_row_matches_request,
    _stream_id,
)
from apps.simulated_trading.domain.corporate_action_deferred_tax import (
    DeferredDividendTaxValidationError,
)
from apps.simulated_trading.domain.corporate_action_posting import (
    CorporateActionEntryKind,
    CorporateActionKind,
    CorporateActionLedgerDelta,
    CorporateActionStage,
    CorporateActionStageRequest,
)
from apps.simulated_trading.domain.corporate_action_tax_assessment import (
    CorporateActionTaxAssessment,
)
from apps.simulated_trading.domain.corporate_action_tax_liability import TaxLiabilityScope
from apps.simulated_trading.domain.simulated_cash_posting_history import (
    SimulatedCashPostingHistoryStep,
    SimulatedCashPostingHistoryValidationError,
    validate_simulated_cash_posting_history,
)
from apps.simulated_trading.infrastructure.corporate_action_posting_models import (
    CorporateActionPostingModel,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    SimulatedAccountModel,
)
from core.exceptions import BusinessLogicError

_BLOCKED_CODE = "SIMULATED_DIVIDEND_PAYMENT_BASIS_BLOCKED"
_CASH_GRANT_EVIDENCE_TYPE = "simulated_corporate_action_write_grant"
_AUDIT_EVENT_VERSION = "1"
_CENT = Decimal("0.01")
_MAX_EVENT_ROWS = 10_000


def _blocked(message: str) -> NoReturn:
    """Raise one stable block for missing or conflicting audited payment history."""

    raise BusinessLogicError(message, code=_BLOCKED_CODE)


def _aware(value: object, *, name: str) -> datetime:
    """Require an exact aware datetime that can be compared in UTC."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        _blocked(f"{name} must be timezone-aware")
    try:
        value.astimezone(UTC)
    except (OverflowError, ValueError) as error:
        raise BusinessLogicError(f"{name} is out of range", code=_BLOCKED_CODE) from error
    return value


def _token(value: object, *, name: str, limit: int = 192) -> str:
    """Require a bounded stable text identifier before ORM lookup."""

    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > limit
        or any(character.isspace() for character in value)
    ):
        _blocked(f"{name} is invalid")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise BusinessLogicError(f"{name} is invalid UTF-8", code=_BLOCKED_CODE) from error
    return value


def _require_outer_read_transaction(using: str) -> None:
    """Require one caller-owned outermost PostgreSQL READ COMMITTED transaction."""

    try:
        connection = connections[using]
        blocks = getattr(connection, "atomic_blocks", None)
        if (
            connection.vendor != "postgresql"
            or not connection.in_atomic_block
            or connection.get_autocommit()
            or not isinstance(blocks, list)
            or len(blocks) != 1
        ):
            _blocked("payment-basis read requires the outermost same-alias PostgreSQL transaction")
        with connection.cursor() as cursor:
            cursor.execute("SHOW transaction_isolation")
            result = cursor.fetchone()
        if result is None or result[0] != "read committed":
            _blocked("payment-basis read requires READ COMMITTED isolation")
    except (ConnectionDoesNotExist, DatabaseError) as error:
        raise BusinessLogicError(
            "payment-basis transaction state is unavailable", code=_BLOCKED_CODE
        ) from error


def _lock_account_owner(*, account_id: int, owner_user_id: int, using: str) -> None:
    """Lock the physical simulated account and recheck its exact active owner."""

    account = (
        SimulatedAccountModel._base_manager.using(using)
        .select_for_update()
        .filter(
            pk=account_id,
            user_id=owner_user_id,
            account_type="simulated",
            is_active=True,
        )
        .first()
    )
    if (
        account is None
        or type(account.user_id) is not int
        or account.user_id != owner_user_id
        or account.account_type != "simulated"
        or account.is_active is not True
    ):
        _blocked("physical account owner differs from the qualified tax owner")


def _request_from_row(
    row: CorporateActionPostingModel,
    *,
    owner_user_id: int,
) -> CorporateActionStageRequest:
    """Reconstruct the complete immutable Domain request from one persisted row."""

    try:
        return CorporateActionStageRequest(
            account_id=row.account_id,
            owner_user_id=owner_user_id,
            security_id=row.security_id,
            asset_code=row.asset_code,
            asset_name=row.asset_name,
            source_namespace=row.source_namespace,
            source_record_id=row.source_record_id,
            source_event_id=row.source_event_id,
            source_revision_id=row.source_revision_id,
            source_payload_sha256=row.source_payload_sha256,
            qualification_sha256=row.qualification_sha256,
            qualifier_identity=row.qualifier_identity,
            source_observed_at=row.source_observed_at,
            qualified_at=row.qualified_at,
            posted_at=row.posted_at,
            action_kind=CorporateActionKind(row.action_kind),
            stage=CorporateActionStage(row.stage),
            entry_kind=CorporateActionEntryKind(row.entry_kind),
            record_date=row.record_date,
            effective_date=row.effective_date,
            stage_date=row.stage_date,
            cash_amount=row.cash_amount,
            share_amount=row.share_amount,
            payment_date=row.payment_date,
            sellable_date=row.sellable_date,
            tax_treatment=row.tax_treatment,
            tax_rule_id=row.tax_rule_id,
            tax_rule_sha256=row.tax_rule_sha256,
            tax_basis_record_id=row.tax_basis_record_id,
            tax_basis_sha256=row.tax_basis_sha256,
            ownership_snapshot_id=row.ownership_snapshot_id,
            ownership_snapshot_sha256=row.ownership_snapshot_sha256,
            ownership_snapshot_as_of_date=row.ownership_snapshot_as_of_date,
            ownership_snapshot_observed_at=row.ownership_snapshot_observed_at,
            eligible_quantity=row.eligible_quantity,
            entitlement_calculation_sha256=row.entitlement_calculation_sha256,
            rights_terms_sha256=row.rights_terms_sha256,
            rights_election=row.rights_election,
            odd_lot_policy=row.odd_lot_policy,
            odd_lot_confirmation_sha256=row.odd_lot_confirmation_sha256,
            supersedes_revision_id=row.supersedes_revision_id,
            reversal_of_entry_id=row.reversal_of_id,
        )
    except (TypeError, ValueError, DeferredDividendTaxValidationError) as error:
        raise BusinessLogicError(
            "persisted cash-stage row is not a valid complete request", code=_BLOCKED_CODE
        ) from error


def _economic(row: CorporateActionPostingModel) -> bool:
    """Return whether a cash stage has any immutable ledger effect."""

    return any(
        value != 0
        for value in (
            row.cash_delta,
            row.cash_receivable_delta,
            row.share_delta,
            row.share_receivable_delta,
            row.available_share_delta,
        )
    )


def _verify_event_revision_chain(
    rows: tuple[CorporateActionPostingModel, ...],
    requests: dict[int, CorporateActionStageRequest],
    *,
    expected_head_revision_id: str,
) -> tuple[dict[int, CorporateActionPostingModel], str]:
    """Validate every append and exact immediate-predecessor correction in order."""

    if not rows or len(rows) > _MAX_EVENT_ROWS:
        _blocked("corporate-action event history is missing or exceeds the safe read bound")
    row_by_id: dict[int, CorporateActionPostingModel] = {}
    previous_account_revision = 0
    for row in rows:
        if (
            type(row.pk) is not int
            or type(row.account_revision) is not int
            or row.account_revision <= previous_account_revision
            or row.pk in row_by_id
            or row.source_revision_id
            not in {request.source_revision_id for request in requests.values()}
        ):
            _blocked("corporate-action account revision order or identity is ambiguous")
        previous_account_revision = row.account_revision
        row_by_id[row.pk] = row

    active: dict[int, CorporateActionPostingModel] = {}
    seen_revisions: set[str] = set()
    stages_by_revision: dict[str, set[CorporateActionStage]] = {}
    head_revision: str | None = None
    index = 0
    while index < len(rows):
        row = rows[index]
        request = requests[row.pk]
        if request.action_kind is not CorporateActionKind.CASH_DIVIDEND:
            _blocked("paid-basis history contains a non-cash corporate action")
        if request.entry_kind is CorporateActionEntryKind.POSTING:
            if head_revision is None:
                if request.supersedes_revision_id is not None:
                    _blocked("initial cash source revision unexpectedly has a predecessor")
                head_revision = request.source_revision_id
                seen_revisions.add(head_revision)
            if (
                request.source_revision_id != head_revision
                or request.supersedes_revision_id is not None
            ):
                _blocked("cash posting is outside the current source revision")
            stages = stages_by_revision.setdefault(head_revision, set())
            if request.stage in stages:
                _blocked("one source revision repeats a cash stage")
            stages.add(request.stage)
            if _economic(row):
                active[row.pk] = row
            index += 1
            continue
        if request.entry_kind not in {
            CorporateActionEntryKind.REVERSAL,
            CorporateActionEntryKind.SUCCESSOR,
        }:
            _blocked("paid-basis history contains an unsupported cash entry kind")
        new_revision_id = request.source_revision_id
        if (
            head_revision is None
            or new_revision_id in seen_revisions
            or new_revision_id == head_revision
            or request.supersedes_revision_id != head_revision
        ):
            _blocked("cash correction does not name one new immediate source successor")
        end = index
        group: list[CorporateActionPostingModel] = []
        correction_kinds = {
            CorporateActionEntryKind.REVERSAL,
            CorporateActionEntryKind.SUCCESSOR,
        }
        while end < len(rows):
            candidate = rows[end]
            candidate_request = requests[candidate.pk]
            if (
                candidate.source_revision_id != new_revision_id
                or candidate_request.entry_kind not in correction_kinds
            ):
                break
            group.append(candidate)
            end += 1
        if any(
            rows[position].account_revision + 1 != rows[position + 1].account_revision
            for position in range(index, end - 1)
        ):
            _blocked("cash correction rows are not one complete account revision batch")
        group_requests = tuple(requests[member.pk] for member in group if member.pk is not None)
        if any(item.supersedes_revision_id != head_revision for item in group_requests):
            _blocked("cash correction batch contains a mixed or stale predecessor")
        reversal_requests = tuple(
            item for item in group_requests if item.entry_kind is CorporateActionEntryKind.REVERSAL
        )
        successor_requests = tuple(
            item for item in group_requests if item.entry_kind is CorporateActionEntryKind.SUCCESSOR
        )
        reversal_ids = tuple(item.reversal_of_entry_id for item in reversal_requests)
        if (
            not reversal_requests
            or not successor_requests
            or len(set(reversal_ids)) != len(reversal_ids)
            or set(reversal_ids) != set(active)
        ):
            _blocked("cash correction must reverse every active stage exactly once and succeed")
        successor_seen: set[CorporateActionStage] = set()
        for correction_row in group:
            correction = requests[correction_row.pk]
            if correction.entry_kind is CorporateActionEntryKind.SUCCESSOR:
                if correction.stage in successor_seen or not _economic(correction_row):
                    _blocked("cash correction successor stages are duplicated or ineffective")
                successor_seen.add(correction.stage)
            elif correction.entry_kind is CorporateActionEntryKind.REVERSAL:
                target_id = correction.reversal_of_entry_id
                if target_id is None or target_id not in active:
                    _blocked("cash correction reversal does not target an active predecessor")
                active.pop(target_id)
        for correction_row in group:
            correction = requests[correction_row.pk]
            target = row_by_id.get(correction.reversal_of_entry_id or 0)
            if not _ledger_row_matches_request(
                correction_row,
                correction,
                reversal_target=target,
            ):
                _blocked("cash correction row differs from its exact reversal or successor")
            if correction.entry_kind is CorporateActionEntryKind.SUCCESSOR:
                active[correction_row.pk] = correction_row
        head_revision = new_revision_id
        seen_revisions.add(new_revision_id)
        stages_by_revision[new_revision_id] = successor_seen
        index = end

    if head_revision != expected_head_revision_id:
        _blocked("paid-basis source revision is not the historical event head")
    try:
        validate_simulated_cash_posting_history(
            tuple(
                SimulatedCashPostingHistoryStep(
                    account_revision=row.account_revision,
                    request=requests[row.pk],
                    delta=CorporateActionLedgerDelta(
                        cash=row.cash_delta,
                        cash_receivable=row.cash_receivable_delta,
                        shares=row.share_delta,
                        share_receivable=row.share_receivable_delta,
                        available_shares=row.available_share_delta,
                    ),
                )
                for row in rows
            )
        )
    except SimulatedCashPostingHistoryValidationError as error:
        _blocked(str(error))
    return active, head_revision


@dataclass(frozen=True, slots=True)
class _VerifiedPosting:
    """One exact persisted cash row with its independently verified original evidence."""

    row: CorporateActionPostingModel
    request: CorporateActionStageRequest
    receipt: CorporateActionPostingReceipt
    event: SystemAuditEvent
    audit_persisted_at: datetime
    outbox_id: str
    outbox_payload_sha256: str
    outbox_created_at: datetime
    grant: SimulatedCorporateActionWriteGrant


def _historical_grant(
    *,
    event: SystemAuditEvent,
    using: str,
    account_namespace: str,
    account_id: str,
    owner_user_id: int,
    audit_scope: AuditScopeRef,
) -> SimulatedCorporateActionWriteGrant:
    """Restore the exact cash-capable grant current when its Audit event was recorded."""

    grant_refs = tuple(
        ref
        for ref in event.evidence_refs
        if ref.owner == "account" and ref.artifact_type == _CASH_GRANT_EVIDENCE_TYPE
    )
    if len(grant_refs) != 1:
        _blocked("cash-stage Audit event lacks one exact original Account grant reference")
    reference = grant_refs[0]
    records = read_simulated_corporate_action_grant_scope_records(
        account_namespace=account_namespace,
        account_id=account_id,
        using=using,
        as_of=event.recorded_at,
    )
    candidates = tuple(
        record
        for record in records
        if record.grant.grant_id == reference.artifact_id
        and record.grant.grant_version == reference.artifact_version
        and record.grant.content_hash == reference.content_hash
    )
    if len(candidates) != 1:
        _blocked("original cash-stage grant is absent or ambiguous at its Audit cutoff")
    record = candidates[0]
    grant = record.grant
    binding = grant.binding
    if (
        binding.account_namespace != account_namespace
        or binding.account_id != account_id
        or binding.owner_user_id != owner_user_id
        or binding.tenant_id != audit_scope.tenant_id
        or binding.owner_id != audit_scope.owner_id
        or not grant.is_active_at(event.recorded_at)
        or not grant.supports_capability(SimulatedCorporateActionWriteCapability.CASH_STAGE_WRITE)
        or (record.revocation is not None and record.revocation.recorded_at <= event.recorded_at)
    ):
        _blocked("original cash-stage grant was not active for this exact owner at Audit time")
    chain_at_cutoff = tuple(
        item.grant
        for item in records
        if item.grant.grant_id == grant.grant_id and item.grant.recorded_at <= event.recorded_at
    )
    if not any(item == grant for item in chain_at_cutoff) or any(
        item != grant and item.recorded_at >= grant.recorded_at for item in chain_at_cutoff
    ):
        _blocked("original cash-stage grant was superseded before its Audit event")
    return grant


def _verify_stage_audit_and_outbox(
    *,
    row: CorporateActionPostingModel,
    request: CorporateActionStageRequest,
    using: str,
    as_of: datetime,
    audit_scope: AuditScopeRef,
    account_namespace: str,
    canonical_account_id: str,
    owner_user_id: int,
) -> _VerifiedPosting:
    """Verify exact Audit and Outbox payloads, physical clocks, and historical consent."""

    if (
        type(row.pk) is not int
        or type(row.account_revision) is not int
        or row.created_at > as_of
        or request.source_observed_at.astimezone(UTC) > as_of.astimezone(UTC)
        or request.qualified_at.astimezone(UTC) > as_of.astimezone(UTC)
        or request.posted_at.astimezone(UTC) > as_of.astimezone(UTC)
    ):
        _blocked("cash ledger row contains facts recorded after the requested cutoff")
    receipt = CorporateActionPostingReceipt(
        entry_id=row.pk,
        account_revision=row.account_revision,
        stage_key=request.stage_key,
        request_payload_sha256=request.payload_sha256,
        replayed=False,
    )
    event_id = _event_id(request)
    stream_id = _stream_id(request)
    pair = read_retained_system_audit_pair(
        event_id=event_id,
        event_version=_AUDIT_EVENT_VERSION,
        stream_id=stream_id,
        scope=audit_scope,
        using=using,
        as_of=as_of,
    )
    if type(pair) is not RetainedSystemAuditPair:
        _blocked("cash-stage Audit/Outbox pair is not a typed retained value")
    pair.verify_at_cutoff(as_of=as_of)
    winner = pair.event
    if winner.scope != audit_scope or winner.stream_id != stream_id:
        _blocked("cash-stage Audit event is outside its exact owner stream")
    grant = _historical_grant(
        event=winner,
        using=using,
        account_namespace=account_namespace,
        account_id=canonical_account_id,
        owner_user_id=owner_user_id,
        audit_scope=audit_scope,
    )
    if not DjangoAuditedCorporateActionPostingRepository._matches_winner(
        winner,
        request,
        receipt,
        audit_scope,
        owner_grant=grant,
    ):
        _blocked("cash-stage Audit event differs from its original canonical request")
    return _VerifiedPosting(
        row=row,
        request=request,
        receipt=receipt,
        event=winner,
        audit_persisted_at=pair.audit_persisted_at,
        outbox_id=pair.outbox_id,
        outbox_payload_sha256=pair.outbox_payload_sha256,
        outbox_created_at=pair.outbox_created_at,
        grant=grant,
    )


def _read_verified_event(
    *,
    account_id: int,
    owner_user_id: int,
    source_namespace: str,
    source_event_id: str,
    expected_head_revision_id: str,
    using: str,
    audit_scope: AuditScopeRef,
    account_namespace: str,
    canonical_account_id: str,
    as_of: datetime,
) -> tuple[str, dict[int, _VerifiedPosting]]:
    """Read every row and original evidence in one bounded event history."""

    rows = tuple(
        CorporateActionPostingModel._base_manager.using(using)
        .select_for_update()
        .filter(
            account_id=account_id,
            source_namespace=source_namespace,
            source_event_id=source_event_id,
            created_at__lte=as_of,
        )
        .order_by("account_revision")[: _MAX_EVENT_ROWS + 1]
    )
    if not rows or len(rows) > _MAX_EVENT_ROWS:
        _blocked("complete same-event cash stage history is missing or too large")
    requests: dict[int, CorporateActionStageRequest] = {}
    row_by_id: dict[int, CorporateActionPostingModel] = {}
    for row in rows:
        request = _request_from_row(row, owner_user_id=owner_user_id)
        if (
            type(row.pk) is not int
            or row.pk in requests
            or row.account_id != account_id
            or row.source_namespace != source_namespace
            or row.source_event_id != source_event_id
            or request.action_kind is not CorporateActionKind.CASH_DIVIDEND
        ):
            _blocked("same-event cash history crosses account, source, or action identity")
        requests[row.pk] = request
        row_by_id[row.pk] = row
    for row in rows:
        request = requests[row.pk]
        target = row_by_id.get(request.reversal_of_entry_id or 0)
        if not _ledger_row_matches_request(row, request, reversal_target=target):
            _blocked("persisted cash stage differs from its canonical request or ledger delta")
    active_rows, head_revision = _verify_event_revision_chain(
        rows,
        requests,
        expected_head_revision_id=expected_head_revision_id,
    )
    verified: dict[int, _VerifiedPosting] = {}
    previous_audit_sequence = 0
    for row in rows:
        if row.pk is None:
            _blocked("cash ledger row has no immutable primary key")
        stage = _verify_stage_audit_and_outbox(
            row=row,
            request=requests[row.pk],
            using=using,
            as_of=as_of,
            audit_scope=audit_scope,
            account_namespace=account_namespace,
            canonical_account_id=canonical_account_id,
            owner_user_id=owner_user_id,
        )
        if stage.event.sequence_no <= previous_audit_sequence:
            _blocked("cash-stage Audit events do not preserve account posting order")
        previous_audit_sequence = stage.event.sequence_no
        verified[row.pk] = stage
    for entry_id, row in active_rows.items():
        if entry_id not in verified or verified[entry_id].row.pk != row.pk:
            _blocked("active cash stage is missing its original Audit and Outbox pair")
    return head_revision, verified


def _current_paid_pair(
    *,
    active_rows: dict[int, CorporateActionPostingModel],
    verified: dict[int, _VerifiedPosting],
) -> tuple[_VerifiedPosting, _VerifiedPosting]:
    """Require exactly one non-reversed account-wide entitlement and payment."""

    active = tuple(verified[entry_id] for entry_id in active_rows)
    entitlements = tuple(
        stage for stage in active if stage.request.stage is CorporateActionStage.CASH_ENTITLEMENT
    )
    payments = tuple(
        stage for stage in active if stage.request.stage is CorporateActionStage.CASH_PAYMENT
    )
    if any(stage.request.stage is CorporateActionStage.TAX_WITHHOLDING for stage in active):
        _blocked("current action already contains an active tax-withholding stage")
    if len(entitlements) != 1 or len(payments) != 1:
        _blocked("current action has no unique non-reversed cash entitlement/payment pair")
    return entitlements[0], payments[0]


def _verified_total_gross(
    *,
    assessment: CorporateActionTaxAssessment,
    entitlement: _VerifiedPosting,
    payment: _VerifiedPosting,
) -> tuple[Decimal, Decimal]:
    """Bind full record-date quantity and exact cent gross to both cash stages."""

    action = assessment.action
    quantity = assessment.history.record_date_entitlement.qualified_total_quantity
    ent_request = entitlement.request
    pay_request = payment.request
    with localcontext() as context:
        context.prec = 80
        gross = quantity * action.dividend_per_share
        try:
            cent_amount = gross.quantize(_CENT)
        except InvalidOperation as error:
            raise BusinessLogicError(
                "gross dividend exceeds exact cash precision", code=_BLOCKED_CODE
            ) from error
    if (
        cent_amount != gross
        or ent_request.eligible_quantity != quantity
        or ent_request.cash_amount != gross
        or pay_request.cash_amount != gross
    ):
        _blocked("entitlement and payment are not the full exact record-date gross amount")
    return quantity, ent_request.cash_amount


def _assert_stage_matches_basis(
    stage: _VerifiedPosting,
    *,
    basis: SimulatedDividendPaymentBasis,
    entitlement: bool,
) -> None:
    """Compare one historical ledger/Audit/Outbox/grant tuple with its sealed DTO fields."""

    prefix = "entitlement" if entitlement else "payment"
    row = stage.row
    request = stage.request
    event = stage.event
    expected_stage = (
        CorporateActionStage.CASH_ENTITLEMENT if entitlement else CorporateActionStage.CASH_PAYMENT
    )
    if (
        request.action_kind is not CorporateActionKind.CASH_DIVIDEND
        or request.stage is not expected_stage
        or request.entry_kind
        not in {CorporateActionEntryKind.POSTING, CorporateActionEntryKind.SUCCESSOR}
        or row.pk != getattr(basis, f"{prefix}_entry_id")
        or row.account_revision != getattr(basis, f"{prefix}_account_revision")
        or request.payload_sha256 != getattr(basis, f"{prefix}_request_payload_sha256")
        or request.stage_date != getattr(basis, f"{prefix}_stage_date")
        or request.source_observed_at != getattr(basis, f"{prefix}_source_observed_at")
        or request.qualified_at != getattr(basis, f"{prefix}_qualified_at")
        or request.posted_at != getattr(basis, f"{prefix}_posted_at")
        or row.created_at != getattr(basis, f"{prefix}_row_created_at")
        or event.event_id != getattr(basis, f"{prefix}_audit_event_id")
        or event.event_version != getattr(basis, f"{prefix}_audit_event_version")
        or event.content_hash != getattr(basis, f"{prefix}_audit_event_sha256")
        or event.recorded_at != getattr(basis, f"{prefix}_audit_recorded_at")
        or stage.audit_persisted_at != getattr(basis, f"{prefix}_audit_persisted_at")
        or event.sequence_no != getattr(basis, f"{prefix}_audit_sequence_no")
        or event.predecessor_hash != getattr(basis, f"{prefix}_audit_predecessor_hash")
        or stage.outbox_id != getattr(basis, f"{prefix}_outbox_record_id")
        or stage.outbox_payload_sha256 != getattr(basis, f"{prefix}_outbox_payload_sha256")
        or stage.outbox_created_at != getattr(basis, f"{prefix}_outbox_created_at")
        or stage.grant.grant_id != getattr(basis, f"{prefix}_grant_id")
        or stage.grant.grant_version != getattr(basis, f"{prefix}_grant_version")
        or stage.grant.content_hash != getattr(basis, f"{prefix}_grant_content_sha256")
    ):
        _blocked("historical paid-basis stage differs from its original sealed receipt")


def _read_locked_simulated_dividend_payment_basis_implementation(
    assessment: CorporateActionTaxAssessment,
    *,
    using: str,
    canonical_account_namespace: str,
    canonical_account_id: str,
    audit_scope: AuditScopeRef,
    as_of: datetime,
) -> SimulatedDividendPaymentBasis:
    """Return current full-entitlement/payment proof under the caller's account fence.

    No grant is required from the caller. Each stage's exact historical CASH
    grant is restored from Account history at its original Audit clock; the
    caller remains responsible for current tax-withholding authority.
    """

    if type(assessment) is not CorporateActionTaxAssessment:
        _blocked("an exact qualified tax assessment is required")
    try:
        assessment.verify_integrity()
    except (DeferredDividendTaxValidationError, TypeError, ValueError) as error:
        raise BusinessLogicError(
            "tax assessment integrity is invalid", code=_BLOCKED_CODE
        ) from error
    cutoff = _aware(as_of, name="as_of")
    account_namespace = _token(
        canonical_account_namespace,
        name="canonical_account_namespace",
        limit=32,
    )
    grant_account_id = _token(canonical_account_id, name="canonical_account_id")
    selected_alias = _token(using, name="database alias", limit=64)
    if type(audit_scope) is not AuditScopeRef or account_namespace != "simulated":
        _blocked("payment-basis grant or Audit owner scope is invalid")
    action = assessment.action
    _require_outer_read_transaction(selected_alias)
    _lock_account_owner(
        account_id=assessment.account_id,
        owner_user_id=assessment.owner_user_id,
        using=selected_alias,
    )
    head_revision, verified = _read_verified_event(
        account_id=assessment.account_id,
        owner_user_id=assessment.owner_user_id,
        source_namespace=action.source_namespace,
        source_event_id=action.source_event_id,
        expected_head_revision_id=action.source_revision_id,
        using=selected_alias,
        audit_scope=audit_scope,
        account_namespace=account_namespace,
        canonical_account_id=grant_account_id,
        as_of=cutoff,
    )
    active_rows, verified_head = _verify_event_revision_chain_from_verified(
        verified=verified,
        head_revision_id=head_revision,
    )
    if verified_head != head_revision:
        _blocked("verified cash history head differs from the selected source revision")
    entitlement, payment = _current_paid_pair(active_rows=active_rows, verified=verified)
    quantity, gross = _verified_total_gross(
        assessment=assessment,
        entitlement=entitlement,
        payment=payment,
    )
    ent_request = entitlement.request
    pay_request = payment.request
    if (
        ent_request.account_id != action.account_id
        or ent_request.owner_user_id != action.owner_user_id
        or ent_request.security_id != action.security_id
        or ent_request.asset_code != action.asset_code
        or ent_request.record_date != action.record_date
        or ent_request.effective_date != action.effective_date
        or ent_request.source_record_id != action.source_record_id
        or ent_request.source_revision_id != action.source_revision_id
        or ent_request.source_payload_sha256 != action.source_payload_sha256
        or ent_request.source_namespace != action.source_namespace
        or ent_request.source_event_id != action.source_event_id
        or pay_request.source_revision_id != action.source_revision_id
        or pay_request.source_payload_sha256 != action.source_payload_sha256
        or pay_request.source_record_id != action.source_record_id
        or pay_request.security_id != action.security_id
        or pay_request.asset_code != action.asset_code
        or pay_request.record_date != action.record_date
        or pay_request.effective_date != action.effective_date
        or pay_request.tax_treatment != ent_request.tax_treatment
        or pay_request.qualification_sha256 != ent_request.qualification_sha256
        or pay_request.qualifier_identity != ent_request.qualifier_identity
        or pay_request.source_observed_at != ent_request.source_observed_at
        or ent_request.ownership_snapshot_observed_at != ent_request.qualified_at
        or ent_request.ownership_snapshot_as_of_date != action.record_date
        or ent_request.eligible_quantity != quantity
        or ent_request.entitlement_calculation_sha256 is None
        or ent_request.cash_amount != gross
        or pay_request.cash_amount != gross
        or pay_request.payment_date is None
    ):
        _blocked(
            "paid cash stages differ from the exact current assessment action and full quantity"
        )
    basis = SimulatedDividendPaymentBasis(
        account_id=action.account_id,
        owner_user_id=action.owner_user_id,
        security_id=action.security_id,
        asset_code=action.asset_code,
        asset_name=ent_request.asset_name,
        corporate_action_id=action.corporate_action_id,
        source_namespace=action.source_namespace,
        source_record_id=action.source_record_id,
        source_event_id=action.source_event_id,
        source_revision_id=action.source_revision_id,
        source_revision_sha256=action.source_revision_sha256,
        source_payload_sha256=action.source_payload_sha256,
        record_date=action.record_date,
        effective_date=action.effective_date,
        payment_date=pay_request.payment_date,
        dividend_per_share=action.dividend_per_share,
        eligible_quantity=quantity,
        gross_entitlement_amount=gross,
        tax_treatment=ent_request.tax_treatment or "",
        qualification_sha256=ent_request.qualification_sha256,
        qualifier_identity=ent_request.qualifier_identity,
        ownership_snapshot_id=ent_request.ownership_snapshot_id or "",
        ownership_snapshot_sha256=ent_request.ownership_snapshot_sha256 or "",
        ownership_snapshot_observed_at=ent_request.ownership_snapshot_observed_at,
        entitlement_calculation_sha256=ent_request.entitlement_calculation_sha256,
        grant_account_namespace=account_namespace,
        grant_account_id=grant_account_id,
        entitlement_entry_id=entitlement.row.pk,
        entitlement_account_revision=entitlement.row.account_revision,
        entitlement_request_payload_sha256=ent_request.payload_sha256,
        entitlement_stage_date=ent_request.stage_date,
        entitlement_source_observed_at=ent_request.source_observed_at,
        entitlement_qualified_at=ent_request.qualified_at,
        entitlement_posted_at=ent_request.posted_at,
        entitlement_row_created_at=entitlement.row.created_at,
        entitlement_audit_event_id=entitlement.event.event_id,
        entitlement_audit_event_version=entitlement.event.event_version,
        entitlement_audit_event_sha256=entitlement.event.content_hash,
        entitlement_audit_recorded_at=entitlement.event.recorded_at,
        entitlement_audit_persisted_at=entitlement.audit_persisted_at,
        entitlement_audit_sequence_no=entitlement.event.sequence_no,
        entitlement_audit_predecessor_hash=entitlement.event.predecessor_hash,
        entitlement_outbox_record_id=entitlement.outbox_id,
        entitlement_outbox_payload_sha256=entitlement.outbox_payload_sha256,
        entitlement_outbox_created_at=entitlement.outbox_created_at,
        entitlement_grant_id=entitlement.grant.grant_id,
        entitlement_grant_version=entitlement.grant.grant_version,
        entitlement_grant_content_sha256=entitlement.grant.content_hash,
        payment_entry_id=payment.row.pk,
        payment_account_revision=payment.row.account_revision,
        payment_request_payload_sha256=pay_request.payload_sha256,
        payment_stage_date=pay_request.stage_date,
        payment_source_observed_at=pay_request.source_observed_at,
        payment_qualified_at=pay_request.qualified_at,
        payment_posted_at=pay_request.posted_at,
        payment_row_created_at=payment.row.created_at,
        payment_audit_event_id=payment.event.event_id,
        payment_audit_event_version=payment.event.event_version,
        payment_audit_event_sha256=payment.event.content_hash,
        payment_audit_recorded_at=payment.event.recorded_at,
        payment_audit_persisted_at=payment.audit_persisted_at,
        payment_audit_sequence_no=payment.event.sequence_no,
        payment_audit_predecessor_hash=payment.event.predecessor_hash,
        payment_outbox_record_id=payment.outbox_id,
        payment_outbox_payload_sha256=payment.outbox_payload_sha256,
        payment_outbox_created_at=payment.outbox_created_at,
        payment_grant_id=payment.grant.grant_id,
        payment_grant_version=payment.grant.grant_version,
        payment_grant_content_sha256=payment.grant.content_hash,
    )
    basis.verify_for(assessment, as_of=cutoff)
    return basis


def _verify_retained_simulated_dividend_payment_basis_implementation(
    basis: SimulatedDividendPaymentBasis,
    *,
    scope: TaxLiabilityScope,
    using: str,
    audit_scope: AuditScopeRef,
    as_of: datetime,
) -> None:
    """Re-read the exact historical payment basis without requiring current consent."""

    if type(basis) is not SimulatedDividendPaymentBasis:
        _blocked("an exact retained payment-basis DTO is required")
    try:
        basis.verify_scope(scope, as_of=as_of)
    except BusinessLogicError as error:
        if error.code == _BLOCKED_CODE:
            raise
        raise BusinessLogicError("retained payment basis is invalid", code=_BLOCKED_CODE) from error
    if type(audit_scope) is not AuditScopeRef:
        _blocked("retained payment basis Audit owner scope is invalid")
    cutoff = _aware(as_of, name="as_of")
    selected_alias = _token(using, name="database alias", limit=64)
    _require_outer_read_transaction(selected_alias)
    _lock_account_owner(
        account_id=basis.account_id,
        owner_user_id=basis.owner_user_id,
        using=selected_alias,
    )
    head_revision, verified = _read_verified_event(
        account_id=basis.account_id,
        owner_user_id=basis.owner_user_id,
        source_namespace=basis.source_namespace,
        source_event_id=basis.source_event_id,
        expected_head_revision_id=basis.source_revision_id,
        using=selected_alias,
        audit_scope=audit_scope,
        account_namespace=basis.grant_account_namespace,
        canonical_account_id=basis.grant_account_id,
        as_of=cutoff,
    )
    active_rows, _ = _verify_event_revision_chain_from_verified(
        verified=verified,
        head_revision_id=head_revision,
    )
    entitlement, payment = _current_paid_pair(active_rows=active_rows, verified=verified)
    _assert_stage_matches_basis(entitlement, basis=basis, entitlement=True)
    _assert_stage_matches_basis(payment, basis=basis, entitlement=False)
    ent_request = entitlement.request
    pay_request = payment.request
    if (
        ent_request.account_id != basis.account_id
        or ent_request.owner_user_id != basis.owner_user_id
        or ent_request.security_id != basis.security_id
        or ent_request.asset_code != basis.asset_code
        or ent_request.asset_name != basis.asset_name
        or ent_request.source_namespace != basis.source_namespace
        or ent_request.source_record_id != basis.source_record_id
        or ent_request.source_event_id != basis.source_event_id
        or ent_request.source_revision_id != basis.source_revision_id
        or ent_request.source_payload_sha256 != basis.source_payload_sha256
        or ent_request.record_date != basis.record_date
        or ent_request.effective_date != basis.effective_date
        or ent_request.payment_date is not None
        or pay_request.payment_date != basis.payment_date
        or ent_request.eligible_quantity != basis.eligible_quantity
        or ent_request.cash_amount != basis.gross_entitlement_amount
        or pay_request.cash_amount != basis.gross_entitlement_amount
        or ent_request.tax_treatment != basis.tax_treatment
        or ent_request.qualification_sha256 != basis.qualification_sha256
        or ent_request.qualifier_identity != basis.qualifier_identity
        or ent_request.ownership_snapshot_id != basis.ownership_snapshot_id
        or ent_request.ownership_snapshot_sha256 != basis.ownership_snapshot_sha256
        or ent_request.ownership_snapshot_observed_at != basis.ownership_snapshot_observed_at
        or ent_request.entitlement_calculation_sha256 != basis.entitlement_calculation_sha256
        or pay_request.source_namespace != basis.source_namespace
        or pay_request.source_event_id != basis.source_event_id
        or pay_request.source_revision_id != basis.source_revision_id
        or pay_request.source_payload_sha256 != basis.source_payload_sha256
        or pay_request.record_date != basis.record_date
        or pay_request.effective_date != basis.effective_date
    ):
        _blocked("retained entitlement or payment economics differ from the original basis")
    gross_quantity = basis.eligible_quantity
    with localcontext() as context:
        context.prec = 80
        gross_amount = gross_quantity * basis.dividend_per_share
    if gross_amount != basis.gross_entitlement_amount:
        _blocked("retained full entitlement gross differs from the original payment basis")


def _verify_event_revision_chain_from_verified(
    *,
    verified: dict[int, _VerifiedPosting],
    head_revision_id: str,
) -> tuple[dict[int, CorporateActionPostingModel], str]:
    """Reconstruct active entries from verified rows without dropping corrections."""

    ordered = tuple(
        sorted(
            (item.row for item in verified.values()),
            key=lambda row: row.account_revision,
        )
    )
    requests = {entry_id: item.request for entry_id, item in verified.items()}
    return _verify_event_revision_chain(
        ordered,
        requests,
        expected_head_revision_id=head_revision_id,
    )


_READ_FAILURES = (
    ConnectionDoesNotExist,
    DatabaseError,
    SimulatedCorporateActionWriteGrantUnavailable,
    SystemAuditEventOutboxCorruption,
    SystemAuditEventOutboxUnavailable,
)


def read_locked_simulated_dividend_payment_basis(
    assessment: CorporateActionTaxAssessment,
    *,
    using: str,
    canonical_account_namespace: str,
    canonical_account_id: str,
    audit_scope: AuditScopeRef,
    as_of: datetime,
) -> SimulatedDividendPaymentBasis:
    """Read exact paid-basis history and normalize unavailable evidence to a stable block."""

    try:
        return _read_locked_simulated_dividend_payment_basis_implementation(
            assessment,
            using=using,
            canonical_account_namespace=canonical_account_namespace,
            canonical_account_id=canonical_account_id,
            audit_scope=audit_scope,
            as_of=as_of,
        )
    except _READ_FAILURES as error:
        raise BusinessLogicError(
            "original simulated cash payment evidence is unavailable", code=_BLOCKED_CODE
        ) from error


def verify_retained_simulated_dividend_payment_basis(
    basis: SimulatedDividendPaymentBasis,
    *,
    scope: TaxLiabilityScope,
    using: str,
    audit_scope: AuditScopeRef,
    as_of: datetime,
) -> None:
    """Re-read retained payment evidence without requiring current write consent."""

    try:
        _verify_retained_simulated_dividend_payment_basis_implementation(
            basis,
            scope=scope,
            using=using,
            audit_scope=audit_scope,
            as_of=as_of,
        )
    except _READ_FAILURES as error:
        raise BusinessLogicError(
            "retained simulated cash payment evidence is unavailable", code=_BLOCKED_CODE
        ) from error


__all__ = (
    "read_locked_simulated_dividend_payment_basis",
    "verify_retained_simulated_dividend_payment_basis",
)
