"""
Management command to sync AI capability catalog.
"""

import logging
import time

from django.core.management.base import BaseCommand

from apps.ai_capability.application.use_cases import SyncCapabilitiesUseCase


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Sync AI capability catalog from all sources"

    def add_arguments(self, parser):
        parser.add_argument(
            "--type",
            type=str,
            default="incremental",
            help="Sync type: full, incremental (default: incremental)",
        )
        parser.add_argument(
            "--source",
            type=str,
            help="Sync only a specific source (builtin, terminal_command, mcp_tool, api)",
        )

    def handle(self, *args, **options):
        start_time = time.time()
        sync_type = options["type"]
        source = options.get("source")

        self.stdout.write(f"Syncing AI capability catalog (type={sync_type})...")

        if source:
            self.stdout.write(f"Syncing only source: {source}")

        use_case = SyncCapabilitiesUseCase()
        result = use_case.execute(sync_type=sync_type, source=source)

        self.stdout.write(self.style.SUCCESS(f"\nSync complete in {result.duration_seconds:.2f}s"))
        self.stdout.write(f"  Total discovered: {result.total_discovered}")
        self.stdout.write(f"  Created: {result.created_count}")
        self.stdout.write(f"  Updated: {result.updated_count}")
        self.stdout.write(f"  Disabled: {result.disabled_count}")
        self.stdout.write(f"  Errors: {result.error_count}")

        if result.summary:
            self.stdout.write("\nDetails by source:")
            for src, stats in result.summary.items():
                if isinstance(stats, dict):
                    self.stdout.write(f"  {src}:")
                    self.stdout.write(f"    Created: {stats.get('created', 0)}")
                    self.stdout.write(f"    Updated: {stats.get('updated', 0)}")

        if result.error_count > 0:
            self.stdout.write(self.style.WARNING(f"\nCompleted with {result.error_count} error(s)"))
