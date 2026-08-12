"""Compact Application DTO shared by decision-facing Evidence consumers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from apps.research.domain.evidence_contracts import (
    EvidenceEnvelope,
    EvidenceOperatorSpec,
    TrackRecordSnapshot,
)


class TrackRecordAvailability(str, Enum):
    """Stable UI-facing distinction between absence and an empty record."""

    NOT_REQUIRED = "not_required"
    UNAVAILABLE = "unavailable"
    EMPTY = "empty"
    AVAILABLE = "available"


@dataclass(frozen=True, slots=True)
class EvidenceSummaryDTO:
    """Compact immutable projection of one exact Evidence envelope."""

    output_owner: str
    output_artifact_type: str
    output_artifact_id: str
    output_artifact_version: str
    output_content_hash: str
    envelope_content_hash: str
    operator_spec_content_hash: str
    claim_kind: str
    method_kind: str
    research_family: str
    governance_state: str
    permission: str
    blocker_codes: tuple[str, ...]
    dependency_flags: tuple[str, ...]
    track_record_availability: str
    track_record_content_hash: str | None
    n_eff: str | None
    coverage: str | None
    evaluated_at: datetime
    valid_until: datetime
    must_not_use_for_decision: bool
    must_not_execute: bool

    @classmethod
    def from_evidence(
        cls,
        *,
        envelope: EvidenceEnvelope,
        operator_spec: EvidenceOperatorSpec,
        track_record: TrackRecordSnapshot | None,
    ) -> EvidenceSummaryDTO:
        """Build a summary only from an exact, internally consistent graph."""

        if envelope.operator_spec_ref != operator_spec.artifact_ref:
            raise ValueError("Evidence summary operator specification does not match envelope")
        availability = TrackRecordAvailability.NOT_REQUIRED
        track_record_hash: str | None = None
        n_eff: str | None = None
        coverage: str | None = None
        if track_record is None:
            if operator_spec.requires_track_record:
                availability = TrackRecordAvailability.UNAVAILABLE
            if envelope.track_record_ref is not None:
                raise ValueError("Evidence summary is missing the envelope Track Record")
        else:
            if envelope.track_record_ref != track_record.artifact_ref:
                raise ValueError("Evidence summary Track Record does not match envelope")
            if track_record.artifact != envelope.output_artifact:
                raise ValueError("Evidence summary Track Record targets a different output")
            availability = (
                TrackRecordAvailability.EMPTY
                if track_record.eligible == 0
                else TrackRecordAvailability.AVAILABLE
            )
            track_record_hash = track_record.content_hash
            n_eff = str(track_record.n_eff)
            coverage = str(track_record.coverage)

        output = envelope.output_artifact
        return cls(
            output_owner=output.owner,
            output_artifact_type=output.artifact_type,
            output_artifact_id=output.artifact_id,
            output_artifact_version=output.artifact_version,
            output_content_hash=output.content_hash,
            envelope_content_hash=envelope.content_hash,
            operator_spec_content_hash=operator_spec.content_hash,
            claim_kind=envelope.claim_kind.value,
            method_kind=envelope.method_kind.value,
            research_family=envelope.research_family,
            governance_state=envelope.governance_state.value,
            permission=envelope.permission.value,
            blocker_codes=tuple(item.value for item in envelope.blockers),
            dependency_flags=tuple(sorted(item.value for item in envelope.dependency_flags)),
            track_record_availability=availability.value,
            track_record_content_hash=track_record_hash,
            n_eff=n_eff,
            coverage=coverage,
            evaluated_at=envelope.evaluated_at,
            valid_until=envelope.valid_until,
            must_not_use_for_decision=envelope.must_not_use_for_decision,
            must_not_execute=envelope.must_not_execute,
        )


__all__ = ["EvidenceSummaryDTO", "TrackRecordAvailability"]
