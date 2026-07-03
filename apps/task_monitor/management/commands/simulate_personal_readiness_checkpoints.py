from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from django.core.management.base import BaseCommand

from apps.task_monitor.management import auto_advisor_weekly_scheduler_status as weekly_status
from apps.task_monitor.management.commands import show_personal_readiness_status as status_command

DEFAULT_SIMULATED_TIMES = (
    "2026-07-03T15:50:00+08:00",
    "2026-07-03T16:20:00+08:00",
    "2026-07-03T17:20:00+08:00",
    "2026-07-03T17:45:00+08:00",
)


class Command(BaseCommand):
    help = "Dry-run personal readiness checkpoint timing without changing system time."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--target-date",
            default="2026-07-03",
            help="Readiness target date in YYYY-MM-DD format. Default: 2026-07-03.",
        )
        parser.add_argument(
            "--time",
            action="append",
            dest="times",
            help=(
                "Simulated ISO datetime. Can be repeated. "
                "Defaults cover 15:50, 16:20, 17:20, and 17:45 on 2026-07-03."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        target_date = date.fromisoformat(str(options["target_date"]))
        times = tuple(options.get("times") or DEFAULT_SIMULATED_TIMES)
        payload = simulate_checkpoints(target_date=target_date, times=times)
        self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))


def simulate_checkpoints(*, target_date: date, times: tuple[str, ...]) -> dict[str, Any]:
    validation = {"next_required_date": target_date.isoformat()}
    next_action = {"target_date": target_date.isoformat()}
    daily_scheduler = status_command._collect_scheduler_status()
    quote_scheduler = status_command._collect_quote_pre_readiness_scheduler_status()
    checkpoints = []
    for time_text in times:
        now = datetime.fromisoformat(time_text)
        quote = status_command._with_quote_pre_readiness_schedule_expectation(
            scheduler=quote_scheduler,
            validation=validation,
            next_action=next_action,
            now=now,
        )
        daily = status_command._build_schedule_expectation(
            validation=validation,
            scheduler=daily_scheduler,
            next_action=next_action,
            now=now,
        )
        weekly = weekly_status.build_auto_advisor_weekly_due_status(
            target_date=target_date,
            now=now,
        )
        checkpoints.append(
            {
                "now": now.isoformat(),
                "quote_pre_readiness": quote.get("schedule_expectation"),
                "daily_readiness": daily,
                "weekly_auto_advisor": weekly,
            }
        )
    return {
        "mode": "simulation",
        "target_date": target_date.isoformat(),
        "mutates_state": False,
        "generates_evidence": False,
        "checkpoints": checkpoints,
    }
