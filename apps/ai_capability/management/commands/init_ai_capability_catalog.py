"""
Management command to initialize AI capability catalog.
"""

import logging
import time

from django.core.management.base import BaseCommand

from apps.ai_capability.application.use_cases import SyncCapabilitiesUseCase

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Initialize AI capability catalog from all sources"

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force re-initialization even if catalog exists",
        )

    def handle(self, *args, **options):
        time.time()

        self.stdout.write("Initializing AI capability catalog...")

        use_case = SyncCapabilitiesUseCase()
        result = use_case.execute(sync_type="init")

        self.stdout.write(
            self.style.SUCCESS(f"\nInitialization complete in {result.duration_seconds:.2f}s")
        )
        self.stdout.write(f"  Total discovered: {result.total_discovered}")
        self.stdout.write(f"  Created: {result.created_count}")
        self.stdout.write(f"  Updated: {result.updated_count}")
        self.stdout.write(f"  Disabled: {result.disabled_count}")
        self.stdout.write(f"  Errors: {result.error_count}")

        if result.summary:
            self.stdout.write("\nDetails by source:")
            for source, stats in result.summary.items():
                if isinstance(stats, dict):
                    self.stdout.write(f"  {source}:")
                    self.stdout.write(f"    Created: {stats.get('created', 0)}")
                    self.stdout.write(f"    Updated: {stats.get('updated', 0)}")

        if result.error_count > 0:
            self.stdout.write(self.style.WARNING(f"\nCompleted with {result.error_count} error(s)"))
