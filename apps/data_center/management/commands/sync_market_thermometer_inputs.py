"""Sync market-thermometer input series."""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from apps.data_center.application.interface_services import (
    make_sync_market_thermometer_inputs_use_case,
)
from apps.data_center.application.tasks import resolve_market_thermometer_as_of_date


class Command(BaseCommand):
    """Sync market-thermometer input series for one date."""

    help = "Sync market-thermometer input series"

    def add_arguments(self, parser) -> None:
        parser.add_argument("--as-of-date", type=str, default="")
        parser.add_argument(
            "--json",
            action="store_true",
            help="Emit machine-readable JSON instead of Python repr output.",
        )

    def handle(self, *args, **options):
        raw_date = str(options.get("as_of_date") or "").strip()
        as_of_date = resolve_market_thermometer_as_of_date(raw_date)
        payload = make_sync_market_thermometer_inputs_use_case().execute(as_of_date=as_of_date)
        if bool(options.get("json")):
            self.stdout.write(json.dumps(payload, ensure_ascii=False, default=str))
        else:
            self.stdout.write(self.style.SUCCESS(str(payload)))
