"""Atomic publication and manifest-audit writes for a validated activation group."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from apps.data_center.application.publication_activation import (
    PublicationActivationError,
    PublicationActivationGroupAuditWriter,
    PublicationActivationGroupRequest,
)
from apps.data_center.domain.control_plane import (
    CanonicalPublication,
    PublicationMember,
    PublicationState,
)
from apps.data_center.domain.raw_audit_manifest import CandidateRawAuditManifest
from core.integration.data_center_audit import (
    AuditOutcome,
    DataPublicationManifestAuditObservation,
    SystemAuditEventOutboxCommit,
)

from .publication_models import CanonicalPublicationModel, CanonicalPublicationPointerModel


class PublicationGroupActivationStateWriter:
    """Switch validated pointers and require all manifest-bound audit writes."""

    def switch_group_publications(
        self,
        *,
        request: PublicationActivationGroupRequest,
        candidates_by_id: dict[str, CanonicalPublicationModel],
        pointers_by_scope: dict[tuple[str, str], CanonicalPublicationPointerModel],
        previous_by_id: dict[str, CanonicalPublicationModel],
        same_current_by_id: dict[str, bool],
        activation_at: datetime,
    ) -> None:
        """Apply the complete validated state transition in stable scope order."""

        for item in request.candidates:
            candidate_id = item.candidate_publication_id
            if same_current_by_id[candidate_id]:
                continue
            pointer = pointers_by_scope[(item.dataset_key, item.publication_key)]
            if pointer.publication_id is not None:
                previous = previous_by_id[str(pointer.publication_id)]
                previous.state = PublicationState.SUPERSEDED.value
                previous.superseded_at = activation_at
                previous.save(update_fields=("state", "superseded_at", "updated_at"))
            candidate = candidates_by_id[candidate_id]
            candidate.state = PublicationState.PUBLISHED.value
            candidate.published_at = activation_at
            candidate.superseded_at = None
            candidate.save(update_fields=("state", "published_at", "superseded_at", "updated_at"))
            self._compare_and_swap_pointer(
                pointer,
                publication_id=candidate.publication_id,
                publication_hash=candidate.publication_hash,
                activation_id=request.activation_id,
                updated_at=activation_at,
            )

    @staticmethod
    def _compare_and_swap_pointer(
        pointer: CanonicalPublicationPointerModel,
        *,
        publication_id: UUID,
        publication_hash: str,
        activation_id: str,
        updated_at: datetime,
    ) -> None:
        """Change a pointer only if all three observed identity fields still match."""

        updated = CanonicalPublicationPointerModel._default_manager.filter(
            pointer_id=pointer.pointer_id,
            publication_id=pointer.publication_id,
            publication_hash=pointer.publication_hash,
            activation_id=pointer.activation_id,
        ).update(
            publication_id=publication_id,
            publication_hash=publication_hash,
            activation_id=activation_id,
            updated_at=updated_at,
        )
        if updated != 1:
            raise PublicationActivationError("current publication pointer compare-and-swap failed")
        pointer.publication_id = publication_id
        pointer.publication_hash = publication_hash
        pointer.activation_id = activation_id

    @staticmethod
    def append_required_manifest_audit(
        *,
        request: PublicationActivationGroupRequest,
        audit_writer: PublicationActivationGroupAuditWriter,
        publication: CanonicalPublication,
        members: tuple[PublicationMember, ...],
        manifest: CandidateRawAuditManifest,
        observation: DataPublicationManifestAuditObservation,
    ) -> None:
        """Require one audit/outbox commit with the complete candidate manifest refs."""

        append_required = getattr(audit_writer, "append_manifest_required", None)
        if not callable(append_required):
            raise PublicationActivationError("required manifest audit/outbox writer is unavailable")
        commit = append_required(
            request=request,
            publication=publication,
            members=members,
            manifest=manifest,
            observation=observation,
        )
        if not isinstance(commit, SystemAuditEventOutboxCommit):
            raise PublicationActivationError(
                "required manifest audit/outbox writer returned an invalid commit"
            )
        event = commit.event
        expected_refs = (
            (
                "candidate_raw_audit_manifest",
                manifest.manifest_id,
                manifest.manifest_version,
                manifest.manifest_hash,
            ),
            *(
                ("raw_audit", item.raw_audit_id, item.version, item.content_hash)
                for item in manifest.raw_audits
            ),
            (
                "canonical_publication",
                publication.publication_id,
                publication.policy_version,
                publication.publication_hash,
            ),
        )
        actual_refs = tuple(
            (item.artifact_type, item.artifact_id, item.artifact_version, item.content_hash)
            for item in event.evidence_refs
        )
        if (
            event.event_type != "data.publication.published"
            or event.outcome is not AuditOutcome.PUBLISHED
            or event.publication_id != publication.publication_id
            or event.dataset_key != publication.dataset_key
            or event.recorded_at != observation.recorded_at
            or event.correlations.run_id != publication.run_id
            or event.scope != observation.scope
            or actual_refs != expected_refs
        ):
            raise PublicationActivationError(
                "required manifest audit event does not match the activated candidate"
            )


__all__ = ["PublicationGroupActivationStateWriter"]
