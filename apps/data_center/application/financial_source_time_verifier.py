"""Read-only recomputation gate for retained financial source-time evidence."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from typing import Protocol, TypeGuard
from uuid import UUID

from apps.data_center.domain.entities import RawAudit, raw_audit_content_hash
from apps.data_center.domain.financial_response_artifact import FinancialResponseArtifactRef
from apps.data_center.domain.financial_source_evidence import FinancialFactDecisionEvidence
from apps.data_center.domain.financial_source_time_contract import FinancialSourceTimeMatchContract
from apps.data_center.domain.financial_source_time_evidence import (
    FinancialSourceTimeArtifactRef,
    FinancialSourceTimeWitness,
)

FINANCIAL_RESPONSE_AUDIT_CAPABILITY = "financial"
FINANCIAL_RESPONSE_AUDIT_PARSER_VERSION = "financial-response-artifact.v1"
FINANCIAL_SOURCE_TIME_AUDIT_CAPABILITY = "financial_source_time"

FinancialResponseBodyReader = Callable[[FinancialResponseArtifactRef], bytes | None]
FinancialSourceTimeBodyReader = Callable[[FinancialSourceTimeArtifactRef], bytes | None]


class FinancialSourceTimeAuditReader(Protocol):
    """Return every audit row linked to either immutable capture identity."""

    def list_financial(self, capture_id: UUID) -> Sequence[RawAudit]:
        """Return all successful financial-response rows for the capture."""

    def list_source_time(self, capture_id: UUID) -> Sequence[RawAudit]:
        """Return all financial-source-time rows for the capture."""


class FinancialSourceTimeContractReader(Protocol):
    """Resolve only an exact owner-approved provider contract identity."""

    def get(
        self,
        *,
        provider_name: str,
        contract_id: str,
        contract_version: str,
        contract_sha256: str,
    ) -> FinancialSourceTimeMatchContract | None:
        """Return the exact active contract or ``None``."""


class FinancialSourceTimeAuditLinkVerifier(Protocol):
    """Verify typed artifact metadata against one redacted audit link."""

    def verify_financial(
        self,
        audit: RawAudit,
        reference: FinancialResponseArtifactRef,
    ) -> int | None:
        """Return the bound provider row id, or ``None`` when invalid."""

    def verify_source_time(
        self,
        audit: RawAudit,
        reference: FinancialSourceTimeArtifactRef,
    ) -> int | None:
        """Return the bound provider row id, or ``None`` when invalid."""


class FinancialSourceTimeContractMatcher(Protocol):
    """Recompute one provider-specific match from both retained bodies."""

    def match(
        self,
        *,
        contract: FinancialSourceTimeMatchContract,
        financial_body: bytes,
        source_time_body: bytes,
        decision_evidence: FinancialFactDecisionEvidence,
    ) -> FinancialSourceTimeWitness | None:
        """Return the independently recomputed unique witness or ``None``."""


class FinancialSourceTimeEvidenceVerifier:
    """Require two retained bodies, exact audits, a contract, and a recomputed match."""

    def __init__(
        self,
        *,
        financial_body_reader: FinancialResponseBodyReader,
        source_time_body_reader: FinancialSourceTimeBodyReader,
        audit_reader: FinancialSourceTimeAuditReader,
        contract_reader: FinancialSourceTimeContractReader,
        audit_link_verifier: FinancialSourceTimeAuditLinkVerifier,
        matcher: FinancialSourceTimeContractMatcher,
    ) -> None:
        """Bind every read-only dependency explicitly."""

        self._financial_body_reader = financial_body_reader
        self._source_time_body_reader = source_time_body_reader
        self._audit_reader = audit_reader
        self._contract_reader = contract_reader
        self._audit_link_verifier = audit_link_verifier
        self._matcher = matcher

    def verify(self, decision_evidence: FinancialFactDecisionEvidence) -> bool:
        """Return true only after independently recomputing the complete evidence chain."""

        if not isinstance(decision_evidence, FinancialFactDecisionEvidence):
            return False
        witness = decision_evidence.source_time_witness
        if witness is None:
            return False
        financial_reference = decision_evidence.artifact_reference
        source_reference = witness.artifact_reference
        provider_name = financial_reference.evidence.request_scope.provider_name
        if (
            financial_reference.capture_id == source_reference.capture_id
            or source_reference.provider_name != provider_name
            or source_reference.requested_asset_code != decision_evidence.native_asset_code
            or source_reference.requested_announcement_date != witness.financial_announced_date
        ):
            return False
        contract = self._contract_reader.get(
            provider_name=provider_name,
            contract_id=witness.governed_match_contract_id,
            contract_version=witness.governed_match_contract_version,
            contract_sha256=witness.governed_match_contract_sha256,
        )
        if contract is None:
            return False
        financial_body = self._financial_body_reader(financial_reference)
        source_time_body = self._source_time_body_reader(source_reference)
        if not _body_matches(
            financial_body, financial_reference.body_sha256, financial_reference.body_size_bytes
        ):
            return False
        if not _body_matches(
            source_time_body, source_reference.body_sha256, source_reference.body_size_bytes
        ):
            return False
        financial_audit = _exact_audit(
            self._audit_reader.list_financial(financial_reference.capture_id)
        )
        source_time_audit = _exact_audit(
            self._audit_reader.list_source_time(source_reference.capture_id)
        )
        if financial_audit is None or source_time_audit is None:
            return False
        if not _audit_matches(
            financial_audit,
            capability=FINANCIAL_RESPONSE_AUDIT_CAPABILITY,
            provider_name=provider_name,
            row_count=financial_reference.evidence.response_scope.row_count,
            completed_at=financial_reference.evidence.response_completed_at,
            parser_version=FINANCIAL_RESPONSE_AUDIT_PARSER_VERSION,
            payload_size_bytes=financial_reference.body_size_bytes,
        ):
            return False
        if not _audit_matches(
            source_time_audit,
            capability=FINANCIAL_SOURCE_TIME_AUDIT_CAPABILITY,
            provider_name=provider_name,
            row_count=source_reference.response_row_count,
            completed_at=source_reference.response_completed_at,
            parser_version=contract.parser_version,
            payload_size_bytes=source_reference.body_size_bytes,
        ):
            return False
        financial_provider_id = self._audit_link_verifier.verify_financial(
            financial_audit, financial_reference
        )
        source_time_provider_id = self._audit_link_verifier.verify_source_time(
            source_time_audit, source_reference
        )
        if (
            financial_provider_id is None
            or source_time_provider_id is None
            or financial_provider_id != source_time_provider_id
        ):
            return False
        recomputed = self._matcher.match(
            contract=contract,
            financial_body=financial_body,
            source_time_body=source_time_body,
            decision_evidence=decision_evidence,
        )
        return recomputed == witness

    def __call__(self, decision_evidence: FinancialFactDecisionEvidence) -> bool:
        """Support the existing canonical repository verifier callback."""

        return self.verify(decision_evidence)


def _body_matches(
    body: bytes | None,
    expected_sha256: str,
    expected_size: int,
) -> TypeGuard[bytes]:
    """Check exact retained bytes without decoding provider content."""

    return (
        type(body) is bytes
        and len(body) == expected_size
        and hashlib.sha256(body).hexdigest() == expected_sha256
    )


def _exact_audit(audits: Sequence[RawAudit]) -> RawAudit | None:
    """Return one content-bound audit; zero, duplicates, and drift fail closed."""

    if len(audits) != 1:
        return None
    audit = audits[0]
    if not isinstance(audit, RawAudit) or not audit.content_hash:
        return None
    return audit if audit.content_hash == raw_audit_content_hash(audit) else None


def _audit_matches(
    audit: RawAudit,
    *,
    capability: str,
    provider_name: str,
    row_count: int,
    completed_at: object,
    parser_version: str,
    payload_size_bytes: int,
) -> bool:
    """Require the immutable audit projection used by evidence verification."""

    return (
        audit.capability == capability
        and audit.provider_name == provider_name
        and audit.status == "ok"
        and audit.row_count == row_count
        and audit.fetched_at == completed_at
        and audit.parser_version == parser_version
        and audit.payload_size_bytes == payload_size_bytes
        and audit.redacted is True
        and audit.error_message == ""
    )


__all__ = [
    "FINANCIAL_RESPONSE_AUDIT_CAPABILITY",
    "FINANCIAL_RESPONSE_AUDIT_PARSER_VERSION",
    "FINANCIAL_SOURCE_TIME_AUDIT_CAPABILITY",
    "FinancialResponseBodyReader",
    "FinancialSourceTimeAuditLinkVerifier",
    "FinancialSourceTimeAuditReader",
    "FinancialSourceTimeBodyReader",
    "FinancialSourceTimeContractMatcher",
    "FinancialSourceTimeContractReader",
    "FinancialSourceTimeEvidenceVerifier",
]
