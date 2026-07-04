"""Synchronize the Data Center A-share master universe."""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from apps.data_center.infrastructure.a_share_universe_sync import (
    AShareUniverseSyncService,
    JsonFileAshareCodeNameProvider,
)


class Command(BaseCommand):
    help = "Synchronize active A-share AssetMaster rows from AKShare code-name metadata."

    def add_arguments(self, parser):
        parser.add_argument(
            "--deactivate-missing",
            action="store_true",
            help="Deactivate local active A-share rows missing from the provider payload.",
        )
        parser.add_argument("--json", action="store_true", dest="as_json")
        parser.add_argument(
            "--input-file",
            default="",
            help="Import A-share code-name rows from a JSON file instead of AKShare.",
        )

    def handle(self, *args, **options):
        provider = (
            JsonFileAshareCodeNameProvider(options["input_file"])
            if options.get("input_file")
            else None
        )
        report = AShareUniverseSyncService(provider=provider).sync(
            deactivate_missing=bool(options.get("deactivate_missing"))
        )
        payload = report.to_dict()
        if options.get("as_json"):
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
            return

        self.stdout.write(self.style.SUCCESS("A-share universe sync completed"))
        self.stdout.write(str(payload))
