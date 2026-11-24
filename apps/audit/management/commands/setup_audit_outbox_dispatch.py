"""Configure the explicitly enabled, database-backed audit outbox dispatch schedule."""

from __future__ import annotations

import json
from functools import partial

from celery import current_app
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction
from django_celery_beat.models import IntervalSchedule, PeriodicTask

SCHEDULE_NAME = "audit-outbox-dispatch"
TASK_PATH = "apps.audit.application.tasks.dispatch_system_audit_outbox_task"


def _interval(seconds: int) -> IntervalSchedule:
    # Beat allows multiple equivalent interval rows. Reuse one without mutating it.
    existing = (
        IntervalSchedule.objects.filter(every=seconds, period=IntervalSchedule.SECONDS)
        .order_by("pk")
        .first()
    )
    if existing is not None:
        return existing
    return IntervalSchedule.objects.create(every=seconds, period=IntervalSchedule.SECONDS)


def _check_task(row: PeriodicTask) -> None:
    if row.task != TASK_PATH:
        raise CommandError(f"Schedule name {SCHEDULE_NAME} belongs to a different task.")


def _existing_kwargs(row: PeriodicTask) -> dict[str, object]:
    try:
        args, kwargs, headers = (json.loads(text) for text in (row.args, row.kwargs, row.headers))
    except (TypeError, ValueError) as exc:
        raise CommandError(f"Schedule {SCHEDULE_NAME} has incompatible JSON arguments.") from exc
    overrides = (
        row.one_off,
        row.start_time,
        row.expires,
        row.expire_seconds is not None,
        row.queue and row.queue != current_app.amqp.router.route({}, TASK_PATH)["queue"].name,
        row.exchange,
        row.routing_key,
        row.priority is not None,
        headers != {},
        args != [],
    )
    if (
        row.interval_id is None
        or any(overrides)
        or not isinstance(kwargs, dict)
        or not kwargs.keys() <= {"limit", "worker_id"}
    ):
        raise CommandError(
            f"Schedule {SCHEDULE_NAME} has incompatible timing, arguments or routing."
        )
    return kwargs


def _disable() -> str:
    row = PeriodicTask.objects.select_for_update().filter(name=SCHEDULE_NAME).first()
    if row is None:
        return "absent"
    _check_task(row)
    if row.enabled:
        row.enabled = False
        row.save(update_fields=("enabled", "last_run_at", "date_changed"))
    return "disabled"


def _enable(seconds: int, limit: int, worker_id: str) -> str:
    if (
        PeriodicTask.objects.filter(task=TASK_PATH, enabled=True)
        .exclude(name=SCHEDULE_NAME)
        .exists()
    ):
        raise CommandError("Another enabled schedule already dispatches the audit outbox.")
    parameters: dict[str, object] = {"limit": limit, "worker_id": worker_id}
    kwargs = json.dumps(parameters, sort_keys=True)
    tasks = PeriodicTask.objects.select_for_update()
    try:
        row, created = tasks.get_or_create(
            name=SCHEDULE_NAME,
            defaults={
                "task": TASK_PATH,
                "interval": partial(_interval, seconds),
                "kwargs": kwargs,
                "enabled": True,
            },
        )
    except ValidationError:
        # Beat checks the unique name before INSERT. A concurrent creator may win there.
        row = tasks.filter(name=SCHEDULE_NAME).first()
        if row is None:
            raise
        created = False
    if created:
        return "enabled"
    _check_task(row)
    existing_kwargs = _existing_kwargs(row)
    changes: list[str] = []
    if row.interval.every != seconds or row.interval.period != IntervalSchedule.SECONDS:
        row.interval = _interval(seconds)
        changes.append("interval")
    # JSON distinguishes booleans/floats from integer batch limits; Python equality does not.
    if json.dumps(existing_kwargs, sort_keys=True) != kwargs:
        row.kwargs = kwargs
        changes.append("kwargs")
    if not row.enabled:
        row.enabled = True
        changes.append("enabled")
    if changes:
        row.save(update_fields=[*changes, "date_changed"])
    return "enabled"


class Command(BaseCommand):
    """Enable, reconfigure or stop the named audit dispatch schedule."""

    help = "Explicitly enable or disable periodic audit outbox dispatch in DatabaseScheduler."

    def add_arguments(self, parser: CommandParser) -> None:
        """Require an operation and expose the operator-controlled settings."""
        # call_command() represents required keyword switches as flags even for False.
        # Keep CLI exclusivity here and enforce an explicit boolean action in handle().
        state = parser.add_mutually_exclusive_group()
        state.add_argument(
            "--enable", action="store_true", help="Set the interval and dispatch parameters."
        )
        state.add_argument(
            "--disable", action="store_true", help="Stop future dispatch from the named schedule."
        )
        parser.add_argument("--interval-seconds", type=int)
        parser.add_argument(
            "--limit", type=int, help="Maximum number of events per dispatch (1 to 100)."
        )
        parser.add_argument("--worker-id", help="Stable dispatch identity used for outbox claims.")

    def handle(self, *args: object, **options: object) -> None:
        """Save the explicit schedule operation without dispatching directly."""
        enable = options.get("enable", False)
        disable = options.get("disable", False)
        if not isinstance(enable, bool) or not isinstance(disable, bool) or enable == disable:
            raise CommandError("Select exactly one boolean action: --enable or --disable.")
        seconds, limit, worker_id = (
            options.get(key) for key in ("interval_seconds", "limit", "worker_id")
        )
        if disable:
            if any(value is not None for value in (seconds, limit, worker_id)):
                raise CommandError("--disable takes no dispatch parameters.")
            with transaction.atomic():
                result = _disable()
        else:
            if (
                isinstance(seconds, bool)
                or not isinstance(seconds, int)
                or not 1 <= seconds <= 2_147_483_647
            ):
                raise CommandError("--interval-seconds must be a positive database integer.")
            if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
                raise CommandError("--limit must be between 1 and 100.")
            if not isinstance(worker_id, str) or not worker_id.strip() or len(worker_id) > 128:
                raise CommandError("--worker-id must be nonblank and at most 128 characters.")
            with transaction.atomic():
                result = _enable(seconds, limit, worker_id)
        self.stdout.write(f"{SCHEDULE_NAME}: {result}")
