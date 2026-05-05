"""Normalize legacy macro fact rows to canonical storage units."""

from __future__ import annotations

from django.core.management import BaseCommand
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

    def add_arguments(self, parser):
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

    def handle(self, *args, **options):
        indicator_codes = _split_codes(options.get("indicator_codes"))
        dry_run = bool(options.get("dry_run"))
        result = MacroGovernanceRepository().normalize_macro_fact_units(
            indicator_codes=indicator_codes or None,
            dry_run=dry_run,
        )

        for message in result["messages"]:
            if message.startswith("skip "):
                self.stdout.write(self.style.WARNING(message))
            else:
                self.stdout.write(message)

        self.stdout.write(
            self.style.SUCCESS(
                "normalize_macro_fact_units complete: "
                f"updated={result['updated_count']}, unchanged={result['unchanged_count']}, "
                f"skipped={result['skipped_count']}, dry_run={result['dry_run']}"
            )
        )
