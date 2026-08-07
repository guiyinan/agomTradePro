"""Explicitly purge all quote snapshots before a trusted-source rebuild."""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError, CommandParser

CONFIRMATION = "DELETE_ALL_QUOTE_SNAPSHOTS"


class Command(BaseCommand):
    """Retain the old command name as a fail-closed compatibility tombstone."""

    help = "Retired: quote snapshots cannot be purged outside lifecycle governance."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--confirm", default="")

    def handle(self, *args: object, **options: object) -> None:
        """Refuse every invocation until a verified lifecycle purge port exists."""

        del args, options
        raise CommandError(
            "Quote snapshot purge is retired: no verified archive/restore evidence port exists"
        )
