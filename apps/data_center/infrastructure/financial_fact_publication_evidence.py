"""Qualification of persisted financial publication references."""

from __future__ import annotations

from apps.data_center.application.financial_numeric_qualification import (
    FinancialNumericVerificationPurpose,
)
from apps.data_center.application.financial_numeric_verification import (
    FinancialNumericEvidenceVerifier,
)
from apps.data_center.application.financial_v3_e1_verification import (
    FinancialV3FactEvidenceVerifier,
    FinancialV3FactVerificationRequest,
)
from apps.data_center.domain.control_plane import PublicationFactReference
from apps.data_center.domain.financial_source_evidence import FinancialFactDecisionEvidence
from apps.data_center.infrastructure.models import FinancialFactModel

from .financial_fact_hydration import financial_fact_from_model
from .financial_fact_publication_helpers import (
    _financial_publication_reference_impl,
    _require_publication_decision_evidence_impl,
)
from .financial_fact_write_guard import (
    FinancialFactProvenanceConflictError,
    FinancialSourceTimeEvidenceVerifier,
)


def _financial_publication_reference(
    row: FinancialFactModel,
    require_verified_source_evidence: bool = False,
    source_time_evidence_verifier: FinancialSourceTimeEvidenceVerifier | None = None,
    numeric_evidence_verifier: FinancialNumericEvidenceVerifier | None = None,
    v3_evidence_verifier: FinancialV3FactEvidenceVerifier | None = None,
    v3_verification_request: FinancialV3FactVerificationRequest | None = None,
) -> PublicationFactReference:
    """Convert one evidence-safe financial row to a publication reference."""
    decision = None
    if isinstance(row.decision_evidence, dict):
        decision = financial_fact_from_model(row).decision_evidence
    if decision is not None and decision.source_time_witness_v3 is not None:
        fact = financial_fact_from_model(row)
        if (
            v3_evidence_verifier is None
            or type(v3_verification_request) is not FinancialV3FactVerificationRequest
            or v3_verification_request.purpose
            is not FinancialNumericVerificationPurpose.CURRENT_PUBLICATION
            or not v3_evidence_verifier.verify(fact, v3_verification_request)
        ):
            raise FinancialFactProvenanceConflictError(
                "v3 financial publication requires current exact-body and temporal verification"
            )
        return _financial_publication_reference_impl(
            row,
            False,
            source_time_evidence_verifier,
            decision_evidence_checker=_require_v3_publication_decision_evidence,
        )
    if row.numeric_schema != "legacy-decimal-v1":
        fact = financial_fact_from_model(row)
        if numeric_evidence_verifier is None or not numeric_evidence_verifier(fact):
            raise FinancialFactProvenanceConflictError(
                "native financial publication requires independent catalog and body verification"
            )
    return _financial_publication_reference_impl(
        row,
        require_verified_source_evidence,
        source_time_evidence_verifier,
        decision_evidence_checker=_require_publication_decision_evidence,
    )


def _require_publication_decision_evidence(
    row: FinancialFactModel,
    source_time_evidence_verifier: FinancialSourceTimeEvidenceVerifier | None,
) -> FinancialFactDecisionEvidence:
    """Require the persisted artifact binding to match the exact candidate row."""
    return _require_publication_decision_evidence_impl(row, source_time_evidence_verifier)


def _require_v3_publication_decision_evidence(
    row: FinancialFactModel,
    source_time_evidence_verifier: FinancialSourceTimeEvidenceVerifier | None,
) -> FinancialFactDecisionEvidence:
    """Require a date-only v3 binding after its composite verifier succeeded."""

    decision = financial_fact_from_model(row).decision_evidence
    if (
        decision is None
        or decision.source_time_witness_v3 is None
        or row.announced_at is not None
        or row.available_at != decision.source_time_witness_v3.available_at
        or row.source_record_id != decision.native_row_id
        or row.raw_payload_hash != decision.artifact_reference.body_sha256
    ):
        raise FinancialFactProvenanceConflictError(
            "v3 publication row does not preserve its original date-only source binding"
        )
    return decision
