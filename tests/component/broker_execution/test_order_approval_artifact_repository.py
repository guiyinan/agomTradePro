"""Component coverage for Broker order approval artifact persistence."""

from __future__ import annotations

import importlib
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection
from django.db.migrations import RunPython, RunSQL

from apps.broker_execution.domain.entities import (
    LiveOrderSide,
    LiveOrderType,
    OrderApprovalSnapshot,
)
from apps.broker_execution.domain.order_approval_artifact import (
    BROKER_ORDER_APPROVAL_ARTIFACT_SCHEMA,
    BrokerOrderApprovalActor,
    BrokerOrderApprovalArtifact,
)
from apps.broker_execution.domain.rules import build_approval_digest
from apps.broker_execution.infrastructure.order_approval_artifact_codec import (
    BrokerOrderApprovalArtifactCodecError,
    decode_broker_order_approval_artifact,
    encode_broker_order_approval_artifact,
)
from apps.broker_execution.infrastructure.order_approval_artifact_models import (
    BrokerOrderApprovalArtifactModel,
)
from apps.broker_execution.infrastructure.order_approval_artifact_repository import (
    BrokerOrderApprovalArtifactConflict,
    BrokerOrderApprovalArtifactCorruption,
    BrokerOrderApprovalArtifactUnavailable,
    DjangoBrokerOrderApprovalArtifactRepository,
    _model_values,
)

ORDER_ID = "56f9ae53-7606-46de-bf88-a6543f822d4a"
APPROVED_AT = datetime(2026, 8, 13, 2, tzinfo=UTC)
RECORDED_AT = APPROVED_AT + timedelta(minutes=1)
VALID_UNTIL = APPROVED_AT + timedelta(hours=1)


@dataclass
class FixedClock:
    value: datetime

    def now(self) -> datetime:
        return self.value


def _snapshot() -> OrderApprovalSnapshot:
    return OrderApprovalSnapshot(
        account_id=7,
        agent_id="agent:primary",
        asset_code="600000.SH",
        market="CN",
        side=LiveOrderSide.BUY,
        order_type=LiveOrderType.LIMIT,
        quantity=Decimal("100.0000"),
        limit_price=Decimal("10.2500"),
        estimated_amount=Decimal("1025.00000000"),
        expires_at=VALID_UNTIL.isoformat(),
        risk_policy_version="risk-policy-v1",
        risk_snapshot_json='{"cash":"10000.00"}',
        approval_mode="manual",
        source_recommendation_ids=("recommendation-1",),
        source_signal_ids=("signal-1",),
    )


def _artifact(*, actor_id: str = "user:19", user_id: int = 19) -> BrokerOrderApprovalArtifact:
    snapshot = _snapshot()
    return BrokerOrderApprovalArtifact(
        artifact_id=ORDER_ID,
        artifact_version=f"{BROKER_ORDER_APPROVAL_ARTIFACT_SCHEMA}.3",
        client_order_id=ORDER_ID,
        account_id=7,
        order_version=3,
        approval_snapshot=snapshot,
        approval_digest=build_approval_digest(snapshot),
        approved_by=BrokerOrderApprovalActor(
            actor_id=actor_id, user_id=user_id, role="broker_approver"
        ),
        approved_at=APPROVED_AT,
        valid_until=VALID_UNTIL,
    )


@pytest.mark.django_db
def test_append_round_trip_and_exact_historical_pit_boundaries() -> None:
    clock = FixedClock(RECORDED_AT)
    repository = DjangoBrokerOrderApprovalArtifactRepository(clock=clock)
    artifact = _artifact()
    with repository.atomic():
        persisted = repository.append(artifact, recorded_at=RECORDED_AT)

    assert persisted == artifact
    assert BrokerOrderApprovalArtifactModel._default_manager.count() == 1
    assert (
        decode_broker_order_approval_artifact(encode_broker_order_approval_artifact(artifact))
        == artifact
    )
    assert (
        repository.get_exact(
            artifact_id=artifact.artifact_id,
            artifact_version=artifact.artifact_version,
            expected_content_hash=artifact.content_hash,
            as_of=RECORDED_AT,
        )
        == artifact
    )
    assert (
        repository.get_exact(
            artifact_id=artifact.artifact_id,
            artifact_version=artifact.artifact_version,
            expected_content_hash=artifact.content_hash,
            as_of=RECORDED_AT - timedelta(microseconds=1),
        )
        is None
    )
    clock.value = VALID_UNTIL
    assert (
        repository.get_exact(
            artifact_id=artifact.artifact_id,
            artifact_version=artifact.artifact_version,
            expected_content_hash=artifact.content_hash,
            as_of=VALID_UNTIL,
        )
        is None
    )


@pytest.mark.django_db
def test_future_cutoff_and_private_uow_fail_closed() -> None:
    repository = DjangoBrokerOrderApprovalArtifactRepository(clock=FixedClock(RECORDED_AT))
    artifact = _artifact()
    with pytest.raises(BrokerOrderApprovalArtifactConflict, match="private unit"):
        repository.append(artifact, recorded_at=RECORDED_AT)
    with pytest.raises(BrokerOrderApprovalArtifactUnavailable, match="future"):
        repository.get_exact(
            artifact_id=artifact.artifact_id,
            artifact_version=artifact.artifact_version,
            expected_content_hash=artifact.content_hash,
            as_of=RECORDED_AT + timedelta(microseconds=1),
        )


