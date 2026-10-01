"""Transactional persistence for immutable candidate RawAudit manifests."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from django.db import connections, transaction

from apps.data_center.application.candidate_raw_audit_manifest import (
    CandidateRawAuditManifestRepositoryProtocol,
)
from apps.data_center.domain.control_plane import PublicationState
from apps.data_center.domain.entities import raw_audit_content_hash
from apps.data_center.domain.raw_audit_manifest import (
    CandidateRawAuditManifest,
    CandidateRawAuditManifestError,
    CandidateRawAuditReference,
)

from .candidate_raw_audit_manifest_models import _allow_candidate_manifest_inserts
from .models import (
    CandidateRawAuditManifestMemberModel,
    CandidateRawAuditManifestModel,
    CanonicalPublicationModel,
    RawAuditModel,
)
from .provider_state_repositories import RawAuditRepository

_MEMBER_INSERT_BATCH_SIZE = 500


class DjangoCandidateRawAuditManifestRepository(CandidateRawAuditManifestRepositoryProtocol):
    """Stage, read, and validate exact candidate-level multi-batch lineage."""

    def __init__(self, using: str = "default") -> None:
        """Bind repository queries to one configured database alias."""

        if using != "default":
            raise ValueError("candidate RawAudit manifests currently require the default database")
        self._using = using

    @transaction.atomic
    def stage(self, manifest: CandidateRawAuditManifest) -> CandidateRawAuditManifest:
        """Atomically persist one complete header and its sorted RawAudit children."""

        if not isinstance(manifest, CandidateRawAuditManifest):
            raise CandidateRawAuditManifestError("candidate manifest value is required")
        publication = self._load_publication(manifest.publication_id, lock=True)
        self._assert_publication_identity(publication, manifest, require_candidate=True)

        existing = (
            CandidateRawAuditManifestModel._default_manager.using(self._using)
            .select_for_update()
            .filter(publication_id=UUID(manifest.publication_id))
            .first()
        )
        if existing is not None:
            persisted = self._read_header_and_members(existing)
            if persisted.manifest_hash != manifest.manifest_hash:
                if persisted.task_attempt_id != manifest.task_attempt_id:
                    raise CandidateRawAuditManifestError(
                        "publication RawAudit manifest retry changed task-attempt identity"
                    )
                raise CandidateRawAuditManifestError(
                    "publication already has a different immutable RawAudit manifest"
                )
            return self._validate_locked(manifest.publication_id)

        self._verify_raw_audits(manifest, lock=True)
        header = CandidateRawAuditManifestModel(
            manifest_id=UUID(manifest.manifest_id),
            manifest_version=manifest.manifest_version,
            publication_id=UUID(manifest.publication_id),
            publication_hash=manifest.publication_hash,
            run_id=UUID(manifest.run_id),
            dataset_key=manifest.dataset_key,
            publication_key=manifest.publication_key,
            task_attempt_id=manifest.task_attempt_id,
            raw_audit_count=manifest.raw_audit_count,
            raw_audit_hash=manifest.raw_audit_hash,
            manifest_hash=manifest.manifest_hash,
        )
        members = [
            CandidateRawAuditManifestMemberModel(
                manifest_id=UUID(manifest.manifest_id),
                ordinal=ordinal,
                raw_audit_id=int(reference.raw_audit_id),
                raw_audit_version=reference.version,
                raw_audit_content_hash=reference.content_hash,
                provider_name=reference.provider_name,
                capability=reference.capability,
                run_id=UUID(reference.run_id),
                ingested_run_id=UUID(reference.ingested_run_id),
            )
            for ordinal, reference in enumerate(manifest.raw_audits)
        ]

        with _allow_candidate_manifest_inserts():
            CandidateRawAuditManifestModel._default_manager.using(self._using).bulk_create([header])
            self._insert_members(members)

        persisted = self._read_by_publication_id(manifest.publication_id)
        if persisted != manifest:
            raise CandidateRawAuditManifestError(
                "persisted candidate RawAudit manifest differs from staged evidence"
            )
        return self._validate_locked(manifest.publication_id)

    def _insert_members(
        self,
        members: list[CandidateRawAuditManifestMemberModel],
    ) -> None:
        """Bulk insert all ordered child references within the active stage transaction."""

        CandidateRawAuditManifestMemberModel._default_manager.using(self._using).bulk_create(
            members,
            batch_size=_MEMBER_INSERT_BATCH_SIZE,
        )

    def get_by_publication_id(self, publication_id: str) -> CandidateRawAuditManifest | None:
        """Read the exact header and all children for one publication UUID."""

        publication_uuid = _parse_uuid(publication_id, "publication_id")
        header = (
            CandidateRawAuditManifestModel._default_manager.using(self._using)
            .filter(publication_id=publication_uuid)
            .first()
        )
        return self._read_header_and_members(header) if header is not None else None

    @transaction.atomic
    def validate(self, publication_id: str) -> CandidateRawAuditManifest:
        """Re-read publication and every referenced RawAudit row, failing closed on drift."""

        return self._validate_locked(publication_id)

    def _validate_locked(self, publication_id: str) -> CandidateRawAuditManifest:
        """Validate a stored manifest inside the caller's transaction."""

        publication_uuid = _parse_uuid(publication_id, "publication_id")
        header = (
            CandidateRawAuditManifestModel._default_manager.using(self._using)
            .select_for_update()
            .filter(publication_id=publication_uuid)
            .first()
        )
        if header is None:
            raise CandidateRawAuditManifestError("candidate RawAudit manifest is missing")
        manifest = self._read_header_and_members(header)
        publication = self._load_publication(manifest.publication_id, lock=True)
        self._assert_publication_identity(publication, manifest, require_candidate=False)
        self._verify_raw_audits(manifest, lock=True)
        return manifest

    def _read_by_publication_id(self, publication_id: str) -> CandidateRawAuditManifest:
        """Re-read one complete header and member list after staging."""

        publication_uuid = _parse_uuid(publication_id, "publication_id")
        header = (
            CandidateRawAuditManifestModel._default_manager.using(self._using)
            .filter(publication_id=publication_uuid)
            .first()
        )
        if header is None:
            raise CandidateRawAuditManifestError("staged candidate manifest disappeared")
        return self._read_header_and_members(header)

    def _read_header_and_members(
        self,
        header: CandidateRawAuditManifestModel,
    ) -> CandidateRawAuditManifest:
        """Reconstruct the domain object with one ordered child query."""

        rows = list(
            CandidateRawAuditManifestMemberModel._default_manager.using(self._using)
            .filter(manifest_id=header.manifest_id)
            .order_by("ordinal", "pk")
        )
        references = tuple(
            CandidateRawAuditReference(
                raw_audit_id=str(row.raw_audit_id),
                version=row.raw_audit_version,
                content_hash=row.raw_audit_content_hash,
                provider_name=row.provider_name,
                capability=row.capability,
                run_id=str(row.run_id),
                ingested_run_id=str(row.ingested_run_id),
            )
            for row in rows
        )
        if tuple(row.ordinal for row in rows) != tuple(range(len(rows))):
            raise CandidateRawAuditManifestError(
                "candidate RawAudit manifest child ordinals are incomplete"
            )
        return CandidateRawAuditManifest(
            manifest_id=str(header.manifest_id),
            manifest_version=header.manifest_version,
            publication_id=str(header.publication_id),
            publication_hash=header.publication_hash,
            run_id=str(header.run_id),
            dataset_key=header.dataset_key,
            publication_key=header.publication_key,
            task_attempt_id=header.task_attempt_id,
            raw_audits=references,
            raw_audit_count=header.raw_audit_count,
            raw_audit_hash=header.raw_audit_hash,
            manifest_hash=header.manifest_hash,
        )

    def _load_publication(
        self,
        publication_id: str,
        *,
        lock: bool,
    ) -> CanonicalPublicationModel:
        """Read the exact publication row, optionally locking it for a write/validation."""

        query = CanonicalPublicationModel._default_manager.using(self._using)
        if lock:
            query = query.select_for_update()
        publication = query.filter(pk=_parse_uuid(publication_id, "publication_id")).first()
        if publication is None:
            raise CandidateRawAuditManifestError("bound publication candidate is missing")
        return publication

    @staticmethod
    def _assert_publication_identity(
        publication: CanonicalPublicationModel,
        manifest: CandidateRawAuditManifest,
        *,
        require_candidate: bool,
    ) -> None:
        """Require the manifest header to match its canonical publication identity."""

        if (
            str(publication.publication_id) != manifest.publication_id
            or publication.publication_hash != manifest.publication_hash
            or str(publication.run_id or "") != manifest.run_id
            or publication.dataset_key != manifest.dataset_key
            or publication.publication_key != manifest.publication_key
        ):
            raise CandidateRawAuditManifestError(
                "candidate manifest publication identity does not match"
            )
        if require_candidate and publication.state != PublicationState.CANDIDATE.value:
            raise CandidateRawAuditManifestError(
                "RawAudit manifests may only be staged for publication candidates"
            )

    def _verify_raw_audits(
        self,
        manifest: CandidateRawAuditManifest,
        *,
        lock: bool,
    ) -> None:
        """Bulk re-read exact RawAudit rows and verify all frozen identity fields and hashes."""

        references_by_id = {int(item.raw_audit_id): item for item in manifest.raw_audits}
        rows: list[RawAuditModel] = []
        for batch in _batches(tuple(references_by_id), self._query_batch_size()):
            query = RawAuditModel._default_manager.using(self._using).filter(pk__in=batch)
            if lock:
                query = query.select_for_update()
            rows.extend(query.order_by("pk"))
        if len(rows) != manifest.raw_audit_count:
            raise CandidateRawAuditManifestError("one or more referenced RawAudit rows are missing")

        rows_by_id = {int(row.pk): row for row in rows}
        if rows_by_id.keys() != references_by_id.keys():
            raise CandidateRawAuditManifestError("RawAudit reference identities do not match rows")
        for raw_audit_id, reference in references_by_id.items():
            row = rows_by_id[raw_audit_id]
            audit = RawAuditRepository._from_model(row)
            if row.status != "ok" or row.row_count <= 0:
                raise CandidateRawAuditManifestError(
                    "candidate RawAudit sources must be successful and non-empty"
                )
            if (
                row.content_hash != reference.content_hash
                or raw_audit_content_hash(audit) != reference.content_hash
                or row.provider_name != reference.provider_name
                or row.capability != reference.capability
                or str(row.run_id or "") != reference.run_id
                or str(row.ingested_run_id or "") != reference.ingested_run_id
            ):
                raise CandidateRawAuditManifestError(
                    f"RawAudit row {reference.raw_audit_id} no longer matches its manifest reference"
                )

    def _query_batch_size(self) -> int:
        """Use one bulk query where supported and respect SQLite parameter limits."""

        maximum = connections[self._using].features.max_query_params
        return max(1, maximum) if maximum is not None else 10_000


def _parse_uuid(value: str, field_name: str) -> UUID:
    """Parse one canonical UUID, returning a typed identity or a domain failure."""

    try:
        parsed = UUID(value)
    except (AttributeError, TypeError, ValueError) as exc:
        raise CandidateRawAuditManifestError(f"{field_name} must be a UUID string") from exc
    if str(parsed) != value:
        raise CandidateRawAuditManifestError(f"{field_name} must use canonical UUID form")
    return parsed


def _batches(values: Sequence[int], batch_size: int) -> tuple[tuple[int, ...], ...]:
    """Split a bounded reference identity list for database parameter limits."""

    return tuple(
        tuple(values[start : start + batch_size]) for start in range(0, len(values), batch_size)
    )


__all__ = ["DjangoCandidateRawAuditManifestRepository"]
