"""Reconcile retained historical index closes across sources without modifying the inputs."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.data_center.infrastructure.historical_index_close_snapshots import (
    merge_historical_index_snapshots,
)


class Command(BaseCommand):
    """Export source-attributed daily index points from retained native responses."""

    help = "Merge historical index closes on a verified calendar and print the resulting JSON."
    requires_system_checks: list[str] = []

    def add_arguments(self, parser: CommandParser) -> None:
        """Register the requested index, dates and native response paths."""
        parser.add_argument("--index-code", required=True)
        parser.add_argument("--start", type=date.fromisoformat, required=True)
        parser.add_argument("--end", type=date.fromisoformat, required=True)
        parser.add_argument("--calendar", type=Path, required=True, nargs="+")
        parser.add_argument("--csi", type=Path, nargs="+", default=[])
        parser.add_argument("--relay", type=Path, nargs="+", default=[])

    def handle(self, *args: Any, **options: Any) -> str:
        """Return a complete verified export or reject the input window."""
        try:
            report = merge_historical_index_snapshots(
                options["index_code"],
                options["start"],
                options["end"],
                calendars=options["calendar"],
                csi=options["csi"],
                relay=options["relay"],
            )
        except (OSError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        return json.dumps(report, ensure_ascii=False, allow_nan=False)
