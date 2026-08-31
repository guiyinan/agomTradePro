"""Preview or repair active-A-share decision-current facts and publications."""

from __future__ import annotations

import json
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.utils import timezone

from apps.data_center.application.query_services import (
    list_active_stock_codes_for_backfill,
)
from apps.data_center.application.query_use_cases import (
    latest_completed_cn_market_session,
)
from apps.data_center.composition import make_core_current_fact_refresh_use_case
from core.exceptions import MissingConfigError


class Command(BaseCommand):
    """Expose a dry-run-first, fail-closed current-fact repair boundary."""

    help = (
        "Preview active-A-share current-fact coverage; use --execute and an "
        "operator identity to refresh real quote/valuation facts, repair financial "
        "availability, materialize completed-session prices, and publish atomically."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        """Register explicit mutation, provider, and batching arguments."""

        parser.add_argument(
            "--execute",
            action="store_true",
            help="Perform provider writes and the final all-dataset publication.",
        )
        parser.add_argument(
            "--operator",
            default="",
            help="Approval/operator identity required with --execute.",
        )
        parser.add_argument(
            "--source",
            default="akshare",
            help="Configured provider source type (default: akshare).",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=200,
            help="Quote/valuation batch size from 1 through 500 (default: 200).",
        )

    def handle(self, *args: object, **options: Any) -> None:
        """Preview locally or execute a provider-backed fail-closed repair."""

        del args
        execute = bool(options.get("execute", False))
        raw_operator = str(options.get("operator") or "")
        operator = raw_operator.strip()
        source_type = str(options.get("source") or "").strip().lower()
        batch_size = options.get("batch_size")
        if execute and not self._valid_operator(raw_operator):
            raise CommandError(
                "--operator must be a non-empty single-line identity of at most 100 characters"
            )
        if not execute and operator:
            raise CommandError("--operator is accepted only together with --execute")
        if (
            not source_type
            or len(source_type) > 50
            or any(marker in source_type for marker in ("\r", "\n"))
        ):
            raise CommandError("--source must be a single-line value of at most 50 characters")
        if (
            isinstance(batch_size, bool)
            or not isinstance(batch_size, int)
            or not 1 <= batch_size <= 500
        ):
            raise CommandError("--batch-size must be an integer between 1 and 500")

        try:
            asset_codes = list_active_stock_codes_for_backfill()
        except MissingConfigError as exc:
            raise CommandError(str(exc)) from exc
        if not asset_codes:
            raise CommandError("active A-share universe is empty")
        started_at = timezone.now()
        session_date = latest_completed_cn_market_session(started_at)
        if session_date is None:
            raise CommandError(
                "latest completed China market session is unavailable during live trading"
            )
        created_by = (
            f"ops.current_fact_refresh:{operator}"
            if execute
            else "ops.current_fact_refresh.preview"
        )
        try:
            coordinator = make_core_current_fact_refresh_use_case(
                source_type=source_type,
                created_by=created_by,
            )
            if execute:
                result = coordinator.execute(
                    asset_codes=asset_codes,
                    session_date=session_date,
                    recorded_at=started_at,
                    batch_size=batch_size,
                )
                payload = {
                    "mode": "execute",
                    "operator": operator,
                    "source": source_type,
                    "batch_size": batch_size,
                    "asset_count": len(asset_codes),
                    "session_date": session_date.isoformat(),
                    "started_at": started_at.isoformat(),
                    **result.to_dict(),
                }
            else:
                preview = coordinator.preview(
                    asset_codes=asset_codes,
                    session_date=session_date,
                    recorded_at=started_at,
                )
                payload = {
                    "mode": "dry_run",
                    "operator": "",
                    "source": source_type,
                    "batch_size": batch_size,
                    "asset_count": len(asset_codes),
                    "session_date": session_date.isoformat(),
                    "started_at": started_at.isoformat(),
                    **preview.to_dict(),
                }
        except (MissingConfigError, TypeError, ValueError) as exc:
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
