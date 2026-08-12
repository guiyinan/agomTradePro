"""Read-only Application facade for exact Research evidence lookups."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from apps.research.domain.evidence_contracts import (
    EvidenceEnvelope,
    EvidenceOperatorSpec,
    TrackRecordSnapshot,
)


class EvidenceReadRepository(Protocol):
    """Port for content-addressed point-in-time evidence reads."""

    def get_operator_spec(
        self,
        *,
        operator_id: str,
        operator_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> EvidenceOperatorSpec | None:
        """Return one exact Operator Spec knowable at ``as_of``."""

        ...

    def get_track_record(
        self,
        *,
        snapshot_id: str,
        snapshot_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> TrackRecordSnapshot | None:
        """Return one exact Track Record knowable at ``as_of``."""

        ...

    def get_envelope(
        self,
        *,
        output_owner: str,
        output_artifact_type: str,
        output_artifact_id: str,
        output_artifact_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> EvidenceEnvelope | None:
        """Return one exact output-version Envelope knowable at ``as_of``."""

        ...


class EvidenceReadFacade:
    """Expose exact evidence reads without leaking Infrastructure concerns."""

    __slots__ = ("_repository",)

    def __init__(self, repository: EvidenceReadRepository) -> None:
        self._repository = repository

    def get_operator_spec(
        self,
        *,
        operator_id: str,
        operator_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> EvidenceOperatorSpec | None:
        """Read one exact Operator Spec through the repository port."""

        return self._repository.get_operator_spec(
            operator_id=operator_id,
            operator_version=operator_version,
            expected_content_hash=expected_content_hash,
            as_of=as_of,
        )

    def get_track_record(
        self,
        *,
        snapshot_id: str,
        snapshot_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> TrackRecordSnapshot | None:
        """Read one exact Track Record through the repository port."""

        return self._repository.get_track_record(
            snapshot_id=snapshot_id,
            snapshot_version=snapshot_version,
            expected_content_hash=expected_content_hash,
            as_of=as_of,
        )

    def get_envelope(
        self,
        *,
        output_owner: str,
        output_artifact_type: str,
        output_artifact_id: str,
        output_artifact_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> EvidenceEnvelope | None:
        """Read one exact output-version Envelope through the repository port."""

        return self._repository.get_envelope(
            output_owner=output_owner,
            output_artifact_type=output_artifact_type,
            output_artifact_id=output_artifact_id,
            output_artifact_version=output_artifact_version,
            expected_content_hash=expected_content_hash,
            as_of=as_of,
        )


__all__ = ["EvidenceReadFacade", "EvidenceReadRepository"]
