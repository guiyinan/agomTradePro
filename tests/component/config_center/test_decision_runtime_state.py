"""Persistent decision-runtime maintenance state contracts."""

from datetime import UTC, datetime
from io import StringIO

import pytest
from django.core.management import call_command

from apps.config_center.application.use_cases import (
    GetDecisionRuntimeStateUseCase,
    UpdateDecisionRuntimeStateUseCase,
)
from apps.config_center.domain.entities import DecisionRuntimeStatus


@pytest.mark.django_db
def test_decision_runtime_defaults_to_active_without_creating_settings() -> None:
    from apps.config_center.infrastructure.decision_runtime_models import DecisionRuntimeStateModel
    from apps.config_center.infrastructure.models import SystemSettingsModel

    state = GetDecisionRuntimeStateUseCase().execute()

    assert state.status is DecisionRuntimeStatus.ACTIVE
    assert state.must_not_use_for_decision is False
    assert SystemSettingsModel._default_manager.count() == 0
    assert DecisionRuntimeStateModel._default_manager.count() == 0


@pytest.mark.django_db
def test_decision_runtime_maintenance_persists_across_reads() -> None:
    changed_at = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)

    from apps.config_center.infrastructure.models import SystemSettingsModel

    legacy = SystemSettingsModel.get_settings()
    legacy_status = legacy.decision_runtime_status

    updated = UpdateDecisionRuntimeStateUseCase().execute(
        status="maintenance",
        reason="全市场核心数据重建中",
        changed_by="deploy:codex",
        release_ref="7061cd11",
        changed_at=changed_at,
    )
    reloaded = GetDecisionRuntimeStateUseCase().execute()

    assert updated.status is DecisionRuntimeStatus.MAINTENANCE
    assert reloaded == updated
    assert reloaded.must_not_use_for_decision is True
    assert reloaded.block_reason_code == "decision_runtime_maintenance"

    from apps.config_center.infrastructure.decision_runtime_models import DecisionRuntimeStateModel

    persisted = DecisionRuntimeStateModel._default_manager.get(pk=1)
    assert persisted.status == "maintenance"
    assert persisted.reason == "全市场核心数据重建中"
    legacy.refresh_from_db()
    assert legacy.decision_runtime_status == legacy_status


@pytest.mark.django_db
def test_decision_runtime_reads_legacy_singleton_before_state_row_exists() -> None:
    from apps.config_center.infrastructure.decision_runtime_models import DecisionRuntimeStateModel
    from apps.config_center.infrastructure.models import SystemSettingsModel

    legacy = SystemSettingsModel.get_settings()
    legacy.decision_runtime_status = "maintenance"
    legacy.decision_runtime_reason = "legacy compatibility state"
    legacy.save(update_fields=["decision_runtime_status", "decision_runtime_reason", "updated_at"])

    state = GetDecisionRuntimeStateUseCase().execute()

    assert state.status is DecisionRuntimeStatus.MAINTENANCE
    assert state.reason == "legacy compatibility state"
    assert DecisionRuntimeStateModel._default_manager.count() == 0


@pytest.mark.django_db
def test_non_active_decision_runtime_requires_reason() -> None:
    with pytest.raises(ValueError, match="reason"):
        UpdateDecisionRuntimeStateUseCase().execute(
            status="blocked",
            reason="",
            changed_by="test",
        )


@pytest.mark.django_db
def test_decision_runtime_rejects_unknown_status() -> None:
    with pytest.raises(ValueError, match="Unsupported"):
        UpdateDecisionRuntimeStateUseCase().execute(
            status="green",
            reason="invalid",
            changed_by="test",
        )


@pytest.mark.django_db
def test_management_command_sets_maintenance_gate() -> None:
    stdout = StringIO()

    call_command(
        "set_decision_runtime_state",
        "maintenance",
        reason="production backfill",
        changed_by="deploy:test",
        release_ref="abc123",
        stdout=stdout,
    )

    state = GetDecisionRuntimeStateUseCase().execute()
    assert state.status is DecisionRuntimeStatus.MAINTENANCE
    assert state.release_ref == "abc123"
    assert "maintenance" in stdout.getvalue()
