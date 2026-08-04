"""Run resumable active-A-share core-data batches synchronously."""

from __future__ import annotations

import json
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.data_center.application.tasks import (
    backfill_active_a_share_core_data_batch_task,
)


class Command(BaseCommand):
    """Execute bounded batches and print a restartable checkpoint after each one."""

    help = "Backfill quote, history, valuation, and financial facts for active A-shares."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--resume-offset", type=int, default=0)
        parser.add_argument("--batch-size", type=int, default=50)
        parser.add_argument("--source", default="tushare")
        parser.add_argument("--history-days", type=int, default=756)
        parser.add_argument("--financial-periods", type=int, default=8)
        parser.add_argument("--max-batches", type=int, default=0)

    def handle(self, *args: object, **options: Any) -> None:
        offset = int(options["resume_offset"])
        max_batches = int(options["max_batches"])
        if max_batches < 0:
            raise CommandError("--max-batches cannot be negative")
        batches_run = 0
        while True:
            result = backfill_active_a_share_core_data_batch_task.run(
                offset=offset,
                batch_size=int(options["batch_size"]),
                source=str(options["source"]),
                history_days=int(options["history_days"]),
                financial_periods=int(options["financial_periods"]),
            )
            self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
            outcome = str(result.get("outcome") or "failed")
            if outcome in {"failed", "partial", "blocked"}:
                checkpoint = result.get("checkpoint") or {}
                raise CommandError(
                    "Core-data backfill stopped with outcome="
                    f"{outcome}; resume from offset "
                    f"{checkpoint.get('offset', offset)} after resolving failures."
                )
            checkpoint = result.get("checkpoint") or {}
            if checkpoint.get("complete") is True:
                self.stdout.write(self.style.SUCCESS("Active A-share core-data backfill complete."))
                return
            offset = int(checkpoint.get("next_offset", offset))
            batches_run += 1
            if max_batches and batches_run >= max_batches:
                self.stdout.write(
                    self.style.WARNING(f"Stopped at requested batch limit; resume from {offset}.")
                )
                return
