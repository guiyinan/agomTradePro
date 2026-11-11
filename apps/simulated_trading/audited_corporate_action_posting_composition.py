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
)
from apps.simulated_trading.corporate_action_owner_grant_gate import (
    DjangoCorporateActionOwnerGrantGate,
    OwnerGrantedCorporateActionAuthority,
)
from apps.simulated_trading.corporate_action_posting_composition import (
    build_corporate_action_payment_use_case,
    build_corporate_action_posting_use_case,
)
from apps.simulated_trading.corporate_action_write_scope_composition import (
    CorporateActionSourceTimestampReplayProof,
    CorporateActionSourceTimestampReplayVerifier,
)
from apps.simulated_trading.domain.corporate_action_posting import (
    CorporateActionEntryKind,
    CorporateActionKind,
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

_EVENT_TYPE = "simulated.corporate_action.stage_posted"
_EVENT_VERSION = "1"
_DETAIL_SCHEMA = "simulated.corporate_action.stage_posted.v1"


def _ledger_row_matches_request(
    row: CorporateActionPostingModel,
    request: CorporateActionStageRequest,
) -> bool:
    """Reject a replay whose immutable row columns no longer match the full request."""

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
        detail=_detail(request, receipt),
        stream_id=_stream_id(request),
        sequence_no=sequence_no,
        predecessor_hash=predecessor_hash,
        idempotency_key=f"{_EVENT_TYPE}:{_event_id(request)}",
        scope=scope,
    )


