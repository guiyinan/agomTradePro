"""Component coverage for Broker execution-risk policy persistence."""

from __future__ import annotations

import importlib
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import connection
from django.db.migrations import RunPython, RunSQL

from apps.risk_center.application.broker_order_execution_policy import (
    ActivateBrokerOrderExecutionPolicy,
    ActivateBrokerOrderExecutionPolicyCommand,
    BrokerOrderExecutionPolicyActor,
    BrokerOrderExecutionPolicyConflict,
    BrokerOrderExecutionPolicyCorruption,
    BrokerOrderExecutionPolicySourceRef,
    BrokerOrderExecutionPolicySourceSnapshot,
    BrokerOrderExecutionPolicyUnavailable,
    ExactCurrentBrokerOrderRiskPolicyProvider,
)
from apps.risk_center.domain.broker_order_execution_policy import (
    BrokerOrderExecutionRiskControls,
)
from apps.risk_center.infrastructure.broker_order_execution_policy_codec import (
    decode_broker_order_execution_policy_activation,
    decode_broker_order_execution_policy_source,
    encode_broker_order_execution_policy_activation,
    encode_broker_order_execution_policy_source,
)
from apps.risk_center.infrastructure.broker_order_execution_policy_models import (
    BrokerOrderExecutionPolicyActivationModel,
    BrokerOrderExecutionPolicySourceModel,
)
from apps.risk_center.infrastructure.broker_order_execution_policy_repository import (
    DjangoBrokerOrderExecutionPolicyRepository,
)

RECORDED_AT = datetime.now(UTC) - timedelta(minutes=5)
ACTIVATED_AT = RECORDED_AT + timedelta(minutes=1)
SECOND_AT = ACTIVATED_AT + timedelta(minutes=1)
VALID_UNTIL = ACTIVATED_AT + timedelta(hours=2)


@dataclass
class FixedClock:
    value: datetime

    def now(self) -> datetime:
        return self.value


class FixedSourceProvider:
    def __init__(self, value: BrokerOrderExecutionPolicySourceSnapshot) -> None:
        self.value = value

    def get_exact_active(
        self,
        *,
        source_snapshot_id: str,
        source_snapshot_version: str,
        as_of: datetime,
    ) -> BrokerOrderExecutionPolicySourceSnapshot | None:
        if (
            self.value.source_snapshot_id != source_snapshot_id
            or self.value.source_snapshot_version != source_snapshot_version
            or not self.value.is_active_at(as_of)
        ):
            return None
        return self.value


def _controls() -> BrokerOrderExecutionRiskControls:
    return BrokerOrderExecutionRiskControls(
        max_total_position_pct=Decimal("0.8"),
        max_single_position_pct=Decimal("0.2"),
        max_daily_loss_pct=Decimal("0.03"),
        max_drawdown_pct=Decimal("0.15"),
        max_stop_loss_pct=Decimal("0.1"),
        take_profit_pct=Decimal("0.2"),
        min_cash_pct=Decimal("0.05"),
        force_stop_loss=True,
        hard_exclusions=("ST",),
    )


def _source_refs(
    *, valid_until: datetime = VALID_UNTIL
) -> tuple[BrokerOrderExecutionPolicySourceRef, ...]:
    kinds = (
        "account_override",
        "account_exceptions",
        "floor",
        "global_exceptions",
        "template",
    )
    return tuple(
        BrokerOrderExecutionPolicySourceRef(
            source_kind=kind,
            source_id=f"{kind}:41:v1",
            source_version="v1",
            source_content_hash=f"{index + 1}" * 64,
            recorded_at=RECORDED_AT,
            valid_until=valid_until,
        )
        for index, kind in enumerate(kinds)
    )


def _source(
    *,
    source_id: str = "broker-policy-source:41:v1",
    source_version: str = "v1",
    controls: BrokerOrderExecutionRiskControls | None = None,
    recorded_at: datetime = RECORDED_AT,
    valid_until: datetime = VALID_UNTIL,
) -> BrokerOrderExecutionPolicySourceSnapshot:
    return BrokerOrderExecutionPolicySourceSnapshot(
        source_snapshot_id=source_id,
        source_snapshot_version=source_version,
        account_id=41,
        controls=controls or _controls(),
        sources=_source_refs(valid_until=valid_until),
        recorded_at=recorded_at,
        valid_until=valid_until,
    )


