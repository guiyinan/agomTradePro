"""
Management command to review AI capability catalog.
"""

import logging
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from apps.ai_capability.infrastructure.repositories import DjangoCapabilityRepository

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Review AI capability catalog status and issues"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--format",
            type=str,
            choices=("text", "json"),
            default="text",
            help="Output format: text, json (default: text)",
        )

    def handle(self, *args: str, **options: Any) -> None:
        output_format = str(options["format"])

        repo = DjangoCapabilityRepository()
        stats = repo.get_stats()

        if output_format == "json":
            import json

            self.stdout.write(json.dumps(stats, indent=2))
            return

        self.stdout.write("\n" + "=" * 60)
        self.stdout.write("AI Capability Catalog Review")
        self.stdout.write("=" * 60)

        self.stdout.write(f"\nTotal capabilities: {stats['total']}")
        self.stdout.write(f"  Enabled: {stats['enabled']}")
        self.stdout.write(f"  Disabled: {stats['disabled']}")
        self.stdout.write(f"  Pending manual governance: {stats['manual_governance']}")

        self.stdout.write("\nBy Source Type:")
        for source, count in stats["by_source"].items():
            self.stdout.write(f"  {source}: {count}")

        self.stdout.write("\nBy Route Group:")
        for group, count in stats["by_route_group"].items():
            self.stdout.write(f"  {group}: {count}")

        self.stdout.write("\nBy Review Status:")
        for status, count in stats["by_review_status"].items():
            self.stdout.write(f"  {status}: {count}")

        self.stdout.write("\n" + "=" * 60)

        warnings = []

        if stats["by_source"].get("builtin", 0) == 0:
            warnings.append("No builtin capabilities found")

        if stats["by_source"].get("mcp_tool", 0) == 0:
            warnings.append("No MCP tools found")

        if stats["by_route_group"].get("unsafe_api", 0) > 0:
            unsafe_count = stats["by_route_group"]["unsafe_api"]
            self.stdout.write(
                self.style.WARNING(f"\nWarning: {unsafe_count} unsafe API(s) detected")
            )

        if warnings:
            self.stdout.write("\nWarnings:")
            for warning in warnings:
                self.stdout.write(self.style.WARNING(f"  - {warning}"))

        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(self.style.SUCCESS("Review complete"))
