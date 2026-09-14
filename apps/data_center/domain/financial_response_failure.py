"""Typed identity for a captured financial response rejected by its provider."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from apps.data_center.domain.financial_response_artifact import FinancialResponseArtifact
from apps.data_center.domain.financial_response_evidence import FinancialResponseEvidence

FINANCIAL_RESPONSE_FAILURE_CAPABILITY = "financial_response_failure"
FINANCIAL_RESPONSE_FAILURE_LINK_KEY = "financial_response_failure_artifact"
FINANCIAL_RESPONSE_FAILURE_LINK_SCHEMA = "financial-response-failure-link.v1"
FINANCIAL_RESPONSE_FAILURE_PARSER_VERSION = "financial-response-failure.v1"
FINANCIAL_RESPONSE_FAILURE_STATUS = "error"


@dataclass(frozen=True, slots=True)
class FinancialResponseFailure:
    """Pair exact captured bytes with one stable business rejection code."""

    capture_id: UUID
    evidence: FinancialResponseEvidence
    body: bytes = field(repr=False)
    failure_code: str

    def __post_init__(self) -> None:
        """Require the same exact-byte identity as the encrypted body artifact."""

        if not isinstance(self.capture_id, UUID):
            raise ValueError("FinancialResponseFailure.capture_id must be a UUID")
        if not isinstance(self.evidence, FinancialResponseEvidence):
            raise ValueError("FinancialResponseFailure.evidence must be typed")
        if type(self.body) is not bytes:
            raise ValueError("FinancialResponseFailure.body must be bytes")
        if (
            not isinstance(self.failure_code, str)
            or not self.failure_code
            or self.failure_code != self.failure_code.strip()
            or len(self.failure_code) > 64
        ):
            raise ValueError("FinancialResponseFailure.failure_code is invalid")
        if any(
            character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
            for character in self.failure_code
        ):
            raise ValueError("FinancialResponseFailure.failure_code is invalid")
        self.as_artifact()

    def as_artifact(self) -> FinancialResponseArtifact:
        """Project the captured bytes into the existing encrypted body-store type."""

        return FinancialResponseArtifact(
            capture_id=self.capture_id,
            evidence=self.evidence,
            body=self.body,
        )


__all__ = [
    "FINANCIAL_RESPONSE_FAILURE_CAPABILITY",
    "FINANCIAL_RESPONSE_FAILURE_LINK_KEY",
    "FINANCIAL_RESPONSE_FAILURE_LINK_SCHEMA",
    "FINANCIAL_RESPONSE_FAILURE_PARSER_VERSION",
    "FINANCIAL_RESPONSE_FAILURE_STATUS",
    "FinancialResponseFailure",
]