@pytest.mark.django_db
def test_direct_update_delete_bulk_raw_and_unclaimed_create_are_blocked() -> None:
    repository = DjangoBrokerOrderApprovalArtifactRepository(clock=FixedClock(RECORDED_AT))
    artifact = _artifact()
    with repository.atomic():
        repository.append(artifact, recorded_at=RECORDED_AT)
    row = BrokerOrderApprovalArtifactModel._default_manager.get()

    row.approved_actor_id = "tampered"
    with pytest.raises(ValidationError, match="append-only"):
        row.save()
    with pytest.raises(ValidationError, match="append-only"):
        row.save_base(force_update=True)
    with pytest.raises(ValidationError, match="cannot be updated"):
        BrokerOrderApprovalArtifactModel._default_manager.update(account_id=8)
    with pytest.raises(ValidationError, match="cannot be deleted"):
        row.delete()
    with pytest.raises(ValidationError, match="cannot be deleted"):
        BrokerOrderApprovalArtifactModel._default_manager.all().delete()
    values = _model_values(artifact, recorded_at=RECORDED_AT)
    with pytest.raises(ValidationError, match="exact insert claim"):
        BrokerOrderApprovalArtifactModel._default_manager.create(**values)
    with pytest.raises(ValidationError, match="exact repository appends"):
        BrokerOrderApprovalArtifactModel._default_manager.bulk_create(
            [BrokerOrderApprovalArtifactModel(**values)]
        )


@pytest.mark.django_db
def test_identity_anchor_conflict_preserves_first_winner() -> None:
    repository = DjangoBrokerOrderApprovalArtifactRepository(clock=FixedClock(RECORDED_AT))
    first = _artifact()
    with repository.atomic():
        repository.append(first, recorded_at=RECORDED_AT)

    conflicting = _artifact(actor_id="user:20", user_id=20)
    with (
        repository.atomic(),
        pytest.raises(BrokerOrderApprovalArtifactConflict, match="another first winner"),
    ):
        repository.append(conflicting, recorded_at=RECORDED_AT)
    assert BrokerOrderApprovalArtifactModel._default_manager.count() == 1


@pytest.mark.django_db
def test_header_and_payload_tamper_are_detected() -> None:
    clock = FixedClock(RECORDED_AT)
    repository = DjangoBrokerOrderApprovalArtifactRepository(clock=clock)
    artifact = _artifact()
    with repository.atomic():
        repository.append(artifact, recorded_at=RECORDED_AT)
    row = BrokerOrderApprovalArtifactModel._default_manager.get()

    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE broker_execution_order_approval_artifact "
            "SET approved_actor_id = %s WHERE id = %s",
            ["tampered", row.pk],
        )
    with pytest.raises(BrokerOrderApprovalArtifactCorruption, match="headers"):
        repository.get_exact(
            artifact_id=artifact.artifact_id,
            artifact_version=artifact.artifact_version,
            expected_content_hash=artifact.content_hash,
            as_of=RECORDED_AT,
        )


@pytest.mark.django_db
def test_canonical_payload_tamper_is_detected() -> None:
    repository = DjangoBrokerOrderApprovalArtifactRepository(clock=FixedClock(RECORDED_AT))
    artifact = _artifact()
    with repository.atomic():
        repository.append(artifact, recorded_at=RECORDED_AT)
    row = BrokerOrderApprovalArtifactModel._default_manager.get()
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE broker_execution_order_approval_artifact "
            "SET canonical_payload = %s WHERE id = %s",
            [json.dumps({}), row.pk],
        )
    with pytest.raises(BrokerOrderApprovalArtifactCorruption, match="payload"):
        repository.get_exact(
            artifact_id=artifact.artifact_id,
            artifact_version=artifact.artifact_version,
            expected_content_hash=artifact.content_hash,
            as_of=RECORDED_AT,
        )


@pytest.mark.django_db
def test_database_persisted_clock_tamper_is_detected() -> None:
    repository = DjangoBrokerOrderApprovalArtifactRepository(clock=FixedClock(RECORDED_AT))
    artifact = _artifact()
    with repository.atomic():
        repository.append(artifact, recorded_at=RECORDED_AT)
    row = BrokerOrderApprovalArtifactModel._default_manager.get()
    with pytest.raises(IntegrityError):
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE broker_execution_order_approval_artifact "
                "SET persisted_at = %s WHERE id = %s",
                [RECORDED_AT - timedelta(microseconds=1), row.pk],
            )


def test_codec_rejects_unknown_fields_and_migration_is_zero_seed() -> None:
    payload = encode_broker_order_approval_artifact(_artifact())
    with pytest.raises(BrokerOrderApprovalArtifactCodecError, match="shape"):
        decode_broker_order_approval_artifact({**payload, "unknown": True})

    migration = importlib.import_module(
        "apps.broker_execution.migrations.0008_order_approval_artifact"
    ).Migration
    assert migration.operations
    assert not any(isinstance(operation, (RunPython, RunSQL)) for operation in migration.operations)


def test_artifact_remains_inactive_after_persistence_contract_projection() -> None:
    artifact = replace(_artifact())
    assert artifact.activation_available is False
    assert artifact.must_not_execute is True
