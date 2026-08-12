"""Contracts for the independent Research-owned R8 monitoring policy registry."""

from contextlib import nullcontext
from dataclasses import fields
from datetime import timedelta

import pytest

from apps.research.application.r8_monitoring_policy_registry import (
    R8MonitoringPolicyRegistryUnavailable,
    RegisterR8MonitoringPolicy,
    RegisterR8MonitoringPolicyCommand,
)
from apps.research.domain.r8_monitoring_policy_registry import (
    R8MonitoringPolicyDefinition,
    R8MonitoringPolicySourceReceipt,
)
from apps.research.infrastructure.r8_monitoring_policy_codec import (
    R8MonitoringPolicyCodecError,
    decode_r8_monitoring_policy_definition,
    decode_r8_monitoring_policy_source_receipt,
    encode_r8_monitoring_policy_definition,
    encode_r8_monitoring_policy_source_receipt,
)
from tests.unit.portfolio.test_governed_optimization_monitoring import (
    NOW,
    _active_result,
    _calendar,
    _policy,
    _receipt_and_result,
)


def _definition() -> R8MonitoringPolicyDefinition:
    receipt, result = _receipt_and_result()
    return R8MonitoringPolicyDefinition.from_policy(
        _policy(_calendar(), _active_result(result), receipt)
    )


def _source() -> R8MonitoringPolicySourceReceipt:
    definition = _definition()
    policy = definition.policy
    return R8MonitoringPolicySourceReceipt.create(
        source_receipt_id="research-r8-monitoring-policy-source:1",
        source_receipt_version="research-r8-monitoring-policy-source.v1",
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        definition_hash=definition.content_hash,
        available_at=policy.recorded_at,
        valid_until=policy.valid_until,
        evidence_ref="research:r8-monitoring-policy:1",
    )


class _Provider:
    unit_of_work_key = "django:default"

    def __init__(self, value: object) -> None:
        self.value = value
        self.calls = 0

    def get_exact(self, **selectors: object) -> object:
        del selectors
        self.calls += 1
        return self.value


class _Store:
    unit_of_work_key = "django:default"

    def __init__(self) -> None:
        self.calls = 0

    def atomic(self):  # type: ignore[no-untyped-def]
        return nullcontext()

    def append(self, *, definition, source, ledger_recorded_at):  # type: ignore[no-untyped-def]
        assert definition == _definition()
        assert source == _source()
        assert ledger_recorded_at == NOW + timedelta(hours=4)
        self.calls += 1
        return definition.policy


class _Clock:
    unit_of_work_key = "django:default"

    def now(self):  # type: ignore[no-untyped-def]
        return NOW + timedelta(hours=4)


def _command() -> RegisterR8MonitoringPolicyCommand:
    policy = _definition().policy
    return RegisterR8MonitoringPolicyCommand(
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
    )


def test_policy_registration_command_is_identity_only() -> None:
    """A caller cannot submit policy thresholds, target, calendar, or clocks."""

    assert tuple(item.name for item in fields(RegisterR8MonitoringPolicyCommand)) == (
        "policy_id",
        "policy_version",
    )


def test_policy_registration_double_reads_independent_owner_and_trusted_clock() -> None:
    """A stable dedicated definition/source graph produces one exact policy append."""

    definition_provider = _Provider(_definition())
    source_provider = _Provider(_source())
    store = _Store()
    use_case = RegisterR8MonitoringPolicy(
        definition_provider=definition_provider,
        source_provider=source_provider,
        store=store,
        clock=_Clock(),
    )

    assert use_case.execute(_command()) == _definition().policy
    assert definition_provider.calls == 2
    assert source_provider.calls == 2
    assert store.calls == 1


def test_missing_source_and_mutated_policy_command_are_zero_write() -> None:
    """Absence and validator bypass fail before the owner store is called."""

    store = _Store()
    use_case = RegisterR8MonitoringPolicy(
        definition_provider=_Provider(_definition()),
        source_provider=_Provider(None),
        store=store,
        clock=_Clock(),
    )
    with pytest.raises(R8MonitoringPolicyRegistryUnavailable):
        use_case.execute(_command())

    command = _command()
    object.__setattr__(command, "policy_id", "")
    object.__setattr__(command, "__post_init__", lambda: None)
    with pytest.raises(R8MonitoringPolicyRegistryUnavailable):
        use_case.execute(command)
    assert store.calls == 0

    definition = _definition()
    object.__setattr__(definition, "content_hash", "0" * 64)
    object.__setattr__(definition, "validated_copy", lambda: definition)
    bypass = RegisterR8MonitoringPolicy(
        definition_provider=_Provider(definition),
        source_provider=_Provider(_source()),
        store=store,
        clock=_Clock(),
    )
    with pytest.raises(R8MonitoringPolicyRegistryUnavailable):
        bypass.execute(_command())
    assert store.calls == 0


def test_policy_registry_codec_is_strict_and_seal_preserving() -> None:
    """Owner payloads round-trip exactly and reject surplus or altered seals."""

    definition_payload = encode_r8_monitoring_policy_definition(_definition())
    source_payload = encode_r8_monitoring_policy_source_receipt(_source())
    assert decode_r8_monitoring_policy_definition(definition_payload) == _definition()
    assert decode_r8_monitoring_policy_source_receipt(source_payload) == _source()

    definition_payload["surplus"] = "forbidden"
    with pytest.raises(R8MonitoringPolicyCodecError):
        decode_r8_monitoring_policy_definition(definition_payload)

    source_payload["content_hash"] = "0" * 64
    with pytest.raises(R8MonitoringPolicyCodecError):
        decode_r8_monitoring_policy_source_receipt(source_payload)
