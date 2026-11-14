"""Compose account-locked corporate-action posting with canonical Audit/Outbox."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from django.db import DEFAULT_DB_ALIAS
from django.utils import timezone

from apps.account.domain.simulated_corporate_action_write_grant import (
    SimulatedCorporateActionWriteGrant,
)
from apps.audit.application.system_audit_event_outbox import ExactSystemAuditOutboxWinner
from apps.audit.domain.system_audit_event import (
    AuditActorRef,
    AuditCategory,
    AuditCorrelations,
    AuditEvidenceRef,
    AuditOutcome,
    AuditResourceRef,
    AuditScopeRef,
    AuditSeverity,
    AuditWritePolicy,
    JSONValue,
    SystemAuditEvent,
)
from apps.audit.infrastructure.system_audit_event_outbox_coordinator import (
    DjangoSystemAuditEventOutboxCoordinator,
)
from apps.simulated_trading.application.corporate_action_current_official_window import (
    CorporateActionCurrentOfficialWindowEvidence,
)
from apps.simulated_trading.application.corporate_action_posting import (
    AuditedCorporateActionPostingRepositoryPort,
    AuditedCorporateActionPostingRepositoryProtocol,
    CorporateActionPostingBlockedError,
    CorporateActionPostingReceipt,
    CorporateActionSourceQualificationVerifierProtocol,
    CorporateActionTaxBasisVerifierProtocol,
    HistoricalAccountOwnershipVerifierProtocol,
    PostCashDividendEntitlementUseCase,
    PostCashDividendPaymentUseCase,
    PostCorporateActionStageUseCase,
)
from apps.simulated_trading.corporate_action_owner_grant_gate import (
    DjangoCorporateActionOwnerGrantGate,
    OwnerGrantedCorporateActionAuthority,
)
from apps.simulated_trading.corporate_action_posting_composition import (
    build_corporate_action_payment_use_case,
    build_corporate_action_posting_use_case,
    build_corporate_action_revision_use_case,
)
from apps.simulated_trading.corporate_action_window_audit_composition import (
    CorporateActionWindowAuditGate,
    corporate_action_window_audit_payload,
    corporate_action_window_audit_sha256,
    restore_corporate_action_window_audit_evidence,
)
from apps.simulated_trading.corporate_action_write_scope_composition import (
    CorporateActionSourceTimestampReplayProof,
    CorporateActionSourceTimestampReplayVerifier,
)
from apps.simulated_trading.domain.corporate_action_posting import (
    CorporateActionEntryKind,
    CorporateActionInputValidationError,
    CorporateActionKind,
    CorporateActionStage,
    CorporateActionStageRequest,
    calculate_corporate_action_delta,
)
from apps.simulated_trading.domain.corporate_action_share_revision import (
    plan_corporate_action_share_revision,
)
from apps.simulated_trading.infrastructure.corporate_action_posting_models import (
    CorporateActionPostingModel,
)
from apps.simulated_trading.infrastructure.corporate_action_posting_repository import (
    DjangoCorporateActionPostingRepository,
    _delta_for_reversal,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    SimulatedAccountModel,
)

_EVENT_TYPE = "simulated.corporate_action.stage_posted"
_EVENT_VERSION = "1"
_DETAIL_SCHEMA = "simulated.corporate_action.stage_posted.v1"
_CASH_CORRECTION_KINDS = frozenset(
    {CorporateActionEntryKind.REVERSAL, CorporateActionEntryKind.SUCCESSOR}
)
_CASH_REVISION_IDENTITY_FIELDS = (
    "account_id",
    "owner_user_id",
    "security_id",
    "asset_code",
    "asset_name",
    "source_namespace",
    "source_record_id",
    "source_event_id",
    "source_revision_id",
    "supersedes_revision_id",
    "record_date",
    "effective_date",
    "source_payload_sha256",
    "qualification_sha256",
    "qualifier_identity",
    "source_observed_at",
    "qualified_at",
    "posted_at",
    "action_kind",
)


def _prepare_cash_revision_requests(
    requests: tuple[CorporateActionStageRequest, ...],
) -> tuple[tuple[CorporateActionStageRequest, ...], CorporateActionStageRequest]:
    """Validate one ordinary cash stage or normalize one complete cash correction."""

    if type(requests) is not tuple or not requests:
        raise CorporateActionPostingBlockedError(
            "cash revision must contain an exact non-empty request tuple",
            code="CORPORATE_ACTION_INPUT_INVALID",
        )
    for request in requests:
        if type(request) is not CorporateActionStageRequest:
            raise CorporateActionPostingBlockedError(
                "cash revision contains an invalid stage request",
                code="CORPORATE_ACTION_INPUT_INVALID",
            )
        try:
            request.__post_init__()
        except (TypeError, ValueError) as error:
            raise CorporateActionPostingBlockedError(
                "cash revision contains an invalid stage request",
                code="CORPORATE_ACTION_INPUT_INVALID",
            ) from error
        if request.action_kind is not CorporateActionKind.CASH_DIVIDEND or request.stage not in {
            CorporateActionStage.CASH_ENTITLEMENT,
            CorporateActionStage.CASH_PAYMENT,
        }:
            raise CorporateActionPostingBlockedError(
                "audited cash revision excludes tax, share, and rights stages",
                code="CORPORATE_ACTION_STAGE_UNSUPPORTED",
            )

    if len(requests) == 1:
        request = requests[0]
        if request.entry_kind not in {
            CorporateActionEntryKind.POSTING,
            CorporateActionEntryKind.SUCCESSOR,
        }:
            raise CorporateActionPostingBlockedError(
                "audited cash posting only accepts one ordinary posting stage",
                code="CORPORATE_ACTION_STAGE_UNSUPPORTED",
            )
        return requests, request

    first = requests[0]
    stage_keys: set[str] = set()
    for request in requests:
        if request.entry_kind not in _CASH_CORRECTION_KINDS:
            raise CorporateActionPostingBlockedError(
                "a multi-stage audited cash revision must be one reversal/successor batch",
                code="CORPORATE_ACTION_STAGE_UNSUPPORTED",
            )
        if any(
            getattr(request, field) != getattr(first, field)
            for field in _CASH_REVISION_IDENTITY_FIELDS
        ):
            raise CorporateActionPostingBlockedError(
                "cash correction stages must share one exact owner and source revision",
                code="CORPORATE_ACTION_BATCH_IDENTITY_INVALID",
            )
        if request.stage_key in stage_keys:
            raise CorporateActionPostingBlockedError(
                "cash correction contains a duplicate stage key",
                code="CORPORATE_ACTION_DUPLICATE_STAGE",
            )
        stage_keys.add(request.stage_key)

    if (
        first.supersedes_revision_id is None
        or first.supersedes_revision_id == first.source_revision_id
        or not any(request.entry_kind is CorporateActionEntryKind.REVERSAL for request in requests)
        or not any(request.entry_kind is CorporateActionEntryKind.SUCCESSOR for request in requests)
    ):
        raise CorporateActionPostingBlockedError(
            "cash correction needs one predecessor and both reversal and successor rows",
            code="CORPORATE_ACTION_REVISION_CONFLICT",
        )

    def _financial_order(request: CorporateActionStageRequest) -> tuple[int, int]:
        reversal = request.entry_kind is CorporateActionEntryKind.REVERSAL
        if reversal:
            return (0, 0 if request.stage is CorporateActionStage.CASH_PAYMENT else 1)
        return (1, 0 if request.stage is CorporateActionStage.CASH_ENTITLEMENT else 1)

    ordered = tuple(sorted(requests, key=_financial_order))
    representative = next(
        request for request in ordered if request.entry_kind is CorporateActionEntryKind.SUCCESSOR
    )
    return ordered, representative


def _restore_cash_revision_receipt_order(
    requests: tuple[CorporateActionStageRequest, ...],
    receipts: tuple[CorporateActionPostingReceipt, ...],
) -> tuple[CorporateActionPostingReceipt, ...]:
    """Return canonical writes in the caller's original request order."""

    receipts_by_stage_key = {receipt.stage_key: receipt for receipt in receipts}
    if len(receipts_by_stage_key) != len(receipts) or set(receipts_by_stage_key) != {
        request.stage_key for request in requests
    }:
        raise CorporateActionPostingBlockedError(
            "cash revision receipts do not match the submitted stage keys",
            code="CORPORATE_ACTION_AUDIT_IDENTITY_CONFLICT",
        )
    return tuple(receipts_by_stage_key[request.stage_key] for request in requests)