def _command(
    *,
    policy_id: str = "broker-execution-policy:41:v1",
    policy_version: str = "v1",
    source_id: str = "broker-policy-source:41:v1",
    source_version: str = "v1",
) -> ActivateBrokerOrderExecutionPolicyCommand:
    return ActivateBrokerOrderExecutionPolicyCommand(
        policy_id=policy_id,
        policy_version=policy_version,
        source_snapshot_id=source_id,
        source_snapshot_version=source_version,
    )


def _activate(
    repository: DjangoBrokerOrderExecutionPolicyRepository,
    source: BrokerOrderExecutionPolicySourceSnapshot,
    command: ActivateBrokerOrderExecutionPolicyCommand | None = None,
):
    return ActivateBrokerOrderExecutionPolicy(
        source_provider=FixedSourceProvider(source),
        repository=repository,
        actor=BrokerOrderExecutionPolicyActor(actor_id="user:risk-owner", user_id=41),
    ).execute(command or _command())


@pytest.mark.django_db
def test_workflow_persists_exact_source_activation_and_current_provider() -> None:
    clock = FixedClock(ACTIVATED_AT)
    repository = DjangoBrokerOrderExecutionPolicyRepository(clock=clock)
    source = _source()

    activation = _activate(repository, source)

    assert BrokerOrderExecutionPolicySourceModel._default_manager.count() == 1
    assert BrokerOrderExecutionPolicyActivationModel._default_manager.count() == 1
    assert (
        decode_broker_order_execution_policy_source(
            encode_broker_order_execution_policy_source(source)
        )
        == source
    )
    assert (
        decode_broker_order_execution_policy_activation(
            encode_broker_order_execution_policy_activation(activation)
        )
        == activation
    )
    assert (
        repository.get_activation_winner(
            policy_id=activation.policy.policy_id,
            policy_version=activation.policy.policy_version,
            as_of=ACTIVATED_AT,
        )
        == activation
    )
    projected = ExactCurrentBrokerOrderRiskPolicyProvider(repository).get_exact_active(
        policy_id=activation.policy.policy_id,
        policy_version=activation.policy.policy_version,
        as_of=ACTIVATED_AT,
    )
    assert projected is not None
    assert projected.policy_content_hash == activation.content_hash


@pytest.mark.django_db
def test_cross_clock_replay_is_exact_and_does_not_duplicate_source() -> None:
    clock = FixedClock(ACTIVATED_AT)
    repository = DjangoBrokerOrderExecutionPolicyRepository(clock=clock)
    source = _source()
    first = _activate(repository, source)
    clock.value = SECOND_AT

    assert _activate(repository, source) == first
    assert BrokerOrderExecutionPolicySourceModel._default_manager.count() == 1
    assert BrokerOrderExecutionPolicyActivationModel._default_manager.count() == 1


@pytest.mark.django_db
def test_source_identity_first_winner_and_content_hash_is_not_a_unique_anchor() -> None:
    repository = DjangoBrokerOrderExecutionPolicyRepository(clock=FixedClock(ACTIVATED_AT))
    source = _source()
    with repository.atomic():
        assert repository.append_source(source, recorded_at=ACTIVATED_AT) == source
        same_content = _source(source_id="broker-policy-source:41:alias")
        assert repository.append_source(same_content, recorded_at=ACTIVATED_AT) == same_content
    assert BrokerOrderExecutionPolicySourceModel._default_manager.count() == 2
    assert BrokerOrderExecutionPolicySourceModel._meta.get_field("content_hash").unique is False

    conflict = _source(controls=replace(_controls(), min_cash_pct=Decimal("0.06")))
    with (
        repository.atomic(),
        pytest.raises(BrokerOrderExecutionPolicyConflict, match="another first winner"),
    ):
        repository.append_source(conflict, recorded_at=ACTIVATED_AT)


@pytest.mark.django_db
def test_successor_advances_head_and_old_policy_is_not_current() -> None:
    clock = FixedClock(ACTIVATED_AT)
    repository = DjangoBrokerOrderExecutionPolicyRepository(clock=clock)
    first = _activate(repository, _source())
    clock.value = SECOND_AT
    second_source = _source(
        source_id="broker-policy-source:41:v2",
        source_version="v2",
        recorded_at=ACTIVATED_AT,
    )
    second = _activate(
        repository,
        second_source,
        _command(
            policy_id="broker-execution-policy:41:v2",
            policy_version="v2",
            source_id="broker-policy-source:41:v2",
            source_version="v2",
        ),
    )

    assert second.policy.supersedes_policy_hash == first.policy.content_hash
    assert repository.get_current_head(account_id=41, as_of=ACTIVATED_AT) == first
    assert repository.get_current_head(account_id=41, as_of=SECOND_AT) == second
    provider = ExactCurrentBrokerOrderRiskPolicyProvider(repository)
    assert (
        provider.get_exact_active(
            policy_id=first.policy.policy_id,
            policy_version=first.policy.policy_version,
            as_of=SECOND_AT,
        )
        is None
    )


