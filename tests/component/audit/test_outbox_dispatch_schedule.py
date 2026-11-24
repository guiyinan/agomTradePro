"""Operator-controlled scheduling for the governed audit outbox dispatcher."""

import json
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from django_celery_beat.models import IntervalSchedule, PeriodicTask, PeriodicTasks
from django_celery_beat.schedulers import ModelEntry

from apps.task_monitor.management.commands.init_scheduler_defaults import SCHEDULER_COMMANDS
from core.settings.celery_schedule import CELERY_BEAT_SCHEDULE

COMMAND = "setup_audit_outbox_dispatch"
NAME = "audit-outbox-dispatch"
TASK = "apps.audit.application.tasks.dispatch_system_audit_outbox_task"

pytestmark = pytest.mark.django_db


def enable(**options: object) -> None:
    """Explicitly configure the scheduler using an operator-provided batch scope."""
    defaults: dict[str, object] = {"interval_seconds": 600, "limit": 3, "worker_id": "ops-audit-a"}
    call_command(COMMAND, "--enable", **(defaults | options))


def test_deployment_enables_once_and_preserves_operator_tuning() -> None:
    call_command(COMMAND, "--ensure-enabled")
    row = PeriodicTask.objects.get(name=NAME, task=TASK)
    assert row.enabled and row.interval.schedule.run_every == timedelta(minutes=5)
    assert ModelEntry(row).kwargs == {"limit": 1, "worker_id": "audit-dispatch-01"}
    enable()
    call_command(COMMAND, "--disable")
    call_command(COMMAND, "--ensure-enabled")
    row.refresh_from_db()
    assert row.enabled and row.interval.schedule.run_every == timedelta(minutes=10)
    assert ModelEntry(row).kwargs == {"limit": 3, "worker_id": "ops-audit-a"}
    marker = PeriodicTasks.last_change()
    call_command(COMMAND, "--ensure-enabled")
    assert PeriodicTasks.last_change() == marker
    assert PeriodicTask.objects.filter(task=TASK).count() == 1


def test_deployment_rejects_an_invalid_stopped_schedule_atomically() -> None:
    enable()
    call_command(COMMAND, "--disable")
    PeriodicTask.objects.filter(name=NAME).update(kwargs='{"worker_id":"ops","limit":true}')
    with pytest.raises(CommandError):
        call_command(COMMAND, "--ensure-enabled")
    assert not PeriodicTask.objects.get(name=NAME).enabled


def test_schedule_lifecycle_preserves_history_and_idempotent_beat_marker() -> None:
    assert COMMAND not in SCHEDULER_COMMANDS
    assert TASK not in {entry["task"] for entry in CELERY_BEAT_SCHEDULE.values()}
    call_command(COMMAND, "--disable")
    assert not PeriodicTask.objects.filter(name=NAME).exists()
    assert not IntervalSchedule.objects.exists()
    enable()
    row = PeriodicTask.objects.get(name=NAME, task=TASK)
    assert row.enabled and row.interval.every == 600 and row.interval.period == "seconds"
    assert json.loads(row.args) == []
    assert json.loads(row.kwargs) == {"worker_id": "ops-audit-a", "limit": 3}
    entry = ModelEntry(row)
    assert entry.task == TASK and entry.args == [] and entry.kwargs == json.loads(row.kwargs)
    assert entry.schedule.run_every == timedelta(seconds=600)
    last = timezone.now() - timedelta(minutes=2)
    PeriodicTask.objects.filter(pk=row.pk).update(total_run_count=4, last_run_at=last)
    marker = PeriodicTasks.last_change()
    enable()
    assert PeriodicTasks.last_change() == marker
    row.refresh_from_db()
    assert row.last_run_at == last and row.total_run_count == 4

    enable(interval_seconds=900, limit=1, worker_id="ops-audit-b")
    row.refresh_from_db()
    assert row.interval.every == 900 and json.loads(row.kwargs) == {
        "worker_id": "ops-audit-b",
        "limit": 1,
    }
    assert row.total_run_count == 4 and row.last_run_at == last
    call_command(COMMAND, "--disable")
    row.refresh_from_db()
    assert not row.enabled and row.interval.every == 900 and row.total_run_count == 4
    assert json.loads(row.kwargs) == {"worker_id": "ops-audit-b", "limit": 1}
    marker = PeriodicTasks.last_change()
    call_command(COMMAND, "--disable")
    assert PeriodicTasks.last_change() == marker
    assert PeriodicTask.objects.filter(task=TASK).count() == 1


