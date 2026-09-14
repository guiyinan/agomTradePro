"""Typed identity for one encrypted original financial response body.

The artifact deliberately models the transport observation separately from
``RawPayload`` and ``FinancialFact``.  Its digest always covers the exact
captured bytes; it does not attest to a provider row identifier, source
announcement time, or fact availability.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from apps.data_center.domain.financial_response_evidence import (
    FinancialResponseEvidence,
    raw_body_sha256,
)


@dataclass(frozen=True, slots=True)
class FinancialResponseArtifact:
    """Pair exact response bytes with their independently validated evidence."""

    capture_id: UUID
    evidence: FinancialResponseEvidence
    body: bytes = field(repr=False)

    def __post_init__(self) -> None:
        """Reject bytes whose digest or size does not match the evidence."""

        if not isinstance(self.capture_id, UUID):
            raise ValueError("FinancialResponseArtifact.capture_id must be a UUID")
        if not isinstance(self.evidence, FinancialResponseEvidence):
            raise ValueError("FinancialResponseArtifact.evidence must be typed")
        if type(self.body) is not bytes:
            raise ValueError("FinancialResponseArtifact.body must be bytes")
        if len(self.body) != self.evidence.body_size_bytes:
            raise ValueError("FinancialResponseArtifact.body_size_mismatch")
        if raw_body_sha256(self.body) != self.evidence.body_sha256:
            raise ValueError("FinancialResponseArtifact.body_hash_mismatch")

    def to_dict(self) -> dict[str, object]:
        """Return safe metadata without including the original body."""

        return {
            "capture_id": str(self.capture_id),
            **self.evidence.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class FinancialResponseArtifactRef:
    """Opaque reference to one immutable encrypted response artifact."""

    capture_id: UUID
    location: str
    evidence: FinancialResponseEvidence
    format_version: str
    encryption_algorithm: str
    encryption_key_ref: str
    encryption_key_version: str

    def __post_init__(self) -> None:
        """Validate reference metadata without making location assumptions."""

        if not isinstance(self.capture_id, UUID):
            raise ValueError("FinancialResponseArtifactRef.capture_id must be a UUID")
        _bounded_text(self.location, "location", 512)
        if not isinstance(self.evidence, FinancialResponseEvidence):
            raise ValueError("FinancialResponseArtifactRef.evidence must be typed")
        _bounded_text(self.format_version, "format_version", 128)
        _bounded_text(self.encryption_algorithm, "encryption_algorithm", 128)
        _bounded_text(self.encryption_key_ref, "encryption_key_ref", 256)
        _bounded_text(self.encryption_key_version, "encryption_key_version", 128)

    @property
    def body_sha256(self) -> str:
        """Return the digest of the exact body represented by this reference."""

        return self.evidence.body_sha256

    @property
    def body_size_bytes(self) -> int:
        """Return the exact byte count represented by this reference."""

        return self.evidence.body_size_bytes

    def to_dict(self) -> dict[str, object]:
        """Return non-secret reference metadata without body bytes."""

        return {
            "capture_id": str(self.capture_id),
            "location": self.location,
            "format_version": self.format_version,
            "encryption_algorithm": self.encryption_algorithm,
            "encryption_key_ref": self.encryption_key_ref,
            "encryption_key_version": self.encryption_key_version,
            **self.evidence.to_dict(),
        }


def _bounded_text(value: object, field_name: str, max_length: int) -> str:
    """Validate reference text without silently normalizing it."""

    if not isinstance(value, str) or not value:
        raise ValueError(f"FinancialResponseArtifactRef.{field_name} is required")
    if value != value.strip() or len(value) > max_length:
        raise ValueError(f"FinancialResponseArtifactRef.{field_name} is invalid")
    if any(ord(character) < 32 for character in value):
        raise ValueError(f"FinancialResponseArtifactRef.{field_name} contains control characters")
    return value


__all__ = ["FinancialResponseArtifact", "FinancialResponseArtifactRef"]
