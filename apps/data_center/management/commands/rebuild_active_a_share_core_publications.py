"""Preview or execute exact active-A-share core current publications."""

from __future__ import annotations

import json
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.utils import timezone

from apps.data_center.application.query_services import (
    list_active_stock_codes_for_backfill,
)
from apps.data_center.composition import (
    make_core_current_publication_rebuild_use_case,
)


class Command(BaseCommand):
    """Expose a dry-run-first operator boundary for core publication rebuilds."""

    help = (
        "Preview full active-A-share quote/price/valuation/financial current publications; "
        "use --execute with an operator identity to commit atomically."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        """Register explicit mutation and operator-evidence arguments."""

        parser.add_argument(
            "--execute",
            action="store_true",
            help="Commit all four publications atomically after exact coverage validation.",
        )
        parser.add_argument(
            "--operator",
            default="",
            help="Approval/operator identity required with --execute.",
        )

    def handle(self, *args: object, **options: Any) -> None:
        """Preview by default or execute after explicit operator authorization."""

        del args
        execute = bool(options.get("execute", False))
        raw_operator = str(options.get("operator") or "")
        operator = raw_operator.strip()
        if execute and not self._valid_operator(raw_operator):
            raise CommandError(
                "--operator must be a non-empty single-line identity of at most 100 characters"
            )
        if not execute and operator:
            raise CommandError("--operator is accepted only together with --execute")

        asset_codes = list_active_stock_codes_for_backfill()
        if not asset_codes:
            raise CommandError("active A-share universe is empty")
        observed_at = timezone.now()
        created_by = (
            f"ops.current_publication_rebuild:{operator}"
            if execute
            else "ops.current_publication_rebuild.preview"
        )
        coordinator = make_core_current_publication_rebuild_use_case(created_by=created_by)
        try:
            if execute:
                result = coordinator.execute(
                    asset_codes=asset_codes,
                    published_at=observed_at,
                )
                payload = {
                    "mode": "execute",
                    "operator": operator,
                    "asset_count": len(asset_codes),
                    "observed_at": observed_at.isoformat(),
                    **result.to_dict(),
                }
            else:
                preview = coordinator.preview(
                    asset_codes=asset_codes,
                    published_at=observed_at,
                )
                payload = {
                    "mode": "dry_run",
                    "operator": "",
                    "asset_count": len(asset_codes),
                    "observed_at": observed_at.isoformat(),
                    **preview.to_dict(),
                }
        except (TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )

    @staticmethod
    def _valid_operator(raw_operator: str) -> bool:
        """Return whether an operator identity is bounded and single-line."""

        normalized = raw_operator.strip()
        return (
            bool(normalized)
            and len(normalized) <= 100
            and not any(marker in raw_operator for marker in ("\r", "\n"))
        )
