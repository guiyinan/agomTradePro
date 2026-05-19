"""Calculate market-thermometer snapshot."""

from __future__ import annotations

from datetime import date

from django.core.management.base import BaseCommand

from apps.data_center.application.interface_services import (
    make_calculate_market_thermometer_use_case,
)


class Command(BaseCommand):
    """Calculate market-thermometer snapshot for one date."""

    help = "Calculate market-thermometer snapshot"

    def add_arguments(self, parser) -> None:
        parser.add_argument("--as-of-date", type=str, default="")

    def handle(self, *args, **options):
        raw_date = str(options.get("as_of_date") or "").strip()
        as_of_date = date.fromisoformat(raw_date) if raw_date else None
        snapshot = make_calculate_market_thermometer_use_case().execute(as_of_date=as_of_date)
        self.stdout.write(self.style.SUCCESS(str(snapshot.to_dict())))
