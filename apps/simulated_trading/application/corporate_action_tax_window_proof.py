"""Original complete official-window facts attached to a simulated tax qualification."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from apps.simulated_trading.application.corporate_action_current_official_window import (
    CorporateActionCurrentOfficialWindowEvidence,
)
from apps.simulated_trading.domain.corporate_action_posting import CorporateActionStageRequest
from apps.simulated_trading.domain.corporate_action_tax_assessment import (
    CorporateActionTaxAssessment,
)
from core.exceptions import BusinessLogicError


def _blocked() -> BusinessLogicError:
    return BusinessLogicError(
        "税务操作的原始官方窗口无法核对。", code="TAX_CURRENT_OFFICIAL_WINDOW_INVALID"
    )


@dataclass(frozen=True, slots=True)
class CorporateActionTaxWindowProof:
    """Retained source and finite window evidence; no independent financial permission."""

    assessment_semantic_sha256: str
    canonical_account_id: str
    source_reference: CorporateActionStageRequest
    evidence: CorporateActionCurrentOfficialWindowEvidence

    def __post_init__(self) -> None:
        """Bind every owner/source selector and its original ordered window clocks."""
        if (
            type(self.assessment_semantic_sha256) is not str
            or len(self.assessment_semantic_sha256) != 64
            or any(char not in "0123456789abcdef" for char in self.assessment_semantic_sha256)
            or type(self.canonical_account_id) is not str
            or not self.canonical_account_id
            or self.canonical_account_id != self.canonical_account_id.strip()
            or len(self.canonical_account_id) > 192
            or type(self.source_reference) is not CorporateActionStageRequest
            or type(self.evidence) is not CorporateActionCurrentOfficialWindowEvidence
        ):
            raise _blocked()
        request, evidence = self.source_reference, self.evidence
        request.__post_init__()
        evidence.__post_init__()
        if (
            evidence.window_ready is not True
            or evidence.account_id != request.account_id
            or evidence.owner_user_id != request.owner_user_id
            or evidence.asset_code != request.asset_code
            or evidence.security_id != request.security_id
            or evidence.source_record_id != request.source_record_id
            or evidence.source_revision_id != request.source_revision_id
            or evidence.source_payload_sha256 != request.source_payload_sha256
            or evidence.source_observed_at != request.source_observed_at
            or evidence.checked_at is None
            or evidence.expires_at is None
            or request.qualified_at > evidence.checked_at
            or request.posted_at > evidence.checked_at
        ):
            raise _blocked()

    def verify_for_assessment(
        self,
        assessment: CorporateActionTaxAssessment,
        *,
        canonical_account_id: str,
        environment: str,
    ) -> None:
        """Bind the original complete window to the exact assessment source revision."""
        self.__post_init__()
        assessment.verify_integrity()
        request, action = self.source_reference, assessment.action
        if (
            self.assessment_semantic_sha256 != assessment.semantic_sha256
            or self.canonical_account_id != canonical_account_id
            or self.evidence.runtime_environment != environment
            or request.account_id != assessment.account_id
            or request.owner_user_id != assessment.owner_user_id
            or request.asset_code != action.asset_code
            or request.security_id != action.security_id
            or request.source_namespace != action.source_namespace
            or request.source_event_id != action.source_event_id
            or request.source_record_id != action.source_record_id
            or request.source_revision_id != action.source_revision_id
            or request.source_payload_sha256 != action.source_payload_sha256
            or self.evidence.selected_event_sha256 != action.source_revision_sha256
        ):
            raise _blocked()

    def assert_recorded_at(self, recorded_at: datetime) -> None:
        """Validate historical retention at the original write clock without refreshing it."""
        self.__post_init__()
        checked, expires = self.evidence.checked_at, self.evidence.expires_at
        if (
            type(recorded_at) is not datetime
            or recorded_at.tzinfo is None
            or recorded_at.utcoffset() is None
            or checked is None
            or expires is None
            or not checked <= recorded_at < expires
        ):
            raise _blocked()
