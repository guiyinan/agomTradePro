"""Compose account-locked corporate-action posting with canonical Audit/Outbox."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from django.db import DEFAULT_DB_ALIAS
from django.utils import timezone

from apps.audit.application.system_audit_authority_renewal_guard import (
    SystemAuditAuthorityLease,
)
from apps.audit.application.system_audit_composition import (
    SystemAuditCompositionUnavailable,
)
from apps.audit.application.system_audit_query import SystemAuditReaderContext
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
from apps.audit.infrastructure.system_audit_outbox_runtime import (
    get_system_audit_authority_lease,
    preflight_system_audit_runtime,
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
)
from apps.simulated_trading.corporate_action_posting_composition import (
    build_corporate_action_posting_use_case,
)
from apps.simulated_trading.domain.corporate_action_posting import (
    CorporateActionEntryKind,
    CorporateActionKind,
    CorporateActionStage,
    CorporateActionStageRequest,
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


@dataclass(frozen=True, slots=True)
class DjangoRuntimeCorporateActionAuditGate:
    """Require live configured System Audit authority before and after account writes."""

    environment: str
    using: str

    def assert_live(self, *, as_of: datetime) -> SystemAuditReaderContext:
        """Fail closed when required Outbox mode or issued staff authority is absent."""

        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise CorporateActionPostingBlockedError(
                "corporate-action Audit authority clock is invalid",
                code="CORPORATE_ACTION_AUDIT_AUTHORITY_UNAVAILABLE",
            )
        try:
            lease = get_system_audit_authority_lease(environment=self.environment, using=self.using)
            if (
                type(lease) is not SystemAuditAuthorityLease
                or lease.mode != "required"
                or lease.outbox_enabled is not True
                or lease.valid_until is None
                or lease.valid_until <= as_of
            ):
                raise CorporateActionPostingBlockedError(
                    "required corporate-action Audit/Outbox lease is unavailable",
                    code="CORPORATE_ACTION_AUDIT_AUTHORITY_UNAVAILABLE",
                )
            authority = preflight_system_audit_runtime(
                environment=self.environment, using=self.using, as_of=as_of
            )
        except SystemAuditCompositionUnavailable as error:
            raise CorporateActionPostingBlockedError(
                "corporate-action Audit runtime authority is unavailable",
                code="CORPORATE_ACTION_AUDIT_AUTHORITY_UNAVAILABLE",
            ) from error
        if authority.authority_valid_until <= as_of:
            raise CorporateActionPostingBlockedError(
                "corporate-action Audit authority expired",
                code="CORPORATE_ACTION_AUDIT_AUTHORITY_UNAVAILABLE",
            )
        return authority


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


class DjangoAuditedCorporateActionPostingRepository(AuditedCorporateActionPostingRepositoryPort):
    """Use one alias and one outer Audit transaction for ledger, event and outbox."""

    def __init__(
        self,
        *,
        posting: DjangoCorporateActionPostingRepository,
        coordinator: DjangoSystemAuditEventOutboxCoordinator,
        authority_gate: DjangoRuntimeCorporateActionAuditGate,
        using: str,
    ) -> None:
        """Reject mismatched transaction participants at composition time."""

        if (
            not using
            or coordinator.database_alias != using
            or posting.database_alias != using
            or type(authority_gate) is not DjangoRuntimeCorporateActionAuditGate
            or authority_gate.using != using
        ):
            raise CorporateActionPostingBlockedError(
                "corporate-action Audit and posting aliases differ",
                code="CORPORATE_ACTION_AUDIT_OUTBOX_UNAVAILABLE",
            )
        self._posting = posting
        self._coordinator = coordinator
        self._authority_gate = authority_gate
        self._using = using

    def get_database_alias(self) -> str:
        """Return the alias shared by account posting and canonical Audit/Outbox."""

        return self._using

    def post_revision_with_audit(
        self,
        requests: tuple[CorporateActionStageRequest, ...],
    ) -> tuple[CorporateActionPostingReceipt, ...]:
        """Rollback all account and Audit writes when any required append fails."""

        if (
            type(requests) is not tuple
            or len(requests) != 1
            or type(requests[0]) is not CorporateActionStageRequest
            or requests[0].action_kind is not CorporateActionKind.CASH_DIVIDEND
            or requests[0].stage is not CorporateActionStage.CASH_ENTITLEMENT
            or requests[0].entry_kind
            not in {CorporateActionEntryKind.POSTING, CorporateActionEntryKind.SUCCESSOR}
        ):
            raise CorporateActionPostingBlockedError(
                "audited production posting only accepts one cash entitlement",
                code="CORPORATE_ACTION_STAGE_UNSUPPORTED",
            )
        authority = self._authority_gate.assert_live(as_of=timezone.now())
        with self._coordinator.atomic():
            receipts = self._posting.post_revision(requests)
            owner_user_id = _locked_owner_user_id(requests[0], using=self._using)
            current_authority = self._authority_gate.assert_live(as_of=timezone.now())
            if current_authority != authority or current_authority.user_id != owner_user_id:
                raise CorporateActionPostingBlockedError(
                    "Audit authority differs from the locked account owner",
                    code="CORPORATE_ACTION_AUDIT_AUTHORITY_SCOPE_INVALID",
                )
            scope = current_authority.scope
            for request, receipt in zip(requests, receipts, strict=True):
                as_of = timezone.now()
                event_id = _event_id(request)
                winner = self._coordinator.get_winner(
                    event_id=event_id,
                    event_version=_EVENT_VERSION,
                    as_of=as_of,
                )
                if receipt.replayed:
                    if winner is None or not self._matches_winner(winner, request, receipt, scope):
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
            if self._authority_gate.assert_live(as_of=timezone.now()) != authority:
                raise CorporateActionPostingBlockedError(
                    "Audit authority changed before corporate-action commit",
                    code="CORPORATE_ACTION_AUDIT_AUTHORITY_SCOPE_INVALID",
                )
        return receipts

    @staticmethod
    def _matches_winner(
        winner: SystemAuditEvent,
        request: CorporateActionStageRequest,
        receipt: CorporateActionPostingReceipt,
        scope: AuditScopeRef,
    ) -> bool:
        """Compare every stable business field and both required evidence links."""

        expected = _build_event(
            request,
            receipt,
            recorded_at=winner.recorded_at,
            sequence_no=winner.sequence_no,
            predecessor_hash=winner.predecessor_hash,
            scope=scope,
        )
        return winner == expected


class DjangoAuditedCorporateActionPostingRepositoryFactory(
    AuditedCorporateActionPostingRepositoryProtocol
):
    """Construct the explicit same-alias Audit/Outbox posting adapter."""

    def __init__(self, *, environment: str = "production") -> None:
        """Bind the control-plane environment used for live authority reads."""

        self._environment = environment

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
            authority_gate=DjangoRuntimeCorporateActionAuditGate(
                environment=self._environment, using=using
            ),
            using=using,
        )


def build_audited_cash_entitlement_use_case(
    *,
    body_store_root: Path,
    runtime_environment: str,
    using: str = DEFAULT_DB_ALIAS,
) -> PostCashDividendEntitlementUseCase:
    """Wire official cash entitlement to canonical same-alias Audit/Outbox."""

    return build_corporate_action_posting_use_case(
        body_store_root=body_store_root,
        runtime_environment=runtime_environment,
        audited_repository=DjangoAuditedCorporateActionPostingRepositoryFactory(
            environment=runtime_environment
        ),
        using=using,
    )
