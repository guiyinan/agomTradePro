"""Import investor-account CSV into macro facts."""

from __future__ import annotations

import json
from argparse import RawDescriptionHelpFormatter

from django.core.management.base import BaseCommand, CommandError

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

    def add_arguments(self, parser) -> None:
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

    def handle(self, *args, **options):
        if bool(options.get("print_template")):
            self.stdout.write(CSV_TEMPLATE.rstrip())
            return

        csv_path = str(options.get("csv_file") or options.get("csv_path") or "").strip()
        if not csv_path:
            raise CommandError("CSV path is required. Pass a positional path or --file <csv_path>.")
        try:
            with open(csv_path, encoding="utf-8-sig") as handle:
                csv_text = handle.read()
        except OSError as exc:
            raise CommandError(f"Failed to read CSV file: {exc}") from exc

        try:
            result = make_import_investor_accounts_use_case().execute(
                csv_text,
                dry_run=bool(options.get("dry_run")),
                value_unit=str(options.get("value_unit") or "户"),
            )
        except ValueError as exc:
            raise CommandError(f"Invalid investor-account CSV: {exc}") from exc
        if bool(options.get("json")):
            self.stdout.write(json.dumps(result, ensure_ascii=False, default=str))
        else:
            self.stdout.write(self.style.SUCCESS(str(result)))
        if bool(options.get("fail_on_warning")) and result.get("warnings"):
            raise CommandError("Investor-account CSV has warnings; inspect output before import.")