def _is_cash_revision(requests: tuple[CorporateActionStageRequest, ...]) -> bool:
    """Select the unchanged historical cash normalization by its first exact family."""

    return (
        type(requests) is tuple
        and bool(requests)
        and type(requests[0]) is CorporateActionStageRequest
        and requests[0].action_kind is CorporateActionKind.CASH_DIVIDEND
    )


def _prepare_audited_revision_requests(
    requests: tuple[CorporateActionStageRequest, ...],
) -> tuple[tuple[CorporateActionStageRequest, ...], CorporateActionStageRequest]:
    """Keep cash on its original planner and normalize only share or rights batches."""

    if _is_cash_revision(requests):
        return _prepare_cash_revision_requests(requests)
    try:
        plan = plan_corporate_action_share_revision(requests)
    except CorporateActionInputValidationError as error:
        raise CorporateActionPostingBlockedError(str(error), code=error.code) from error
    return plan.requests, plan.gate_anchor


def _restore_audited_revision_receipt_order(
    requests: tuple[CorporateActionStageRequest, ...],
    receipts: tuple[CorporateActionPostingReceipt, ...],
) -> tuple[CorporateActionPostingReceipt, ...]:
    """Restore the original request order while retaining cash's exact old check path."""

    if _is_cash_revision(requests):
        return _restore_cash_revision_receipt_order(requests, receipts)
    try:
        plan = plan_corporate_action_share_revision(requests)
    except CorporateActionInputValidationError as error:
        raise CorporateActionPostingBlockedError(str(error), code=error.code) from error
    receipts_by_stage_key = {receipt.stage_key: receipt for receipt in receipts}
    if len(receipts_by_stage_key) != len(receipts) or set(receipts_by_stage_key) != set(
        plan.caller_stage_keys
    ):
        raise CorporateActionPostingBlockedError(
            "share revision receipts do not match the submitted stage keys",
            code="CORPORATE_ACTION_AUDIT_IDENTITY_CONFLICT",
        )
    return tuple(receipts_by_stage_key[stage_key] for stage_key in plan.caller_stage_keys)


