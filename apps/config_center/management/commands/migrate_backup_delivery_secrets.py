"""Move legacy backup secrets into the Config Center secret owner."""

from __future__ import annotations

import json
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.config_center.application.public import (
    config_secret_present,
    update_backup_delivery_settings,
)
from apps.config_center.domain.backup_delivery import (
    BACKUP_ARCHIVE_PASSWORD_SECRET_REF,
    BACKUP_SMTP_PASSWORD_SECRET_REF,
)
from apps.config_center.infrastructure.models import SystemSettingsModel


class Command(BaseCommand):
    """Copy legacy encrypted backup values through the owner port once."""

    help = "Migrate legacy backup delivery secrets to Config Center's encrypted owner."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report which legacy secrets need migration without writing.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        del args
        dry_run = bool(options.get("dry_run", False))
        settings_obj = SystemSettingsModel.get_settings_for_read()
        candidates = (
            (
                "backup_archive_password",
                BACKUP_ARCHIVE_PASSWORD_SECRET_REF,
                settings_obj.get_backup_password(),
            ),
            (
                "backup_smtp_password",
                BACKUP_SMTP_PASSWORD_SECRET_REF,
                settings_obj.get_backup_smtp_password(),
            ),
        )
        pending: dict[str, str] = {}
        skipped: list[str] = []
        for field_name, secret_ref, plaintext in candidates:
            if config_secret_present(secret_ref):
                skipped.append(field_name)
                continue
            if plaintext:
                pending[field_name] = plaintext

        if not dry_run and pending:
            payload: dict[str, object] = {}
            # Only pass the two secret values here; the repository carries the
            # active policy forward and records a new typed profile revision.
            payload.update(pending)
            update_backup_delivery_settings(payload, actor="migrate-backup-delivery-secrets")

        result = {
            "dry_run": dry_run,
            "migrated": [] if dry_run else sorted(pending),
            "pending": sorted(pending),
            "already_present": sorted(skipped),
            "unavailable": sorted(
                field_name
                for field_name, _secret_ref, plaintext in candidates
                if not plaintext and field_name not in skipped
            ),
        }
        self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
        if not dry_run and result["unavailable"] and settings_obj.backup_enabled:
            raise CommandError("backup_delivery_secret_unavailable")
