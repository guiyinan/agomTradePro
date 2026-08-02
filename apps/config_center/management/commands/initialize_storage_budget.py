"""Initialize an explicit Config Center storage policy projection."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.config_center.domain.runtime_config import StorageBudgetPolicy
from apps.config_center.infrastructure.runtime_config_repositories import (
    StorageBudgetPolicyRepository,
)


class Command(BaseCommand):
    """Create/update a storage policy; no runtime component reads this default implicitly."""

    help = "Initialize an explicit Config Center storage budget policy."

    def add_arguments(self, parser: CommandParser) -> None:
        """Register policy initialization options."""

        parser.add_argument("--profile-key", default="production-90g")
        parser.add_argument("--capacity-gib", type=int, default=90)
        parser.add_argument("--version", type=int, default=1)
        parser.add_argument("--activate", action="store_true")
        parser.add_argument("--actor", default="bootstrap")
        parser.add_argument("--reason", default="explicit storage policy initialization")

    def handle(self, *args: Any, **options: Any) -> None:
        """Persist a typed policy with explicit activation intent."""

        capacity_gib = options.get("capacity_gib")
        version = options.get("version")
        if isinstance(capacity_gib, bool) or not isinstance(capacity_gib, int) or capacity_gib <= 0:
            raise CommandError("capacity-gib must be a positive integer")
        if isinstance(version, bool) or not isinstance(version, int) or version <= 0:
            raise CommandError("version must be a positive integer")
        policy = StorageBudgetPolicy(
            policy_key=str(options["profile_key"]),
            version=version,
            configured_capacity_bytes=capacity_gib * 1024**3,
            raw_budget_ratio=0.05,
            quarantine_budget_ratio=0.05,
            database_budget_ratio=0.55,
            logs_budget_ratio=0.10,
            emergency_reserve_ratio=0.10,
            warning_ratio=0.70,
            critical_ratio=0.85,
            active=bool(options.get("activate")),
        )
        repository = StorageBudgetPolicyRepository()
        saved = repository.activate(policy) if bool(options.get("activate")) else repository.save(policy)
        self.stdout.write(
            self.style.SUCCESS(
                f"storage policy {saved.policy_key} v{saved.version} saved; active={saved.active}"
            )
        )
