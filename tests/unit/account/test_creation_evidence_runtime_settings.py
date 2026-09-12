"""Typed runtime settings and fail-closed bridge contracts for creation evidence."""

from __future__ import annotations

import traceback
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from io import StringIO
from math import inf, nan

import pytest
from django.core.management.base import CommandError
from django.db import DatabaseError

from apps.account.application.creation_evidence_settings import (
    ACCOUNT_CREATION_EVIDENCE_SETTINGS_KEY,
    ACCOUNT_CREATION_EVIDENCE_SETTINGS_SCHEMA_VERSION,
    CanonicalAccountCreationEvidenceSettings,
    decode_canonical_account_creation_evidence_settings,
)
from apps.account.management.commands import activate_creation_evidence_settings
from apps.config_center.application import runtime_definition_reconcile
from apps.config_center.domain.runtime_config import (
    RuntimeConfigCriticality,
    RuntimeValueType,
)
from core.integration import account_creation_evidence_runtime


def _settings(**changes: object) -> CanonicalAccountCreationEvidenceSettings:
    values: dict[str, object] = {
        "schema_version": ACCOUNT_CREATION_EVIDENCE_SETTINGS_SCHEMA_VERSION,
        "ttl_seconds": 300,
        "allocation_recorder_service_id": "account-allocation-recorder-v1",
        "physical_v2_recorder_service_id": "account-physical-v2-recorder-v1",
        "allocated_v3_recorder_service_id": "account-allocated-v3-recorder-v1",
        "binding_recorder_service_id": "account-binding-recorder-v1",
    }
    values.update(changes)
    return CanonicalAccountCreationEvidenceSettings(**values)  # type: ignore[arg-type]


def test_settings_are_frozen_safe_and_round_trip_to_one_closed_payload() -> None:
    settings = _settings()

    assert settings.to_payload() == {
        "schema_version": ACCOUNT_CREATION_EVIDENCE_SETTINGS_SCHEMA_VERSION,
        "ttl_seconds": 300,
        "allocation_recorder_service_id": "account-allocation-recorder-v1",
        "physical_v2_recorder_service_id": "account-physical-v2-recorder-v1",
        "allocated_v3_recorder_service_id": "account-allocated-v3-recorder-v1",
        "binding_recorder_service_id": "account-binding-recorder-v1",
    }
    assert decode_canonical_account_creation_evidence_settings(settings.to_payload()) == settings
    assert settings.as_timedelta() == timedelta(seconds=300)
    assert settings.deadline_at(datetime(2026, 9, 11, tzinfo=UTC)) == datetime(
        2026, 9, 11, 0, 5, tzinfo=UTC
    )
    with pytest.raises(FrozenInstanceError):
        settings.ttl_seconds = 301  # type: ignore[misc]


def test_settings_reject_datetime_deadline_overflow_at_consumption_boundary() -> None:
    with pytest.raises(ValueError, match="datetime deadline"):
        _settings(ttl_seconds=1).deadline_at(datetime.max.replace(tzinfo=UTC))


def test_settings_accepts_large_ttl_when_actual_cutoff_can_represent_deadline() -> None:
    cutoff = datetime(2026, 9, 11, tzinfo=UTC)
    settings = _settings(ttl_seconds=10**9)

    assert settings.deadline_at(cutoff) == cutoff + timedelta(seconds=10**9)


@pytest.mark.parametrize("cutoff", [datetime(2026, 9, 11), "cutoff", True])
def test_settings_rejects_naive_or_non_datetime_deadline_cutoff(cutoff: object) -> None:
    with pytest.raises(ValueError, match="aware datetime"):
        _settings().deadline_at(cutoff)  # type: ignore[arg-type]


def test_settings_rejects_datetime_overflow_for_large_but_valid_ttl() -> None:
    settings = _settings(ttl_seconds=10**12)

    with pytest.raises(ValueError, match="datetime deadline"):
        settings.deadline_at(datetime(2026, 9, 11, tzinfo=UTC))


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"schema_version": ACCOUNT_CREATION_EVIDENCE_SETTINGS_SCHEMA_VERSION},
        {
            **_settings().to_payload(),
            "unexpected": "value",
        },
        {
            **_settings().to_payload(),
            "schema_version": True,
        },
        {
            **_settings().to_payload(),
            "schema_version": "account.creation_evidence.settings.v2",
        },
        {
            **_settings().to_payload(),
            "ttl_seconds": True,
        },
        {
            **_settings().to_payload(),
            "ttl_seconds": 0,
        },
        {
            **_settings().to_payload(),
            "ttl_seconds": -1,
        },
        {
            **_settings().to_payload(),
            "ttl_seconds": nan,
        },
        {
            **_settings().to_payload(),
            "ttl_seconds": inf,
        },
        {
            **_settings().to_payload(),
            "ttl_seconds": 10**1000,
        },
        {
            **_settings().to_payload(),
            "allocation_recorder_service_id": " ",
        },
        {
            **_settings().to_payload(),
            "physical_v2_recorder_service_id": "bad service",
        },
        {
            **_settings().to_payload(),
            "allocated_v3_recorder_service_id": True,
        },
        {
            **_settings().to_payload(),
            "binding_recorder_service_id": "x" * 193,
        },
    ],
)
def test_decoder_rejects_missing_unknown_wrong_type_nonfinite_overflow_and_bad_tokens(
    payload: object,
) -> None:
    with pytest.raises((TypeError, ValueError)):
        decode_canonical_account_creation_evidence_settings(payload)


