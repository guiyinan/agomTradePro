"""Compose nonfinancial assessment evidence with its exact atomic Audit/Outbox proof."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol, cast, runtime_checkable

from django.db import connections, transaction
from django.utils import timezone

from apps.audit.application.system_audit_event_outbox import ExactSystemAuditOutboxWinner
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
    TaxAssessmentExactReplayEvidence,
    TaxAssessmentWriteLease,
    TaxAssessmentWriteReceipt,
)
from apps.simulated_trading.application.corporate_action_tax_window_proof import (
    CorporateActionTaxWindowProof,
)
from apps.simulated_trading.corporate_action_tax_assessment_window_composition import (
    assert_tax_assessment_window_header,
    read_retained_tax_assessment_window_proof,
)
from apps.simulated_trading.domain.corporate_action_tax_assessment import (
    CorporateActionTaxAssessment,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_assessment_models import (
    CorporateActionTaxAssessmentHeaderModel as Header,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_assessment_repository import (
    DjangoCorporateActionTaxAssessmentRepository,
    StoredTaxAssessment,
    TaxAssessmentPersistedAuthority,
    canonical_json,
    material_sha256,
    read_material,
    recorded_id,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_window_codec import (
    encode_corporate_action_tax_window_proof,
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
    official_window_proof: CorporateActionTaxWindowProof | None = None
    write_mode: Literal["append", "exact_retry_only"] = "append"
    replay_evidence: TaxAssessmentExactReplayEvidence | None = None

    def __post_init__(self) -> None:
        """Require the exact typed lease, original grant seal and transactional policy."""
        if type(self.lease) is not TaxAssessmentWriteLease or type(self.scope) is not AuditScopeRef:
            raise _blocked("A typed locked tax authority and Audit scope are required.")
        self.lease.__post_init__()
        self.scope.__post_init__()
        if self.official_window_proof is not None:
            proof = self.official_window_proof
            proof.__post_init__()
            if (
                proof.source_reference.account_id != self.lease.account_id
                or proof.source_reference.owner_user_id != self.lease.owner_user_id
                or proof.source_reference.asset_code != self.lease.asset_code
                or proof.source_reference.security_id != self.lease.security_id
                or proof.source_reference.source_namespace != self.lease.action_source_namespace
                or proof.source_reference.source_record_id != self.lease.action_source_record_id
                or proof.source_reference.source_event_id != self.lease.action_source_event_id
                or proof.source_reference.source_revision_id != self.lease.action_source_revision_id
                or proof.source_reference.source_payload_sha256
                != self.lease.action_source_payload_sha256
                or proof.evidence.selected_event_sha256 != self.lease.action_source_revision_sha256
                or proof.source_reference.record_date != self.lease.record_date
                or proof.evidence.expires_at is None
                or (
                    self.write_mode == "append"
                    and self.lease.valid_until > proof.evidence.expires_at
                )
            ):
                raise _blocked("Assessment origin differs from its exact official window")
        if self.write_mode not in {"append", "exact_retry_only"}:
            raise _blocked("Assessment Audit origin has an unknown write mode")
        if self.write_mode == "append" and self.replay_evidence is not None:
            raise _blocked("An append origin cannot carry historical replay evidence")
        if self.write_mode == "exact_retry_only":
            evidence = self.replay_evidence
            if (
                type(evidence) is not TaxAssessmentExactReplayEvidence
                or self.official_window_proof is None
                or evidence.semantic_sha256 != self.official_window_proof.assessment_semantic_sha256
                or evidence.audit_scope != self.scope
                or evidence.official_window_proof != self.official_window_proof
            ):
                raise _blocked("Read-only retry origin lacks its exact retained original")
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


def _replay_evidence(
    header: Header,
    winner: SystemAuditEvent,
    outbox: ExactSystemAuditOutboxWinner,
    proof: CorporateActionTaxWindowProof | None,
) -> TaxAssessmentExactReplayEvidence:
    """Project locked originals into a typed marker that grants no write authority."""
    if outbox.event != winner:
        raise _blocked("Assessment replay Outbox does not contain its Audit winner")
    return TaxAssessmentExactReplayEvidence(
        assessment_revision_id=header.assessment_revision_id,
        idempotency_key=header.idempotency_key,
        semantic_sha256=header.semantic_sha256,
        observation_manifest_sha256=header.observation_manifest_sha256,
        recorded_at=header.recorded_at,
        audit_scope=AuditScopeRef(header.audit_tenant_id, header.audit_owner_id),
        audit_event_id=winner.event_id,
        audit_content_sha256=winner.content_hash,
        outbox_id=str(outbox.outbox_id),
        outbox_payload_sha256=outbox.payload_hash,
        official_window_proof=proof,
    )


def _build_event(
    header: Header,
    *,
    sequence_no: int,
    predecessor_hash: str | None,
    official_window_proof: CorporateActionTaxWindowProof | None = None,
) -> SystemAuditEvent:
    """Build only concise references to the complete retained professional evidence."""
    manifest = read_material(header.observation_manifest_json, header.observation_manifest_sha256)
    proof = manifest.get("ownership_proof")
    if type(proof) is not dict or type(proof.get("ownership_snapshot_observed_at")) is not str:
        raise _blocked("Original ownership observation material is incomplete.")
    observed_at = datetime.fromisoformat(proof["ownership_snapshot_observed_at"])
    if official_window_proof is not None:
        assert_tax_assessment_window_header(official_window_proof, header)
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
            **(
                {
                    "current_official_window": encode_corporate_action_tax_window_proof(
                        official_window_proof
                    )
                }
                if official_window_proof is not None
                else {}
            ),
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

    def find_exact_replay(
        self,
        assessment: CorporateActionTaxAssessment,
        *,
        actor_user_id: int,
        audit_scope: AuditScopeRef,
        as_of: datetime,
    ) -> TaxAssessmentExactReplayEvidence | None:
        """Verify the complete immutable header and Audit/Outbox lineage before retry."""
        if (
            not self._active
            or not connections[self._using].in_atomic_block
            or type(assessment) is not CorporateActionTaxAssessment
            or type(actor_user_id) is not int
            or actor_user_id <= 0
            or actor_user_id != assessment.owner_user_id
            or type(audit_scope) is not AuditScopeRef
            or type(as_of) is not datetime
            or as_of.tzinfo is None
            or as_of.utcoffset() is None
        ):
            raise _blocked("Exact assessment replay requires the active owner UOW")
        lineage = self._repository.read_locked_assessment_lineage(assessment)
        if not lineage:
            return None
        stream_id = _stream_id(lineage[-1])
        self._audit.lock_streams((stream_id,))
        previous: SystemAuditEvent | None = None
        retained: TaxAssessmentExactReplayEvidence | None = None
        for sequence_no, header in enumerate(lineage, start=1):
            if (
                (header.audit_tenant_id, header.audit_owner_id)
                != (audit_scope.tenant_id, audit_scope.owner_id)
                or _stream_id(header) != stream_id
                or header.recorded_at > as_of
            ):
                raise _blocked("The retained lineage differs from the current owner Audit scope")
            winner = self._audit.get_winner_targeted(
                event_id=_event_id(header), event_version="1", as_of=as_of, lock=True
            )
            if type(winner) is not SystemAuditEvent:
                raise _blocked("The assessment lineage has no original Audit winner")
            proof = read_retained_tax_assessment_window_proof(header, winner)
            expected = _build_event(
                header,
                sequence_no=sequence_no,
                predecessor_hash=None if previous is None else previous.content_hash,
                official_window_proof=proof,
            )
            outbox = self._audit.get_exact_outbox_winner_targeted(winner)
            if winner != expected or outbox is None or outbox.event != expected:
                raise _blocked(
                    "The original assessment Audit/Outbox lineage is incomplete or changed"
                )
            retained = _replay_evidence(header, winner, outbox, proof)
            previous = winner
        audit_head = self._audit.get_current_head_targeted(
            stream_id=stream_id,
            as_of=as_of,
            scope=audit_scope,
            lock=True,
        )
        if audit_head != previous:
            raise _blocked("The retained assessment lineage is not the current Audit head")
        if lineage[-1].semantic_sha256 != assessment.semantic_sha256:
            return None
        self._repository.verify_stored(lineage[-1], assessment)
        if retained is None or retained.official_window_proof is None:
            # Legacy material remains readable and can still pass through the
            # current qualifier, but it cannot stand in for a retained window
            # proof when deciding to skip that current-source check.
            return None
        return retained

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
        if origin.write_mode == "exact_retry_only":
            result = self._repository.find_exact_semantic_head(assessment)
            if type(result) is not StoredTaxAssessment or result.replayed is not True:
                raise _blocked("A read-only exact retry cannot append a new assessment header")
        else:
            authority = TaxAssessmentPersistedAuthority(
                origin.lease.authority_grant_id,
                origin.lease.authority_grant_version,
                origin.grant_content_sha256,
                origin.scope.tenant_id,
                origin.scope.owner_id,
            )
            result = self._repository.append_locked(
                assessment, authority=authority, recorded_at=now
            )
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
            proof = read_retained_tax_assessment_window_proof(header, winner)
            expected = _build_event(
                header,
                sequence_no=winner.sequence_no,
                predecessor_hash=winner.predecessor_hash,
                official_window_proof=proof,
            )
            outbox = self._audit.get_exact_outbox_winner_targeted(winner)
            audit_head = self._audit.get_current_head_targeted(
                stream_id=_stream_id(header),
                as_of=now,
                scope=origin.scope,
                lock=True,
            )
            if (
                winner != expected
                or audit_head != winner
                or outbox is None
                or outbox.event != expected
            ):
                raise _blocked(
                    "Original assessment Audit/Outbox evidence is incomplete or different."
                )
            replay_evidence = _replay_evidence(header, winner, outbox, proof)
            if (
                origin.write_mode == "exact_retry_only"
                and replay_evidence != origin.replay_evidence
            ):
                raise _blocked("The exact assessment replay changed after its locked preflight")
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
                official_window_proof=origin.official_window_proof,
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
