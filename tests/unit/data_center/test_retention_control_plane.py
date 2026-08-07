"""Retention/hold/archive control-plane tests."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from apps.data_center.application.retention import RetentionGuard
from apps.data_center.domain.retention import (
    ArchiveManifest,
    ArchiveState,
    RetentionMemberExecution,
    RetentionPlan,
    RetentionPlanDecision,
    RetentionPlanMember,
    RetentionPlanStatus,
    RetentionPolicy,
    RetentionRun,
    StorageHold,
    retention_plan_snapshot_digest,
)
from apps.data_center.infrastructure.models import ArchiveManifestModel
from apps.data_center.infrastructure.retention_repositories import (
    ArchiveManifestRepository,
    RetentionPlanRepository,
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
        archive_after_days=3,
        archive_retention_days=30,
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


@pytest.mark.django_db
def test_archive_manifest_verification_rejects_failed_state_and_missing_checksum() -> None:
    repository = ArchiveManifestRepository()
    failed = ArchiveManifest(
        archive_id=str(uuid4()),
        dataset_key="market.raw",
        object_count=1,
        size_bytes=10,
        location="s3://external/archive.tar.zst",
        checksum="sha256:archive",
        state=ArchiveState.FAILED,
        created_at=NOW,
    )
    repository.save(failed)
    with pytest.raises(ValueError, match="state_not_verifiable"):
        repository.mark_verified(failed.archive_id, verified_at=NOW)

    missing_checksum_id = uuid4()
    ArchiveManifestModel._default_manager.create(
        archive_id=missing_checksum_id,
        dataset_key="market.raw",
        object_count=1,
        size_bytes=10,
        location="s3://external/archive.tar.zst",
        checksum="",
        state=ArchiveState.EXPORTED.value,
        created_at=NOW,
    )
    with pytest.raises(ValueError, match="checksum_missing"):
        repository.mark_verified(str(missing_checksum_id), verified_at=NOW)

    with pytest.raises(ValueError, match="timezone_aware"):
        repository.mark_verified(failed.archive_id, verified_at=datetime(2026, 8, 2, 5, 0))


def _exact_plan() -> tuple[RetentionPlan, tuple[RetentionPlanMember, ...], ArchiveManifest]:
    archive = ArchiveManifest(
        archive_id=str(uuid4()),
        dataset_key="market.raw",
        object_count=1,
        size_bytes=128,
        location="s3://external/exact-plan.bin",
        checksum="sha256:exact-plan",
        state=ArchiveState.EXPORTED,
        created_at=NOW,
    )
    member = RetentionPlanMember(
        ordinal=0,
        payload_id=str(uuid4()),
        payload_hash="a" * 64,
        record_digest="b" * 64,
        schema_fingerprint="sha256:schema",
        fetched_at=NOW - timedelta(days=31),
        retention_until=None,
        size_bytes=128,
        decision=RetentionPlanDecision.ELIGIBLE,
        archive_id=archive.archive_id,
    )
    members = (member,)
    policy_id = str(uuid4())
    cutoff = NOW - timedelta(days=30)
    plan = RetentionPlan(
        plan_id=str(uuid4()),
        operation_id=f"plan-{uuid4()}",
        dataset_key="market.raw",
        policy_id=policy_id,
        policy_version=1,
        requested=10,
        candidates=1,
        planned=1,
        held=0,
        blocked=0,
        bytes_planned=128,
        cutoff=cutoff,
        created_at=NOW,
        expires_at=NOW + timedelta(hours=24),
        snapshot_digest=retention_plan_snapshot_digest(
            dataset_key="market.raw",
            policy_id=policy_id,
            policy_version=1,
            cutoff=cutoff,
            members=members,
        ),
        status=RetentionPlanStatus.READY,
        outcome="success",
        reason="retention_plan_created",
    )
    return plan, members, archive


@pytest.mark.django_db
def test_retention_plan_repository_persists_exact_members_and_claims_once() -> None:
    plan, members, archive = _exact_plan()
    ArchiveManifestRepository().save(archive)
    repository = RetentionPlanRepository()

    saved, saved_members = repository.create(plan, members)
    claimed, claimed_members, replayed = repository.claim(
        saved.plan_id, operation_id="enforce-one", now=NOW
    )

    assert saved == plan
    assert saved_members == members
    assert claimed.status is RetentionPlanStatus.ENFORCING
    assert claimed_members == members
    assert replayed is False
    with pytest.raises(ValueError, match="already_claimed"):
        repository.claim(saved.plan_id, operation_id="enforce-two", now=NOW)


@pytest.mark.django_db
def test_retention_plan_repository_replays_terminal_result_without_reclaiming() -> None:
    plan, members, archive = _exact_plan()
    ArchiveManifestRepository().save(archive)
    repository = RetentionPlanRepository()
    repository.create(plan, members)
    claimed, _, _ = repository.claim(plan.plan_id, operation_id="stable-enforce", now=NOW)
    repository.save_member(
        plan.plan_id,
        RetentionPlanMember(
            **{
                **members[0].__dict__,
                "execution": RetentionMemberExecution.DELETED,
                "execution_reason": "deleted",
                "deleted_at": NOW,
            }
        ),
    )
    completed = repository.finish(
        RetentionPlan(
            **{
                **claimed.__dict__,
                "status": RetentionPlanStatus.COMPLETED,
                "outcome": "success",
                "deleted": 1,
                "bytes_deleted": 128,
                "finished_at": NOW,
                "reason": "retention_plan_enforced",
            }
        )
    )

    replay, replay_members, replayed = repository.claim(
        plan.plan_id, operation_id="stable-enforce", now=NOW
    )

    assert replay == completed
    assert replayed is True
    assert replay_members[0].execution is RetentionMemberExecution.DELETED


@pytest.mark.django_db
def test_retention_plan_repository_expires_and_replays_without_claiming_members() -> None:
    plan, members, archive = _exact_plan()
    ArchiveManifestRepository().save(archive)
    repository = RetentionPlanRepository()
    repository.create(plan, members)
    expired_at = plan.expires_at

    expired, expired_members, replayed = repository.claim(
        plan.plan_id, operation_id="expired-enforce", now=expired_at
    )
    replay, _, replayed_again = repository.claim(
        plan.plan_id, operation_id="expired-enforce", now=expired_at
    )

    assert expired.status is RetentionPlanStatus.EXPIRED
    assert expired.outcome == "blocked"
    assert expired_members == members
    assert replayed is False
    assert replay == expired
    assert replayed_again is True


@pytest.mark.django_db
def test_retention_run_repository_rejects_mutating_existing_evidence() -> None:
    run = RetentionRun(
        run_id=str(uuid4()),
        dataset_key="market.raw",
        policy_version=1,
        dry_run=True,
        outcome="noop",
        requested=1,
        candidates=0,
        planned=0,
        deleted=0,
        held=0,
        blocked=0,
        started_at=NOW,
        finished_at=NOW,
    )
    repository = RetentionRunRepository()
    repository.save(run)

    with pytest.raises(ValueError, match="immutable_conflict"):
        repository.save(RetentionRun(**{**run.__dict__, "reason": "changed"}))
