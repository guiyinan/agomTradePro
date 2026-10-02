"""Atomic publication and manifest-audit writes for a validated activation group."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from django.db.models import Case, Q, Value, When

from apps.data_center.application.publication_activation import (
    PublicationActivationError,
    PublicationActivationGroupAuditWriter,
    PublicationActivationGroupRequest,
    PublicationActivationManifestAuditWrite,
)
from apps.data_center.domain.control_plane import PublicationState
from core.integration.data_center_audit import (
    AuditOutcome,
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

        publication_rows: list[CanonicalPublicationModel] = []
        pointer_transitions: list[tuple[CanonicalPublicationPointerModel, UUID, str]] = []
        for item in request.candidates:
            candidate_id = item.candidate_publication_id
            if same_current_by_id[candidate_id]:
                continue
            pointer = pointers_by_scope[(item.dataset_key, item.publication_key)]
            if pointer.publication_id is not None:
                previous = previous_by_id[str(pointer.publication_id)]
                previous.state = PublicationState.SUPERSEDED.value
                previous.superseded_at = activation_at
                previous.updated_at = activation_at
                publication_rows.append(previous)
            candidate = candidates_by_id[candidate_id]
            candidate.state = PublicationState.PUBLISHED.value
            candidate.published_at = activation_at
            candidate.superseded_at = None
            candidate.updated_at = activation_at
            publication_rows.append(candidate)
            pointer_transitions.append(
                (pointer, candidate.publication_id, candidate.publication_hash)
            )
        if publication_rows:
            CanonicalPublicationModel._default_manager.bulk_update(
                publication_rows,
                fields=("state", "published_at", "superseded_at", "updated_at"),
            )
        self._compare_and_swap_pointers(
            pointer_transitions,
            activation_id=request.activation_id,
            updated_at=activation_at,
        )

    @staticmethod
    def _compare_and_swap_pointers(
        transitions: list[tuple[CanonicalPublicationPointerModel, UUID, str]],
        *,
        activation_id: str,
        updated_at: datetime,
    ) -> None:
        """Change all locked pointers in one exact observed-identity CAS statement."""

        if not transitions:
            return
        predicate = Q()
        publication_cases: list[When] = []
        hash_cases: list[When] = []
        for pointer, publication_id, publication_hash in transitions:
            predicate |= Q(
                pointer_id=pointer.pointer_id,
                publication_id=pointer.publication_id,
                publication_hash=pointer.publication_hash,
                activation_id=pointer.activation_id,
            )
            publication_cases.append(
                When(pointer_id=pointer.pointer_id, then=Value(publication_id))
            )
            hash_cases.append(When(pointer_id=pointer.pointer_id, then=Value(publication_hash)))
        updated = CanonicalPublicationPointerModel._default_manager.filter(predicate).update(
            publication_id=Case(
                *publication_cases,
                output_field=CanonicalPublicationPointerModel._meta.get_field("publication_id"),
            ),
            publication_hash=Case(
                *hash_cases,
                output_field=CanonicalPublicationPointerModel._meta.get_field("publication_hash"),
            ),
            activation_id=activation_id,
            updated_at=updated_at,
        )
        if updated != len(transitions):
            raise PublicationActivationError("current publication pointer compare-and-swap failed")
        for pointer, publication_id, publication_hash in transitions:
            pointer.publication_id = publication_id
            pointer.publication_hash = publication_hash
            pointer.activation_id = activation_id

    @staticmethod
    def append_required_manifest_group_audit(
        *,
        request: PublicationActivationGroupRequest,
        audit_writer: PublicationActivationGroupAuditWriter,
        writes: tuple[PublicationActivationManifestAuditWrite, ...],
    ) -> None:
        """Require one atomic batch of manifest-bound audit/outbox commits."""

        append_required = getattr(audit_writer, "append_manifest_group_required", None)
        if not callable(append_required):
            raise PublicationActivationError("required manifest audit/outbox writer is unavailable")
        commits = append_required(
            request=request,
            writes=writes,
        )
        if (
            not isinstance(commits, tuple)
            or len(commits) != len(writes)
            or any(not isinstance(commit, SystemAuditEventOutboxCommit) for commit in commits)
        ):
            raise PublicationActivationError(
                "required manifest audit/outbox writer returned an invalid commit"
            )
        for write, commit in zip(writes, commits, strict=True):
            publication = write.publication
            manifest = write.manifest
            observation = write.observation
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