@pytest.mark.parametrize("value", [None, [], "payload", True])
def test_decoder_requires_exact_json_object(value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        decode_canonical_account_creation_evidence_settings(value)


def test_definition_is_one_critical_typed_json_without_business_defaults() -> None:
    definitions = {
        definition.key: definition
        for definition in runtime_definition_reconcile.DEFAULT_RUNTIME_DEFINITIONS
    }
    definition = definitions[ACCOUNT_CREATION_EVIDENCE_SETTINGS_KEY]

    assert definition.namespace == "account"
    assert definition.owner_app == "account"
    assert definition.value_type is RuntimeValueType.TYPED_JSON
    assert definition.criticality is RuntimeConfigCriticality.CRITICAL
    definition.validate(_settings().to_payload())


def test_core_bridge_reads_one_complete_snapshot_and_decodes_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []
    payload = _settings().to_payload()

    def _read(*, environment: str, definition_key: str) -> object:
        calls.append((environment, definition_key))
        return payload

    monkeypatch.setattr(
        account_creation_evidence_runtime.config_center_runtime, "get_active_runtime_value", _read
    )

    result = account_creation_evidence_runtime.get_active_account_creation_evidence_settings(
        "staging"
    )

    assert result == _settings()
    assert calls == [("staging", ACCOUNT_CREATION_EVIDENCE_SETTINGS_KEY)]


@pytest.mark.parametrize("raw", [None, {}, {"ttl_seconds": 0}])
def test_core_bridge_fails_closed_for_missing_or_malformed_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    raw: object,
) -> None:
    calls = 0

    def _read(*, environment: str, definition_key: str) -> object:
        nonlocal calls
        calls += 1
        return raw

    monkeypatch.setattr(
        account_creation_evidence_runtime.config_center_runtime, "get_active_runtime_value", _read
    )

    assert (
        account_creation_evidence_runtime.get_active_account_creation_evidence_settings("staging")
        is None
    )
    assert calls == 1


def test_core_bridge_rejects_ttl_that_overflows_the_current_server_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def _read(*, environment: str, definition_key: str) -> object:
        nonlocal calls
        calls += 1
        return _settings(ttl_seconds=10**12).to_payload()

    monkeypatch.setattr(
        account_creation_evidence_runtime.config_center_runtime, "get_active_runtime_value", _read
    )

    assert (
        account_creation_evidence_runtime.get_active_account_creation_evidence_settings("staging")
        is None
    )
    assert calls == 1


def test_core_bridge_fails_closed_when_runtime_owner_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def _read(*, environment: str, definition_key: str) -> object:
        nonlocal calls
        calls += 1
        raise RuntimeError("database details")

    monkeypatch.setattr(
        account_creation_evidence_runtime.config_center_runtime, "get_active_runtime_value", _read
    )

    assert (
        account_creation_evidence_runtime.get_active_account_creation_evidence_settings("staging")
        is None
    )
    assert calls == 1


def test_core_bridge_does_not_lookup_blank_or_non_string_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def _unexpected_read(*, environment: str, definition_key: str) -> object:
        nonlocal calls
        calls += 1
        return _settings().to_payload()

    monkeypatch.setattr(
        account_creation_evidence_runtime.config_center_runtime,
        "get_active_runtime_value",
        _unexpected_read,
    )

    assert (
        account_creation_evidence_runtime.get_active_account_creation_evidence_settings("") is None
    )
    assert (
        account_creation_evidence_runtime.get_active_account_creation_evidence_settings(
            cast_object("staging")
        )
        is None
    )
    assert calls == 0


def cast_object(value: str) -> object:
    """Provide a non-string environment without a test-only type ignore."""

    return value.encode("utf-8")


class _Parser:
    def __init__(self) -> None:
        self.arguments: dict[str, dict[str, object]] = {}

    def add_argument(self, name: str, **options: object) -> None:
        self.arguments[name] = options


