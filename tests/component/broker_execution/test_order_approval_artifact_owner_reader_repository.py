"""Component tests for the Broker order artifact identity-winner adapter."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from django.db import connection

from apps.broker_execution.application.order_approval_artifact_owner_reader import (
    BrokerOrderApprovalArtifactIdentityWinnerRepository,
)
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
from apps.broker_execution.infrastructure.order_approval_artifact_models import (
    BrokerOrderApprovalArtifactModel,
)
from apps.broker_execution.infrastructure.order_approval_artifact_owner_reader_repository import (
    DjangoBrokerOrderApprovalArtifactIdentityWinnerRepository,
)
from apps.broker_execution.infrastructure.order_approval_artifact_repository import (
    BrokerOrderApprovalArtifactCorruption,
    DjangoBrokerOrderApprovalArtifactRepository,
)

ORDER_ID = "56f9ae53-7606-46de-bf88-a6543f822d4a"
APPROVED_AT = datetime(2026, 8, 13, 2, tzinfo=UTC)
RECORDED_AT = APPROVED_AT + timedelta(minutes=5)
VALID_UNTIL = APPROVED_AT + timedelta(hours=1)


@dataclass
class _Clock:
    value: datetime

    def now(self) -> datetime:
        return self.value


def _artifact() -> BrokerOrderApprovalArtifact:
    snapshot = OrderApprovalSnapshot(
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
        risk_policy_version="risk-policy-v4",
        risk_snapshot_json='{"cash":"10000.00"}',
        approval_mode="manual",
        source_recommendation_ids=("recommendation-1",),
        source_signal_ids=("signal-1",),
    )
    return BrokerOrderApprovalArtifact(
        artifact_id=ORDER_ID,
        artifact_version=f"{BROKER_ORDER_APPROVAL_ARTIFACT_SCHEMA}.3",
        client_order_id=ORDER_ID,
        account_id=7,
        order_version=3,
        approval_snapshot=snapshot,
        approval_digest=build_approval_digest(snapshot),
        approved_by=BrokerOrderApprovalActor(
            actor_id="user:19",
            user_id=19,
            role="broker_approver",
        ),
        approved_at=APPROVED_AT,
        valid_until=VALID_UNTIL,
    )


def _protocol(
    value: BrokerOrderApprovalArtifactIdentityWinnerRepository,
) -> BrokerOrderApprovalArtifactIdentityWinnerRepository:
    return value


@pytest.mark.django_db(transaction=True)
def test_adapter_returns_identity_winner_with_authoritative_recorded_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _Clock(RECORDED_AT)
    writer = DjangoBrokerOrderApprovalArtifactRepository(clock=clock)
    artifact = _artifact()
    with writer.atomic():
        writer.append(artifact, recorded_at=RECORDED_AT)

    def _forbidden_get_exact(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("hash-heavy get_exact must not be called")

    monkeypatch.setattr(
        DjangoBrokerOrderApprovalArtifactRepository,
        "get_exact",
        _forbidden_get_exact,
    )
    adapter = DjangoBrokerOrderApprovalArtifactIdentityWinnerRepository(clock=clock)
    winner = _protocol(adapter).get_identity_winner(
        artifact_id=artifact.artifact_id,
        artifact_version=artifact.artifact_version,
        as_of=RECORDED_AT,
    )

    assert winner is not None
    assert winner.identity_hash == artifact.identity_hash
    assert winner.content_hash == artifact.content_hash
    assert winner.approval_digest == artifact.approval_digest
    assert winner.risk_policy_version == "risk-policy-v4"
    assert winner.approved_at == APPROVED_AT
    assert winner.recorded_at == RECORDED_AT
    assert winner.approved_at != winner.recorded_at


@pytest.mark.django_db(transaction=True)
def test_pit_is_recorded_first_and_expiry_exclusive() -> None:
    clock = _Clock(VALID_UNTIL)
    writer = DjangoBrokerOrderApprovalArtifactRepository(clock=clock)
    artifact = _artifact()
    with writer.atomic():
        writer.append(artifact, recorded_at=RECORDED_AT)
    adapter = DjangoBrokerOrderApprovalArtifactIdentityWinnerRepository(clock=clock)

    assert (
        adapter.get_identity_winner(
            artifact_id=artifact.artifact_id,
            artifact_version=artifact.artifact_version,
            as_of=RECORDED_AT - timedelta(microseconds=1),
        )
        is None
    )
    assert (
        adapter.get_identity_winner(
            artifact_id=artifact.artifact_id,
            artifact_version=artifact.artifact_version,
            as_of=RECORDED_AT,
        )
        is not None
    )
    assert (
        adapter.get_identity_winner(
            artifact_id=artifact.artifact_id,
            artifact_version=artifact.artifact_version,
            as_of=VALID_UNTIL,
        )
        is None
    )


@pytest.mark.django_db(transaction=True)
def test_closed_world_restore_detects_double_selector_hiding() -> None:
    clock = _Clock(RECORDED_AT)
    writer = DjangoBrokerOrderApprovalArtifactRepository(clock=clock)
    artifact = _artifact()
    with writer.atomic():
        writer.append(artifact, recorded_at=RECORDED_AT)
    row = BrokerOrderApprovalArtifactModel._default_manager.get()
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE broker_execution_order_approval_artifact "
            "SET artifact_id = %s, artifact_version = %s WHERE id = %s",
            ["56f9ae53-7606-46de-bf88-a6543f822d4b", "hidden.v1", row.pk],
        )

    adapter = DjangoBrokerOrderApprovalArtifactIdentityWinnerRepository(clock=clock)
    with pytest.raises(BrokerOrderApprovalArtifactCorruption, match="headers"):
        adapter.get_identity_winner(
            artifact_id=artifact.artifact_id,
            artifact_version=artifact.artifact_version,
            as_of=RECORDED_AT,
        )


@pytest.mark.django_db(transaction=True)
def test_missing_identity_returns_none_after_full_restore() -> None:
    adapter = DjangoBrokerOrderApprovalArtifactIdentityWinnerRepository(clock=_Clock(RECORDED_AT))
    assert (
        adapter.get_identity_winner(
            artifact_id=ORDER_ID,
            artifact_version=f"{BROKER_ORDER_APPROVAL_ARTIFACT_SCHEMA}.3",
            as_of=RECORDED_AT,
        )
        is None
    )
