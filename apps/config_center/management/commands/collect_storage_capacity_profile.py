"""Collect and persist one explicit storage capacity profile observation."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.config_center.application.public import (
    StorageCapacityProfileBlockedError,
    collect_and_record_storage_capacity_profile,
)


class Command(BaseCommand):
    """Persist read-only filesystem/database capacity evidence."""

    help = "Collect a storage capacity profile against the active policy."

    def add_arguments(self, parser: CommandParser) -> None:
        """Register environment and policy options."""

        parser.add_argument("--environment", default="development")
        parser.add_argument("--source", default="runtime-observer")

    def handle(self, *args: Any, **options: Any) -> None:
        """Fail closed without an active policy and persist one observation."""

        environment = str(options["environment"]).strip()
        if not environment:
            raise CommandError("environment cannot be empty")
        try:
            saved = collect_and_record_storage_capacity_profile(
                environment=environment,
                source=str(options["source"]),
            )
        except (StorageCapacityProfileBlockedError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            self.style.SUCCESS(
                "Storage capacity profile recorded: "
                f"observation_id={saved.observation_id}, environment={saved.environment}, "
                f"state={saved.pressure_state}, usage_ratio={saved.usage_ratio}"
            )
        )
