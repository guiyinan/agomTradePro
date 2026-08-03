"""Reconcile the Config Center runtime definition registry."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.config_center.application.runtime_public import (
    reconcile_runtime_definitions,
    validate_active_runtime_profile,
)


class Command(BaseCommand):
    """Create/update the owned runtime definitions and optionally validate a profile."""

    help = "Reconcile Config Center runtime definitions and validate an active profile."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--check-environment",
            default="",
            help="Also validate the active runtime profile for this environment.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        """Run an idempotent definition reconcile with optional active-profile check."""

        saved = reconcile_runtime_definitions()
        self.stdout.write(
            self.style.SUCCESS(
                "Reconciled runtime definitions: "
                + ", ".join(definition.key for definition in saved)
            )
        )

        environment = str(options.get("check_environment") or "").strip()
        if not environment:
            return
        report = validate_active_runtime_profile(environment)
        if not bool(report.get("valid")):
            raw_errors = report.get("errors", ())
            if isinstance(raw_errors, (tuple, list)):
                errors = ", ".join(str(error) for error in raw_errors)
            else:
                errors = str(raw_errors)
            raise CommandError(
                f"Active runtime profile validation failed for {environment}: {errors}"
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"Active runtime profile valid: {report.get('profile_key')} "
                f"v{report.get('profile_version')}"
            )
        )