def _ledger_row_matches_request(
    row: CorporateActionPostingModel,
    request: CorporateActionStageRequest,
    *,
    reversal_target: CorporateActionPostingModel | None = None,
) -> bool:
    """Reject a replay whose immutable row columns no longer match the full request."""

    if request.entry_kind is CorporateActionEntryKind.REVERSAL:
        if (
            reversal_target is None
            or reversal_target.pk != request.reversal_of_entry_id
            or reversal_target.account_id != request.account_id
            or reversal_target.source_namespace != request.source_namespace
            or reversal_target.source_event_id != request.source_event_id
            or reversal_target.source_revision_id != request.supersedes_revision_id
            or reversal_target.security_id != request.security_id
            or reversal_target.asset_code != request.asset_code
            or reversal_target.action_kind != request.action_kind.value
            or reversal_target.stage != request.stage.value
            or reversal_target.entry_kind
            not in {
                CorporateActionEntryKind.POSTING.value,
                CorporateActionEntryKind.SUCCESSOR.value,
            }
            or reversal_target.reversal_of_id is not None
            or reversal_target.account_revision >= row.account_revision
        ):
            return False
        delta = _delta_for_reversal(reversal_target)
    else:
        if reversal_target is not None:
            return False
        delta = calculate_corporate_action_delta(request)
    return all(
        (
            row.account_id == request.account_id,
            row.source_namespace == request.source_namespace,
            row.source_record_id == request.source_record_id,
            row.source_event_id == request.source_event_id,
            row.source_revision_id == request.source_revision_id,
            row.asset_code == request.asset_code,
            row.security_id == request.security_id,
            row.asset_name == request.asset_name,
            row.action_kind == request.action_kind.value,
            row.stage == request.stage.value,
            row.entry_kind == request.entry_kind.value,
            row.stage_key == request.stage_key,
            row.request_payload_sha256 == request.payload_sha256,
            row.source_payload_sha256 == request.source_payload_sha256,
            row.qualification_sha256 == request.qualification_sha256,
            row.qualifier_identity == request.qualifier_identity,
            row.source_observed_at == request.source_observed_at,
            row.qualified_at == request.qualified_at,
            row.posted_at == request.posted_at,
            row.record_date == request.record_date,
            row.effective_date == request.effective_date,
            row.stage_date == request.stage_date,
            row.payment_date == request.payment_date,
            row.sellable_date == request.sellable_date,
            row.cash_amount == request.cash_amount,
            row.share_amount == request.share_amount,
            row.tax_treatment == request.tax_treatment,
            row.tax_rule_id == request.tax_rule_id,
            row.tax_rule_sha256 == request.tax_rule_sha256,
            row.tax_basis_record_id == request.tax_basis_record_id,
            row.tax_basis_sha256 == request.tax_basis_sha256,
            row.ownership_snapshot_id == request.ownership_snapshot_id,
            row.ownership_snapshot_sha256 == request.ownership_snapshot_sha256,
            row.ownership_snapshot_as_of_date == request.ownership_snapshot_as_of_date,
            row.ownership_snapshot_observed_at == request.ownership_snapshot_observed_at,
            row.eligible_quantity == request.eligible_quantity,
            row.entitlement_calculation_sha256 == request.entitlement_calculation_sha256,
            row.rights_terms_sha256 == request.rights_terms_sha256,
            row.rights_election == request.rights_election,
            row.odd_lot_policy == request.odd_lot_policy,
            row.odd_lot_confirmation_sha256 == request.odd_lot_confirmation_sha256,
            row.supersedes_revision_id == request.supersedes_revision_id,
            row.reversal_of_id == request.reversal_of_entry_id,
            row.cash_delta == delta.cash,
            row.cash_receivable_delta == delta.cash_receivable,
            row.share_delta == delta.shares,
            row.share_receivable_delta == delta.share_receivable,
            row.available_share_delta == delta.available_shares,
        )
    )


def _locked_owner_user_id(request: CorporateActionStageRequest, *, using: str) -> int:
    """Recheck the durable account owner while its posting row lock is held."""

    account = (
        SimulatedAccountModel._base_manager.using(using)
        .select_for_update()
        .filter(
            pk=request.account_id,
            user_id=request.owner_user_id,
            account_type="simulated",
            is_active=True,
        )
        .first()
    )
    if account is None:
        raise CorporateActionPostingBlockedError(
            "locked corporate-action account owner changed before Audit append",
            code="CORPORATE_ACTION_ACCOUNT_SCOPE_INVALID",
        )
    owner_user_id = account.user_id
    if owner_user_id is None or owner_user_id != request.owner_user_id:
        raise CorporateActionPostingBlockedError(
            "locked corporate-action account owner is unavailable",
            code="CORPORATE_ACTION_ACCOUNT_SCOPE_INVALID",
        )
    return owner_user_id


