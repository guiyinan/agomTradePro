"""Unit contracts for the Research-owned R2 trial-policy registry."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from apps.research.application.r2_market_structure_trial_policy_registry import (
    R2TrialPolicyRegistryUnavailable,
    RegisterR2MarketStructureTrialPolicy,
    RegisterR2MarketStructureTrialPolicyCommand,
)
from apps.research.domain.r2_market_structure_trial_monitoring import (
    R2MarketStructureTrialPolicy,
)
from apps.research.domain.r2_market_structure_trial_policy_registry import (
    PersistedR2MarketStructureTrialPolicy,
)
from apps.research.infrastructure.r2_market_structure_trial_policy_codec import (
    R2TrialPolicyRegistryCodecError,
    decode_r2_trial_policy_record,
    encode_r2_trial_policy_record,
)
from tests.unit.research.r2_market_structure_trial_monitoring_factories import (
    NOW,
    build_r2_scenario,
)

LEDGER_TIME = NOW - timedelta(days=30, hours=12)
CUTOFF = NOW - timedelta(days=30, hours=18)


class _Clock:
    def __init__(self, now: datetime = LEDGER_TIME, *, key: str = "test:r2") -> None:
        self.value = now
        self.key = key
        self.calls = 0

    @property
    def unit_of_work_key(self) -> str:
        return self.key

    def now(self) -> datetime:
        self.calls += 1
        return self.value


class _Owner:
    def __init__(
        self,
        policy: R2MarketStructureTrialPolicy | None,
        *,
        key: str = "test:r2",
    ) -> None:
        self.policy = policy
        self.key = key
        self.calls: list[datetime] = []
        self.replacement: R2MarketStructureTrialPolicy | None = None
        self.error: Exception | None = None

    @property
    def unit_of_work_key(self) -> str:
        return self.key

    def get_exact(
        self,
        *,
        policy_id: str,
        policy_version: str,
        as_of: datetime,
    ) -> R2MarketStructureTrialPolicy | None:
        del policy_id, policy_version
        self.calls.append(as_of)
        if self.error is not None:
            raise self.error
        if len(self.calls) == 2 and self.replacement is not None:
            return deepcopy(self.replacement)
        return deepcopy(self.policy)


class _Store:
    def __init__(self, *, key: str = "test:r2") -> None:
        self.key = key
        self.rows: list[PersistedR2MarketStructureTrialPolicy] = []
        self.pending: list[PersistedR2MarketStructureTrialPolicy] = []
        self.atomic_depth = 0
        self.append_calls = 0
        self.substitute: PersistedR2MarketStructureTrialPolicy | None = None

    @property
    def unit_of_work_key(self) -> str:
        return self.key

    @contextmanager
    def atomic(self) -> Iterator[None]:
        self.atomic_depth += 1
        try:
            yield
        except Exception:
            self.pending.clear()
            raise
        else:
            self.rows.extend(self.pending)
            self.pending.clear()
        finally:
            self.atomic_depth -= 1

    def append(
        self, record: PersistedR2MarketStructureTrialPolicy
    ) -> PersistedR2MarketStructureTrialPolicy:
        assert self.atomic_depth == 1
        self.append_calls += 1
        self.pending.append(record)
        return self.substitute or record


def _command(
    policy: R2MarketStructureTrialPolicy,
) -> RegisterR2MarketStructureTrialPolicyCommand:
    return RegisterR2MarketStructureTrialPolicyCommand(
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        as_of=CUTOFF,
    )


def _use_case(
    *,
    policy: R2MarketStructureTrialPolicy | None = None,
    owner: _Owner | None = None,
    store: _Store | None = None,
    clock: _Clock | None = None,
) -> tuple[RegisterR2MarketStructureTrialPolicy, _Owner, _Store, _Clock]:
    selected = policy or build_r2_scenario().policy
    selected_owner = owner or _Owner(selected)
    selected_store = store or _Store()
    selected_clock = clock or _Clock()
    return (
        RegisterR2MarketStructureTrialPolicy(
            definition_provider=selected_owner,
            store=selected_store,
            clock=selected_clock,
        ),
        selected_owner,
        selected_store,
        selected_clock,
    )


def test_registration_command_is_strictly_id_only_and_live_sealed() -> None:
    policy = build_r2_scenario().policy
    command = _command(policy)

    assert tuple(command.__dataclass_fields__) == (
        "policy_id",
        "policy_version",
        "as_of",
    )
    object.__setattr__(command, "policy_id", "")
    with pytest.raises(ValueError, match="policy_id"):
        command.__post_init__()


def test_registration_double_reads_owner_and_uses_trusted_clock() -> None:
    policy = build_r2_scenario().policy
    use_case, owner, store, clock = _use_case(policy=policy)

    record = use_case.execute(_command(policy))

    assert owner.calls == [CUTOFF, LEDGER_TIME]
    assert clock.calls == 1
    assert record.policy == policy
    assert record.ledger_recorded_at == LEDGER_TIME
    assert store.rows == [record]
    assert (
        record.research_only,
        record.must_not_publish_current,
        record.must_not_use_for_decision,
        record.must_not_execute,
    ) == (True, True, True, True)


@pytest.mark.parametrize("field,value", [("policy_id", ""), ("as_of", object())])
def test_mutated_command_is_rejected_before_reads_or_writes(field: str, value: object) -> None:
    policy = build_r2_scenario().policy
    use_case, owner, store, clock = _use_case(policy=policy)
    command = _command(policy)
    object.__setattr__(command, field, value)

    with pytest.raises(R2TrialPolicyRegistryUnavailable):
        use_case.execute(command)

    assert owner.calls == []
    assert clock.calls == 0
    assert store.append_calls == 0
    assert store.rows == []


def test_command_subclass_with_noop_validator_is_rejected_before_reads() -> None:
    policy = build_r2_scenario().policy
    use_case, owner, store, clock = _use_case(policy=policy)

    class _Subcommand(RegisterR2MarketStructureTrialPolicyCommand):
        def __post_init__(self) -> None:
            pass

    command = _Subcommand(policy.policy_id, policy.policy_version, CUTOFF)

    with pytest.raises(R2TrialPolicyRegistryUnavailable):
        use_case.execute(command)

    assert owner.calls == []
    assert clock.calls == 0
    assert store.rows == []


def test_future_cutoff_owner_failure_and_missing_owner_are_zero_write() -> None:
    policy = build_r2_scenario().policy
    for owner, command, clock in (
        (
            _Owner(policy),
            replace(_command(policy), as_of=LEDGER_TIME + timedelta(seconds=1)),
            _Clock(),
        ),
        (_Owner(None), _command(policy), _Clock()),
        (_Owner(policy), _command(policy), _Clock()),
    ):
        if owner.policy is not None and command.as_of == CUTOFF:
            owner.error = OSError("owner offline")
        store = _Store()
        use_case, _, _, _ = _use_case(owner=owner, store=store, clock=clock)
        with pytest.raises(R2TrialPolicyRegistryUnavailable):
            use_case.execute(command)
        assert store.rows == []
        assert store.append_calls == 0


def test_owner_replacement_rolls_back_without_winner() -> None:
    policy = build_r2_scenario().policy
    owner = _Owner(policy)
    owner.replacement = replace(policy, expected_label_set_hash="f" * 64)
    store = _Store()
    use_case, _, _, _ = _use_case(owner=owner, store=store)

    with pytest.raises(R2TrialPolicyRegistryUnavailable, match="changed"):
        use_case.execute(_command(policy))

    assert len(owner.calls) == 2
    assert store.append_calls == 0
    assert store.rows == []


def test_live_policy_mutation_and_uow_drift_are_zero_write() -> None:
    policy = build_r2_scenario().policy
    object.__setattr__(policy, "expected_label_set_hash", "0" * 64)
    store = _Store()
    use_case, owner, _, _ = _use_case(policy=policy, store=store)
    with pytest.raises(R2TrialPolicyRegistryUnavailable):
        use_case.execute(_command(policy))
    assert len(owner.calls) == 1
    assert store.rows == []

    fresh = build_r2_scenario().policy
    owner = _Owner(fresh)
    use_case, _, store, _ = _use_case(owner=owner)
    owner.key = "test:replaced"
    with pytest.raises(R2TrialPolicyRegistryUnavailable, match="UoW"):
        use_case.execute(_command(fresh))
    assert owner.calls == []
    assert store.rows == []


def test_store_substitution_after_append_rolls_back() -> None:
    policy = build_r2_scenario().policy
    store = _Store()
    use_case, _, _, _ = _use_case(policy=policy, store=store)
    store.substitute = PersistedR2MarketStructureTrialPolicy.create(
        policy=policy,
        ledger_recorded_at=LEDGER_TIME + timedelta(seconds=1),
    )

    with pytest.raises(R2TrialPolicyRegistryUnavailable, match="substituted"):
        use_case.execute(_command(policy))

    assert store.append_calls == 1
    assert store.rows == []


def test_record_codec_roundtrip_is_canonical_and_strict() -> None:
    record = PersistedR2MarketStructureTrialPolicy.create(
        policy=build_r2_scenario().policy,
        ledger_recorded_at=LEDGER_TIME,
    )
    payload = encode_r2_trial_policy_record(record)

    assert decode_r2_trial_policy_record(payload) == record
    payload["extra"] = True
    with pytest.raises(R2TrialPolicyRegistryCodecError):
        decode_r2_trial_policy_record(payload)


def test_codec_rejects_live_seal_and_safety_tampering() -> None:
    record = PersistedR2MarketStructureTrialPolicy.create(
        policy=build_r2_scenario().policy,
        ledger_recorded_at=LEDGER_TIME,
    )
    payload = encode_r2_trial_policy_record(record)
    payload["must_not_publish_current"] = False
    with pytest.raises(R2TrialPolicyRegistryCodecError):
        decode_r2_trial_policy_record(payload)

    object.__setattr__(record.policy, "expected_label_set_hash", "f" * 64)
    with pytest.raises(R2TrialPolicyRegistryCodecError):
        encode_r2_trial_policy_record(record)
