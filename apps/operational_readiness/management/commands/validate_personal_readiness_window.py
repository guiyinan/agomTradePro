"""Validate the continuous personal readiness evidence window."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.operational_readiness.infrastructure.readiness_window_validation_calendar import (
    _load_qlib_trading_calendar,
    _parse_date,
)
from apps.operational_readiness.infrastructure.readiness_window_validation_core import (
    validate_personal_readiness_window as _validate_personal_readiness_window,
)
from apps.operational_readiness.infrastructure.readiness_window_validation_evidence import (
    _evaluate_payload,
)

DEFAULT_OUTPUT_DIR = "var/readiness-evidence"
DEFAULT_REQUIRED_DAYS = 20
DEFAULT_CALENDAR_SOURCE = "auto"


class Command(BaseCommand):
    help = "Validate continuous personal readiness evidence over trading days."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--output-dir",
            default=DEFAULT_OUTPUT_DIR,
            help=f"Evidence directory. Default: {DEFAULT_OUTPUT_DIR}",
        )
        parser.add_argument(
            "--required-days",
            type=int,
            default=DEFAULT_REQUIRED_DAYS,
            help=f"Required accepted trading-day records. Default: {DEFAULT_REQUIRED_DAYS}",
        )
        parser.add_argument(
            "--calendar-source",
            choices=("auto", "qlib", "weekday"),
            default=DEFAULT_CALENDAR_SOURCE,
            help="Trading calendar source. Default: auto.",
        )
        parser.add_argument(
            "--expected-latest-date",
            default=None,
            help="Expected latest readiness date in YYYY-MM-DD format.",
        )
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Exit with CommandError when the window is not yet accepted.",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            dest="print_json",
            help="Print full JSON result.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        payload = validate_personal_readiness_window(
            output_dir=Path(str(options["output_dir"])),
            required_days=int(options["required_days"]),
            calendar_source=str(options["calendar_source"]),
            expected_latest_date=_parse_date(options.get("expected_latest_date")),
        )
        if options.get("print_json"):
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    "Personal readiness window: "
                    f"status={payload['status']}, "
                    f"accepted_days={payload['accepted_days']}/{payload['required_days']}, "
                    f"remaining_days={payload['remaining_days']}"
                )
            )
            for issue in payload["blocking_issues"][:10]:
                self.stdout.write(
                    self.style.WARNING(f"  {issue['target_date']}: {issue['reason']}")
                )

        if options.get("strict") and payload["status"] != "accepted":
            raise CommandError(
                "Personal readiness window is not accepted: "
                f"{payload['accepted_days']}/{payload['required_days']} days"
            )


def validate_personal_readiness_window(
    *,
    output_dir: Path,
    required_days: int = DEFAULT_REQUIRED_DAYS,
    calendar_source: str = DEFAULT_CALENDAR_SOURCE,
    expected_latest_date: date | None = None,
    trading_calendar: set[date] | list[date] | tuple[date, ...] | None = None,
) -> dict[str, Any]:
    """Validate readiness evidence files against the continuous-run acceptance gate."""

    return _validate_personal_readiness_window(
        output_dir=output_dir,
        required_days=required_days,
        calendar_source=calendar_source,
        expected_latest_date=expected_latest_date,
        trading_calendar=trading_calendar,
        load_qlib_trading_calendar=_load_qlib_trading_calendar,
        base_dir=settings.BASE_DIR,
    )


__all__ = [
    "DEFAULT_CALENDAR_SOURCE",
    "DEFAULT_OUTPUT_DIR",
    "DEFAULT_REQUIRED_DAYS",
    "Command",
    "_evaluate_payload",
    "_load_qlib_trading_calendar",
    "_parse_date",
    "validate_personal_readiness_window",
]
