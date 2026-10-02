"""Bulk resolver for candidate RawAudit identities and hash-bound source metadata."""

from __future__ import annotations

from apps.data_center.application.current_publication_staging import (
    CurrentPublicationStageRawAuditBinding,
)
from apps.data_center.domain.entities import raw_audit_content_hash
from apps.data_center.domain.raw_audit_manifest import (
    CandidateRawAuditManifestError,
    CandidateRawAuditReference,
    canonical_capability_for_publication_dataset,
    validate_raw_audit_source_type,
)

from .fact_and_operational_models import RawAuditModel
from .provider_state_repositories import RawAuditRepository


class DjangoCandidateRawAuditMetadataResolver:
    """Resolve a complete, exact RawAudit set with one bounded ORM query."""

    def resolve(
        self,
        bindings: tuple[CurrentPublicationStageRawAuditBinding, ...],
        *,
        dataset_key: str,
    ) -> tuple[CandidateRawAuditReference, ...]:
        """Validate persisted identity, outcome, capability, and explicit source type."""

        expected_capability = canonical_capability_for_publication_dataset(dataset_key)
        if expected_capability is None:
            raise CandidateRawAuditManifestError(
                "candidate RawAudit staging does not support this dataset"
            )
        if not bindings:
            raise CandidateRawAuditManifestError("candidate RawAudit references are required")
        requested_ids = tuple(
            _canonical_raw_audit_id(item.reference.raw_audit_id) for item in bindings
        )
        if len(requested_ids) != len(set(requested_ids)):
            raise CandidateRawAuditManifestError("candidate RawAudit identities must be unique")
        rows = list(RawAuditModel._default_manager.filter(pk__in=requested_ids).order_by("pk"))
        if len(rows) != len(requested_ids):
            raise CandidateRawAuditManifestError("one or more candidate RawAudit rows are missing")
        rows_by_id = {int(row.pk): row for row in rows}
        if rows_by_id.keys() != set(requested_ids):
            raise CandidateRawAuditManifestError("candidate RawAudit identities do not match")

        resolved: list[CandidateRawAuditReference] = []
        for binding, raw_audit_id in zip(bindings, requested_ids, strict=True):
            row = rows_by_id[raw_audit_id]
            audit = RawAuditRepository._from_model(row)
            reference = binding.reference
            if (
                audit.raw_audit_id != reference.raw_audit_id
                or not audit.content_hash
                or audit.content_hash != reference.content_hash
                or raw_audit_content_hash(audit) != reference.content_hash
                or not audit.run_id
                or audit.run_id != reference.run_id
                or not audit.ingested_run_id
                or audit.ingested_run_id != reference.ingested_run_id
            ):
                raise CandidateRawAuditManifestError(
                    f"RawAudit row {reference.raw_audit_id} identity or content hash changed"
                )
            if row.status != "ok" or row.row_count <= 0:
                raise CandidateRawAuditManifestError(
                    "candidate RawAudit sources must be successful and non-empty"
                )
            if row.capability != expected_capability:
                raise CandidateRawAuditManifestError(
                    "candidate RawAudit capability does not match its dataset"
                )
            _require_source_type(row, binding.expected_source_type)
            resolved.append(
                CandidateRawAuditReference(
                    raw_audit_id=str(row.pk),
                    version=reference.version,
                    content_hash=reference.content_hash,
                    provider_name=row.provider_name,
                    capability=row.capability,
                    run_id=str(row.run_id),
                    ingested_run_id=str(row.ingested_run_id),
                )
            )
        return tuple(resolved)


def _canonical_raw_audit_id(value: str) -> int:
    """Parse one canonical positive RawAudit primary key."""

    if (
        not value
        or not value.isascii()
        or not value.isdecimal()
        or value.startswith("0")
        or str(int(value)) != value
    ):
        raise CandidateRawAuditManifestError("raw_audit_id must be canonical positive decimal text")
    return int(value)


def _require_source_type(row: RawAuditModel, expected_source_type: str) -> str:
    """Read and match the explicit source type stored in hash-bound audit metadata."""

    extra = row.extra
    if not isinstance(extra, dict):
        raise CandidateRawAuditManifestError("RawAudit source metadata is missing")
    source_type_value: object = extra.get("source_type")
    if not isinstance(source_type_value, str):
        raise CandidateRawAuditManifestError("RawAudit source_type metadata is missing")
    try:
        source_type = validate_raw_audit_source_type(source_type_value)
    except CandidateRawAuditManifestError as error:
        raise CandidateRawAuditManifestError(
            "RawAudit source_type metadata is missing or invalid"
        ) from error
    if source_type != expected_source_type:
        raise CandidateRawAuditManifestError(
            "RawAudit source_type does not match the stage request"
        )
    return source_type


__all__ = ["DjangoCandidateRawAuditMetadataResolver"]
