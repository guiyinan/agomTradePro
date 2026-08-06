"""Encrypt legacy Data Center provider credentials in place."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db.models import Q

from apps.data_center.infrastructure.models import ProviderConfigModel
from apps.data_center.infrastructure.provider_credentials import (
    ProviderCredentialEncryptionUnavailable,
    ProviderCredentialStore,
)


class Command(BaseCommand):
    """Migrate plaintext provider credential columns to the secret store."""

    help = "Encrypt legacy Data Center provider credentials and clear plaintext columns"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            dest="dry_run",
            help="Report legacy credentials without changing the database",
        )

    def handle(self, *args: str, **options: Any) -> None:
        """Execute the migration without printing credential values."""

        dry_run = bool(options.get("dry_run", False))
        store = ProviderCredentialStore()
        providers = ProviderConfigModel._default_manager.filter(
            Q(api_key__gt="") | Q(api_secret__gt="")
        )
        migrated = 0
        skipped = 0
        for provider in providers.order_by("pk"):
            try:
                changed = store.migrate_legacy(provider, dry_run=dry_run)
            except ProviderCredentialEncryptionUnavailable as exc:
                raise CommandError(str(exc)) from exc
            if changed:
                migrated += 1
            else:
                skipped += 1

        prefix = "Would migrate" if dry_run else "Migrated"
        self.stdout.write(
            self.style.SUCCESS(
                f"{prefix} {migrated} provider credential record(s); skipped {skipped}."
            )
        )
