"""Task Monitor Admin typing and evidence immutability regressions."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast

from django.contrib import admin

from apps.task_monitor.interface.admin import TaskAlertAdmin, TaskExecutionAdmin
from apps.task_monitor.models import TaskAlertModel, TaskExecutionModel
from shared.infrastructure.django_admin import TypedModelAdmin


def test_task_monitor_models_use_typed_admins() -> None:
    """Django autodiscovery retains one typed owner for both operations models."""

    expected = {
        TaskExecutionModel: TaskExecutionAdmin,
        TaskAlertModel: TaskAlertAdmin,
    }
    for model, admin_class in expected.items():
        assert admin.site.is_registered(model)
        assert isinstance(admin.site._registry[model], admin_class)
        assert issubclass(admin_class, TypedModelAdmin)


def test_task_execution_and_alert_evidence_are_fully_immutable() -> None:
    """Admin cannot fabricate, alter, or delete task history and alerts."""

    for model in (TaskExecutionModel, TaskAlertModel):
        evidence_admin = admin.site._registry[model]
        assert evidence_admin.has_add_permission(None) is False
        assert evidence_admin.has_change_permission(None) is False
        assert evidence_admin.has_delete_permission(None) is False


def test_task_monitor_badges_escape_content_and_publish_ordering_metadata() -> None:
    """Badge renderers keep stable colors while escaping dynamic display labels."""

    execution_admin = cast(TaskExecutionAdmin, admin.site._registry[TaskExecutionModel])
    alert_admin = cast(TaskAlertAdmin, admin.site._registry[TaskAlertModel])
    execution = cast(
        TaskExecutionModel,
        SimpleNamespace(
            status="failure",
            priority="critical",
            get_status_display=lambda: "<failure>",
            get_priority_display=lambda: "critical",
        ),
    )
    alert = cast(
        TaskAlertModel,
        SimpleNamespace(level="critical", get_level_display=lambda: "<critical>"),
    )

    assert "&lt;failure&gt;" in str(execution_admin.status_colored(execution))
    assert "critical" in str(execution_admin.priority_colored(execution))
    assert "&lt;critical&gt;" in str(alert_admin.level_colored(alert))
    assert TaskExecutionAdmin.status_colored.admin_order_field == "status"
    assert TaskAlertAdmin.level_colored.admin_order_field == "level"
