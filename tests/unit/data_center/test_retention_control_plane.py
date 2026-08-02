"""Retention/hold/archive control-plane tests."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from apps.data_center.application.retention import RetentionGuard
from apps.data_center.domain.retention import (
    ArchiveManifest,
    ArchiveState,
    RetentionPolicy,
    RetentionRun,
    StorageHold,
)
from apps.data_center.infrastructure.retention_repositories import (
    RetentionRunRepository,
    StorageHoldRepository,
)

NOW = datetime(2026, 8, 2, 5, 0, tzinfo=UTC)


def test_retention_policy_and_verified_archive_invariants() -> None:
    policy = RetentionPolicy(
        policy_id=str(uuid4()),
        dataset_key="equity.daily",
        version=1,
        retention_days=7,
        archive_after_days=30,
        active=True,
    )
    assert policy.active
    archive = ArchiveManifest(
        archive_id=str(uuid4()),
        dataset_key=policy.dataset_key,
        object_count=1,
        size_bytes=100,
        location="s3://external/archive.tar.zst",
        checksum="sha256:archive",
        state=ArchiveState.VERIFIED,
        created_at=NOW,
        verified_at=NOW,
    )
    assert archive.verified_at == NOW


@pytest.mark.django_db
def test_retention_run_repository_round_trip_preserves_audit_counts() -> None:
    """Retention execution evidence survives a database round trip."""

    run = RetentionRun(
        run_id=str(uuid4()),
        dataset_key="market.raw",
        policy_version=1,
        dry_run=False,
        outcome="success",
        requested=10,
        candidates=2,
        planned=0,
        deleted=2,
        held=0,
        blocked=0,
        bytes_deleted=256,
        cutoff=NOW - timedelta(days=30),
        started_at=NOW,
        finished_at=NOW,
        reason="expired_payloads_deleted",
    )

    saved = RetentionRunRepository().save(run)
    assert saved == run


@pytest.mark.django_db
def test_storage_hold_blocks_retention_delete_until_release_or_expiry() -> None:
    hold = StorageHold(
        hold_id=str(uuid4()),
        resource_type="dataset",
        resource_key="equity.daily",
        reason="reconciliation evidence",
        created_by="pytest",
        created_at=NOW,
        expires_at=NOW + timedelta(days=1),
    )
    repository = StorageHoldRepository()
    repository.save(hold)
    guard = RetentionGuard(repository)
    assert not guard.can_delete("dataset", "equity.daily", now=NOW)
    assert guard.can_delete("dataset", "equity.daily", now=NOW + timedelta(days=2))
