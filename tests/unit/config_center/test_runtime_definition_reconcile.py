from __future__ import annotations

from datetime import UTC, datetime
from io import StringIO

import pytest
from django.core.management.base import CommandError

from apps.config_center.application.runtime_config import RuntimeConfigService
from apps.config_center.application.runtime_definition_reconcile import (
    DEFAULT_RUNTIME_DEFINITIONS,
    reconcile_runtime_definitions,
)
from apps.config_center.domain.runtime_config import (
    RuntimeConfigDefinition,
    RuntimeConfigProfile,
    RuntimeConfigValue,
    RuntimeProfileStatus,
)
from apps.config_center.management.commands import initialize_runtime_definitions

NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)


class _DefinitionRepository:
    def __init__(self) -> None:
        self.items: dict[str, RuntimeConfigDefinition] = {}

    def list_all(self) -> list[RuntimeConfigDefinition]:
        return list(self.items.values())

    def get(self, key: str) -> RuntimeConfigDefinition | None:
        return self.items.get(key)

    def save(self, definition: RuntimeConfigDefinition) -> RuntimeConfigDefinition:
        self.items[definition.key] = definition
        return definition


def test_runtime_definition_reconcile_is_idempotent() -> None:
    repository = _DefinitionRepository()

    first = reconcile_runtime_definitions(repository)
    second = reconcile_runtime_definitions(repository)

    assert first == second == DEFAULT_RUNTIME_DEFINITIONS
    assert list(repository.items) == [definition.key for definition in DEFAULT_RUNTIME_DEFINITIONS]


class _ProfileRepository:
    def __init__(self, profile: RuntimeConfigProfile) -> None:
        self.profile = profile

    def get_active(self, environment: str) -> RuntimeConfigProfile | None:
        return self.profile if self.profile.environment == environment else None


class _ValueRepository:
    def __init__(self, values: list[RuntimeConfigValue]) -> None:
        self.values = values

    def list_for_profile(self, profile_id: str) -> list[RuntimeConfigValue]:
        return [value for value in self.values if value.profile_id == profile_id]


def test_active_profile_passes_reconciled_definition_validation() -> None:
    profile = RuntimeConfigProfile(
        profile_id="profile-1",
        profile_key="development",
        environment="development",
        version=1,
        status=RuntimeProfileStatus.ACTIVE,
        content_hash="hash",
        created_at=NOW,
        activated_at=NOW,
    )
    value = RuntimeConfigValue(
        profile_id=profile.profile_id,
        definition_key=DEFAULT_RUNTIME_DEFINITIONS[0].key,
        value_json=0.025,
    )
    service = RuntimeConfigService(
        _DefinitionRepositoryWithDefaults(),
        _ProfileRepository(profile),
        _ValueRepository([value]),
        revisions=object(),
        snapshots=object(),
    )

    report = service.validate_active_profile("development")

    assert report["valid"] is True
    assert report["validated"] == 1
    assert report["errors"] == ()


def test_active_profile_reports_missing_critical_definition() -> None:
    profile = RuntimeConfigProfile(
        profile_id="profile-1",
        profile_key="development",
        environment="development",
        version=1,
        status=RuntimeProfileStatus.ACTIVE,
        content_hash="hash",
        created_at=NOW,
        activated_at=NOW,
    )
    service = RuntimeConfigService(
        _DefinitionRepositoryWithDefaults(),
        _ProfileRepository(profile),
        _ValueRepository([]),
        revisions=object(),
        snapshots=object(),
    )

    report = service.validate_active_profile("development")

    assert report["valid"] is False
    assert report["errors"] == (
        "missing_critical_definition:data_center.provider.failover_tolerance",
    )


class _DefinitionRepositoryWithDefaults(_DefinitionRepository):
    def __init__(self) -> None:
        super().__init__()
        self.items = {item.key: item for item in DEFAULT_RUNTIME_DEFINITIONS}


def test_initialize_runtime_definitions_command_checks_active_profile(monkeypatch) -> None:
    command = initialize_runtime_definitions.Command()
    command.stdout = StringIO()
    monkeypatch.setattr(
        initialize_runtime_definitions,
        "reconcile_runtime_definitions",
        lambda: DEFAULT_RUNTIME_DEFINITIONS,
    )
    monkeypatch.setattr(
        initialize_runtime_definitions,
        "validate_active_runtime_profile",
        lambda environment: {
            "valid": True,
            "profile_key": environment,
            "profile_version": 1,
            "errors": (),
        },
    )

    command.handle(check_environment="development")

    assert "Reconciled runtime definitions" in command.stdout.getvalue()
    assert "Active runtime profile valid: development v1" in command.stdout.getvalue()


def test_initialize_runtime_definitions_command_blocks_invalid_active_profile(monkeypatch) -> None:
    command = initialize_runtime_definitions.Command()
    command.stdout = StringIO()
    monkeypatch.setattr(
        initialize_runtime_definitions,
        "reconcile_runtime_definitions",
        lambda: DEFAULT_RUNTIME_DEFINITIONS,
    )
    monkeypatch.setattr(
        initialize_runtime_definitions,
        "validate_active_runtime_profile",
        lambda _environment: {"valid": False, "errors": ("active_profile_missing",)},
    )

    with pytest.raises(CommandError, match="active_profile_missing"):
        command.handle(check_environment="production")
