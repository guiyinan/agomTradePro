"""Pure-domain invariants for exact retention plan snapshots."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from apps.data_center.domain.retention import (
    RetentionPlan,
    RetentionPlanDecision,
    RetentionPlanMember,
    RetentionPlanStatus,
    retention_plan_snapshot_digest,
)

NOW = datetime(2026, 8, 7, 5, 0, tzinfo=UTC)


def _member(*, ordinal: int = 0) -> RetentionPlanMember:
    return RetentionPlanMember(
        ordinal=ordinal,
        payload_id=str(uuid4()),
        payload_hash="a" * 64,
        record_digest="b" * 64,
        schema_fingerprint="sha256:schema",
        fetched_at=NOW - timedelta(days=31),
        retention_until=None,
        size_bytes=128,
        decision=RetentionPlanDecision.ELIGIBLE,
        archive_id=str(uuid4()),
    )


def _digest(member: RetentionPlanMember) -> str:
    return retention_plan_snapshot_digest(
        dataset_key="market.raw",
        policy_id="policy-v1",
        policy_version=1,
        cutoff=NOW - timedelta(days=30),
        members=(member,),
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("payload_hash", "c" * 64),
        ("record_digest", "d" * 64),
        ("schema_fingerprint", "sha256:changed"),
        ("fetched_at", NOW - timedelta(days=32)),
        ("retention_until", NOW - timedelta(days=1)),
        ("size_bytes", 129),
        ("archive_id", "22222222-2222-2222-2222-222222222222"),
    ],
)
def test_snapshot_digest_covers_every_immutable_member_field(field: str, value: object) -> None:
    member = _member()

    assert _digest(replace(member, **{field: value})) != _digest(member)


def test_retention_plan_requires_exact_count_partition_and_aware_expiry() -> None:
    member = _member()
    cutoff = NOW - timedelta(days=30)
    kwargs = {
        "plan_id": str(uuid4()),
        "operation_id": "plan-domain",
        "dataset_key": "market.raw",
        "policy_id": str(uuid4()),
        "policy_version": 1,
        "requested": 10,
        "candidates": 1,
        "planned": 1,
        "held": 0,
        "blocked": 0,
        "bytes_planned": 128,
        "cutoff": cutoff,
        "created_at": NOW,
        "expires_at": NOW + timedelta(hours=1),
        "snapshot_digest": retention_plan_snapshot_digest(
            dataset_key="market.raw",
            policy_id="ignored-for-validation",
            policy_version=1,
            cutoff=cutoff,
            members=(member,),
        ),
        "status": RetentionPlanStatus.READY,
        "outcome": "success",
    }
    assert RetentionPlan(**kwargs).planned == 1

    with pytest.raises(ValueError, match="partition"):
        RetentionPlan(**{**kwargs, "candidates": 2})
    with pytest.raises(ValueError, match="must follow"):
        RetentionPlan(**{**kwargs, "expires_at": NOW})
    with pytest.raises(ValueError, match="timezone-aware"):
        RetentionPlan(**{**kwargs, "expires_at": datetime(2026, 8, 8)})


def test_ineligible_member_cannot_smuggle_archive_evidence() -> None:
    with pytest.raises(ValueError, match="cannot carry archive evidence"):
        replace(_member(), decision=RetentionPlanDecision.HELD)
