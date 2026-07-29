"""Management command to govern AI capability routing policy."""

import json
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from apps.ai_capability.application.governance_services import (
    CapabilityCatalogGovernanceService,
)


class Command(BaseCommand):
    help = "Apply conservative governance to the AI capability catalog"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Persist changes. Without this flag the command only reports a dry run.",
        )
        parser.add_argument(
            "--keep-stale",
            action="store_true",
            help="Keep stale auto-collected API/MCP entries instead of deleting them.",
        )
        parser.add_argument(
            "--format",
            choices=["text", "json"],
            default="text",
            help="Output format: text or json.",
        )

    def handle(self, *args: str, **options: Any) -> None:
        service = CapabilityCatalogGovernanceService()
        result = service.execute(
            apply=bool(options["apply"]),
            purge_stale=not bool(options["keep_stale"]),
        )
        payload = result.to_dict()

        if options["format"] == "json":
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
            return

        mode = "APPLY" if result.apply else "DRY RUN"
        self.stdout.write(f"AI Capability Catalog Governance [{mode}]")
        self.stdout.write(f"  Reviewed current entries: {result.total_reviewed}")
        self.stdout.write(f"  Changed entries: {result.changed_count}")
        self.stdout.write(f"  Stale entries: {result.stale_count}")
        self.stdout.write(f"  Stale deleted: {result.stale_deleted_count}")
        self.stdout.write(f"  Routing enabled: {result.routing_enabled_count}")
        self.stdout.write(f"  Routing disabled: {result.routing_disabled_count}")
        self.stdout.write(f"  Approved: {result.approved_count}")
        self.stdout.write(f"  Pending manual review: {result.pending_count}")
        self.stdout.write(f"  Rejected: {result.rejected_count}")

        if result.by_reason:
            self.stdout.write("  Reasons:")
            for reason, count in sorted(result.by_reason.items()):
                self.stdout.write(f"    {reason}: {count}")

        if result.apply:
            self.stdout.write(self.style.SUCCESS("Governance applied"))
        else:
            self.stdout.write(self.style.WARNING("Dry run only; pass --apply to persist"))
