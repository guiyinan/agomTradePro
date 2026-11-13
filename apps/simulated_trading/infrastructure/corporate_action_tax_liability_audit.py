"""Canonical original Audit events for a financial tax liability operation."""

from __future__ import annotations

import hashlib

from apps.audit.domain.system_audit_event import (
    AuditActorRef,
    AuditCategory,
    AuditCorrelations,
    AuditEvidenceRef,
    AuditOutcome,
    AuditResourceRef,
    AuditSeverity,
    AuditWritePolicy,
    SystemAuditEvent,
)
from apps.simulated_trading.application.corporate_action_tax_payment_basis import (
    SimulatedDividendPaymentBasis,
)
from apps.simulated_trading.domain.corporate_action_tax_liability import (
    TaxLiabilityOperationIdentity,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_liability_codec import (
    canonical_liability_json,
    tax_liability_scope_sha256,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_liability_evidence import (
    TaxLiabilityOperationMaterial,
    _decimal,
)

TAX_LIABILITY_EVENT_TYPE = "simulated.corporate_action.tax_liability_applied"


def tax_liability_operation_artifact_id(identity: TaxLiabilityOperationIdentity) -> str:
    """Identify the operation slot independently of changed intent or grant versions."""
    identity.verify_integrity()
    material = canonical_liability_json(
        {
            "account_id": identity.scope.account_id,
            "operation_id": identity.operation_id,
        }
    )
    return f"simulated-tax-operation:{hashlib.sha256(material.encode()).hexdigest()}"


def tax_liability_audit_stream_id(identity: TaxLiabilityOperationIdentity) -> str:
    """Keep each disposition's recognized debt, recoveries and corrections in one stream."""
    identity.verify_integrity()
    return f"simulated-tax-liability-stream:{tax_liability_scope_sha256(identity.scope)}"


def tax_payment_basis_artifact_id(basis: SimulatedDividendPaymentBasis) -> str:
    """Locate the exact original account payment behind a retained tax operation."""
    basis.__post_init__()
    return f"simulated-dividend-payment-basis:{basis.account_id}:{basis.payment_entry_id}"


def build_tax_liability_audit_event(
    material: TaxLiabilityOperationMaterial,
    *,
    predecessor_hash: str | None,
) -> SystemAuditEvent:
    """Build a stable event from original facts without refreshing any source clock."""
    material.__post_init__()
    identity = material.identity
    scope = identity.scope
    transition = material.transition
    state = transition.state_after
    lease = material.origin.lease
    artifact_id = tax_liability_operation_artifact_id(identity)
    noop = (
        transition.tax_due_delta == 0
        and transition.collected_delta == 0
        and transition.outstanding_delta == 0
    )
    if noop:
        reason = "tax_liability_noop"
    elif transition.cash_delta > 0:
        reason = "tax_liability_overcollection_refunded"
    elif transition.cash_delta < 0:
        reason = "tax_liability_collected"
    else:
        reason = "tax_liability_recognized"
    observed_at = (
        material.cash_snapshot.observed_at
        if material.cash_snapshot is not None
        else material.physical_updated_before
    )
    basis = material.origin.payment_basis
    payment_evidence = (
        ()
        if basis is None
        else (
            AuditEvidenceRef(
                "simulated_trading",
                "simulated_dividend_payment_basis",
                tax_payment_basis_artifact_id(basis),
                "v1",
                basis.content_sha256,
            ),
        )
    )
    return SystemAuditEvent.create(
        event_id=artifact_id,
        event_version="1",
        schema_version="system-audit-event.v1",
        category=AuditCategory.EXECUTION_CONTROL,
        event_type=TAX_LIABILITY_EVENT_TYPE,
        owner="simulated_trading",
        write_policy=AuditWritePolicy.TRANSACTIONAL_OUTBOX,
        outcome=AuditOutcome.NOOP if noop else AuditOutcome.SUCCESS,
        severity=AuditSeverity.INFO,
        reason_codes=(reason,),
        occurred_at=material.recorded_at,
        recorded_at=material.recorded_at,
        observed_at=observed_at,
        actor=AuditActorRef("service", lease.service_actor_id),
        source_app="simulated_trading",
        source_component="corporate_action_tax_liability",
        source_surface="application",
        correlations=AuditCorrelations(evidence_ref=material.content_sha256),
        resource=AuditResourceRef(
            "simulated_tax_liability_operation", artifact_id, material.content_sha256
        ),
        dataset_key=None,
        provider_key=None,
        capability=lease.permission,
        publication_id=None,
        evidence_refs=(
            AuditEvidenceRef(
                "simulated_trading",
                "tax_liability_operation",
                artifact_id,
                "v1" if basis is None else "v2",
                material.content_sha256,
            ),
            AuditEvidenceRef(
                "simulated_trading", "tax_liability_state", artifact_id, "v1", state.state_sha256
            ),
            AuditEvidenceRef(
                "simulated_trading",
                "tax_cash_journal",
                artifact_id,
                "v1",
                transition.transition_sha256,
            ),
            AuditEvidenceRef(
                "simulated_trading",
                "tax_assessment_semantics",
                str(material.assessment_id),
                "v1",
                identity.assessment_semantic_sha256,
            ),
            AuditEvidenceRef(
                "simulated_trading",
                "tax_assessment_observations",
                str(material.assessment_id),
                "v1",
                identity.stored_assessment_manifest_sha256,
            ),
            AuditEvidenceRef(
                "account",
                "simulated_corporate_action_write_grant",
                lease.authority_grant_id,
                lease.authority_grant_version,
                lease.authority_grant_content_sha256,
            ),
        )
        + payment_evidence,
        detail_schema=f"{TAX_LIABILITY_EVENT_TYPE}.v1",
        detail={
            "account_id": scope.account_id,
            "owner_user_id": scope.owner_user_id,
            "operation_id": identity.operation_id,
            "operation_request_sha256": identity.request_sha256,
            "asset_code": scope.asset_code,
            "security_id": scope.security_id,
            "corporate_action_id": scope.corporate_action_id,
            "source_event_id": scope.logical_source_event_id,
            "disposition_id": scope.target_disposition_id,
            "record_date": scope.record_date.isoformat(),
            "settlement_date": scope.target_settlement_date.isoformat(),
            "currency": identity.currency.value,
            "cash_action": None if identity.cash_action is None else identity.cash_action.value,
            "assessed_amount": _decimal(state.assessed_amount),
            "net_collected_amount": _decimal(state.net_collected_amount),
            "outstanding_amount": _decimal(state.outstanding_amount),
            "tax_due_delta": _decimal(transition.tax_due_delta),
            "collected_delta": _decimal(transition.collected_delta),
            "outstanding_delta": _decimal(transition.outstanding_delta),
            "cash_delta": _decimal(transition.cash_delta),
            "state_sha256": state.state_sha256,
            "transition_sha256": transition.transition_sha256,
            "operation_sha256": material.content_sha256,
            "qualification_id": material.origin.qualification.qualification_id,
            "qualification_sha256": material.origin.qualification.qualification_sha256,
            "grant_id": lease.authority_grant_id,
            "grant_version": lease.authority_grant_version,
            "simulated_account_only": True,
            "automatic_trade": False,
        },
        stream_id=tax_liability_audit_stream_id(identity),
        sequence_no=material.sequence,
        predecessor_hash=predecessor_hash,
        idempotency_key=f"{TAX_LIABILITY_EVENT_TYPE}:{artifact_id}",
        scope=material.origin.scope,
    )


__all__ = [
    "TAX_LIABILITY_EVENT_TYPE",
    "build_tax_liability_audit_event",
    "tax_liability_audit_stream_id",
    "tax_payment_basis_artifact_id",
    "tax_liability_operation_artifact_id",
]
