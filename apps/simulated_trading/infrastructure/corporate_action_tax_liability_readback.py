"""Verify original financial operations, their complete chain and Audit/Outbox.

Readback never reconstructs missing persisted evidence and never issues current
owner permission. Historical qualification clocks are retained unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.audit.corporate_action_tax_assessment_composition import TaxAssessmentAuditCoordinatorPort
from apps.audit.domain.system_audit_event import SystemAuditEvent
from apps.simulated_trading.application.corporate_action_tax_liability import (
    TaxLiabilityAppendDisposition,
    TaxLiabilityEvidenceReference,
    TaxLiabilityWriteReceipt,
    _blocked,
)
from apps.simulated_trading.domain.corporate_action_tax_liability import (
    TaxLiabilityOperationIdentity,
    TaxLiabilityScope,
)
from apps.simulated_trading.domain.simulated_dividend_tax_policy_scope import (
    SimulatedDividendTaxCurrency,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_assessment_models import (
    CorporateActionTaxAssessmentHeaderModel as Header,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_assessment_repository import (
    DjangoCorporateActionTaxAssessmentRepository,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_liability_audit import (
    build_tax_liability_audit_event,
    tax_liability_audit_stream_id,
    tax_liability_operation_artifact_id,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_liability_codec import (
    decode_liability_state,
    decode_liability_transition,
    tax_liability_scope_sha256,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_liability_evidence import (
    TaxLiabilityOperationMaterial,
    _decimal,
    decode_operation_material,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_liability_models import (
    CorporateActionTaxLiabilityOperationModel as Operation,
)


class RetainedTaxAssessmentAuditVerifierPort(Protocol):
    """Composition-owned verification of the assessment's exact original Audit pair."""

    def verify_original(self, header: Header, *, as_of: datetime) -> None:
        """Reject missing or different original assessment Audit/Outbox evidence."""


@dataclass(frozen=True, slots=True)
class VerifiedTaxLiabilityOperation:
    """One fully checked immutable operation and its original event references."""

    row: Operation
    material: TaxLiabilityOperationMaterial
    event: SystemAuditEvent
    receipt: TaxLiabilityWriteReceipt