def _stream_id(request: CorporateActionStageRequest) -> str:
    """Serialize all stage events for one exact simulated account."""

    return f"simulated_trading.corporate_action:{request.account_id}"


def _event_id(request: CorporateActionStageRequest) -> str:
    """Derive a bounded identity from the immutable account and stage key."""

    identity = (
        f"{request.account_id}:{request.source_event_id}:"
        f"{request.source_revision_id}:{request.stage_key}"
    ).encode()
    return f"corporate-action-{hashlib.sha256(identity).hexdigest()[:48]}"


def _detail(
    request: CorporateActionStageRequest,
    receipt: CorporateActionPostingReceipt,
) -> dict[str, JSONValue]:
    """Retain exact ledger and qualified source identities without volatile replay flags."""

    return {
        "account_id": request.account_id,
        "owner_user_id": request.owner_user_id,
        "asset_code": request.asset_code,
        "security_id": request.security_id,
        "source_event_id": request.source_event_id,
        "source_revision_id": request.source_revision_id,
        "source_payload_sha256": request.source_payload_sha256,
        "qualification_sha256": request.qualification_sha256,
        "stage": request.stage.value,
        "stage_key": receipt.stage_key,
        "entry_id": receipt.entry_id,
        "account_revision": receipt.account_revision,
        "request_payload_sha256": receipt.request_payload_sha256,
    }


def _build_event(
    request: CorporateActionStageRequest,
    receipt: CorporateActionPostingReceipt,
    *,
    recorded_at: datetime,
    sequence_no: int,
    predecessor_hash: str | None,
    scope: AuditScopeRef,
    owner_grant: SimulatedCorporateActionWriteGrant,
    window_evidence: CorporateActionCurrentOfficialWindowEvidence | None = None,
) -> SystemAuditEvent:
    """Create the registered canonical event for an inserted stage row."""

    if request.posted_at > recorded_at:
        raise CorporateActionPostingBlockedError(
            "corporate-action posting time is after the Audit persistence clock",
            code="CORPORATE_ACTION_AUDIT_CLOCK_INVALID",
        )
    evidence_refs = [
        AuditEvidenceRef(
            owner="data_center",
            artifact_type="official_corporate_action_source",
            artifact_id=request.source_record_id,
            artifact_version=request.source_revision_id,
            content_hash=request.source_payload_sha256,
        )
    ]
    if request.ownership_snapshot_id is not None:
        if request.ownership_snapshot_sha256 is None:
            raise CorporateActionPostingBlockedError(
                "ownership Audit evidence is incomplete",
                code="CORPORATE_ACTION_AUDIT_EVIDENCE_INVALID",
            )
        evidence_refs.append(
            AuditEvidenceRef(
                owner="simulated_trading",
                artifact_type="record_date_ownership_proof",
                artifact_id=request.ownership_snapshot_id,
                artifact_version=request.record_date.isoformat(),
                content_hash=request.ownership_snapshot_sha256,
            )
        )
    owner_grant.__post_init__()
    evidence_refs.append(
        AuditEvidenceRef(
            owner="account",
            artifact_type="simulated_corporate_action_write_grant",
            artifact_id=owner_grant.grant_id,
            artifact_version=owner_grant.grant_version,
            content_hash=owner_grant.content_hash,
        )
    )
    detail = _detail(request, receipt)
    if window_evidence is not None:
        window_payload = corporate_action_window_audit_payload(
            window_evidence,
            request,
            recorded_at=recorded_at,
        )
        detail["current_official_window"] = window_payload
        evidence_refs.append(
            AuditEvidenceRef(
                owner="data_center",
                artifact_type="official_corporate_action_window",
                artifact_id=str(window_evidence.scope_sha256),
                artifact_version=str(window_evidence.policy_sha256),
                content_hash=corporate_action_window_audit_sha256(window_payload),
            )
        )
    return SystemAuditEvent.create(
        event_id=_event_id(request),
        event_version=_EVENT_VERSION,
        schema_version="system-audit-event.v1",
        category=AuditCategory.EXECUTION_CONTROL,
        event_type=_EVENT_TYPE,
        owner="simulated_trading",
        write_policy=AuditWritePolicy.TRANSACTIONAL_OUTBOX,
        outcome=AuditOutcome.SUCCESS,
        severity=AuditSeverity.INFO,
        reason_codes=("corporate_action_stage_posted",),
        occurred_at=request.posted_at,
        recorded_at=recorded_at,
        observed_at=request.qualified_at,
        actor=AuditActorRef("service", "simulated-trading"),
        source_app="simulated_trading",
        source_component="corporate_action_posting",
        source_surface="application",
        correlations=AuditCorrelations(evidence_ref=request.source_payload_sha256),
        resource=AuditResourceRef(
            "simulated_corporate_action_stage",
            _event_id(request),
            receipt.request_payload_sha256,
        ),
        dataset_key=None,
        provider_key=None,
        capability=None,
        publication_id=None,
        evidence_refs=tuple(evidence_refs),
        detail_schema=_DETAIL_SCHEMA,
        detail=detail,
        stream_id=_stream_id(request),
        sequence_no=sequence_no,
        predecessor_hash=predecessor_hash,
        idempotency_key=f"{_EVENT_TYPE}:{_event_id(request)}",
        scope=scope,
    )


