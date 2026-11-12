"""Compose nonfinancial assessment evidence with its exact atomic Audit/Outbox proof."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, cast, runtime_checkable

from django.db import connections, transaction
from django.utils import timezone

from apps.audit.corporate_action_tax_assessment_composition import (
    TaxAssessmentAuditCoordinatorPort,
    build_tax_assessment_audit_coordinator,
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
    SystemAuditEvent,
)
from apps.simulated_trading.application.corporate_action_tax_assessment import (
    CorporateActionTaxAssessmentUseCase,
    CurrentTaxAssessmentScopeVerifierPort,
    TaxAssessmentAppendDisposition,
    TaxAssessmentAtomicWriterPort,
    TaxAssessmentClockPort,
    TaxAssessmentWriteLease,
    TaxAssessmentWriteReceipt,
)
from apps.simulated_trading.domain.corporate_action_tax_assessment import (
    CorporateActionTaxAssessment,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_assessment_models import (
    CorporateActionTaxAssessmentHeaderModel as Header,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_assessment_repository import (
    DjangoCorporateActionTaxAssessmentRepository,
    TaxAssessmentPersistedAuthority,
    canonical_json,
    material_sha256,
    read_material,
    recorded_id,
)
from core.exceptions import BusinessLogicError

_EVENT_TYPE = "simulated.corporate_action.tax_assessed"
_DETAIL_SCHEMA = "simulated.corporate_action.tax_assessed.v1"


def _blocked(message: str) -> BusinessLogicError:
    """Reject missing or non-exact assessment/Audit evidence without repairing it."""
    return BusinessLogicError(message, code="TAX_ASSESSMENT_AUDIT_BLOCKED")


@dataclass(frozen=True, slots=True)
class TaxAssessmentAuditOrigin:
    """References yielded only inside an actual locked current-scope verifier.

    The producer must independently require current owner consent, role, source,
    policy/date scope and required operational Audit/Outbox configuration. This
    DTO never issues any of those permissions.
    """

    lease: TaxAssessmentWriteLease
    scope: AuditScopeRef
    grant_content_sha256: str
    write_policy: AuditWritePolicy

    def __post_init__(self) -> None:
        """Require the exact typed lease, original grant seal and transactional policy."""
        if type(self.lease) is not TaxAssessmentWriteLease or type(self.scope) is not AuditScopeRef:
            raise _blocked("A typed locked tax authority and Audit scope are required.")
        self.lease.__post_init__()
        self.scope.__post_init__()
        if self.write_policy is not AuditWritePolicy.TRANSACTIONAL_OUTBOX:
            raise _blocked("Tax assessments require transactional Audit/Outbox policy.")
        TaxAssessmentPersistedAuthority(
            self.lease.authority_grant_id,
            self.lease.authority_grant_version,
            self.grant_content_sha256,
            self.scope.tenant_id,
            self.scope.owner_id,
        )


@runtime_checkable
class AuditedTaxAssessmentScopeVerifierPort(CurrentTaxAssessmentScopeVerifierPort, Protocol):
    """Current verifier and its active original-grant Audit origin from the same locks."""

    def get_locked_audit_origin(self) -> TaxAssessmentAuditOrigin:
        """Return only while the exact current-scope context is active; otherwise block."""
        ...


class _ServerClock:
    """Supply actual UTC server time when a controlled QA clock is not injected."""

    def now(self) -> datetime:
        """Read the server clock without rewriting source observation times."""
        return timezone.now()


def _event_id(header: Header) -> str:
    """Derive event identity from the logical revision, independent of database sequence."""
    digest = material_sha256(
        canonical_json(
            {
                "account_id": header.account_id,
                "idempotency_key": header.idempotency_key,
                "assessment_revision_id": header.assessment_revision_id,
            }
        )
    )
    return f"simulated-tax-assessment:{digest}"


def _stream_id(header: Header) -> str:
    """Keep partial-sale assessments and their explicit successors in one exact stream."""
    return f"simulated-tax-assessment-stream:{header.idempotency_key}"


def _build_event(
    header: Header, *, sequence_no: int, predecessor_hash: str | None
) -> SystemAuditEvent:
    """Build only concise references to the complete retained professional evidence."""
    manifest = read_material(header.observation_manifest_json, header.observation_manifest_sha256)
    proof = manifest.get("ownership_proof")
    if type(proof) is not dict or type(proof.get("ownership_snapshot_observed_at")) is not str:
        raise _blocked("Original ownership observation material is incomplete.")
    observed_at = datetime.fromisoformat(proof["ownership_snapshot_observed_at"])
    return SystemAuditEvent.create(
        event_id=_event_id(header),
        event_version="1",
        schema_version="system-audit-event.v1",
        category=AuditCategory.EXECUTION_CONTROL,
        event_type=_EVENT_TYPE,
        owner="simulated_trading",
        write_policy=AuditWritePolicy.TRANSACTIONAL_OUTBOX,
        outcome=AuditOutcome.SUCCESS,
        severity=AuditSeverity.INFO,
        reason_codes=("corporate_action_tax_assessed",),
        occurred_at=header.recorded_at,
        recorded_at=header.recorded_at,
        observed_at=observed_at,
        actor=AuditActorRef("service", "simulated-trading"),
        source_app="simulated_trading",
        source_component="corporate_action_tax_assessment",
        source_surface="application",
        correlations=AuditCorrelations(evidence_ref=header.semantic_sha256),
        resource=AuditResourceRef(
            "simulated_tax_assessment", str(recorded_id(header)), header.semantic_sha256
        ),
        dataset_key=None,
        provider_key=None,
        capability=None,
        publication_id=None,
        evidence_refs=(
            AuditEvidenceRef(
                "simulated_trading",
                "tax_assessment_semantics",
                str(recorded_id(header)),
                "v1",
                header.semantic_sha256,
            ),
            AuditEvidenceRef(
                "simulated_trading",
                "tax_assessment_observations",
                str(recorded_id(header)),
                "v1",
                header.observation_manifest_sha256,
            ),
            AuditEvidenceRef(
                "data_center",
                "statutory_revision_set",
                header.policy_source_identity,
                "v1",
                header.statutory_revision_set_sha256,
            ),
            AuditEvidenceRef(
                "account",
                "simulated_corporate_action_write_grant",
                header.authority_grant_id,
                header.authority_grant_version,
                header.authority_grant_sha256,
            ),
        ),
        detail_schema=_DETAIL_SCHEMA,
        detail={
            "account_id": header.account_id,
            "owner_user_id": header.owner_user_id,
            "assessment_id": recorded_id(header),
            "assessment_revision_id": header.assessment_revision_id,
            "asset_code": header.asset_code,
            "security_id": header.security_id,
            "corporate_action_id": header.corporate_action_id,
            "disposition_id": header.disposition_id,
            "source_event_id": header.source_event_id,
            "source_revision_id": header.action_source_revision_id,
            "record_date": header.record_date.isoformat(),
            "settlement_date": header.settlement_date.isoformat(),
            "semantic_sha256": header.semantic_sha256,
            "observation_manifest_sha256": header.observation_manifest_sha256,
            "policy_sha256": header.policy_sha256,
            "withholding_amount": header.withholding_amount_text,
            "grant_id": header.authority_grant_id,
            "grant_version": header.authority_grant_version,
            "nonfinancial_assessment_only": True,
        },
        stream_id=_stream_id(header),
        sequence_no=sequence_no,
        predecessor_hash=predecessor_hash,
        idempotency_key=f"{_EVENT_TYPE}:{_event_id(header)}",
        scope=AuditScopeRef(header.audit_tenant_id, header.audit_owner_id),
    )


class DjangoTaxAssessmentAtomicUnitOfWork:
    """Write header, ordered allocations, canonical Audit and Outbox in one alias."""

    def __init__(
        self,
        *,
        using: str,
        scope_verifier: AuditedTaxAssessmentScopeVerifierPort,
        audit: TaxAssessmentAuditCoordinatorPort,
        clock: TaxAssessmentClockPort,
    ) -> None:
        """Require the exact verifier and existing Audit coordinator, with no fallback permission."""
        if audit.database_alias != using or scope_verifier.database_alias != using:
            raise _blocked("Assessment, current authority and Audit must use one alias.")
        self._using = using
        self._verifier = scope_verifier
        self._audit = audit
        self._clock = clock
        self._active = False
        self._repository = DjangoCorporateActionTaxAssessmentRepository(using=using)

    @property
    def database_alias(self) -> str:
        """Return the single storage, permission and Audit alias."""
        return self._using

    @contextmanager
    def atomic(self, *, using: str) -> Iterator[TaxAssessmentAtomicWriterPort]:
        """Open the outermost transaction before binding the existing Audit capabilities."""
        if using != self._using or self._active or connections[using].in_atomic_block:
            raise _blocked("An unnested caller-owned assessment transaction is required.")
        self._active = True
        try:
            with transaction.atomic(using=using):
                with self._audit.caller_owned_atomic():
                    yield self
        finally:
            self._active = False

    def append_with_audit_outbox(
        self, assessment: CorporateActionTaxAssessment, *, actor_user_id: int
    ) -> TaxAssessmentWriteReceipt:
        """Append complete evidence or verify its original exact Audit/Outbox pair."""
        if not self._active or not connections[self._using].in_atomic_block:
            raise _blocked("The assessment writer is not in its own active UOW.")
        origin = self._verifier.get_locked_audit_origin()
        origin.__post_init__()
        now = self._clock.now()
        if type(now) is not datetime or now.tzinfo is None or now.utcoffset() is None:
            raise _blocked("Assessment recording requires an aware server clock.")
        now.astimezone(UTC)
        origin.lease.verify_for(
            assessment, actor_user_id=actor_user_id, using=self._using, as_of=now
        )
        authority = TaxAssessmentPersistedAuthority(
            origin.lease.authority_grant_id,
            origin.lease.authority_grant_version,
            origin.grant_content_sha256,
            origin.scope.tenant_id,
            origin.scope.owner_id,
        )
        result = self._repository.append_locked(assessment, authority=authority, recorded_at=now)
        header = result.header
        if (header.audit_tenant_id, header.audit_owner_id) != (
            origin.scope.tenant_id,
            origin.scope.owner_id,
        ):
            raise _blocked("The retained assessment belongs to another exact Audit owner scope.")
        self._audit.lock_streams((_stream_id(header),))
        winner = self._audit.get_winner_targeted(
            event_id=_event_id(header), event_version="1", as_of=now, lock=True
        )
        if result.replayed:
            if winner is None:
                raise _blocked(
                    "Original assessment Audit evidence is missing; it cannot be synthesized."
                )
            expected = _build_event(
                header, sequence_no=winner.sequence_no, predecessor_hash=winner.predecessor_hash
            )
            outbox = self._audit.get_exact_outbox_winner_targeted(winner)
            if winner != expected or outbox is None or outbox.event != expected:
                raise _blocked(
                    "Original assessment Audit/Outbox evidence is incomplete or different."
                )
            disposition = TaxAssessmentAppendDisposition.EXACT_RETRY
        else:
            if winner is not None:
                raise _blocked("An orphan Audit identity cannot be rebound to a new assessment.")
            scope = AuditScopeRef(header.audit_tenant_id, header.audit_owner_id)
            head = self._audit.get_current_head_targeted(
                stream_id=_stream_id(header), as_of=now, scope=scope, lock=True
            )
            predecessor_id = cast(int | None, header.__dict__.get("supersedes_id"))
            if predecessor_id is None:
                if head is not None:
                    raise _blocked("A first assessment cannot follow an orphan Audit stream.")
            else:
                predecessor = Header._default_manager.using(self._using).get(pk=predecessor_id)
                if (
                    head is None
                    or head.event_id != _event_id(predecessor)
                    or self._audit.get_exact_outbox_winner_targeted(head) is None
                ):
                    raise _blocked(
                        "Assessment successor requires complete predecessor Audit/Outbox."
                    )
            event = _build_event(
                header,
                sequence_no=head.sequence_no + 1 if head else 1,
                predecessor_hash=head.content_hash if head else None,
            )
            if self._audit.get_exact_outbox_winner_targeted(event) is not None:
                raise _blocked(
                    "An orphan Outbox identity cannot be repaired by a new assessment append."
                )
            committed = self._audit.append_and_enqueue_targeted(
                event,
                expected_predecessor_hash=head.content_hash if head else None,
                recorded_at=now,
                scope=scope,
                identity_winner=None,
                stream_head=head,
            )
            if (
                committed.event != event
                or self._audit.get_exact_outbox_winner_targeted(event) is None
            ):
                raise _blocked(
                    "Assessment append did not retain the exact required Audit/Outbox pair."
                )
            disposition = TaxAssessmentAppendDisposition.STORED
        return TaxAssessmentWriteReceipt(
            disposition,
            header.assessment_revision_id,
            header.semantic_sha256,
            header.observation_manifest_sha256,
        )


def build_audited_tax_assessment_use_case(
    *,
    scope_verifier: AuditedTaxAssessmentScopeVerifierPort | None,
    using: str,
    clock: TaxAssessmentClockPort | None = None,
    audit: TaxAssessmentAuditCoordinatorPort | None = None,
) -> CorporateActionTaxAssessmentUseCase:
    """Require a real current-scope implementation before exposing assessment writes.

    No default verifier, cash grant, staff reader or DTO creates tax authority.
    Live endpoint composition remains disabled until that provider is wired.
    """
    if not isinstance(scope_verifier, AuditedTaxAssessmentScopeVerifierPort):
        raise _blocked("A locked current tax-specific source/policy/owner verifier is required.")
    selected_clock = clock if clock is not None else _ServerClock()
    selected_audit = (
        audit if audit is not None else build_tax_assessment_audit_coordinator(using=using)
    )
    unit = DjangoTaxAssessmentAtomicUnitOfWork(
        using=using, scope_verifier=scope_verifier, audit=selected_audit, clock=selected_clock
    )
    return CorporateActionTaxAssessmentUseCase(
        scope_verifier=scope_verifier, unit_of_work=unit, clock=selected_clock, using=using
    )


__all__ = [
    "AuditedTaxAssessmentScopeVerifierPort",
    "DjangoTaxAssessmentAtomicUnitOfWork",
    "TaxAssessmentAuditOrigin",
    "build_audited_tax_assessment_use_case",
]