class DjangoTaxLiabilityReadback:
    """Read exact ordered operations only within the caller's same-alias UOW."""

    def __init__(
        self,
        *,
        using: str,
        audit: TaxAssessmentAuditCoordinatorPort,
        assessment_audit: RetainedTaxAssessmentAuditVerifierPort,
    ) -> None:
        """Require the actual Audit coordinator and original-assessment verifier."""
        if audit.database_alias != using:
            raise _blocked("Financial readback and Audit must share a database alias")
        self._using = using
        self._audit = audit
        self._assessment_audit = assessment_audit
        self._assessments = DjangoCorporateActionTaxAssessmentRepository(using=using)

    def verify_assessment(self, header: Header, *, as_of: datetime) -> None:
        """Check original immutable header/allocations and its independent Audit pair."""
        self._assessments.verify_retained_integrity(header)
        self._assessment_audit.verify_original(header, as_of=as_of)

    def read_chain(
        self,
        *,
        scope: TaxLiabilityScope,
        canonical_account_namespace: str,
        canonical_account_id: str,
        currency: SimulatedDividendTaxCurrency,
        as_of: datetime,
    ) -> tuple[VerifiedTaxLiabilityOperation, ...]:
        """Verify every predecessor in one disposition; no gaps or alternate heads."""
        rows = tuple(
            Operation._default_manager.using(self._using)
            .select_for_update()
            .filter(account_id=scope.account_id, scope_sha256=tax_liability_scope_sha256(scope))
            .order_by("sequence")
        )
        result: list[VerifiedTaxLiabilityOperation] = []
        for sequence, row in enumerate(rows, 1):
            prior = result[-1] if result else None
            if (
                row.sequence != sequence
                or row.predecessor_id != (None if prior is None else prior.row.pk)
                or row.owner_user_id != scope.owner_user_id
                or row.canonical_account_namespace != canonical_account_namespace
                or row.canonical_account_id != canonical_account_id
                or row.currency != currency.value
                or row.recorded_at > as_of
            ):
                raise _blocked("Financial operation chain has a gap or different owner/currency")
            verified = self._verify_row(row, prior=prior, as_of=as_of)
            if verified.material.identity.scope != scope:
                raise _blocked("Financial operation scope differs from its stored selector")
            result.append(verified)
        return tuple(result)

    def _verify_row(
        self,
        row: Operation,
        *,
        prior: VerifiedTaxLiabilityOperation | None,
        as_of: datetime,
    ) -> VerifiedTaxLiabilityOperation:
        """Reconstruct exact stored components and independently verify all original pairs."""
        state = decode_liability_state(row.state_payload_json, row.state_sha256)
        transition = decode_liability_transition(
            row.transition_payload_json,
            row.transition_sha256,
            before_state=None if prior is None else prior.material.transition.state_after,
            state_after=state,
        )
        header = (
            Header._default_manager.using(self._using).select_for_update().get(pk=row.assessment_id)
        )
        self.verify_assessment(header, as_of=as_of)
        identity = TaxLiabilityOperationIdentity(
            operation_id=row.operation_id,
            scope=state.scope,
            canonical_account_namespace=row.canonical_account_namespace,
            canonical_account_id=row.canonical_account_id,
            currency=SimulatedDividendTaxCurrency(row.currency),
            assessment_revision_id=state.assessment_revision_id,
            supersedes_assessment_revision_id=state.supersedes_assessment_revision_id,
            assessment_semantic_sha256=state.assessment_semantic_sha256,
            stored_assessment_manifest_sha256=header.observation_manifest_sha256,
            cash_action=None if transition.cash_request is None else transition.cash_request.action,
        )
        material = decode_operation_material(
            row.operation_payload_json,
            row.operation_sha256,
            identity=identity,
            transition=transition,
        )
        scope = state.scope
        if (
            material.assessment_id != header.pk
            or row.assessment_id != header.pk
            or row.account_id != scope.account_id
            or row.owner_user_id != scope.owner_user_id
            or material.sequence != row.sequence
            or material.recorded_at != row.recorded_at
            or material.predecessor_operation_sha256
            != (None if prior is None else prior.row.operation_sha256)
            or row.operation_request_sha256 != identity.request_sha256
            or header.account_id != scope.account_id
            or header.owner_user_id != scope.owner_user_id
            or header.asset_code != scope.asset_code
            or header.security_id != scope.security_id
            or header.corporate_action_id != scope.corporate_action_id
            or header.source_namespace != scope.source_namespace
            or header.source_event_id != scope.logical_source_event_id
            or header.disposition_id != scope.target_disposition_id
            or header.record_date != scope.record_date
            or header.settlement_date != scope.target_settlement_date
            or header.assessment_revision_id != state.assessment_revision_id
            or header.semantic_sha256 != state.assessment_semantic_sha256
            or header.withholding_amount_text != _decimal(state.assessed_amount)
        ):
            raise _blocked("Financial journal differs from its original persisted assessment")
        expected_amounts = {
            "assessed_amount_text": state.assessed_amount,
            "net_collected_amount_text": state.net_collected_amount,
            "outstanding_amount_text": state.outstanding_amount,
            "tax_due_delta_text": transition.tax_due_delta,
            "collected_delta_text": transition.collected_delta,
            "outstanding_delta_text": transition.outstanding_delta,
            "cash_delta_text": transition.cash_delta,
        }
        if any(
            getattr(row, field) != _decimal(amount) for field, amount in expected_amounts.items()
        ):
            raise _blocked("Financial journal amount columns differ from sealed components")
        event = build_tax_liability_audit_event(
            material,
            predecessor_hash=None if prior is None else prior.event.content_hash,
        )
        self._audit.lock_streams((tax_liability_audit_stream_id(identity),))
        winner = self._audit.get_winner_targeted(
            event_id=event.event_id,
            event_version=event.event_version,
            as_of=as_of,
            lock=True,
        )
        outbox = self._audit.get_exact_outbox_winner_targeted(event)
        if (
            winner != event
            or outbox is None
            or outbox.event != event
            or row.audit_event_id != event.event_id
            or row.audit_event_version != event.event_version
            or row.audit_event_sha256 != event.content_hash
            or row.outbox_record_id != str(outbox.outbox_id)
            or row.outbox_payload_sha256 != outbox.payload_hash
        ):
            raise _blocked(
                "Original financial Audit/Outbox is missing or different; repair is forbidden"
            )
        artifact = tax_liability_operation_artifact_id(identity)
        receipt = TaxLiabilityWriteReceipt(
            disposition=TaxLiabilityAppendDisposition.STORED,
            operation_id=identity.operation_id,
            operation_request_sha256=identity.request_sha256,
            scope=scope,
            canonical_account_namespace=identity.canonical_account_namespace,
            canonical_account_id=identity.canonical_account_id,
            currency=identity.currency,
            currency_quantum=state.currency_quantum,
            cash_action=identity.cash_action,
            cash_snapshot_reference=(
                None if material.cash_snapshot is None else material.cash_snapshot.evidence
            ),
            assessment_revision_id=state.assessment_revision_id,
            assessment_semantic_sha256=state.assessment_semantic_sha256,
            assessment_observation_manifest_sha256=identity.stored_assessment_manifest_sha256,
            transition_sha256=transition.transition_sha256,
            state_after_sha256=state.state_sha256,
            tax_due_delta=transition.tax_due_delta,
            collected_delta=transition.collected_delta,
            outstanding_delta=transition.outstanding_delta,
            cash_delta=transition.cash_delta,
            liability_record=TaxLiabilityEvidenceReference(artifact, "v1", state.state_sha256),
            journal_entry=TaxLiabilityEvidenceReference(
                artifact, "v1", transition.transition_sha256
            ),
            audit_event=TaxLiabilityEvidenceReference(
                event.event_id, event.event_version, event.content_hash
            ),
            outbox_record=TaxLiabilityEvidenceReference(
                str(outbox.outbox_id), "v1", outbox.payload_hash
            ),
        )
        return VerifiedTaxLiabilityOperation(row, material, event, receipt)


__all__ = [
    "DjangoTaxLiabilityReadback",
    "RetainedTaxAssessmentAuditVerifierPort",
    "VerifiedTaxLiabilityOperation",
]
