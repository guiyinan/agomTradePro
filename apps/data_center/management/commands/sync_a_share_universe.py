"""Synchronize the Data Center A-share master universe."""

from __future__ import annotations

import json
from argparse import ArgumentParser
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.data_center.infrastructure.a_share_universe_sync import (
    AShareUniverseSyncService,
    JsonFileAshareCodeNameProvider,
)


class Command(BaseCommand):
    help = "Synchronize active A-share AssetMaster rows from AKShare code-name metadata."

    def add_arguments(self, parser: ArgumentParser | CommandParser) -> None:
        """Register A-share universe synchronization options."""

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

    def handle(self, *args: Any, **options: Any) -> None:
        """Synchronize the A-share universe from one validated source."""

        raw_input_file = options.get("input_file")
        if not isinstance(raw_input_file, str):
            raise CommandError("input-file must be a path string")
        input_file = raw_input_file.strip()
        if len(input_file) > 4096:
            raise CommandError("input-file path is too long")
        deactivate_missing = options.get("deactivate_missing")
        if not isinstance(deactivate_missing, bool):
            raise CommandError("deactivate-missing must be a boolean flag")
        if not isinstance(options.get("as_json"), bool):
            raise CommandError("json must be a boolean flag")
        provider = JsonFileAshareCodeNameProvider(input_file) if input_file else None
        try:
            report = AShareUniverseSyncService(provider=provider).sync(
                deactivate_missing=deactivate_missing
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise CommandError("A-share universe input could not be loaded.") from exc
        payload = report.to_dict()
        if options.get("as_json"):
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
            return

        self.stdout.write(self.style.SUCCESS("A-share universe sync completed"))
        self.stdout.write(str(payload))