def test_command_requires_every_snapshot_component_without_defaults() -> None:
    parser = _Parser()

    activate_creation_evidence_settings.Command().add_arguments(parser)  # type: ignore[arg-type]

    for name in (
        "--environment",
        "--actor",
        "--reason",
        "--ttl-seconds",
        "--allocation-recorder-service-id",
        "--physical-v2-recorder-service-id",
        "--allocated-v3-recorder-service-id",
        "--binding-recorder-service-id",
    ):
        assert parser.arguments[name]["required"] is True
    assert "default" not in parser.arguments["--ttl-seconds"]


def test_command_decodes_and_activates_one_complete_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def _activate(**kwargs: object) -> dict[str, object]:
        calls.append(kwargs)
        return {"profile_id": "profile-1", "profile_version": 4}

    monkeypatch.setattr(
        activate_creation_evidence_settings, "activate_runtime_profile_patch", _activate
    )
    command = activate_creation_evidence_settings.Command(stdout=StringIO())
    command.handle(
        environment="staging",
        actor="operator-1",
        reason="enable creation evidence chain",
        ttl_seconds=300,
        allocation_recorder_service_id="account-allocation-recorder-v1",
        physical_v2_recorder_service_id="account-physical-v2-recorder-v1",
        allocated_v3_recorder_service_id="account-allocated-v3-recorder-v1",
        binding_recorder_service_id="account-binding-recorder-v1",
    )

    assert calls == [
        {
            "environment": "staging",
            "patch": {ACCOUNT_CREATION_EVIDENCE_SETTINGS_KEY: _settings().to_payload()},
            "bootstrap_values": None,
            "actor": "operator-1",
            "reason": "enable creation evidence chain",
        }
    ]
    assert "profile-1" in command.stdout.getvalue()


def test_command_rejects_invalid_snapshot_before_activation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    activated = False

    def _unexpected_activate(**kwargs: object) -> dict[str, object]:
        nonlocal activated
        activated = True
        return {}

    monkeypatch.setattr(
        activate_creation_evidence_settings, "activate_runtime_profile_patch", _unexpected_activate
    )
    command = activate_creation_evidence_settings.Command(stdout=StringIO())

    with pytest.raises(CommandError, match="ttl-seconds"):
        command.handle(
            environment="staging",
            actor="operator-1",
            reason="bad ttl",
            ttl_seconds=True,
            allocation_recorder_service_id="a",
            physical_v2_recorder_service_id="b",
            allocated_v3_recorder_service_id="c",
            binding_recorder_service_id="d",
        )

    assert activated is False


def test_command_rejects_ttl_that_overflows_current_deadline_before_activation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    activated = False

    def _unexpected_activate(**kwargs: object) -> dict[str, object]:
        nonlocal activated
        activated = True
        return {}

    monkeypatch.setattr(
        activate_creation_evidence_settings, "activate_runtime_profile_patch", _unexpected_activate
    )
    command = activate_creation_evidence_settings.Command(stdout=StringIO())

    with pytest.raises(CommandError, match="datetime deadline"):
        command.handle(
            environment="staging",
            actor="operator-1",
            reason="overflowing ttl",
            ttl_seconds=10**12,
            allocation_recorder_service_id="a",
            physical_v2_recorder_service_id="b",
            allocated_v3_recorder_service_id="c",
            binding_recorder_service_id="d",
        )

    assert activated is False


def test_command_maps_runtime_activation_failure_to_clear_command_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fail(**kwargs: object) -> dict[str, object]:
        raise RuntimeError("runtime owner unavailable")

    monkeypatch.setattr(
        activate_creation_evidence_settings, "activate_runtime_profile_patch", _fail
    )
    command = activate_creation_evidence_settings.Command(stdout=StringIO())

    with pytest.raises(CommandError, match="activation failed"):
        command.handle(
            environment="staging",
            actor="operator-1",
            reason="activation",
            ttl_seconds=300,
            allocation_recorder_service_id="a",
            physical_v2_recorder_service_id="b",
            allocated_v3_recorder_service_id="c",
            binding_recorder_service_id="d",
        )


def test_command_maps_database_activation_failure_without_leaking_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fail(**kwargs: object) -> dict[str, object]:
        raise DatabaseError("secret database connection details")

    monkeypatch.setattr(
        activate_creation_evidence_settings, "activate_runtime_profile_patch", _fail
    )
    command = activate_creation_evidence_settings.Command(stdout=StringIO())

    with pytest.raises(CommandError) as caught:
        command.handle(
            environment="staging",
            actor="operator-1",
            reason="activation",
            ttl_seconds=300,
            allocation_recorder_service_id="a",
            physical_v2_recorder_service_id="b",
            allocated_v3_recorder_service_id="c",
            binding_recorder_service_id="d",
        )

    assert str(caught.value) == "creation evidence settings activation failed"
    assert "secret database" not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__ is True
    rendered = "".join(traceback.format_exception(caught.value))
    assert "secret database" not in rendered
    assert "During handling of the above exception" not in rendered