@dataclass(frozen=True, slots=True)
class _DjangoCorporateActionReplayTimestampVerifier(CorporateActionSourceTimestampReplayVerifier):
    """Verify one exact request tuple and every ledger/Audit/Outbox row before timestamp bypass."""

    coordinator: DjangoSystemAuditEventOutboxCoordinator
    posting: DjangoCorporateActionPostingRepository
    requests: tuple[CorporateActionStageRequest, ...]
    representative: CorporateActionStageRequest
    using: str

    def __post_init__(self) -> None:
        """Bind the verifier to its canonical immutable request tuple and representative."""

        if (
            type(self.requests) is not tuple
            or not self.requests
            or type(self.representative) is not CorporateActionStageRequest
            or not any(request is self.representative for request in self.requests)
            or type(self.posting) is not DjangoCorporateActionPostingRepository
            or self.posting.database_alias != self.using
            or self.coordinator.database_alias != self.using
        ):
            raise ValueError("replay verifier scope is invalid")
        ordered, representative = _prepare_audited_revision_requests(self.requests)
        if ordered != self.requests or representative is not self.representative:
            raise ValueError("replay verifier request tuple is not its captured canonical tuple")

    def verify_exact_replay(
        self,
        *,
        request: CorporateActionStageRequest,
        grant: SimulatedCorporateActionWriteGrant,
    ) -> CorporateActionSourceTimestampReplayProof | None:
        """Return one representative proof only after the whole captured batch is exact."""

        if type(request) is not CorporateActionStageRequest or request is not self.representative:
            return None
        request.__post_init__()
        grant.__post_init__()
        event_rows = tuple(
            CorporateActionPostingModel._base_manager.using(self.using)
            .select_for_update()
            .filter(
                account_id=request.account_id,
                source_namespace=request.source_namespace,
                source_event_id=request.source_event_id,
            )
            .order_by("account_revision")
        )
        if not event_rows:
            return None
        receipts = self.posting._resolve_exact_replay(self.requests, list(event_rows))
        if receipts is None or len(receipts) != len(self.requests):
            raise CorporateActionPostingBlockedError(
                "corporate-action replay is not the complete retained request tuple",
                code="CORPORATE_ACTION_AUDIT_REPLAY_INVALID",
            )
        rows_by_key = {(row.source_revision_id, row.stage_key): row for row in event_rows}
        rows_by_id = {row.pk: row for row in event_rows}
        receipt_scope = AuditScopeRef(
            tenant_id=grant.binding.tenant_id,
            owner_id=grant.binding.owner_id,
        )
        previous_winner: SystemAuditEvent | None = None
        representative_evidence: tuple[SystemAuditEvent, ExactSystemAuditOutboxWinner] | None = None
        prior_account_revision = 0
        for batch_request, receipt in zip(self.requests, receipts, strict=True):
            row = rows_by_key.get((batch_request.source_revision_id, batch_request.stage_key))
            target_id = batch_request.reversal_of_entry_id
            reversal_target = rows_by_id.get(target_id) if target_id is not None else None
            if (
                row is None
                or type(row.pk) is not int
                or type(row.account_revision) is not int
                or row.account_revision <= prior_account_revision
                or receipt.entry_id != row.pk
                or receipt.account_revision != row.account_revision
                or receipt.stage_key != batch_request.stage_key
                or receipt.request_payload_sha256 != batch_request.payload_sha256
                or not _ledger_row_matches_request(
                    row,
                    batch_request,
                    reversal_target=reversal_target,
                )
            ):
                raise CorporateActionPostingBlockedError(
                    "corporate-action correction ledger order or row differs from its request",
                    code="CORPORATE_ACTION_AUDIT_REPLAY_INVALID",
                )
            prior_account_revision = row.account_revision
            winner = self.coordinator.get_winner(
                event_id=_event_id(batch_request),
                event_version=_EVENT_VERSION,
                as_of=timezone.now(),
            )
            if winner is None or not DjangoAuditedCorporateActionPostingRepository._matches_winner(
                winner,
                batch_request,
                receipt,
                receipt_scope,
                owner_grant=grant,
            ):
                raise CorporateActionPostingBlockedError(
                    "corporate-action replay lacks exact owner-grant Audit evidence",
                    code="CORPORATE_ACTION_AUDIT_REPLAY_INVALID",
                )
            if previous_winner is not None and (
                winner.stream_id != previous_winner.stream_id
                or winner.sequence_no != previous_winner.sequence_no + 1
                or winner.predecessor_hash != previous_winner.content_hash
            ):
                raise CorporateActionPostingBlockedError(
                    "corporate-action correction Audit events are not one ordered stream batch",
                    code="CORPORATE_ACTION_AUDIT_REPLAY_INVALID",
                )
            outbox = self.coordinator.get_exact_outbox_winner_targeted(winner)
            if outbox is None or outbox.event != winner:
                raise CorporateActionPostingBlockedError(
                    "corporate-action replay lacks exact Outbox evidence",
                    code="CORPORATE_ACTION_AUDIT_REPLAY_INVALID",
                )
            if batch_request is self.representative:
                representative_evidence = (winner, outbox)
            previous_winner = winner
        if representative_evidence is None:
            raise CorporateActionPostingBlockedError(
                "corporate-action replay did not retain its exact gate representative",
                code="CORPORATE_ACTION_AUDIT_REPLAY_INVALID",
            )
        winner, outbox = representative_evidence
        return CorporateActionSourceTimestampReplayProof(
            request_payload_sha256=request.payload_sha256,
            grant_content_hash=grant.content_hash,
            audit_event_id=winner.event_id,
            audit_event_content_hash=winner.content_hash,
            outbox_event_content_hash=outbox.event.content_hash,
        )


