from argparse import ArgumentParser
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.data_center.infrastructure.asset_master_backfill import (
    AssetMasterBackfillService,
)
from core.integration.asset_master_sources import build_legacy_asset_master_source


class Command(BaseCommand):
    help = "Backfill data center asset master rows from legacy sources."

    def add_arguments(self, parser: ArgumentParser | CommandParser) -> None:
        """Register asset-master backfill options."""

        parser.add_argument(
            "--codes",
            nargs="*",
            default=[],
            help="Optional canonical or legacy asset codes to backfill.",
        )
        parser.add_argument(
            "--include-remote",
            action="store_true",
            help="Fetch missing names from EastMoney after exhausting local legacy sources.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        """Backfill the requested codes from local and optional remote sources."""

        service = AssetMasterBackfillService(source_provider=build_legacy_asset_master_source())
        raw_codes = options.get("codes")
        if not isinstance(raw_codes, list) or not all(isinstance(code, str) for code in raw_codes):
            raise CommandError("codes must be supplied as text values")
        if len(raw_codes) > 1000:
            raise CommandError("codes accepts at most 1000 values")
        codes = [code.strip() for code in raw_codes if code.strip()]
        include_remote = options.get("include_remote")
        if not isinstance(include_remote, bool):
            raise CommandError("include-remote must be a boolean flag")
        if codes:
            report = service.backfill_codes(codes, include_remote=include_remote)
        else:
            report = service.backfill_all(include_remote=include_remote)

        self.stdout.write(self.style.SUCCESS("Asset master backfill completed"))
        self.stdout.write(str(report.to_dict()))
