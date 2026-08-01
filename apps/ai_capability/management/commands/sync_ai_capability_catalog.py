"""
Management command to sync AI capability catalog.
"""

import logging
import time
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.ai_capability.application.governance_services import (
    CapabilityCatalogGovernanceService,
)
from apps.ai_capability.application.use_cases import SyncCapabilitiesUseCase

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Sync AI capability catalog from all sources"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--type",
            type=str,
            choices=("full", "incremental"),
            default="incremental",
            help="Sync type: full, incremental (default: incremental)",
        )
        parser.add_argument(
            "--source",
            type=str,
            choices=("builtin", "terminal_command", "mcp_tool", "api"),
            help="Sync only a specific source (builtin, terminal_command, mcp_tool, api)",
        )
        parser.add_argument(
            "--skip-governance",
            action="store_true",
            help="Skip post-sync governance for API/MCP capability routing.",
        )
        parser.add_argument(
            "--fail-on-error",
            action="store_true",
            help="Exit non-zero when any source synchronization error is reported.",
        )

    def handle(self, *args: str, **options: Any) -> None:
        time.time()
        sync_type = str(options["type"])
        source = options.get("source")
        if source is not None:
            source = str(source)

        self.stdout.write(f"Syncing AI capability catalog (type={sync_type})...")

        if source:
            self.stdout.write(f"Syncing only source: {source}")

        use_case = SyncCapabilitiesUseCase()
        result = use_case.execute(sync_type=sync_type, source=source)
        governance_result = None
        if not options["skip_governance"] and source in (None, "api", "mcp_tool"):
            governance_result = CapabilityCatalogGovernanceService().execute(apply=True)

        self.stdout.write(self.style.SUCCESS(f"\nSync complete in {result.duration_seconds:.2f}s"))
        self.stdout.write(f"  Total discovered: {result.total_discovered}")
        self.stdout.write(f"  Created: {result.created_count}")
        self.stdout.write(f"  Updated: {result.updated_count}")
        self.stdout.write(f"  Disabled: {result.disabled_count}")
        self.stdout.write(f"  Errors: {result.error_count}")

        if governance_result is not None:
            self.stdout.write("\nPost-sync governance:")
            self.stdout.write(f"  Changed: {governance_result.changed_count}")
            self.stdout.write(f"  Stale deleted: {governance_result.stale_deleted_count}")
            self.stdout.write(f"  Routing enabled: {governance_result.routing_enabled_count}")
            self.stdout.write(f"  Routing disabled: {governance_result.routing_disabled_count}")
            self.stdout.write(f"  Pending manual review: {governance_result.pending_count}")

        if result.summary:
            self.stdout.write("\nDetails by source:")
            for src, stats in result.summary.items():
                if isinstance(stats, dict):
                    self.stdout.write(f"  {src}:")
                    self.stdout.write(f"    Created: {stats.get('created', 0)}")
                    self.stdout.write(f"    Updated: {stats.get('updated', 0)}")

        if result.error_count > 0:
            self.stdout.write(self.style.WARNING(f"\nCompleted with {result.error_count} error(s)"))
            if options.get("fail_on_error"):
                raise CommandError("AI capability catalog synchronization reported errors")
