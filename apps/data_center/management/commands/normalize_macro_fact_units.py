"""Normalize legacy macro fact rows to canonical storage units."""

from __future__ import annotations

from argparse import ArgumentParser
from typing import Any

from django.core.management import BaseCommand, CommandError
from django.core.management.base import CommandParser

from apps.data_center.infrastructure.repositories import MacroGovernanceRepository


def _split_codes(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [item.strip().upper() for item in raw.split(",") if item.strip()]


class Command(BaseCommand):
    help = (
        "Normalize legacy data_center_macro_fact rows to canonical storage value/unit "
        "using IndicatorUnitRule."
    )

    def add_arguments(self, parser: ArgumentParser | CommandParser) -> None:
        """Register macro-fact normalization options."""

        parser.add_argument(
            "--indicator-codes",
            dest="indicator_codes",
            default=None,
            help="Comma-separated indicator codes to limit the repair scope.",
        )
        parser.add_argument(
            "--dry-run",
            dest="dry_run",
            action="store_true",
            default=False,
            help="Preview changes without saving them.",
        )
        parser.add_argument(
            "--check",
            dest="check",
            action="store_true",
            default=False,
            help="Exit non-zero if any fact needs normalization or cannot be normalized.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        """Normalize governed macro facts or report drift without mutation."""

        raw_indicator_codes = options.get("indicator_codes")
        if raw_indicator_codes is not None and not isinstance(raw_indicator_codes, str):
            raise CommandError("indicator-codes must be comma-separated text")
        indicator_codes = _split_codes(raw_indicator_codes)
        if len(indicator_codes) > 1000:
            raise CommandError("indicator-codes accepts at most 1000 codes")
        for option_name in ("check", "dry_run"):
            if not isinstance(options.get(option_name), bool):
                raise CommandError(f"{option_name.replace('_', '-')} must be a boolean flag")
        check = options["check"]
        dry_run = options["dry_run"] or check
        result = MacroGovernanceRepository().normalize_macro_fact_units(
            indicator_codes=indicator_codes or None,
            dry_run=dry_run,
        )

        for message in result["messages"]:
            if message.startswith("skip "):
                self.stdout.write(self.style.WARNING(message))
            else:
                self.stdout.write(message)

        summary = (
            "normalize_macro_fact_units complete: "
            f"updated={result['updated_count']}, unchanged={result['unchanged_count']}, "
            f"skipped={result['skipped_count']}, dry_run={result['dry_run']}"
        )
        if check and (result["updated_count"] or result["skipped_count"]):
            raise CommandError(summary)
        self.stdout.write(self.style.SUCCESS(summary))
