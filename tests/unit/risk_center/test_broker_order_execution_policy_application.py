"""Pure Application tests for Broker execution-policy activation."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.risk_center.application.broker_order_execution_policy import (
    ActivateBrokerOrderExecutionPolicy,
    ActivateBrokerOrderExecutionPolicyCommand,
    BrokerOrderExecutionPolicyActivation,
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

NOW = datetime(2026, 8, 13, 8, tzinfo=UTC)
LATER = NOW + timedelta(minutes=5)
EXPIRES = NOW + timedelta(hours=2)


def _source_refs() -> tuple[BrokerOrderExecutionPolicySourceRef, ...]:
    return tuple(
        BrokerOrderExecutionPolicySourceRef(
            source_kind=kind,
            source_id=f"{kind}:7:v1",
            source_version="v1",
            source_content_hash=(str(index + 1) * 64)[:64],
            recorded_at=NOW - timedelta(minutes=2),
            valid_until=EXPIRES,
        )
        for index, kind in enumerate(
            (
                "account_override",
                "account_exceptions",
                "floor",
                "global_exceptions",
                "template",
            )
        )
    )


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


def _source(**changes: object) -> BrokerOrderExecutionPolicySourceSnapshot:
    values: dict[str, object] = {
        "source_snapshot_id": "risk-source:7:v1",
        "source_snapshot_version": "v1",
        "account_id": 7,
        "controls": _controls(),
        "sources": _source_refs(),
        "recorded_at": NOW - timedelta(minutes=1),
        "valid_until": EXPIRES,
    }
    values.update(changes)
    return BrokerOrderExecutionPolicySourceSnapshot(**values)  # type: ignore[arg-type]


def _command(
    *, policy_id: str = "broker-risk-policy:7:v1", policy_version: str = "v1"
) -> ActivateBrokerOrderExecutionPolicyCommand:
    return ActivateBrokerOrderExecutionPolicyCommand(
        policy_id=policy_id,
        policy_version=policy_version,
        source_snapshot_id="risk-source:7:v1",
        source_snapshot_version="v1",
    )


def _actor(user_id: int = 19) -> BrokerOrderExecutionPolicyActor:
    return BrokerOrderExecutionPolicyActor(actor_id=f"user:{user_id}", user_id=user_id)


class SourceProvider:
    def __init__(self, *values: object) -> None:
        self.values = list(values)
        self.calls: list[tuple[str, str, datetime]] = []

    def get_exact_active(
        self,
        *,
        source_snapshot_id: str,
        source_snapshot_version: str,
        as_of: datetime,
    ) -> object:
        self.calls.append((source_snapshot_id, source_snapshot_version, as_of))
        if len(self.values) > 1:
            return self.values.pop(0)
        return self.values[0]


@dataclass
class MemoryRepository:
    clock: datetime

    def __post_init__(self) -> None:
        self.records: list[BrokerOrderExecutionPolicyActivation] = []
        self.atomic_depth = 0
        self.append_calls: list[tuple[str | None, datetime]] = []
        self.append_override: BrokerOrderExecutionPolicyActivation | None = None

    @contextmanager
    def atomic(self) -> Iterator[None]:
        self.atomic_depth += 1
        try:
            yield
        finally:
            self.atomic_depth -= 1

    def now(self) -> datetime:
        return self.clock

    def get_activation_winner(
        self, *, policy_id: str, policy_version: str, as_of: datetime
    ) -> BrokerOrderExecutionPolicyActivation | None:
        return next(
            (
                item
                for item in self.records
                if item.policy.policy_id == policy_id
                and item.policy.policy_version == policy_version
                and item.recorded_at <= as_of
            ),
            None,
        )

    def get_current_head(
        self, *, account_id: int, as_of: datetime
    ) -> BrokerOrderExecutionPolicyActivation | None:
        known = [
            item
            for item in self.records
            if item.policy.account_id == account_id and item.recorded_at <= as_of
        ]
        superseded = {
            item.policy.supersedes_policy_hash
            for item in known
            if item.policy.supersedes_policy_hash is not None
        }
        heads = [item for item in known if item.policy.content_hash not in superseded]
        if not heads:
            return None
        assert len(heads) == 1
        return heads[0]

    def append(
        self,
        activation: BrokerOrderExecutionPolicyActivation,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> BrokerOrderExecutionPolicyActivation:
        assert self.atomic_depth == 1
        head = self.get_current_head(account_id=activation.policy.account_id, as_of=recorded_at)
        assert (head.policy.content_hash if head else None) == expected_predecessor_hash
        self.append_calls.append((expected_predecessor_hash, recorded_at))
        if self.append_override is not None:
            return self.append_override
        self.records.append(activation)
        return activation


def _activate(
    repository: MemoryRepository,
    provider: SourceProvider,
    *,
    actor: BrokerOrderExecutionPolicyActor | None = None,
    command: ActivateBrokerOrderExecutionPolicyCommand | None = None,
) -> BrokerOrderExecutionPolicyActivation:
    return ActivateBrokerOrderExecutionPolicy(
        source_provider=provider,  # type: ignore[arg-type]
        repository=repository,
        actor=actor or _actor(),
    ).execute(command or _command())


def test_id_only_activation_double_reads_source_and_uses_server_clock() -> None:
    repository = MemoryRepository(NOW)
    provider = SourceProvider(_source())

    activation = _activate(repository, provider)

    assert len(provider.calls) == 2
    assert provider.calls == [
        ("risk-source:7:v1", "v1", NOW),
        ("risk-source:7:v1", "v1", NOW),
    ]
    assert activation.policy.account_id == 7
    assert activation.policy.recorded_at == NOW
    assert activation.policy.activated_at == NOW
    assert activation.policy.supersedes_policy_hash is None
    assert activation.policy.source_snapshot_hash == _source().content_hash
    assert activation.activated_by == _actor()
    assert len(activation.content_hash) == 64
    assert repository.append_calls == [(None, NOW)]


def test_successor_predecessor_is_derived_from_repository_head() -> None:
    repository = MemoryRepository(NOW)
    first = _activate(repository, SourceProvider(_source()))
    repository.clock = LATER
    second_source = _source(
        source_snapshot_id="risk-source:7:v2",
        source_snapshot_version="v2",
        recorded_at=NOW + timedelta(minutes=1),
    )
    command = ActivateBrokerOrderExecutionPolicyCommand(
        policy_id="broker-risk-policy:7:v2",
        policy_version="v2",
        source_snapshot_id="risk-source:7:v2",
        source_snapshot_version="v2",
    )

    second = _activate(repository, SourceProvider(second_source), command=command)

    assert second.policy.supersedes_policy_hash == first.policy.content_hash
    assert repository.append_calls[-1] == (first.policy.content_hash, LATER)


def test_cross_clock_retry_is_idempotent_only_for_original_actor() -> None:
    repository = MemoryRepository(NOW)
    provider = SourceProvider(_source())
    first = _activate(repository, provider)
    repository.clock = LATER

    assert _activate(repository, provider) == first
    assert len(repository.records) == 1
    with pytest.raises(BrokerOrderExecutionPolicyConflict, match="another actor"):
        _activate(repository, provider, actor=_actor(20))


def test_activation_seal_binds_the_server_actor_without_changing_policy_content() -> None:
    repository = MemoryRepository(NOW)
    first = _activate(repository, SourceProvider(_source()))
    other = replace(first, activated_by=_actor(20), content_hash="")

    assert other.policy.content_hash == first.policy.content_hash
    assert other.content_hash != first.content_hash


def test_activation_fails_closed_when_source_drifts_or_is_unavailable() -> None:
    changed = replace(
        _source(),
        controls=replace(_controls(), min_cash_pct=Decimal("0.06")),
        content_hash="",
    )
    repository = MemoryRepository(NOW)
    with pytest.raises(BrokerOrderExecutionPolicyCorruption, match="changed"):
        _activate(repository, SourceProvider(_source(), changed))
    assert repository.records == []

    with pytest.raises(BrokerOrderExecutionPolicyUnavailable, match="unavailable"):
        _activate(repository, SourceProvider(None))


def test_existing_identity_must_still_bind_current_source_and_head() -> None:
    repository = MemoryRepository(NOW)
    first = _activate(repository, SourceProvider(_source()))
    repository.clock = LATER
    changed = replace(
        _source(),
        controls=replace(_controls(), min_cash_pct=Decimal("0.06")),
        content_hash="",
    )
    with pytest.raises(BrokerOrderExecutionPolicyConflict, match="another first winner"):
        _activate(repository, SourceProvider(changed))

    successor_source = _source(
        source_snapshot_id="risk-source:7:v2",
        source_snapshot_version="v2",
        recorded_at=NOW + timedelta(minutes=1),
    )
    successor_command = ActivateBrokerOrderExecutionPolicyCommand(
        policy_id="broker-risk-policy:7:v2",
        policy_version="v2",
        source_snapshot_id="risk-source:7:v2",
        source_snapshot_version="v2",
    )
    _activate(repository, SourceProvider(successor_source), command=successor_command)
    with pytest.raises(BrokerOrderExecutionPolicyConflict, match="no longer the current head"):
        _activate(repository, SourceProvider(_source()))
    assert first.policy.content_hash != repository.records[-1].policy.content_hash


def test_exact_provider_enforces_pit_current_head_and_expiry() -> None:
    repository = MemoryRepository(NOW)
    first = _activate(repository, SourceProvider(_source()))
    facade = ExactCurrentBrokerOrderRiskPolicyProvider(repository)

    assert (
        facade.get_exact_active(
            policy_id=first.policy.policy_id,
            policy_version=first.policy.policy_version,
            as_of=NOW - timedelta(microseconds=1),
        )
        is None
    )
    projected = facade.get_exact_active(
        policy_id=first.policy.policy_id,
        policy_version=first.policy.policy_version,
        as_of=NOW,
    )
    assert projected is not None
    assert projected.policy_content_hash == first.content_hash
    assert projected.permission_cap == "execution_eligible"

    repository.clock = LATER
    successor_source = _source(
        source_snapshot_id="risk-source:7:v2",
        source_snapshot_version="v2",
        recorded_at=NOW + timedelta(minutes=1),
    )
    successor_command = ActivateBrokerOrderExecutionPolicyCommand(
        policy_id="broker-risk-policy:7:v2",
        policy_version="v2",
        source_snapshot_id="risk-source:7:v2",
        source_snapshot_version="v2",
    )
    second = _activate(repository, SourceProvider(successor_source), command=successor_command)
    assert (
        facade.get_exact_active(
            policy_id=first.policy.policy_id,
            policy_version=first.policy.policy_version,
            as_of=LATER,
        )
        is None
    )
    assert (
        facade.get_exact_active(
            policy_id=second.policy.policy_id,
            policy_version=second.policy.policy_version,
            as_of=LATER,
        )
        is not None
    )
    assert (
        facade.get_exact_active(
            policy_id=second.policy.policy_id,
            policy_version=second.policy.policy_version,
            as_of=EXPIRES,
        )
        is None
    )


def test_facade_rejects_repository_identity_and_head_corruption() -> None:
    repository = MemoryRepository(NOW)
    activation = _activate(repository, SourceProvider(_source()))
    substituted_policy = replace(activation.policy, policy_id="another-policy", content_hash="")
    substituted = replace(activation, policy=substituted_policy, content_hash="")

    class SubstitutingRepository(MemoryRepository):
        def get_activation_winner(
            self, *, policy_id: str, policy_version: str, as_of: datetime
        ) -> BrokerOrderExecutionPolicyActivation | None:
            del policy_id, policy_version, as_of
            return substituted

    bad_repository = SubstitutingRepository(NOW)
    bad_repository.records.append(substituted)
    facade = ExactCurrentBrokerOrderRiskPolicyProvider(bad_repository)

    with pytest.raises(BrokerOrderExecutionPolicyCorruption, match="identity substitution"):
        facade.get_exact_active(
            policy_id=activation.policy.policy_id,
            policy_version=activation.policy.policy_version,
            as_of=NOW,
        )


def test_command_and_source_reject_caller_controlled_or_invalid_shapes() -> None:
    with pytest.raises(ValueError):
        ActivateBrokerOrderExecutionPolicyCommand(
            policy_id="bad policy",
            policy_version="v1",
            source_snapshot_id="source-1",
            source_snapshot_version="v1",
        )
    with pytest.raises(ValueError, match="validity"):
        _source(recorded_at=EXPIRES)
    with pytest.raises(ValueError, match="complete ordered source bundle"):
        _source(sources=_source_refs()[:-1])
    refs = list(_source_refs())
    refs[0] = replace(refs[0], valid_until=EXPIRES - timedelta(minutes=1))
    with pytest.raises(ValueError, match="component intersection"):
        _source(sources=tuple(refs))
    with pytest.raises(ValueError, match="human staff"):
        BrokerOrderExecutionPolicyActor(
            actor_id="service:risk", user_id=19, kind="service", is_staff=True
        )