@pytest.mark.django_db
def test_private_uow_append_only_and_future_cutoff_fail_closed() -> None:
    source = _source()
    repository = DjangoBrokerOrderExecutionPolicyRepository(clock=FixedClock(ACTIVATED_AT))
    with pytest.raises(BrokerOrderExecutionPolicyConflict, match="private unit"):
        repository.append_source(source, recorded_at=ACTIVATED_AT)
    with pytest.raises(ValidationError, match="exact insert claim"):
        BrokerOrderExecutionPolicySourceModel._default_manager.create(
            source_snapshot_id=source.source_snapshot_id
        )
    with pytest.raises(ValidationError, match="exact repository appends"):
        BrokerOrderExecutionPolicyActivationModel._default_manager.bulk_create(
            [BrokerOrderExecutionPolicyActivationModel(policy_id="bad")]
        )
    with pytest.raises(BrokerOrderExecutionPolicyUnavailable, match="future"):
        repository.get_current_head(account_id=41, as_of=ACTIVATED_AT + timedelta(microseconds=1))


@pytest.mark.django_db
def test_payload_header_chain_and_persisted_clock_tamper_fail_closed() -> None:
    clock = FixedClock(ACTIVATED_AT)
    repository = DjangoBrokerOrderExecutionPolicyRepository(clock=clock)
    activation = _activate(repository, _source())
    row = BrokerOrderExecutionPolicyActivationModel._default_manager.get()
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE risk_center_broker_execution_policy_activation "
            "SET canonical_activation = %s WHERE id = %s",
            [json.dumps({}), row.pk],
        )
    with pytest.raises(BrokerOrderExecutionPolicyCorruption, match="payload"):
        repository.get_activation_winner(
            policy_id=activation.policy.policy_id,
            policy_version=activation.policy.policy_version,
            as_of=ACTIVATED_AT,
        )


@pytest.mark.django_db
def test_selector_header_tamper_cannot_revive_an_old_head() -> None:
    clock = FixedClock(ACTIVATED_AT)
    repository = DjangoBrokerOrderExecutionPolicyRepository(clock=clock)
    first = _activate(repository, _source())
    clock.value = SECOND_AT
    second_source = _source(
        source_id="broker-policy-source:41:v2",
        source_version="v2",
        recorded_at=ACTIVATED_AT,
    )
    second = _activate(
        repository,
        second_source,
        _command(
            policy_id="broker-execution-policy:41:v2",
            policy_version="v2",
            source_id="broker-policy-source:41:v2",
            source_version="v2",
        ),
    )
    row = BrokerOrderExecutionPolicyActivationModel._default_manager.get(
        policy_content_hash=second.policy.content_hash
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE risk_center_broker_execution_policy_activation "
            "SET account_id = %s WHERE id = %s",
            [999, row.pk],
        )
    with pytest.raises(BrokerOrderExecutionPolicyCorruption, match="headers"):
        repository.get_current_head(account_id=first.policy.account_id, as_of=SECOND_AT)


@pytest.mark.django_db
def test_persisted_clock_tamper_fails_closed() -> None:
    repository = DjangoBrokerOrderExecutionPolicyRepository(clock=FixedClock(ACTIVATED_AT))
    activation = _activate(repository, _source())
    row = BrokerOrderExecutionPolicyActivationModel._default_manager.select_related("source").get()
    row.persisted_at = activation.recorded_at - timedelta(microseconds=1)
    with pytest.raises(BrokerOrderExecutionPolicyCorruption, match="persistence clock"):
        repository._restore_activation(row)


def test_migration_is_schema_only_and_zero_seed() -> None:
    migration = importlib.import_module(
        "apps.risk_center.migrations.0009_broker_order_execution_policies"
    ).Migration

    assert migration.dependencies == [("risk_center", "0008_broker_order_risk_authorizations")]
    assert migration.operations
    assert not any(isinstance(operation, (RunPython, RunSQL)) for operation in migration.operations)