class DjangoAuditedCorporateActionPostingRepository(AuditedCorporateActionPostingRepositoryPort):
    """Require one exact owner grant and atomically append ledger, Audit and Outbox."""

    def __init__(
        self,
        *,
        posting: DjangoCorporateActionPostingRepository,
        coordinator: DjangoSystemAuditEventOutboxCoordinator,
        owner_grant_gate: DjangoCorporateActionOwnerGrantGate,
        using: str,
        window_gate: CorporateActionWindowAuditGate | None = None,
    ) -> None:
        """Require exact owner-grant authority and same-alias transaction participants."""

        if (
            not using
            or coordinator.database_alias != using
            or posting.database_alias != using
            or type(owner_grant_gate) is not DjangoCorporateActionOwnerGrantGate
            or owner_grant_gate.database_alias != using
            or (window_gate is not None and type(window_gate) is not CorporateActionWindowAuditGate)
        ):
            raise CorporateActionPostingBlockedError(
                "corporate-action owner grant and posting aliases differ or authority is missing",
                code="CORPORATE_ACTION_AUDIT_OUTBOX_UNAVAILABLE",
            )
        self._posting = posting
        self._coordinator = coordinator
        self._owner_grant_gate = owner_grant_gate
        self._using = using
        self._window_gate = window_gate

    def get_database_alias(self) -> str:
        """Return the alias shared by account posting and canonical Audit/Outbox."""

        return self._using

    def post_revision_with_audit(
        self,
        requests: tuple[CorporateActionStageRequest, ...],
    ) -> tuple[CorporateActionPostingReceipt, ...]:
        """Append one supported audited action or one complete correction batch."""

        ordered_requests, representative = _prepare_audited_revision_requests(requests)
        replay_verifier = _DjangoCorporateActionReplayTimestampVerifier(
            coordinator=self._coordinator,
            posting=self._posting,
            requests=ordered_requests,
            representative=representative,
            using=self._using,
        )
        with self._owner_grant_gate.atomic_authority(
            representative,
            replay_timestamp_verifier=replay_verifier,
        ) as authority:
            with self._coordinator.atomic():
                self._owner_grant_gate.assert_source_timestamp_current_or_proven(
                    request=representative
                )
                receipts = self._post_revision_in_atomic(
                    ordered_requests,
                    authority=authority,
                )
                return _restore_audited_revision_receipt_order(requests, receipts)

    def _post_revision_in_atomic(
        self,
        requests: tuple[CorporateActionStageRequest, ...],
        *,
        authority: OwnerGrantedCorporateActionAuthority,
    ) -> tuple[CorporateActionPostingReceipt, ...]:
        """Append canonical ledger rows with ordered authority-scoped Audit/Outbox events."""

        owner_user_id = _locked_owner_user_id(requests[0], using=self._using)
        current_authority = self._assert_current_authority(authority)
        if current_authority != authority or current_authority.user_id != owner_user_id:
            raise CorporateActionPostingBlockedError(
                "Audit authority differs from the locked account owner",
                code="CORPORATE_ACTION_AUDIT_AUTHORITY_SCOPE_INVALID",
            )
        receipts = self._posting.post_revision(requests)
        entry_windows: dict[str, CorporateActionCurrentOfficialWindowEvidence] = {}
        scope = current_authority.scope
        owner_grant = current_authority.grant
        for request, receipt in zip(requests, receipts, strict=True):
            as_of = timezone.now()
            event_id = _event_id(request)
            winner = self._coordinator.get_winner(
                event_id=event_id,
                event_version=_EVENT_VERSION,
                as_of=as_of,
            )
            if receipt.replayed:
                if winner is None or not self._matches_winner(
                    winner,
                    request,
                    receipt,
                    scope,
                    owner_grant=owner_grant,
                ):
                    raise CorporateActionPostingBlockedError(
                        "replayed corporate-action row lacks exact Audit evidence",
                        code="CORPORATE_ACTION_AUDIT_REPLAY_INVALID",
                    )
                outbox = self._coordinator.get_exact_outbox_winner_targeted(winner)
                if outbox is None or outbox.event != winner:
                    raise CorporateActionPostingBlockedError(
                        "replayed corporate-action row lacks exact Outbox evidence",
                        code="CORPORATE_ACTION_AUDIT_REPLAY_INVALID",
                    )
                continue
            if winner is not None:
                raise CorporateActionPostingBlockedError(
                    "new corporate-action row conflicts with prior Audit identity",
                    code="CORPORATE_ACTION_AUDIT_IDENTITY_CONFLICT",
                )
            window_evidence = None
            if self._window_gate is not None:
                window_evidence = self._window_gate.read_entry_evidence(request)
                self._bind_window_deadline(window_evidence)
                entry_windows[request.payload_sha256] = window_evidence
                as_of = timezone.now()
            head = self._coordinator.get_current_head(
                stream_id=_stream_id(request), as_of=as_of, scope=scope
            )
            event = _build_event(
                request,
                receipt,
                recorded_at=as_of,
                sequence_no=head.sequence_no + 1 if head is not None else 1,
                predecessor_hash=head.content_hash if head is not None else None,
                scope=scope,
                owner_grant=owner_grant,
                window_evidence=window_evidence,
            )
            commit = self._coordinator.append_and_enqueue(
                event,
                expected_predecessor_hash=event.predecessor_hash,
                recorded_at=event.recorded_at,
            )
            if commit.event != event:
                raise CorporateActionPostingBlockedError(
                    "corporate-action Audit writer substituted the event",
                    code="CORPORATE_ACTION_AUDIT_IDENTITY_CONFLICT",
                )
        if any(not receipt.replayed for receipt in receipts):
            self._posting.assert_current_sources(requests)
            if self._window_gate is not None:
                for request in requests:
                    original = entry_windows.get(request.payload_sha256)
                    if original is not None:
                        current = self._window_gate.assert_unchanged(request, original)
                        self._bind_window_deadline(current)
        if self._assert_current_authority(authority) != authority:
            raise CorporateActionPostingBlockedError(
                "Audit authority changed before corporate-action commit",
                code="CORPORATE_ACTION_AUDIT_AUTHORITY_SCOPE_INVALID",
            )
        return receipts

    def _bind_window_deadline(self, evidence: CorporateActionCurrentOfficialWindowEvidence) -> None:
        """Keep the source cutoff enforced after every owner context has exited."""
        if evidence.checked_at is None or evidence.expires_at is None:
            raise CorporateActionPostingBlockedError(
                "current official-window deadline is missing",
                code="CORPORATE_ACTION_CURRENT_OFFICIAL_WINDOW_BLOCKED",
            )
        self._owner_grant_gate.bind_current_window_commit_deadline(
            checked_at=evidence.checked_at,
            valid_until=evidence.expires_at,
        )

    def _assert_current_authority(
        self,
        authority: OwnerGrantedCorporateActionAuthority,
    ) -> OwnerGrantedCorporateActionAuthority:
        """Recheck this exact owner grant inside the same outer transaction."""

        current = self._owner_grant_gate.assert_live(as_of=timezone.now())
        if current != authority:
            raise CorporateActionPostingBlockedError(
                "owner grant changed during corporate-action posting",
                code="CORPORATE_ACTION_AUDIT_AUTHORITY_SCOPE_INVALID",
            )
        return current

    @staticmethod
    def _matches_winner(
        winner: SystemAuditEvent,
        request: CorporateActionStageRequest,
        receipt: CorporateActionPostingReceipt,
        scope: AuditScopeRef,
        owner_grant: SimulatedCorporateActionWriteGrant,
    ) -> bool:
        """Compare every stable business field and every active authority evidence link."""

        window_evidence = None
        if "current_official_window" in winner.detail:
            try:
                window_evidence = restore_corporate_action_window_audit_evidence(
                    winner.detail["current_official_window"],
                    request,
                    recorded_at=winner.recorded_at,
                )
            except CorporateActionPostingBlockedError:
                return False
        expected = _build_event(
            request,
            receipt,
            recorded_at=winner.recorded_at,
            sequence_no=winner.sequence_no,
            predecessor_hash=winner.predecessor_hash,
            scope=scope,
            owner_grant=owner_grant,
            window_evidence=window_evidence,
        )
        return winner == expected


