"""Retired compatibility entry point for the legacy credential migration command."""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser


class Command(BaseCommand):
    """Keep the historical command name while refusing unsafe legacy execution."""

    help = "Retired: legacy plaintext credential migration is no longer available"
    requires_system_checks: list[str] = []

    def add_arguments(self, parser: CommandParser) -> None:
        """Accept the historical options so old invocations fail consistently."""
        parser.add_argument(
            "--dry-run",
            action="store_true",
            dest="dry_run",
            help="Retained for compatibility; the retired command performs no work",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            dest="force",
            help="Retained for compatibility; the retired command performs no work",
        )

    def handle(self, *args: str, **options: Any) -> None:
        """Reject the retired command without querying or mutating the database."""
        raise CommandError(
            "encrypt_api_keys is retired; apply the guarded ai_provider schema migration "
            "only after credential recovery and migration evidence is accepted."
        )
