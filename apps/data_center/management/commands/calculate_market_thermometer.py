"""Calculate market-thermometer snapshot."""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from apps.data_center.application.interface_services import (
    make_calculate_market_thermometer_use_case,
    make_sync_market_thermometer_inputs_use_case,
)
from apps.data_center.application.tasks import resolve_market_thermometer_as_of_date


class Command(BaseCommand):
    """Calculate market-thermometer snapshot for one date."""

    help = "Calculate market-thermometer snapshot"

    def add_arguments(self, parser) -> None:
        parser.add_argument("--as-of-date", type=str, default="")
        parser.add_argument(
            "--skip-sync",
            action="store_true",
            help="Skip input sync before calculating the thermometer snapshot.",
        )
        parser.add_argument(
            "--allow-blocked-write",
            action="store_true",
            help="Persist the snapshot even when it is marked must_not_use_for_decision.",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            help="Emit machine-readable JSON instead of Python repr output.",
        )

    def handle(self, *args, **options):
        raw_date = str(options.get("as_of_date") or "").strip()
        as_of_date = resolve_market_thermometer_as_of_date(raw_date)
        sync_payload = None
        if not bool(options.get("skip_sync")):
            sync_payload = make_sync_market_thermometer_inputs_use_case().execute(
                as_of_date=as_of_date
            )
        allow_blocked_write = bool(options.get("allow_blocked_write"))
        snapshot = make_calculate_market_thermometer_use_case().execute(
            as_of_date=as_of_date,
            persist_blocked=allow_blocked_write,
        )
        payload = snapshot.to_dict()
        payload["persisted"] = bool(allow_blocked_write or not snapshot.must_not_use_for_decision)
        if snapshot.must_not_use_for_decision and not allow_blocked_write:
            payload["blocked_write_skipped"] = True
        if sync_payload is not None:
            payload["sync"] = sync_payload
        if bool(options.get("json")):
            self.stdout.write(json.dumps(payload, ensure_ascii=False, default=str))
        else:
            self.stdout.write(self.style.SUCCESS(str(payload)))
