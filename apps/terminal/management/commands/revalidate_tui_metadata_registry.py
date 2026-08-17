"""Dry-run revalidation for every stored TUI metadata registry row."""

from __future__ import annotations

import json
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from apps.terminal.infrastructure.tui_metadata_revalidation import (
    TuiMetadataRegistryRevalidationService,
)


class Command(BaseCommand):
    """Report metadata registry health without repairing or archiving rows."""

    help = (
        "Revalidate every TUI metadata registry row in dry-run mode; "
        "no database mutation is performed."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        """Register the explicit dry-run flag for discoverability."""

        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=True,
            help="Keep the command read-only (the only supported execution mode).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        """Emit the stable JSON revalidation report."""

        report = TuiMetadataRegistryRevalidationService().run()
        self.stdout.write(
            json.dumps(
                report.as_dict(),
                ensure_ascii=False,
                sort_keys=True,
            )
        )