@pytest.mark.parametrize(
    "args",
    [
        (),
        ("--enable",),
        ("--enable", "--interval-seconds", "0", "--limit", "1", "--worker-id", "a"),
        ("--enable", "--interval-seconds", "3", "--limit", "101", "--worker-id", "a"),
        ("--enable", "--interval-seconds", "3", "--limit", "1", "--worker-id", " "),
        ("--enable", "--interval-seconds", "3", "--limit", "1", "--worker-id", "a" * 129),
        ("--disable", "--enable"),
        ("--disable", "--interval-seconds", "3"),
        ("--ensure-enabled", "--limit", "1"),
        ("--ensure-enabled", "--disable"),
    ],
)
def test_invalid_scope_has_no_scheduler_side_effects(args: tuple[str, ...]) -> None:
    with pytest.raises(CommandError):
        call_command(COMMAND, *args)
    assert not PeriodicTask.objects.filter(name=NAME).exists()
    assert not IntervalSchedule.objects.exists()


@pytest.mark.parametrize(
    "switches",
    [{"enable": False}, {"disable": False}, {"enable": "yes"}, {"enable": 1}, {"disable": 1}],
)
def test_programmatic_command_requires_an_explicit_boolean_action(
    switches: dict[str, object],
) -> None:
    with CaptureQueriesContext(connection) as queries, pytest.raises(CommandError):
        call_command(COMMAND, interval_seconds=600, limit=1, worker_id="ops", **switches)
    assert len(queries) == 0
    assert not PeriodicTask.objects.exists()
    assert not IntervalSchedule.objects.exists()
    assert not PeriodicTasks.objects.exists()


def test_conflicting_schedule_is_neither_overwritten_nor_duplicated() -> None:
    interval = IntervalSchedule.objects.create(every=120, period="seconds")
    other = PeriodicTask.objects.create(name=NAME, task="other.task", interval=interval)
    for action in (enable, lambda: call_command(COMMAND, "--disable")):
        with pytest.raises(CommandError):
            action()
    other.refresh_from_db()
    assert other.task == "other.task" and other.enabled
    other.name = "independently-managed"
    other.task = TASK
    other.save()
    with pytest.raises(CommandError):
        enable()
    assert list(PeriodicTask.objects.filter(task=TASK).values_list("name", flat=True)) == [
        other.name
    ]


@pytest.mark.parametrize(
    "overrides",
    [
        {"kwargs": '{"as_of":"2000-01-01T00:00:00Z"}'},
        {"queue": "wrong-queue"},
        {"args": "malformed"},
    ],
)
def test_existing_nonstandard_schedule_requires_operator_reconciliation(
    overrides: dict[str, str],
) -> None:
    interval = IntervalSchedule.objects.create(every=90, period="seconds")
    row = PeriodicTask.objects.create(name=NAME, task=TASK, interval=interval, **overrides)
    with pytest.raises(CommandError, match="incompatible"):
        enable()
    row.refresh_from_db()
    assert row.interval_id == interval.pk
    assert all(getattr(row, k) == v for k, v in overrides.items())
    call_command(COMMAND, "--disable")
    row.refresh_from_db()
    assert not row.enabled


def test_duplicate_interval_rows_are_reused_without_modifying_other_schedules() -> None:
    old = IntervalSchedule.objects.create(every=600, period="seconds")
    IntervalSchedule.objects.create(every=600, period="seconds")
    other = PeriodicTask.objects.create(name="consumer", task="other.task", interval=old)
    enable()
    assert PeriodicTask.objects.get(name=NAME).interval_id == old.pk
    enable(interval_seconds=1200)
    other.refresh_from_db()
    assert other.interval_id == old.pk and other.interval.every == 600


def test_existing_explicit_default_queue_is_preserved() -> None:
    interval = IntervalSchedule.objects.create(every=90, period="seconds")
    row = PeriodicTask.objects.create(name=NAME, task=TASK, interval=interval, queue="celery")
    enable()
    row.refresh_from_db()
    assert row.queue == "celery" and row.interval.every == 600 and row.enabled


def test_programmatic_command_accepts_both_explicit_boolean_switches() -> None:
    call_command(COMMAND, enable=True, disable=False, interval_seconds=60, limit=1, worker_id="ops")
    assert PeriodicTask.objects.get(name=NAME).enabled
    call_command(COMMAND, enable=False, disable=True)
    assert not PeriodicTask.objects.get(name=NAME).enabled


@pytest.mark.parametrize("legacy_limit", [True, 1.0])
def test_explicit_config_repairs_non_integer_batch_size(legacy_limit: bool | float) -> None:
    interval = IntervalSchedule.objects.create(every=600, period="seconds")
    row = PeriodicTask.objects.create(
        name=NAME,
        task=TASK,
        interval=interval,
        kwargs=json.dumps({"limit": legacy_limit, "worker_id": "ops-audit-a"}),
    )
    enable(limit=1)
    row.refresh_from_db()
    assert type(json.loads(row.kwargs)["limit"]) is int
