"""Bind retained assessment Audit window material to immutable header columns."""

from apps.audit.domain.system_audit_event import SystemAuditEvent
from apps.simulated_trading.application.corporate_action_tax_window_proof import (
    CorporateActionTaxWindowProof,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_assessment_models import (
    CorporateActionTaxAssessmentHeaderModel,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_window_codec import (
    decode_corporate_action_tax_window_proof,
)
from core.exceptions import BusinessLogicError


def assert_tax_assessment_window_header(
    proof: CorporateActionTaxWindowProof, header: CorporateActionTaxAssessmentHeaderModel
) -> None:
    """Verify original source selectors and expiry without loading current sources."""
    proof.assert_recorded_at(header.recorded_at)
    source = proof.source_reference
    if (
        proof.assessment_semantic_sha256 != header.semantic_sha256
        or source.account_id != header.account_id
        or source.owner_user_id != header.owner_user_id
        or source.asset_code != header.asset_code
        or source.security_id != header.security_id
        or source.source_namespace != header.source_namespace
        or source.source_record_id != header.source_record_id
        or source.source_event_id != header.source_event_id
        or source.source_revision_id != header.action_source_revision_id
        or source.source_payload_sha256 != header.action_source_payload_sha256
        or source.record_date != header.record_date
        or proof.evidence.selected_event_sha256 != header.action_source_revision_sha256
    ):
        raise BusinessLogicError(
            "税务评估原始窗口与来源不一致。", code="TAX_CURRENT_OFFICIAL_WINDOW_INVALID"
        )


def read_retained_tax_assessment_window_proof(
    header: CorporateActionTaxAssessmentHeaderModel, event: SystemAuditEvent
) -> CorporateActionTaxWindowProof | None:
    """Restore optional original material; absence preserves the original legacy bytes."""
    if "current_official_window" not in event.detail:
        return None
    proof = decode_corporate_action_tax_window_proof(event.detail["current_official_window"])
    assert_tax_assessment_window_header(proof, header)
    return proof