class DjangoAuditedCorporateActionPostingRepositoryFactory(
    AuditedCorporateActionPostingRepositoryProtocol
):
    """Construct the same-alias posting adapter only with an explicit owner grant gate."""

    def __init__(
        self,
        *,
        environment: str = "production",
        owner_grant_gate: DjangoCorporateActionOwnerGrantGate,
        window_gate: CorporateActionWindowAuditGate | None = None,
    ) -> None:
        """Bind one exact owner-grant gate for every financial posting use case."""

        if (
            type(owner_grant_gate) is not DjangoCorporateActionOwnerGrantGate
            or owner_grant_gate.runtime_environment != environment
            or owner_grant_gate.database_alias != DEFAULT_DB_ALIAS
        ):
            raise CorporateActionPostingBlockedError(
                "cash posting requires an exact default-alias owner-grant gate",
                code="CORPORATE_ACTION_WRITE_AUTHORITY_UNAVAILABLE",
            )

        self._owner_grant_gate = owner_grant_gate
        self._window_gate = window_gate

    def build_posting_repository(
        self,
        *,
        source_qualifier: CorporateActionSourceQualificationVerifierProtocol,
        ownership_verifier: HistoricalAccountOwnershipVerifierProtocol,
        tax_basis_verifier: CorporateActionTaxBasisVerifierProtocol | None,
        using: str,
    ) -> AuditedCorporateActionPostingRepositoryPort:
        """Bind official and ownership verifiers to one atomic posting UOW."""

        if (
            not using
            or source_qualifier is None
            or ownership_verifier is None
            or tax_basis_verifier is not None
        ):
            raise CorporateActionPostingBlockedError(
                "cash-only Audit posting verifiers or database alias are invalid",
                code="CORPORATE_ACTION_AUDIT_OUTBOX_UNAVAILABLE",
            )
        return DjangoAuditedCorporateActionPostingRepository(
            posting=DjangoCorporateActionPostingRepository(
                source_qualifier=source_qualifier,
                ownership_verifier=ownership_verifier,
                tax_basis_verifier=None,
                using=using,
            ),
            coordinator=DjangoSystemAuditEventOutboxCoordinator(using=using),
            owner_grant_gate=self._owner_grant_gate,
            window_gate=self._window_gate,
            using=using,
        )


