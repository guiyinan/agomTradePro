"""PostgreSQL-only concurrency evidence for exact retention plans."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, Event
from uuid import uuid4

import pytest
from django.db import close_old_connections, connection, transaction

from apps.data_center.domain.retention import (
    RetentionMemberExecution,
    RetentionPlan,
    RetentionPlanStatus,
    retention_plan_snapshot_digest,
)
from apps.data_center.infrastructure.models import StorageHoldModel
from apps.data_center.infrastructure.retention_repositories import (
    ArchiveManifestRepository,
    RetentionPlanRepository,
    _acquire_resource_locks,
)
from tests.unit.data_center.test_retention_control_plane import (
    NOW,
    _consumable_retention_plan,
    _exact_plan,
)

pytestmark = pytest.mark.django_db(transaction=True)


def _require_postgresql() -> None:
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL advisory-lock evidence requires PostgreSQL")


def test_two_workers_cannot_claim_one_plan_with_different_operations() -> None:
    _require_postgresql()
    plan, members, archive = _exact_plan()
    ArchiveManifestRepository().save(archive)
    RetentionPlanRepository().create(plan, members)
    barrier = Barrier(2)

    def claim(operation_id: str) -> str:
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            claimed, _, _ = RetentionPlanRepository().claim(
                plan.plan_id, operation_id=operation_id, now=NOW
            )
            return f"claimed:{claimed.enforce_operation_id}"
        except ValueError as exc:
            return f"blocked:{exc}"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = sorted(executor.map(claim, ("worker-one", "worker-two")))

    assert sum(result.startswith("claimed:") for result in results) == 1
    assert sum("retention_plan_already_claimed" in result for result in results) == 1


def test_concurrent_same_operation_plan_creation_replays_single_snapshot() -> None:
    _require_postgresql()
    operation_id = f"concurrent-plan-{uuid4()}"
    policy_id = str(uuid4())
    barrier = Barrier(2)

    def create_plan(_: int) -> str:
        close_old_connections()
        try:
            cutoff = NOW - timedelta(days=30)
            plan = RetentionPlan(
                plan_id=str(uuid4()),
                operation_id=operation_id,
                dataset_key="market.raw",
                policy_id=policy_id,
                policy_version=1,
                requested=10,
                candidates=0,
                planned=0,
                held=0,
                blocked=0,
                bytes_planned=0,
                cutoff=cutoff,
                created_at=NOW,
                expires_at=NOW + timedelta(hours=1),
                snapshot_digest=retention_plan_snapshot_digest(
                    dataset_key="market.raw",
                    policy_id=policy_id,
                    policy_version=1,
                    cutoff=cutoff,
                    members=(),
                ),
                status=RetentionPlanStatus.EMPTY,
                outcome="noop",
            )
            barrier.wait(timeout=5)
            saved, _ = RetentionPlanRepository().create(plan, ())
            return saved.plan_id
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        plan_ids = list(executor.map(create_plan, (1, 2)))

    assert len(set(plan_ids)) == 1


def test_hold_insert_serializes_before_member_delete_and_blocks_it() -> None:
    _require_postgresql()
    _, raw_rows, plan, member, payload = _consumable_retention_plan()
    hold_locked = Event()
    release_hold = Event()
    consume_done = Event()

    def create_hold_while_locked() -> None:
        close_old_connections()
        try:
            with transaction.atomic():
                _acquire_resource_locks((("raw_payload", payload.payload_id),))
                StorageHoldModel._default_manager.create(
                    hold_id=uuid4(),
                    resource_type="raw_payload",
                    resource_key=payload.payload_id,
                    reason="concurrent legal hold",
                    created_by="pytest",
                    created_at=NOW,
                )
                hold_locked.set()
                assert release_hold.wait(timeout=10)
        finally:
            close_old_connections()

    def consume() -> RetentionMemberExecution:
        close_old_connections()
        try:
            consumed = RetentionPlanRepository().consume_member(plan.plan_id, member, now=NOW)
            return consumed.execution
        finally:
            consume_done.set()
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        hold_future = executor.submit(create_hold_while_locked)
        assert hold_locked.wait(timeout=10)
        consume_future = executor.submit(consume)
        assert not consume_done.wait(timeout=0.2)
        release_hold.set()
        hold_future.result(timeout=10)
        execution = consume_future.result(timeout=10)

    assert execution is RetentionMemberExecution.BLOCKED
    assert raw_rows.get_by_id(payload.payload_id) == payload
