"""Application contracts for trusted RawPayload archive lifecycle orchestration."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet

from apps.data_center.application.archive import (
    ArchiveRawPayloadsUseCase,
    AuditArchiveRestoreUseCase,
    VerifyStoredArchiveUseCase,
)
from apps.data_center.domain.contracts import (
    DatasetContract,
    DatasetFieldContract,
    DatasetKey,
)
from apps.data_center.domain.raw_landing import RawPayload
from apps.data_center.domain.retention import (
    ArchiveArtifact,
    ArchiveManifest,
    ArchiveMember,
    ArchiveRestoreAudit,
    ArchiveRestoreOutcome,
    ArchiveState,
    RetentionPolicy,
)
from apps.data_center.infrastructure.raw_archive_store import FilesystemRawArchiveStore

NOW = datetime(2026, 8, 7, 2, 0, tzinfo=UTC)
DATASET_KEY = "market.raw"


def _payload(*, offset: int) -> RawPayload:
    return RawPayload(
        payload_id=str(uuid4()),
        dataset_key=DATASET_KEY,
        provider_name="fixture",
        payload_hash=f"sha256:payload-{offset}",
        schema_fingerprint=f"sha256:schema-{offset}",
        payload={"offset": offset},
        fetched_at=NOW - timedelta(days=20) + timedelta(minutes=offset),
        payload_size_bytes=128 + offset,
    )


def _policy() -> RetentionPolicy:
    return RetentionPolicy(
        policy_id=str(uuid4()),
        dataset_key=DATASET_KEY,
        version=1,
        retention_days=30,
        archive_after_days=7,
        archive_retention_days=90,
        active=True,
    )


def _contract() -> DatasetContract:
    return DatasetContract(
        key=DatasetKey(
            value=DATASET_KEY,
            contract_version="contract-v1",
            schema_version="schema-v1",
        ),
        owner="data-center",
        frequency="event",
        decision_critical=False,
        fields=(
            DatasetFieldContract(
                name="payload",
                value_type="json",
                unit=None,
                nullable=False,
                zero_allowed=True,
            ),
        ),
    )


class _Policies:
    def __init__(self, policy: RetentionPolicy | None = None) -> None:
        self.policy = policy

    def get_active(self, dataset_key: str) -> RetentionPolicy | None:
        if self.policy is not None and self.policy.dataset_key == dataset_key:
            return self.policy
        return None


class _Contracts:
    def __init__(self, contract: DatasetContract | None = None) -> None:
        self.contract = contract

    def get_active(self, dataset_key: str) -> DatasetContract | None:
        if self.contract is not None and self.contract.key.value == dataset_key:
            return self.contract
        return None


class _Candidates:
    def __init__(self, rows: tuple[RawPayload, ...]) -> None:
        self.rows = rows
        self.calls = 0

    def list_unarchived(
        self,
        dataset_key: str,
        *,
        before: datetime,
        now: datetime,
        limit: int,
    ) -> list[RawPayload]:
        self.calls += 1
        return [
            row
            for row in self.rows
            if row.dataset_key == dataset_key
            and row.fetched_at < before
            and (row.retention_until is None or row.retention_until <= now)
        ][:limit]


class _Capacity:
    def __init__(self, allowed: bool = True) -> None:
        self.allowed = allowed

    def can_write(self, projected_bytes: int) -> bool:
        assert projected_bytes > 0
        return self.allowed


class _MemoryManifests:
    def __init__(self) -> None:
        self.manifests: dict[str, ArchiveManifest] = {}
        self.members: dict[str, tuple[ArchiveMember, ...]] = {}
        self.audits: dict[str, ArchiveRestoreAudit] = {}
        self.mark_verified_calls = 0
        self.record_restore_calls = 0

    def save_export(
        self,
        manifest: ArchiveManifest,
        members: tuple[ArchiveMember, ...],
    ) -> ArchiveManifest:
        existing = self.manifests.get(manifest.archive_id)
        if existing is not None:
            assert existing == manifest
            assert self.members[manifest.archive_id] == members
            return existing
        self.manifests[manifest.archive_id] = manifest
        self.members[manifest.archive_id] = members
        return manifest

    def get(self, archive_id: str) -> ArchiveManifest | None:
        return self.manifests.get(archive_id)

    def list_members(self, archive_id: str) -> tuple[ArchiveMember, ...]:
        return self.members.get(archive_id, ())

    def mark_verified(
        self,
        archive_id: str,
        *,
        verified_at: datetime | None = None,
    ) -> ArchiveManifest:
        self.mark_verified_calls += 1
        manifest = self.manifests[archive_id]
        verified = replace(
            manifest,
            state=ArchiveState.VERIFIED,
            verified_at=verified_at or NOW,
        )
        self.manifests[archive_id] = verified
        return verified

    def record_restore(self, audit: ArchiveRestoreAudit) -> ArchiveManifest:
        self.record_restore_calls += 1
        existing = self.audits.get(audit.operation_key)
        if existing is not None:
            assert existing == audit
            return self.manifests[audit.archive_id]
        self.audits[audit.operation_key] = audit
        manifest = self.manifests[audit.archive_id]
        updated = replace(
            manifest,
            restore_outcome=audit.outcome,
            last_restored_at=audit.finished_at,
        )
        self.manifests[audit.archive_id] = updated
        return updated

    def get_restore_audit(self, operation_key: str) -> ArchiveRestoreAudit | None:
        return self.audits.get(operation_key)


class _CountingStore:
    def __init__(self, delegate: FilesystemRawArchiveStore) -> None:
        self.delegate = delegate
        self.write_calls = 0
        self.inspect_calls = 0
        self.restore_calls = 0

    def write(self, **kwargs: object) -> ArchiveArtifact:
        self.write_calls += 1
        return self.delegate.write(**kwargs)  # type: ignore[arg-type]

    def inspect(self, location: str) -> ArchiveArtifact:
        self.inspect_calls += 1
        return self.delegate.inspect(location)

    def restore_to_staging(self, location: str) -> ArchiveArtifact:
        self.restore_calls += 1
        return self.delegate.restore_to_staging(location)


class _WrongArtifactStore:
    def __init__(self, artifact: ArchiveArtifact) -> None:
        self.artifact = artifact

    def write(self, **_kwargs: object) -> ArchiveArtifact:
        return self.artifact


def _store(tmp_path: Path) -> _CountingStore:
    return _CountingStore(
        FilesystemRawArchiveStore(
            tmp_path,
            encryption_key=Fernet.generate_key(),
            encryption_key_ref="config-center://archive/test-key",
            encryption_key_version="v1",
        )
    )


def _export(
    *,
    rows: tuple[RawPayload, ...],
    manifests: _MemoryManifests,
    store: object,
) -> str:
    result = ArchiveRawPayloadsUseCase(
        _Policies(_policy()),
        _Contracts(_contract()),
        _Candidates(rows),
        manifests,
        store,  # type: ignore[arg-type]
        _Capacity(),
    ).execute(dataset_key=DATASET_KEY, limit=100, now=NOW)
    assert result.outcome == "success"
    return result.archive_id


def test_export_inspect_verify_restore_lifecycle_preserves_exact_members_and_is_idempotent(
    tmp_path: Path,
) -> None:
    oldest = _payload(offset=1)
    newest = _payload(offset=2)
    manifests = _MemoryManifests()
    store = _store(tmp_path)

    archive_id = _export(rows=(oldest, newest), manifests=manifests, store=store)
    exported = manifests.manifests[archive_id]
    artifact = store.inspect(exported.location)
    verify = VerifyStoredArchiveUseCase(manifests, store).execute(
        archive_id=archive_id,
        now=NOW,
    )
    first_restore = AuditArchiveRestoreUseCase(manifests, store).execute(
        archive_id=archive_id,
        operation_id="monthly-audit-2026-08",
        now=NOW,
    )
    retried_restore = AuditArchiveRestoreUseCase(manifests, store).execute(
        archive_id=archive_id,
        operation_id="monthly-audit-2026-08",
        now=NOW + timedelta(hours=1),
    )

    assert artifact.members == manifests.members[archive_id]
    assert [member.payload_id for member in artifact.members] == [
        oldest.payload_id,
        newest.payload_id,
    ]
    assert verify.outcome == "success"
    assert first_restore.outcome == "success"
    assert retried_restore.outcome == "noop"
    assert retried_restore.reason == "archive_restore_operation_already_recorded"
    assert store.restore_calls == 1
    assert manifests.record_restore_calls == 1
    assert len(manifests.audits) == 1


def test_export_rejects_store_evidence_for_a_different_dataset_without_manifest_write(
    tmp_path: Path,
) -> None:
    row = _payload(offset=1)
    seed_store = _store(tmp_path)
    seed = seed_store.delegate.write(
        archive_id=str(uuid4()),
        dataset_key=DATASET_KEY,
        contract_version="contract-v1",
        schema_version="schema-v1",
        payloads=(row,),
        created_at=NOW,
    )
    manifests = _MemoryManifests()

    with pytest.raises(ValueError, match="archive_store_evidence_mismatch"):
        ArchiveRawPayloadsUseCase(
            _Policies(_policy()),
            _Contracts(_contract()),
            _Candidates((row,)),
            manifests,
            _WrongArtifactStore(replace(seed, dataset_key="other.raw")),
            _Capacity(),
        ).execute(dataset_key=DATASET_KEY, now=NOW)

    assert manifests.manifests == {}
    assert manifests.members == {}


def test_verify_fails_closed_when_exact_member_evidence_differs(tmp_path: Path) -> None:
    row = _payload(offset=1)
    manifests = _MemoryManifests()
    store = _store(tmp_path)
    archive_id = _export(rows=(row,), manifests=manifests, store=store)
    member = manifests.members[archive_id][0]
    manifests.members[archive_id] = (
        replace(member, record_digest="sha256:database-evidence-tampered"),
    )

    result = VerifyStoredArchiveUseCase(manifests, store).execute(
        archive_id=archive_id,
        now=NOW,
    )

    assert result.outcome == "blocked"
    assert result.reason == "archive_manifest_evidence_mismatch"
    assert manifests.manifests[archive_id].state is ArchiveState.EXPORTED
    assert manifests.mark_verified_calls == 0


def test_restore_corruption_records_one_failed_operation_and_retry_does_not_reread(
    tmp_path: Path,
) -> None:
    row = _payload(offset=1)
    manifests = _MemoryManifests()
    store = _store(tmp_path)
    archive_id = _export(rows=(row,), manifests=manifests, store=store)
    verify = VerifyStoredArchiveUseCase(manifests, store).execute(
        archive_id=archive_id,
        now=NOW,
    )
    assert verify.outcome == "success"
    artifact_path = next(tmp_path.rglob("*.jsonl.gz"))
    artifact_bytes = artifact_path.read_bytes()
    artifact_path.write_bytes(artifact_bytes[: max(1, len(artifact_bytes) // 2)])

    first = AuditArchiveRestoreUseCase(manifests, store).execute(
        archive_id=archive_id,
        operation_id="monthly-audit-2026-08",
        now=NOW,
    )
    retry = AuditArchiveRestoreUseCase(manifests, store).execute(
        archive_id=archive_id,
        operation_id="monthly-audit-2026-08",
        now=NOW + timedelta(hours=2),
    )

    assert first.outcome == "failed"
    assert first.reason == "archive_restore_failed"
    assert retry.outcome == "failed"
    assert retry.reason == "archive_restore_operation_already_recorded"
    assert store.restore_calls == 1
    assert manifests.record_restore_calls == 1
    assert len(manifests.audits) == 1
    assert manifests.manifests[archive_id].restore_outcome is ArchiveRestoreOutcome.FAILED


def test_export_blocks_before_store_when_capacity_gate_is_closed(tmp_path: Path) -> None:
    row = _payload(offset=1)
    manifests = _MemoryManifests()
    store = _store(tmp_path)

    result = ArchiveRawPayloadsUseCase(
        _Policies(_policy()),
        _Contracts(_contract()),
        _Candidates((row,)),
        manifests,
        store,
        _Capacity(allowed=False),
    ).execute(dataset_key=DATASET_KEY, now=NOW)

    assert result.outcome == "blocked"
    assert result.reason == "archive_projected_storage_pressure_blocked"
    assert store.write_calls == 0
    assert manifests.manifests == {}
