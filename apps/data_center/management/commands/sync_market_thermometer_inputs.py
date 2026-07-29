"""Sync market-thermometer input series."""

from __future__ import annotations

import json
from argparse import ArgumentParser
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.data_center.application.interface_services import (
    make_sync_market_thermometer_inputs_use_case,
)
from apps.data_center.application.market_thermometer_dates import (
    resolve_market_thermometer_as_of_date,
)


class Command(BaseCommand):
    """Sync market-thermometer input series for one date."""

    help = "Sync market-thermometer input series"

    def add_arguments(self, parser: ArgumentParser | CommandParser) -> None:
        """Register market-thermometer input-sync options."""

        parser.add_argument("--as-of-date", type=str, default="")
        parser.add_argument(
            "--json",
            action="store_true",
            help="Emit machine-readable JSON instead of Python repr output.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        """Synchronize inputs for one validated market date."""

        raw_option = options.get("as_of_date")
        if raw_option is not None and not isinstance(raw_option, str):
            raise CommandError("as-of-date must be an ISO date")
        raw_date = (raw_option or "").strip()
        try:
            as_of_date = resolve_market_thermometer_as_of_date(raw_date)
        except ValueError as exc:
            raise CommandError("as-of-date must use YYYY-MM-DD format") from exc
        if not isinstance(options.get("json"), bool):
            raise CommandError("json must be a boolean flag")
        payload = make_sync_market_thermometer_inputs_use_case().execute(as_of_date=as_of_date)
        if bool(options.get("json")):
            self.stdout.write(json.dumps(payload, ensure_ascii=False, default=str))
        else:
            self.stdout.write(self.style.SUCCESS(str(payload)))
