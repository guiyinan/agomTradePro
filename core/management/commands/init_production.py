"""Compatibility entry point for the verified cold-start bootstrap workflow."""

from __future__ import annotations

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError, CommandParser

BOOTSTRAP_COMMAND = "bootstrap_cold_start"


class Command(BaseCommand):
    """Delegate production initialization to the readiness-aware bootstrap command."""

    help = "Initialize production configuration through bootstrap_cold_start."

    def add_arguments(self, parser: CommandParser) -> None:
        """Keep dry-run compatibility and reject unsafe legacy partial skips."""

        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show the canonical bootstrap command without executing it.",
        )
        parser.add_argument(
            "--skip",
            type=str,
            default="",
            help=(
                "Deprecated. Partial legacy script skips cannot be mapped safely; "
                "invoke bootstrap_cold_start directly for supported controls."
            ),
        )

    def handle(self, *args: object, **options: object) -> None:
        """Validate compatibility options and execute the canonical bootstrap once."""

        del args
        dry_run = options.get("dry_run", False)
        if not isinstance(dry_run, bool):
            raise CommandError("--dry-run must be a boolean")
        raw_skip = options.get("skip", "")
        if not isinstance(raw_skip, str):
            raise CommandError("--skip must be a comma-separated string")
        if raw_skip.strip():
            raise CommandError(
                "--skip is no longer supported because legacy script imports did not "
                "execute initialization; use bootstrap_cold_start directly"
            )

        self.stdout.write(self.style.MIGRATE_HEADING("AgomTradePro Initialization"))
        if dry_run:
            self.stdout.write(f"  [DRY] python manage.py {BOOTSTRAP_COMMAND}")
            return

        self.stdout.write(f"  RUN   {BOOTSTRAP_COMMAND}")
        call_command(
            BOOTSTRAP_COMMAND,
            stdout=self.stdout,
            stderr=self.stderr,
        )
        self.stdout.write(self.style.SUCCESS("Production initialization complete."))
