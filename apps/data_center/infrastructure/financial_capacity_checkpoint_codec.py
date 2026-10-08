"""Strict JSON codec for durable financial capacity workflow state."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from typing import Literal, cast
from uuid import UUID

from apps.data_center.application.financial_publication_capacity import (
    FinancialCapacityActivationIntent,
    FinancialCapacityBinding,
    FinancialCapacityCheckpoint,
    FinancialCapacityPublicationPlan,
    FinancialCapacityReceipt,
    FinancialCapacitySliceEvidence,
    FinancialCapacityWorkflowError,
    FinancialPublicationSlice,
    FinancialWorkflowStage,
    FinancialWorkflowStatus,
    GovernedFinancialCapacityRehearsalCeiling,
    GovernedFinancialProductionCeiling,
    GovernedFinancialQualificationCeiling,
)


def _checkpoint_to_payload(checkpoint: FinancialCapacityCheckpoint) -> dict[str, object]:
    """Encode only bounded control-plane state; ledgers live in dedicated rows."""

    return {
        "schema": "financial-publication-capacity-checkpoint.v5",
        "workflow_id": checkpoint.workflow_id,
        "stage": checkpoint.stage,
        "binding": checkpoint.binding.to_dict(),
        "manifest_count": checkpoint.manifest_count,
        "manifest_sha256": checkpoint.manifest_sha256,
        "source_revision_sha256": checkpoint.source_revision_sha256,
        "total_provider_request_budget": checkpoint.total_provider_request_budget,
        "status": checkpoint.status,
        "next_slice_index": checkpoint.next_slice_index,
        "reserved_provider_requests": checkpoint.reserved_provider_requests,
        "observed_provider_requests": checkpoint.observed_provider_requests,
        "requested": checkpoint.requested,
        "succeeded": checkpoint.succeeded,
        "failed": checkpoint.failed,
        "stored": checkpoint.stored,
        "evidence_count": checkpoint.evidence_count,
        "evidence_sha256": checkpoint.evidence_sha256,
        "raw_body_count": checkpoint.raw_body_count,
        "raw_audit_count": checkpoint.raw_audit_count,
        "typed_evidence_count": checkpoint.typed_evidence_count,
        "atomic_fact_write_count": checkpoint.atomic_fact_write_count,
        "error_codes": list(checkpoint.error_codes),
        "started_at": checkpoint.started_at.isoformat(),
        "run_id": checkpoint.run_id,
        "finished_at": (
            checkpoint.finished_at.isoformat() if checkpoint.finished_at is not None else None
        ),
        "in_flight_slice_index": checkpoint.in_flight_slice_index,
        "in_flight_claim_token": checkpoint.in_flight_claim_token,
        "in_flight_claim_expires_at": (
            checkpoint.in_flight_claim_expires_at.isoformat()
            if checkpoint.in_flight_claim_expires_at is not None
            else None
        ),
        "capacity_receipt": (
            checkpoint.capacity_receipt.to_dict()
            if checkpoint.capacity_receipt is not None
            else None
        ),
        "qualification_ceiling": (
            _qualification_ceiling_to_payload(checkpoint.qualification_ceiling)
            if checkpoint.qualification_ceiling is not None
            else None
        ),
        "capacity_rehearsal_ceiling": (
            _capacity_rehearsal_ceiling_to_payload(checkpoint.capacity_rehearsal_ceiling)
            if checkpoint.capacity_rehearsal_ceiling is not None
            else None
        ),
        "governed_ceiling": (
            _ceiling_to_payload(checkpoint.governed_ceiling)
            if checkpoint.governed_ceiling is not None
            else None
        ),
        "activation_intent": (
            _activation_intent_to_payload(checkpoint.activation_intent)
            if checkpoint.activation_intent is not None
            else None
        ),
        "publication_plan": (
            _publication_plan_to_payload(checkpoint.publication_plan)
            if checkpoint.publication_plan is not None
            else None
        ),
        "publication_hash": checkpoint.publication_hash,
        "blocked_reason": checkpoint.blocked_reason,
        "revision": checkpoint.revision,
    }


def _activation_intent_to_payload(
    intent: FinancialCapacityActivationIntent,
) -> dict[str, object]:
    """Encode the exact durable pointer and RawAudit identities before candidate staging."""

    return {
        "run_id": str(intent.run_id),
        "activation_id": str(intent.activation_id),
        "expected_current_publication_id": intent.expected_current_publication_id,
        "expected_current_publication_hash": intent.expected_current_publication_hash,
        "financial_raw_audit_id": intent.financial_raw_audit_id,
        "financial_raw_audit_content_hash": intent.financial_raw_audit_content_hash,
        "ingested_run_id": str(intent.ingested_run_id),
        "provider_key": intent.provider_key,
        "occurred_at": intent.occurred_at.isoformat(),
    }


def _publication_plan_to_payload(
    plan: FinancialCapacityPublicationPlan,
) -> dict[str, object]:
    """Encode the exact staged candidate and member seal before activation."""

    return {
        "intent": _activation_intent_to_payload(plan.intent),
        "manifest_sha256": plan.manifest_sha256,
        "candidate_publication_id": plan.candidate_publication_id,
        "candidate_publication_hash": plan.candidate_publication_hash,
        "member_manifest_sha256": plan.member_manifest_sha256,
    }


def _activation_intent_from_payload(payload: object) -> FinancialCapacityActivationIntent:
    """Narrow a saved activation intent before it can control a pointer write."""

    raw = _mapping(payload, "activation intent")
    _exact_keys(
        raw,
        {
            "run_id",
            "activation_id",
            "expected_current_publication_id",
            "expected_current_publication_hash",
            "financial_raw_audit_id",
            "financial_raw_audit_content_hash",
            "ingested_run_id",
            "provider_key",
            "occurred_at",
        },
        "activation intent",
    )
    expected_id = raw.get("expected_current_publication_id")
    expected_hash = raw.get("expected_current_publication_hash")
    if expected_id is not None and type(expected_id) is not str:
        raise FinancialCapacityWorkflowError(
            "financial capacity expected publication ID is invalid"
        )
    if expected_hash is not None and type(expected_hash) is not str:
        raise FinancialCapacityWorkflowError(
            "financial capacity expected publication hash is invalid"
        )
    return FinancialCapacityActivationIntent(
        run_id=_uuid(raw, "run_id"),
        activation_id=_uuid(raw, "activation_id"),
        expected_current_publication_id=expected_id,
        expected_current_publication_hash=expected_hash,
        financial_raw_audit_id=_token(raw, "financial_raw_audit_id"),
        financial_raw_audit_content_hash=_token(raw, "financial_raw_audit_content_hash"),
        ingested_run_id=_uuid(raw, "ingested_run_id"),
        provider_key=_token(raw, "provider_key"),
        occurred_at=_datetime(raw, "occurred_at"),
    )


def _publication_plan_from_payload(payload: object) -> FinancialCapacityPublicationPlan:
    """Narrow a saved staged candidate plan before an activation replay."""

    raw = _mapping(payload, "publication plan")
    _exact_keys(
        raw,
        {
            "intent",
            "manifest_sha256",
            "candidate_publication_id",
            "candidate_publication_hash",
            "member_manifest_sha256",
        },
        "publication plan",
    )
    return FinancialCapacityPublicationPlan(
        intent=_activation_intent_from_payload(raw.get("intent")),
        manifest_sha256=_token(raw, "manifest_sha256"),
        candidate_publication_id=_token(raw, "candidate_publication_id"),
        candidate_publication_hash=_token(raw, "candidate_publication_hash"),
        member_manifest_sha256=_token(raw, "member_manifest_sha256"),
    )


def _checkpoint_from_payload(payload: object) -> FinancialCapacityCheckpoint:
    """Narrow stored JSON before it re-enters the application layer."""

    raw = _mapping(payload, "checkpoint")
    checkpoint_keys: set[str] = {
        "schema",
        "workflow_id",
        "stage",
        "binding",
        "manifest_count",
        "manifest_sha256",
        "source_revision_sha256",
        "total_provider_request_budget",
        "status",
        "next_slice_index",
        "reserved_provider_requests",
        "observed_provider_requests",
        "requested",
        "succeeded",
        "failed",
        "stored",
        "evidence_count",
        "evidence_sha256",
        "raw_body_count",
        "raw_audit_count",
        "typed_evidence_count",
        "atomic_fact_write_count",
        "error_codes",
        "started_at",
        "finished_at",
        "in_flight_slice_index",
        "capacity_receipt",
        "qualification_ceiling",
        "governed_ceiling",
        "publication_hash",
        "blocked_reason",
        "revision",
    }
    schema = raw.get("schema")
    if schema != "financial-publication-capacity-checkpoint.v5":
        raise FinancialCapacityWorkflowError("financial capacity checkpoint schema is invalid")
    _exact_keys(
        raw,
        checkpoint_keys
        | {
            "capacity_rehearsal_ceiling",
            "in_flight_claim_token",
            "in_flight_claim_expires_at",
            "run_id",
            "activation_intent",
            "publication_plan",
        },
        "checkpoint",
    )
    stage = _token(raw, "stage")
    allowed_stages = {"qualification", "capacity_rehearsal", "formal_publication"}
    if stage not in allowed_stages:
        raise FinancialCapacityWorkflowError("financial capacity checkpoint stage is invalid")
    status = _token(raw, "status")
    if status not in {"running", "success", "partial", "failed", "blocked"}:
        raise FinancialCapacityWorkflowError("financial capacity checkpoint status is invalid")
    raw_errors = _sequence(raw, "error_codes")
    if any(type(item) is not str for item in raw_errors):
        raise FinancialCapacityWorkflowError(
            "financial capacity checkpoint error codes are invalid"
        )
    raw_finished = raw.get("finished_at")
    raw_in_flight = raw.get("in_flight_slice_index")
    raw_claim_token = raw.get("in_flight_claim_token")
    raw_claim_expires_at = raw.get("in_flight_claim_expires_at")
    raw_run_id = raw.get("run_id")
    raw_publication_hash = raw.get("publication_hash")
    raw_blocked_reason = raw.get("blocked_reason")
    if raw_finished is not None and type(raw_finished) is not str:
        raise FinancialCapacityWorkflowError("financial capacity finish time is invalid")
    if raw_in_flight is not None and type(raw_in_flight) is not int:
        raise FinancialCapacityWorkflowError("financial capacity in-flight index is invalid")
    if raw_claim_token is not None and type(raw_claim_token) is not str:
        raise FinancialCapacityWorkflowError("financial capacity in-flight claim token is invalid")
    if raw_claim_expires_at is not None and type(raw_claim_expires_at) is not str:
        raise FinancialCapacityWorkflowError("financial capacity in-flight claim expiry is invalid")
    if raw_run_id is not None and type(raw_run_id) is not str:
        raise FinancialCapacityWorkflowError("financial capacity workflow run ID is invalid")
    claim_expires_at = (
        _parse_datetime(raw_claim_expires_at, "in_flight_claim_expires_at")
        if raw_claim_expires_at is not None
        else None
    )
    if raw_publication_hash is not None and type(raw_publication_hash) is not str:
        raise FinancialCapacityWorkflowError("financial capacity publication hash is invalid")
    if raw_blocked_reason is not None and type(raw_blocked_reason) is not str:
        raise FinancialCapacityWorkflowError("financial capacity blocked reason is invalid")
    receipt_payload = raw.get("capacity_receipt")
    qualification_ceiling_payload = raw.get("qualification_ceiling")
    capacity_rehearsal_ceiling_payload = raw.get("capacity_rehearsal_ceiling")
    ceiling_payload = raw.get("governed_ceiling")
    activation_intent_payload = raw.get("activation_intent")
    publication_plan_payload = raw.get("publication_plan")
    return FinancialCapacityCheckpoint(
        workflow_id=_token(raw, "workflow_id"),
        stage=cast(FinancialWorkflowStage, stage),
        binding=_binding_from_payload(raw.get("binding")),
        manifest=(),
        manifest_count=_int(raw, "manifest_count"),
        manifest_sha256=_token(raw, "manifest_sha256"),
        source_revision_sha256=_token(raw, "source_revision_sha256"),
        total_provider_request_budget=_int(raw, "total_provider_request_budget"),
        status=cast(FinancialWorkflowStatus, status),
        next_slice_index=_int(raw, "next_slice_index"),
        reserved_provider_requests=_int(raw, "reserved_provider_requests"),
        observed_provider_requests=_int(raw, "observed_provider_requests"),
        requested=_int(raw, "requested"),
        succeeded=_int(raw, "succeeded"),
        failed=_int(raw, "failed"),
        stored=_int(raw, "stored"),
        evidence=(),
        evidence_count=_int(raw, "evidence_count"),
        evidence_sha256=_token(raw, "evidence_sha256"),
        raw_body_count=_int(raw, "raw_body_count"),
        raw_audit_count=_int(raw, "raw_audit_count"),
        typed_evidence_count=_int(raw, "typed_evidence_count"),
        atomic_fact_write_count=_int(raw, "atomic_fact_write_count"),
        error_codes=tuple(cast(str, item) for item in raw_errors),
        started_at=_datetime(raw, "started_at"),
        run_id=raw_run_id,
        finished_at=(
            _parse_datetime(raw_finished, "finished_at") if raw_finished is not None else None
        ),
        in_flight_slice_index=raw_in_flight,
        in_flight_claim_token=raw_claim_token,
        in_flight_claim_expires_at=claim_expires_at,
        capacity_receipt=(
            _receipt_from_payload(receipt_payload) if receipt_payload is not None else None
        ),
        qualification_ceiling=(
            _qualification_ceiling_from_payload(qualification_ceiling_payload)
            if qualification_ceiling_payload is not None
            else None
        ),
        capacity_rehearsal_ceiling=(
            _capacity_rehearsal_ceiling_from_payload(capacity_rehearsal_ceiling_payload)
            if capacity_rehearsal_ceiling_payload is not None
            else None
        ),
        governed_ceiling=(
            _ceiling_from_payload(ceiling_payload) if ceiling_payload is not None else None
        ),
        activation_intent=(
            _activation_intent_from_payload(activation_intent_payload)
            if activation_intent_payload is not None
            else None
        ),
        publication_plan=(
            _publication_plan_from_payload(publication_plan_payload)
            if publication_plan_payload is not None
            else None
        ),
        publication_hash=(raw_publication_hash),
        blocked_reason=raw_blocked_reason,
        revision=_int(raw, "revision"),
    )


def _binding_from_payload(payload: object) -> FinancialCapacityBinding:
    """Decode the exact non-secret runtime identity snapshot."""

    raw = _mapping(payload, "binding")
    _exact_keys(
        raw,
        {
            "environment",
            "candidate_sha",
            "provider_id",
            "provider_name",
            "provider_source",
            "provider_identity_sha256",
            "contract_id",
            "contract_version",
            "contract_sha256",
            "parser_id",
            "parser_sha256",
            "deployment_region",
            "publication_policy_version",
            "publication_policy_sha256",
            "isolation_attestation_sha256",
        },
        "binding",
    )
    return FinancialCapacityBinding(
        environment=_token(raw, "environment"),
        candidate_sha=_token(raw, "candidate_sha"),
        provider_id=_int(raw, "provider_id"),
        provider_name=_token(raw, "provider_name"),
        provider_source=_token(raw, "provider_source"),
        provider_identity_sha256=_token(raw, "provider_identity_sha256"),
        contract_id=_token(raw, "contract_id"),
        contract_version=_token(raw, "contract_version"),
        contract_sha256=_token(raw, "contract_sha256"),
        parser_id=_token(raw, "parser_id"),
        parser_sha256=_token(raw, "parser_sha256"),
        deployment_region=_token(raw, "deployment_region"),
        publication_policy_version=_token(raw, "publication_policy_version"),
        publication_policy_sha256=_token(raw, "publication_policy_sha256"),
        isolation_attestation_sha256=_token(raw, "isolation_attestation_sha256"),
    )


def _slice_from_payload(payload: object) -> FinancialPublicationSlice:
    """Decode one exact dynamic manifest member."""

    raw = _mapping(payload, "manifest slice")
    _exact_keys(raw, {"asset_code", "announcement_date"}, "manifest slice")
    return FinancialPublicationSlice(
        asset_code=_token(raw, "asset_code"),
        announcement_date=_parse_date(_token(raw, "announcement_date"), "announcement_date"),
    )


def _evidence_from_payload(payload: object) -> FinancialCapacitySliceEvidence:
    """Decode one successful dual-capture and atomic-write evidence record."""

    raw = _mapping(payload, "slice evidence")
    fields = {
        "asset_code",
        "announcement_date",
        "financial_body_sha256",
        "source_time_body_sha256",
        "financial_body_size_bytes",
        "source_time_body_size_bytes",
        "financial_capture_id",
        "source_time_capture_id",
        "financial_raw_audit_id",
        "source_time_raw_audit_id",
        "financial_raw_audit_count",
        "source_time_raw_audit_count",
        "typed_financial_evidence_count",
        "source_time_witness_count",
        "atomic_fact_write_count",
        "stored",
        "duration_ms",
    }
    _exact_keys(raw, fields, "slice evidence")
    return FinancialCapacitySliceEvidence(
        asset_code=_token(raw, "asset_code"),
        announcement_date=_parse_date(_token(raw, "announcement_date"), "announcement_date"),
        financial_body_sha256=_token(raw, "financial_body_sha256"),
        source_time_body_sha256=_token(raw, "source_time_body_sha256"),
        financial_body_size_bytes=_int(raw, "financial_body_size_bytes"),
        source_time_body_size_bytes=_int(raw, "source_time_body_size_bytes"),
        financial_capture_id=_token(raw, "financial_capture_id"),
        source_time_capture_id=_token(raw, "source_time_capture_id"),
        financial_raw_audit_id=_token(raw, "financial_raw_audit_id"),
        source_time_raw_audit_id=_token(raw, "source_time_raw_audit_id"),
        financial_raw_audit_count=_int(raw, "financial_raw_audit_count"),
        source_time_raw_audit_count=_int(raw, "source_time_raw_audit_count"),
        typed_financial_evidence_count=_int(raw, "typed_financial_evidence_count"),
        source_time_witness_count=_int(raw, "source_time_witness_count"),
        atomic_fact_write_count=_int(raw, "atomic_fact_write_count"),
        stored=_int(raw, "stored"),
        duration_ms=_int(raw, "duration_ms"),
    )


def _receipt_from_payload(payload: object) -> FinancialCapacityReceipt:
    """Decode the compact v3 receipt seal without hydrating slice evidence."""

    raw = _mapping(payload, "capacity receipt")
    schema = _token(raw, "schema")
    fields = {
        "schema",
        "workflow_id",
        "binding",
        "manifest_count",
        "manifest_sha256",
        "source_revision_sha256",
        "evidence_count",
        "evidence_sha256",
        "outcome",
        "review_status",
        "total_provider_request_budget",
        "provider_requests",
        "reserved_provider_requests",
        "requested",
        "succeeded",
        "failed",
        "stored",
        "raw_body_count",
        "raw_audit_count",
        "typed_evidence_count",
        "atomic_fact_write_count",
        "duration_ms",
        "error_codes",
        "started_at",
        "finished_at",
        "stage",
        "approval_id",
    }
    if schema != "financial-publication-capacity-receipt.v3":
        raise FinancialCapacityWorkflowError("financial capacity receipt schema is invalid")
    _exact_keys(raw, fields, "capacity receipt")
    raw_stage = _token(raw, "stage")
    if raw_stage not in {"qualification", "capacity_rehearsal"}:
        raise FinancialCapacityWorkflowError("financial capacity receipt stage is invalid")
    stage = cast(FinancialWorkflowStage, raw_stage)
    approval_id = _token(raw, "approval_id")
    outcome = _token(raw, "outcome")
    if outcome not in {"running", "success", "partial", "failed", "blocked"}:
        raise FinancialCapacityWorkflowError("financial capacity receipt outcome is invalid")
    review_status = _token(raw, "review_status")
    if review_status not in {"pending_review", "not_eligible"}:
        raise FinancialCapacityWorkflowError("financial capacity receipt review status is invalid")
    errors = _sequence(raw, "error_codes")
    if any(type(item) is not str for item in errors):
        raise FinancialCapacityWorkflowError("financial capacity receipt error codes are invalid")
    return FinancialCapacityReceipt(
        workflow_id=_token(raw, "workflow_id"),
        stage=stage,
        approval_id=approval_id,
        binding=_binding_from_payload(raw.get("binding")),
        manifest_count=_int(raw, "manifest_count"),
        manifest_sha256=_token(raw, "manifest_sha256"),
        source_revision_sha256=_token(raw, "source_revision_sha256"),
        evidence_count=_int(raw, "evidence_count"),
        evidence_sha256=_token(raw, "evidence_sha256"),
        outcome=cast(FinancialWorkflowStatus, outcome),
        review_status=cast(Literal["pending_review", "not_eligible"], review_status),
        total_provider_request_budget=_int(raw, "total_provider_request_budget"),
        provider_requests=_int(raw, "provider_requests"),
        reserved_provider_requests=_int(raw, "reserved_provider_requests"),
        requested=_int(raw, "requested"),
        succeeded=_int(raw, "succeeded"),
        failed=_int(raw, "failed"),
        stored=_int(raw, "stored"),
        raw_body_count=_int(raw, "raw_body_count"),
        raw_audit_count=_int(raw, "raw_audit_count"),
        typed_evidence_count=_int(raw, "typed_evidence_count"),
        atomic_fact_write_count=_int(raw, "atomic_fact_write_count"),
        duration_ms=_int(raw, "duration_ms"),
        error_codes=tuple(cast(str, item) for item in errors),
        started_at=_datetime(raw, "started_at"),
        finished_at=_datetime(raw, "finished_at"),
        schema_version="v3",
    )


def _ceiling_to_payload(
    ceiling: GovernedFinancialProductionCeiling,
) -> dict[str, object]:
    """Encode one exact approval linked to the source receipt."""

    return {
        "approval_id": ceiling.approval_id,
        "approved_by": ceiling.approved_by,
        "approved_at": ceiling.approved_at.isoformat(),
        "approval_receipt_sha256": ceiling.approval_receipt_sha256,
        "receipt_sha256": ceiling.receipt_sha256,
        "binding": ceiling.binding.to_dict(),
        "manifest_sha256": ceiling.manifest_sha256,
        "maximum_slices": ceiling.maximum_slices,
        "maximum_provider_requests": ceiling.maximum_provider_requests,
        "expires_at": ceiling.expires_at.isoformat(),
        "approved": ceiling.approved,
    }


def _qualification_ceiling_to_payload(
    ceiling: GovernedFinancialQualificationCeiling,
) -> dict[str, object]:
    """Encode the exact reviewed qualification approval in its durable checkpoint."""

    return {
        "approval_id": ceiling.approval_id,
        "approved_by": ceiling.approved_by,
        "approved_at": ceiling.approved_at.isoformat(),
        "approval_receipt_sha256": ceiling.approval_receipt_sha256,
        "binding": ceiling.binding.to_dict(),
        "manifest_sha256": ceiling.manifest_sha256,
        "maximum_slices": ceiling.maximum_slices,
        "maximum_provider_requests": ceiling.maximum_provider_requests,
        "expires_at": ceiling.expires_at.isoformat(),
        "approved": ceiling.approved,
    }


def _qualification_ceiling_from_payload(
    payload: object,
) -> GovernedFinancialQualificationCeiling:
    """Decode the exact qualification approval attached to a checkpoint."""

    raw = _mapping(payload, "qualification ceiling")
    _exact_keys(
        raw,
        {
            "approval_id",
            "approved_by",
            "approved_at",
            "approval_receipt_sha256",
            "binding",
            "manifest_sha256",
            "maximum_slices",
            "maximum_provider_requests",
            "expires_at",
            "approved",
        },
        "qualification ceiling",
    )

    approved = raw.get("approved")
    if type(approved) is not bool:
        raise FinancialCapacityWorkflowError("qualification ceiling approval flag is invalid")
    return GovernedFinancialQualificationCeiling(
        approval_id=_token(raw, "approval_id"),
        approved_by=_token(raw, "approved_by"),
        approved_at=_datetime(raw, "approved_at"),
        approval_receipt_sha256=_token(raw, "approval_receipt_sha256"),
        binding=_binding_from_payload(raw.get("binding")),
        manifest_sha256=_token(raw, "manifest_sha256"),
        maximum_slices=_int(raw, "maximum_slices"),
        maximum_provider_requests=_int(raw, "maximum_provider_requests"),
        expires_at=_datetime(raw, "expires_at"),
        approved=approved,
    )


def _capacity_rehearsal_ceiling_to_payload(
    ceiling: GovernedFinancialCapacityRehearsalCeiling,
) -> dict[str, object]:
    """Encode the exact reviewed full-scope rehearsal approval."""

    return {
        "approval_id": ceiling.approval_id,
        "approved_by": ceiling.approved_by,
        "approved_at": ceiling.approved_at.isoformat(),
        "approval_receipt_sha256": ceiling.approval_receipt_sha256,
        "binding": ceiling.binding.to_dict(),
        "manifest_sha256": ceiling.manifest_sha256,
        "maximum_slices": ceiling.maximum_slices,
        "maximum_provider_requests": ceiling.maximum_provider_requests,
        "expires_at": ceiling.expires_at.isoformat(),
        "approved": ceiling.approved,
    }


def _capacity_rehearsal_ceiling_from_payload(
    payload: object,
) -> GovernedFinancialCapacityRehearsalCeiling:
    """Decode the exact rehearsal approval attached to a durable checkpoint."""

    raw = _mapping(payload, "capacity rehearsal ceiling")
    _exact_keys(
        raw,
        {
            "approval_id",
            "approved_by",
            "approved_at",
            "approval_receipt_sha256",
            "binding",
            "manifest_sha256",
            "maximum_slices",
            "maximum_provider_requests",
            "expires_at",
            "approved",
        },
        "capacity rehearsal ceiling",
    )
    approved = raw.get("approved")
    if type(approved) is not bool:
        raise FinancialCapacityWorkflowError("capacity rehearsal ceiling approval flag is invalid")
    return GovernedFinancialCapacityRehearsalCeiling(
        approval_id=_token(raw, "approval_id"),
        approved_by=_token(raw, "approved_by"),
        approved_at=_datetime(raw, "approved_at"),
        approval_receipt_sha256=_token(raw, "approval_receipt_sha256"),
        binding=_binding_from_payload(raw.get("binding")),
        manifest_sha256=_token(raw, "manifest_sha256"),
        maximum_slices=_int(raw, "maximum_slices"),
        maximum_provider_requests=_int(raw, "maximum_provider_requests"),
        expires_at=_datetime(raw, "expires_at"),
        approved=approved,
    )


def _ceiling_from_payload(payload: object) -> GovernedFinancialProductionCeiling:
    """Decode a governed approval attached to a formal checkpoint."""

    raw = _mapping(payload, "governed ceiling")
    _exact_keys(
        raw,
        {
            "approval_id",
            "approved_by",
            "approved_at",
            "approval_receipt_sha256",
            "receipt_sha256",
            "binding",
            "manifest_sha256",
            "maximum_slices",
            "maximum_provider_requests",
            "expires_at",
            "approved",
        },
        "governed ceiling",
    )
    approved = raw.get("approved")
    if type(approved) is not bool:
        raise FinancialCapacityWorkflowError("governed ceiling approval flag is invalid")
    return GovernedFinancialProductionCeiling(
        approval_id=_token(raw, "approval_id"),
        approved_by=_token(raw, "approved_by"),
        approved_at=_datetime(raw, "approved_at"),
        approval_receipt_sha256=_token(raw, "approval_receipt_sha256"),
        receipt_sha256=_token(raw, "receipt_sha256"),
        binding=_binding_from_payload(raw.get("binding")),
        manifest_sha256=_token(raw, "manifest_sha256"),
        maximum_slices=_int(raw, "maximum_slices"),
        maximum_provider_requests=_int(raw, "maximum_provider_requests"),
        expires_at=_datetime(raw, "expires_at"),
        approved=approved,
    )


def _mapping(payload: object, name: str) -> Mapping[str, object]:
    """Require a string-keyed JSON object."""

    if not isinstance(payload, Mapping) or any(type(key) is not str for key in payload):
        raise FinancialCapacityWorkflowError(f"financial capacity {name} is not an object")
    return cast(Mapping[str, object], payload)


def _exact_keys(
    payload: Mapping[str, object],
    keys: set[str],
    name: str,
) -> None:
    """Reject schema drift rather than silently dropping a persisted field."""

    if set(payload) != keys:
        raise FinancialCapacityWorkflowError(f"financial capacity {name} shape is invalid")


def _sequence(payload: Mapping[str, object], name: str) -> tuple[object, ...]:
    """Narrow one JSON array into an immutable sequence."""

    value = payload.get(name)
    if not isinstance(value, list):
        raise FinancialCapacityWorkflowError(f"financial capacity {name} is not an array")
    return tuple(value)


def _token(payload: Mapping[str, object], name: str) -> str:
    """Require one exact JSON string without whitespace coercion."""

    value = payload.get(name)
    if type(value) is not str:
        raise FinancialCapacityWorkflowError(f"financial capacity {name} is invalid")
    return value


def _uuid(payload: Mapping[str, object], name: str) -> UUID:
    """Parse one lowercase canonical UUID from durable JSON."""

    value = _token(payload, name)
    try:
        parsed = UUID(value)
    except (AttributeError, TypeError, ValueError) as exc:
        raise FinancialCapacityWorkflowError(f"financial capacity {name} is invalid") from exc
    if str(parsed) != value:
        raise FinancialCapacityWorkflowError(f"financial capacity {name} is invalid")
    return parsed


def _int(payload: Mapping[str, object], name: str) -> int:
    """Require an exact JSON integer without bool coercion."""

    value = payload.get(name)
    if type(value) is not int:
        raise FinancialCapacityWorkflowError(f"financial capacity {name} is invalid")
    return value


def _datetime(payload: Mapping[str, object], name: str) -> datetime:
    """Parse an aware timestamp from ISO-8601 JSON."""

    return _parse_datetime(_token(payload, name), name)


def _parse_datetime(value: str, name: str) -> datetime:
    """Require timezone-aware ISO-8601 datetime data."""

    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FinancialCapacityWorkflowError(f"financial capacity {name} is invalid") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise FinancialCapacityWorkflowError(f"financial capacity {name} must be timezone-aware")
    return result


def _parse_date(value: str, name: str) -> date:
    """Require an exact ISO calendar date."""

    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise FinancialCapacityWorkflowError(f"financial capacity {name} is invalid") from exc
