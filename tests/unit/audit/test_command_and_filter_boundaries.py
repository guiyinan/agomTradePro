"""Audit command and template-filter boundary invariants."""

from __future__ import annotations

from datetime import timedelta
from io import StringIO

import pytest
from django.core.management.base import CommandError
from django.utils import timezone

from apps.audit.infrastructure.models import OperationLogModel
from apps.audit.management.commands import cleanup_operation_logs, init_indicator_thresholds
from apps.audit.templatetags.audit_filters import absolute_width, percentage


@pytest.mark.parametrize(
    ("options", "message"),
    (
        ({"days": 0, "dry_run": True, "batch_size": 100}, "days"),
        ({"days": True, "dry_run": True, "batch_size": 100}, "days"),
        ({"days": 90, "dry_run": "true", "batch_size": 100}, "dry-run"),
        ({"days": 90, "dry_run": True, "batch_size": 0}, "batch-size"),
    ),
)
def test_cleanup_command_rejects_invalid_dynamic_options(
    options: dict[str, object], message: str
) -> None:
    """Programmatic callers cannot bypass retention and batch bounds."""

    with pytest.raises(CommandError, match=message):
        cleanup_operation_logs.Command(stdout=StringIO()).handle(**options)


def test_threshold_seed_command_rejects_truthy_non_boolean_refresh() -> None:
    """Dynamic callers cannot accidentally enable destructive refresh mode."""

    with pytest.raises(CommandError, match="refresh"):
        init_indicator_thresholds.Command(stdout=StringIO()).handle(refresh="yes")


@pytest.mark.django_db
def test_cleanup_command_preserves_recent_and_dry_run_evidence() -> None:
    """Retention cleanup deletes only expired rows and honors dry-run."""

    old_log = OperationLogModel._default_manager.create(
        request_id="old-evidence",
        username="auditor",
        operation_type="READ",
        module="audit",
        action="READ",
    )
    recent_log = OperationLogModel._default_manager.create(
        request_id="recent-evidence",
        username="auditor",
        operation_type="READ",
        module="audit",
        action="READ",
    )
    OperationLogModel._default_manager.filter(pk=old_log.pk).update(
        timestamp=timezone.now() - timedelta(days=91)
    )

    command = cleanup_operation_logs.Command(stdout=StringIO())
    command.handle(days=90, dry_run=True, batch_size=1)
    assert OperationLogModel._default_manager.filter(pk=old_log.pk).exists()

    command.handle(days=90, dry_run=False, batch_size=1)
    assert not OperationLogModel._default_manager.filter(pk=old_log.pk).exists()
    assert OperationLogModel._default_manager.filter(pk=recent_log.pk).exists()


@pytest.mark.parametrize("value", (float("nan"), float("inf"), "secret"))
def test_percentage_rejects_nonfinite_or_invalid_values(value: object) -> None:
    assert percentage(value) == "-"


def test_template_filter_format_bounds_are_enforced() -> None:
    assert percentage(0.5, 10_000) == "-"
    assert absolute_width(float("nan")) == "0"
    assert absolute_width(1, -1) == "0"
