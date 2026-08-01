"""Explicitly purge all quote snapshots before a trusted-source rebuild."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.data_center.application.interface_services import (
    purge_all_quote_snapshots_for_rebuild,
)

CONFIRMATION = "DELETE_ALL_QUOTE_SNAPSHOTS"


class Command(BaseCommand):
    """Require an exact confirmation phrase before deleting quote snapshots."""

    help = "Delete all quote snapshots after a verified production backup."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--confirm", default="")

    def handle(self, *args: object, **options: Any) -> None:
        if str(options["confirm"] or "") != CONFIRMATION:
            raise CommandError(f"Refusing purge; pass --confirm {CONFIRMATION}")
        deleted_count = purge_all_quote_snapshots_for_rebuild()
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted_count} quote snapshots."))