def build_audited_cash_entitlement_use_case(
    *,
    body_store_root: Path,
    runtime_environment: str,
    owner_grant_gate: DjangoCorporateActionOwnerGrantGate,
    using: str = DEFAULT_DB_ALIAS,
    window_gate: CorporateActionWindowAuditGate | None = None,
) -> PostCashDividendEntitlementUseCase:
    """Wire official entitlement with the explicit same-alias owner grant."""

    if using != DEFAULT_DB_ALIAS:
        raise CorporateActionPostingBlockedError(
            "cash entitlement valuation currently supports the default account database only",
            code="CORPORATE_ACTION_AUDIT_OUTBOX_UNAVAILABLE",
        )
    return build_corporate_action_posting_use_case(
        body_store_root=body_store_root,
        runtime_environment=runtime_environment,
        audited_repository=DjangoAuditedCorporateActionPostingRepositoryFactory(
            environment=runtime_environment,
            owner_grant_gate=owner_grant_gate,
            window_gate=window_gate,
        ),
        using=using,
    )


def build_audited_cash_payment_use_case(
    *,
    body_store_root: Path,
    runtime_environment: str,
    owner_grant_gate: DjangoCorporateActionOwnerGrantGate,
    using: str = DEFAULT_DB_ALIAS,
    window_gate: CorporateActionWindowAuditGate | None = None,
) -> PostCashDividendPaymentUseCase:
    """Wire official payment with the explicit same-alias owner grant."""

    if using != DEFAULT_DB_ALIAS:
        raise CorporateActionPostingBlockedError(
            "cash payment valuation currently supports the default account database only",
            code="CORPORATE_ACTION_AUDIT_OUTBOX_UNAVAILABLE",
        )
    return build_corporate_action_payment_use_case(
        body_store_root=body_store_root,
        runtime_environment=runtime_environment,
        audited_repository=DjangoAuditedCorporateActionPostingRepositoryFactory(
            environment=runtime_environment,
            owner_grant_gate=owner_grant_gate,
            window_gate=window_gate,
        ),
        using=using,
    )


def build_audited_cash_revision_use_case(
    *,
    body_store_root: Path,
    runtime_environment: str,
    owner_grant_gate: DjangoCorporateActionOwnerGrantGate,
    using: str = DEFAULT_DB_ALIAS,
    window_gate: CorporateActionWindowAuditGate | None = None,
) -> PostCorporateActionStageUseCase:
    """Wire the generic cash stage use case to the same explicit owner-grant Audit UOW."""

    if using != DEFAULT_DB_ALIAS:
        raise CorporateActionPostingBlockedError(
            "cash correction valuation currently supports the default account database only",
            code="CORPORATE_ACTION_AUDIT_OUTBOX_UNAVAILABLE",
        )
    return build_corporate_action_revision_use_case(
        body_store_root=body_store_root,
        runtime_environment=runtime_environment,
        audited_repository=DjangoAuditedCorporateActionPostingRepositoryFactory(
            environment=runtime_environment,
            owner_grant_gate=owner_grant_gate,
            window_gate=window_gate,
        ),
        using=using,
    )
