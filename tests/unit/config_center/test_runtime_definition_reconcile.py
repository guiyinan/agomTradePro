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


def test_provider_default_source_is_typed_enum_definition() -> None:
    definition = next(
        item
        for item in DEFAULT_RUNTIME_DEFINITIONS
        if item.key == "data_center.provider.default_source"
    )

    assert definition.value_type.value == "enum"
    assert definition.constraints["choices"] == ["akshare", "tushare", "failover"]


def test_backup_retention_is_bounded_typed_runtime_definition() -> None:
    definition = next(
        item for item in DEFAULT_RUNTIME_DEFINITIONS if item.key == "task_monitor.retention_days"
    )

    assert definition.value_type.value == "int"
    assert definition.owner_app == "task_monitor"
    assert definition.constraints == {"minimum": 1, "maximum": 3650}


def test_backup_delivery_definitions_are_typed() -> None:
    definitions = {
        item.key: item for item in DEFAULT_RUNTIME_DEFINITIONS if item.namespace == "backup"
    }

    assert set(definitions) == {
        "backup.enabled",
        "backup.recipient_email",
        "backup.app_base_url",
        "backup.mail_from_email",
        "backup.smtp_host",
        "backup.smtp_port",
        "backup.smtp_username",
        "backup.smtp_use_tls",
        "backup.smtp_use_ssl",
        "backup.interval_days",
        "backup.link_ttl_days",
        "backup.password_hint",
        "backup.archive_password",
        "backup.smtp_password",
    }
    assert definitions["backup.smtp_port"].constraints == {
        "minimum": 1,
        "maximum": 65535,
    }
    assert definitions["backup.archive_password"].secret is True
    assert definitions["backup.smtp_password"].secret is True


def test_account_runtime_definitions_are_bounded_and_typed() -> None:
    definitions = {
        item.key: item for item in DEFAULT_RUNTIME_DEFINITIONS if item.namespace == "account"
    }

    assert set(definitions) == {
        "account.require_user_approval",
        "account.auto_approve_first_admin",
        "account.default_mcp_enabled",
        "account.allow_token_plaintext_view",
        "account.user_agreement_content",
        "account.risk_warning_content",
        "account.notes",
    }
    assert all(item.owner_app == "account" for item in definitions.values())
    assert all(item.value_type.value in {"bool", "string"} for item in definitions.values())


def test_system_audit_runtime_definitions_are_critical_and_typed() -> None:
    definitions = {
        item.key: item for item in DEFAULT_RUNTIME_DEFINITIONS if item.namespace == "audit"
    }

    assert set(definitions) == {
        "audit.system_event.mode",
        "audit.system_event.outbox_enabled",
        "audit.system_event.authority_selector",
    }
    assert all(item.owner_app == "audit" for item in definitions.values())
    assert all(item.criticality.value == "critical" for item in definitions.values())
    assert all(item.reload_mode.value == "next_task" for item in definitions.values())
    assert definitions["audit.system_event.mode"].value_type.value == "enum"
    assert definitions["audit.system_event.mode"].constraints == {
        "choices": ["off", "shadow", "required"]
    }
    assert definitions["audit.system_event.outbox_enabled"].value_type.value == "bool"
    assert definitions["audit.system_event.authority_selector"].value_type.value == "typed_json"


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
    values = [
        RuntimeConfigValue(
            profile_id=profile.profile_id,
            definition_key="data_center.provider.failover_tolerance",
            value_json=0.025,
        ),
        RuntimeConfigValue(
            profile_id=profile.profile_id,
            definition_key="audit.system_event.mode",
            value_json="shadow",
        ),
        RuntimeConfigValue(
            profile_id=profile.profile_id,
            definition_key="audit.system_event.outbox_enabled",
            value_json=False,
        ),
        RuntimeConfigValue(
            profile_id=profile.profile_id,
            definition_key="audit.system_event.authority_selector",
            value_json={
                "actor_source_id": "actor-source",
                "actor_source_version": "v1",
                "actor_content_hash": "a" * 64,
                "scope_source_id": "scope-source",
                "scope_source_version": "v1",
                "scope_content_hash": "b" * 64,
            },
        ),
    ]
    service = RuntimeConfigService(
        _DefinitionRepositoryWithDefaults(),
        _ProfileRepository(profile),
        _ValueRepository(values),
        revisions=object(),
        snapshots=object(),
    )

    report = service.validate_active_profile("development")

    assert report["valid"] is True
    assert report["validated"] == 4
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
        "missing_critical_definition:audit.system_event.mode",
        "missing_critical_definition:audit.system_event.outbox_enabled",
        "missing_critical_definition:audit.system_event.authority_selector",
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
