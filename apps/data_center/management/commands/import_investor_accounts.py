"""Import investor-account CSV into macro facts."""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.data_center.application.interface_services import (
    make_import_investor_accounts_use_case,
)


class Command(BaseCommand):
    """Import investor-account history from a CSV file."""

    help = "Import investor-account history from CSV"

    def add_arguments(self, parser) -> None:
        parser.add_argument("csv_path", type=str)

    def handle(self, *args, **options):
        csv_path = str(options["csv_path"])
        try:
            with open(csv_path, "r", encoding="utf-8-sig") as handle:
                csv_text = handle.read()
        except OSError as exc:
            raise CommandError(f"Failed to read CSV file: {exc}") from exc

        result = make_import_investor_accounts_use_case().execute(csv_text)
        self.stdout.write(self.style.SUCCESS(str(result)))
