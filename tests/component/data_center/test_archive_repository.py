"""Database evidence for exact archive coverage and candidate re-archival."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from apps.data_center.domain.raw_landing import RawPayload, raw_payload_record_digest
from apps.data_center.domain.retention import (
    ArchiveManifest,
    ArchiveMember,
    ArchiveRestoreAudit,
    ArchiveRestoreOutcome,
    ArchiveState,
)
from apps.data_center.infrastructure.archive_repositories import ArchiveCandidateRepository
from apps.data_center.infrastructure.models import RawPayloadModel
from apps.data_center.infrastructure.retention_repositories import ArchiveManifestRepository

NOW = datetime(2026, 8, 7, 6, 0, tzinfo=UTC)


def _payload(*, offset: int) -> RawPayload:
    return RawPayload(
        payload_id=str(uuid4()),
        dataset_key="market.raw",
        provider_name="fixture",
        payload_hash=f"sha256:payload-{uuid4()}-{offset}",
        schema_fingerprint="sha256:schema-v1",
        payload={"offset": offset},
        fetched_at=NOW - timedelta(days=30, minutes=offset),
        payload_size_bytes=128 + offset,
    )


def _member(payload: RawPayload) -> ArchiveMember:
    return ArchiveMember(
        payload_id=payload.payload_id,
        payload_hash=payload.payload_hash,
        record_digest=raw_payload_record_digest(payload),
        schema_fingerprint=payload.schema_fingerprint,
        fetched_at=payload.fetched_at,
        size_bytes=payload.payload_size_bytes,
    )


def _manifest(payload: RawPayload, *, retention_until: datetime) -> ArchiveManifest:
    return ArchiveManifest(
        archive_id=str(uuid4()),
        dataset_key=payload.dataset_key,
        object_count=1,
        size_bytes=512,
        location=f"archive:///raw/{payload.payload_id}.jsonl.gz",
        checksum=f"sha256:{uuid4().hex}",
        state=ArchiveState.EXPORTED,
        created_at=NOW - timedelta(days=1),
        retention_until=retention_until,
        contract_version="contract-v1",
        schema_version="schema-v1",
        format_version="raw-payload-fernet-jsonl-gzip-v1",
        encryption_algorithm="fernet-aes128cbc-hmacsha256",
        encryption_key_ref="config-center://archive/test-key",
        encryption_key_version="v1",
        coverage_started_at=payload.fetched_at,
        coverage_ended_at=payload.fetched_at,
    )


@pytest.mark.django_db
def test_exact_coverage_requires_verified_current_archive_and_successful_restore() -> None:
    payload = _payload(offset=1)
    repository = ArchiveManifestRepository()
    exported = repository.save_export(
        _manifest(payload, retention_until=NOW + timedelta(days=90)),
        (_member(payload),),
    )

    assert repository.find_covering_manifests(payload, now=NOW) == ()

    verified = repository.mark_verified(exported.archive_id, verified_at=NOW)
    repository.record_restore(
        ArchiveRestoreAudit(
            audit_id=str(uuid4()),
            operation_key=f"archive-restore:{exported.archive_id}:monthly-2026-08",
            archive_id=exported.archive_id,
            outcome=ArchiveRestoreOutcome.SUCCESS,
            observed_checksum=verified.checksum,
            observed_object_count=verified.object_count,
            observed_size_bytes=verified.size_bytes,
            restored_object_count=verified.object_count,
            restored_bytes=verified.size_bytes,
            started_at=NOW + timedelta(minutes=1),
            finished_at=NOW + timedelta(minutes=2),
            reason="archive_staging_restore_verified",
        )
    )

    covered = repository.find_covering_manifests(payload, now=NOW + timedelta(minutes=3))
    assert [manifest.archive_id for manifest in covered] == [exported.archive_id]

    changed = replace(payload, payload={"offset": 999})
    assert repository.find_covering_manifests(changed, now=NOW + timedelta(minutes=3)) == ()


@pytest.mark.django_db
def test_archive_candidates_exclude_only_members_with_unexpired_export_evidence() -> None:
    protected = _payload(offset=1)
    expired = _payload(offset=2)
    for payload in (protected, expired):
        RawPayloadModel._default_manager.create(
            payload_id=payload.payload_id,
            dataset_key=payload.dataset_key,
            provider_name=payload.provider_name,
            payload_hash=payload.payload_hash,
            schema_fingerprint=payload.schema_fingerprint,
            payload=payload.payload,
            fetched_at=payload.fetched_at,
            payload_size_bytes=payload.payload_size_bytes,
        )
    repository = ArchiveManifestRepository()
    repository.save_export(
        _manifest(protected, retention_until=NOW + timedelta(days=30)),
        (_member(protected),),
    )
    repository.save_export(
        _manifest(expired, retention_until=NOW - timedelta(seconds=1)),
        (_member(expired),),
    )

    candidates = ArchiveCandidateRepository().list_unarchived(
        "market.raw",
        before=NOW,
        now=NOW,
        limit=10,
    )

    assert [payload.payload_id for payload in candidates] == [expired.payload_id]
