"""Import investor-account CSV into macro facts."""

from __future__ import annotations

import json
from argparse import ArgumentParser, RawDescriptionHelpFormatter
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.data_center.application.interface_services import (
    make_import_investor_accounts_use_case,
)

CSV_TEMPLATE = "reporting_period,value\n2026-05-31,12345\n"
CSV_FORMAT_HELP = """CSV format:
  Accepted date columns: reporting_period, date, or month.
  Accepted value columns: value, accounts, or new_accounts.
  Values default to canonical account counts in 户.
  If the CSV uses 万户, pass --value-unit 万户 to convert to 户.
  Example:
    reporting_period,value
    2026-05-31,12345
"""


class Command(BaseCommand):
    """Import investor-account history from a CSV file."""

    help = "Import investor-account history from CSV"

    def add_arguments(self, parser: ArgumentParser | CommandParser) -> None:
        """Register investor-account CSV import options."""

        parser.formatter_class = RawDescriptionHelpFormatter
        parser.epilog = CSV_FORMAT_HELP
        parser.add_argument("csv_path", nargs="?", type=str)
        parser.add_argument("--file", dest="csv_file", type=str)
        parser.add_argument(
            "--print-template",
            action="store_true",
            help="Print a minimal accepted CSV template and exit.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse and validate the CSV without writing macro facts.",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            help="Emit machine-readable JSON for import or dry-run results.",
        )
        parser.add_argument(
            "--fail-on-warning",
            action="store_true",
            help="Exit non-zero when parsed CSV warnings are present.",
        )
        parser.add_argument(
            "--value-unit",
            choices=("户", "万户"),
            default="户",
            help="Unit used by CSV values. Values are stored canonically as 户.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        """Validate and import one bounded investor-account CSV file."""

        for option_name in ("print_template", "dry_run", "json", "fail_on_warning"):
            if not isinstance(options.get(option_name), bool):
                raise CommandError(f"{option_name.replace('_', '-')} must be a boolean flag")
        if options["print_template"]:
            self.stdout.write(CSV_TEMPLATE.rstrip())
            return

        raw_csv_path = options.get("csv_file") or options.get("csv_path") or ""
        if not isinstance(raw_csv_path, str):
            raise CommandError("CSV path must be text.")
        csv_path = raw_csv_path.strip()
        if not csv_path:
            raise CommandError("CSV path is required. Pass a positional path or --file <csv_path>.")
        if len(csv_path) > 4096:
            raise CommandError("CSV path is too long.")
        csv_file = Path(csv_path)
        try:
            if csv_file.stat().st_size > 10 * 1024 * 1024:
                raise CommandError("CSV file exceeds the 10 MiB import limit.")
            with csv_file.open(encoding="utf-8-sig") as handle:
                csv_text = handle.read()
        except OSError as exc:
            raise CommandError("Failed to read CSV file.") from exc

        raw_value_unit = options.get("value_unit")
        if raw_value_unit not in {"户", "万户"}:
            raise CommandError("value-unit must be 户 or 万户.")

        try:
            result = make_import_investor_accounts_use_case().execute(
                csv_text,
                dry_run=options["dry_run"],
                value_unit=raw_value_unit,
            )
        except ValueError as exc:
            raise CommandError("Invalid investor-account CSV.") from exc
        if options["json"]:
            self.stdout.write(json.dumps(result, ensure_ascii=False, default=str))
        else:
            self.stdout.write(self.style.SUCCESS(str(result)))
        if options["fail_on_warning"] and result.get("warnings"):
            raise CommandError("Investor-account CSV has warnings; inspect output before import.")
