"""Collect and persist one explicit storage capacity profile observation."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.config_center.application.runtime_public import (
    get_active_storage_budget,
    record_storage_capacity_observation,
)
from apps.config_center.application.runtime_repository_provider import (
    get_storage_budget_query_service,
)
from apps.config_center.application.storage_budget import StoragePressureGuard
from apps.config_center.infrastructure.capacity_observer import (
    collect_storage_capacity_observation,
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
        policy = get_active_storage_budget()
        if policy is None:
            raise CommandError("no active StorageBudgetPolicy; initialize and activate one first")
        base = collect_storage_capacity_observation(
            environment=environment,
            policy_key=policy.policy_key,
            configured_capacity_bytes=policy.configured_capacity_bytes,
            source=str(options["source"]),
        )
        pressure = StoragePressureGuard(get_storage_budget_query_service()).evaluate(
            used_bytes=base.filesystem_used_bytes,
            actual_capacity_bytes=base.filesystem_total_bytes,
        )
        observed = replace(
            base,
            effective_capacity_bytes=pressure.effective_capacity_bytes,
            usage_ratio=pressure.usage_ratio,
            pressure_state=pressure.state.value,
        )
        saved = record_storage_capacity_observation(observed)
        self.stdout.write(
            self.style.SUCCESS(
                "Storage capacity profile recorded: "
                f"observation_id={saved.observation_id}, environment={saved.environment}, "
                f"state={saved.pressure_state}, usage_ratio={saved.usage_ratio}"
            )
        )
