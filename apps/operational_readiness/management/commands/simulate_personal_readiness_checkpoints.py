from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.operational_readiness.infrastructure import (
    auto_advisor_weekly_scheduler_status as weekly_status,
)
from apps.operational_readiness.management.commands import (
    show_personal_readiness_status as status_command,
)

DEFAULT_SIMULATED_CLOCKS = (
    "15:50:00",
    "16:20:00",
    "17:20:00",
    "17:45:00",
)


class Command(BaseCommand):
    help = "Dry-run personal readiness checkpoint timing without changing system time."

    def add_arguments(self, parser: CommandParser) -> None:
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
                "Defaults cover 15:50, 16:20, 17:20, and 17:45 on the target date."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        target_date = date.fromisoformat(str(options["target_date"]))
        times = tuple(options.get("times") or _default_simulated_times(target_date))
        payload = simulate_checkpoints(target_date=target_date, times=times)
        self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))


def simulate_checkpoints(*, target_date: date, times: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(target_date, date):
        raise CommandError("target_date must be a date")
    if not times:
        raise CommandError("at least one simulated checkpoint time is required")
    validation = {"next_required_date": target_date.isoformat()}
    next_action = {"target_date": target_date.isoformat()}
    daily_scheduler = status_command._collect_scheduler_status()
    quote_scheduler = status_command._collect_quote_pre_readiness_scheduler_status()
    checkpoints = []
    for time_text in times:
        try:
            now = datetime.fromisoformat(time_text)
        except (TypeError, ValueError) as exc:
            raise CommandError("simulated checkpoint time must be ISO datetime") from exc
        if now.tzinfo is None or now.utcoffset() is None:
            raise CommandError("simulated checkpoint time must be timezone-aware")
        if now.date() != target_date:
            raise CommandError("simulated checkpoint time must match target_date")
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


def _default_simulated_times(target_date: date) -> tuple[str, ...]:
    return tuple(f"{target_date.isoformat()}T{clock}+08:00" for clock in DEFAULT_SIMULATED_CLOCKS)