@dataclass(frozen=True, slots=True)
class _DjangoCorporateActionReplayTimestampVerifier(CorporateActionSourceTimestampReplayVerifier):
    """Verify one exact existing ledger/Audit/Outbox identity before timestamp bypass."""

    coordinator: DjangoSystemAuditEventOutboxCoordinator
    using: str

    def verify_exact_replay(
        self,
        *,
        request: CorporateActionStageRequest,
        grant: SimulatedCorporateActionWriteGrant,
    ) -> CorporateActionSourceTimestampReplayProof | None:
        """Return a proof only for the exact immutable request under this current grant."""

        request.__post_init__()
        grant.__post_init__()
        rows = tuple(
            CorporateActionPostingModel._base_manager.using(self.using)
            .select_for_update()
            .filter(
                account_id=request.account_id,
                source_event_id=request.source_event_id,
                source_revision_id=request.source_revision_id,
                stage_key=request.stage_key,
            )
            .order_by("pk")[:2]
        )
        if not rows:
            return None
        if len(rows) != 1:
            raise CorporateActionPostingBlockedError(
                "corporate-action replay ledger identity is ambiguous",
                code="CORPORATE_ACTION_AUDIT_REPLAY_INVALID",
            )
        row = rows[0]
        if (
            type(row.pk) is not int
            or not _ledger_row_matches_request(row, request)
            or row.request_payload_sha256 != request.payload_sha256
            or row.stage_key != request.stage_key
        ):
            raise CorporateActionPostingBlockedError(
                "corporate-action replay request differs from its ledger hash",
                code="CORPORATE_ACTION_AUDIT_REPLAY_INVALID",
            )
        receipt = CorporateActionPostingReceipt(
            entry_id=row.pk,
            account_revision=row.account_revision,
            stage_key=row.stage_key,
            request_payload_sha256=row.request_payload_sha256,
            replayed=True,
        )
        receipt_scope = AuditScopeRef(
            tenant_id=grant.binding.tenant_id,
            owner_id=grant.binding.owner_id,
        )
        winner = self.coordinator.get_winner(
            event_id=_event_id(request),
            event_version=_EVENT_VERSION,
            as_of=timezone.now(),
        )
        if winner is None or not DjangoAuditedCorporateActionPostingRepository._matches_winner(
            winner,
            request,
            receipt,
            receipt_scope,
            owner_grant=grant,
        ):
            raise CorporateActionPostingBlockedError(
                "corporate-action replay lacks exact owner-grant Audit evidence",
                code="CORPORATE_ACTION_AUDIT_REPLAY_INVALID",
            )
        outbox = self.coordinator.get_exact_outbox_winner_targeted(winner)
        if outbox is None or outbox.event != winner:
            raise CorporateActionPostingBlockedError(
                "corporate-action replay lacks exact Outbox evidence",
                code="CORPORATE_ACTION_AUDIT_REPLAY_INVALID",
            )
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
    ) -> None:
        """Require exact owner-grant authority and same-alias transaction participants."""

        if (
            not using
            or coordinator.database_alias != using
            or posting.database_alias != using
            or type(owner_grant_gate) is not DjangoCorporateActionOwnerGrantGate
            or owner_grant_gate.database_alias != using
        ):
            raise CorporateActionPostingBlockedError(
                "corporate-action owner grant and posting aliases differ or authority is missing",
                code="CORPORATE_ACTION_AUDIT_OUTBOX_UNAVAILABLE",
            )
        self._posting = posting
        self._coordinator = coordinator
        self._owner_grant_gate = owner_grant_gate
        self._using = using

    def get_database_alias(self) -> str:
        """Return the alias shared by account posting and canonical Audit/Outbox."""

        return self._using

    def post_revision_with_audit(
        self,
        requests: tuple[CorporateActionStageRequest, ...],
    ) -> tuple[CorporateActionPostingReceipt, ...]:
        """Rollback all ledger and Audit writes when any required append fails."""

        if (
            type(requests) is not tuple
            or len(requests) != 1
            or type(requests[0]) is not CorporateActionStageRequest
            or requests[0].action_kind is not CorporateActionKind.CASH_DIVIDEND
            or requests[0].stage
            not in {
                CorporateActionStage.CASH_ENTITLEMENT,
                CorporateActionStage.CASH_PAYMENT,
            }
            or requests[0].entry_kind
            not in {CorporateActionEntryKind.POSTING, CorporateActionEntryKind.SUCCESSOR}
        ):
            raise CorporateActionPostingBlockedError(
                "audited production posting only accepts one cash entitlement or payment",
                code="CORPORATE_ACTION_STAGE_UNSUPPORTED",
            )
        request = requests[0]
        replay_verifier = _DjangoCorporateActionReplayTimestampVerifier(
            coordinator=self._coordinator,
            using=self._using,
        )
        with self._owner_grant_gate.atomic_authority(
            request,
            replay_timestamp_verifier=replay_verifier,
        ) as authority:
            with self._coordinator.atomic():
                self._owner_grant_gate.assert_source_timestamp_current_or_proven(request=request)
                return self._post_revision_in_atomic(
                    requests,
                    authority=authority,
                )

    def _post_revision_in_atomic(
        self,
        requests: tuple[CorporateActionStageRequest, ...],
        *,
        authority: OwnerGrantedCorporateActionAuthority,
    ) -> tuple[CorporateActionPostingReceipt, ...]:
        """Append one ledger request with its exact authority-scoped Audit/Outbox event."""

        owner_user_id = _locked_owner_user_id(requests[0], using=self._using)
        current_authority = self._assert_current_authority(authority)
        if current_authority != authority or current_authority.user_id != owner_user_id:
            raise CorporateActionPostingBlockedError(
                "Audit authority differs from the locked account owner",
                code="CORPORATE_ACTION_AUDIT_AUTHORITY_SCOPE_INVALID",
            )
        receipts = self._posting.post_revision(requests)
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
        if self._assert_current_authority(authority) != authority:
            raise CorporateActionPostingBlockedError(
                "Audit authority changed before corporate-action commit",
                code="CORPORATE_ACTION_AUDIT_AUTHORITY_SCOPE_INVALID",
            )
        return receipts

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

        expected = _build_event(
            request,
            receipt,
            recorded_at=winner.recorded_at,
            sequence_no=winner.sequence_no,
            predecessor_hash=winner.predecessor_hash,
            scope=scope,
            owner_grant=owner_grant,
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
            using=using,
        )


def build_audited_cash_entitlement_use_case(
    *,
    body_store_root: Path,
    runtime_environment: str,
    owner_grant_gate: DjangoCorporateActionOwnerGrantGate,
    using: str = DEFAULT_DB_ALIAS,
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
        ),
        using=using,
    )


def build_audited_cash_payment_use_case(
    *,
    body_store_root: Path,
    runtime_environment: str,
    owner_grant_gate: DjangoCorporateActionOwnerGrantGate,
    using: str = DEFAULT_DB_ALIAS,
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
        ),
        using=using,
    )
