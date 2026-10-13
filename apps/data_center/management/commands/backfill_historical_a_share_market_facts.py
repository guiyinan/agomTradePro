"""Preview or execute an exact-date historical A-share market-fact backfill."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.utils import timezone

from apps.data_center.application.historical_market_backfill import (
    target_date_universe_evidence,
)
from apps.data_center.application.market_calendar import load_open_cn_market_sessions
from apps.data_center.application.tasks import (
    backfill_active_a_share_core_data_batch_task,
)
from apps.data_center.domain.market_time import CN_MARKET_TIMEZONE
from apps.data_center.target_date_universe_composition import (
    build_target_date_a_share_universe_scope,
)
from core.exceptions import DataFetchError


class Command(BaseCommand):
    """Run an authority-bound fact-only backfill without current publication changes."""

    help = (
        "Preview or backfill quote, valuation, and price facts for one completed "
        "A-share trading date without financial or current-publication writes."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--target-trade-date", required=True)
        parser.add_argument(
            "--execute",
            action="store_true",
            help="Perform authority-bound provider, raw-audit, and historical fact writes.",
        )
        parser.add_argument(
            "--operator",
            default="",
            help="Server-issued actor identity required with --execute.",
        )
        parser.add_argument("--resume-offset", type=int, default=0)
        parser.add_argument("--universe-hash", default="")
        parser.add_argument("--batch-size", type=int, default=50)
        parser.add_argument("--source", default="tushare")
        parser.add_argument("--max-batches", type=int, default=0)

    def handle(self, *args: object, **options: Any) -> None:
        target_trade_date = self._validated_target_trade_date(str(options["target_trade_date"]))
        scope = build_target_date_a_share_universe_scope(target_trade_date)
        scope_evidence = target_date_universe_evidence(scope)
        preview = {
            "success": True,
            "outcome": "noop",
            "stage": "dry_run",
            "mode": "historical_market_facts",
            "target_trade_date": target_trade_date.isoformat(),
            "candidate_count": len(scope.candidate_codes),
            "candidate_sha256": scope_evidence["candidate_sha256"],
            "requested": len(scope.requested_codes),
            "requested_sha256": scope_evidence["requested_sha256"],
            "excluded_not_yet_listed_count": len(scope.excluded_not_yet_listed),
            "unknown_listing_date_count": len(scope.unknown_listing_date_codes),
            "stored": 0,
            "published": 0,
            "financial_requested": 0,
            "current_publication_changed": False,
            "must_not_use_for_decision": True,
        }
        if not bool(options.get("execute", False)):
            self.stdout.write(json.dumps(preview, ensure_ascii=False, sort_keys=True))
            return

        operator = self._validated_operator(str(options.get("operator") or ""))
        offset = int(options["resume_offset"])
        universe_hash = str(options.get("universe_hash") or "")
        max_batches = int(options["max_batches"])
        if max_batches < 0:
            raise CommandError("--max-batches cannot be negative")
        batches_run = 0
        partial_batches = 0
        aggregate_requested = 0
        aggregate_succeeded = 0
        aggregate_failed = 0
        aggregate_stored = 0
        while True:
            result = backfill_active_a_share_core_data_batch_task.run(
                offset=offset,
                batch_size=int(options["batch_size"]),
                source=str(options["source"]),
                operator=operator,
                universe_hash=universe_hash,
                historical_market_date=target_trade_date.isoformat(),
            )
            self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
            outcome = str(result.get("outcome") or "failed")
            checkpoint = result.get("checkpoint") or {}
            if outcome in {"failed", "blocked"}:
                raise CommandError(
                    "Historical market backfill stopped with outcome="
                    f"{outcome}; resume from offset "
                    f"{checkpoint.get('offset', offset)} after resolving failures."
                )
            aggregate_requested += int(result.get("requested") or 0)
            aggregate_succeeded += int(result.get("succeeded") or 0)
            aggregate_failed += int(result.get("failed") or 0)
            aggregate_stored += int(result.get("stored") or 0)
            if outcome == "partial":
                partial_batches += 1
            if checkpoint.get("complete") is True:
                summary = {
                    "success": partial_batches == 0,
                    "outcome": "partial" if partial_batches else "success",
                    "stage": "complete",
                    "mode": "historical_market_facts",
                    "target_trade_date": target_trade_date.isoformat(),
                    "requested": aggregate_requested,
                    "succeeded": aggregate_succeeded,
                    "failed": aggregate_failed,
                    "stored": aggregate_stored,
                    "published": 0,
                    "partial_batches": partial_batches,
                    "current_publication_changed": False,
                    "must_not_use_for_decision": True,
                }
                self.stdout.write(json.dumps(summary, ensure_ascii=False, sort_keys=True))
                if partial_batches:
                    raise CommandError(
                        "Historical market facts were stored with unresolved provider rows; "
                        "inspect the emitted per-asset evidence."
                    )
                self.stdout.write(self.style.SUCCESS("Historical market-fact backfill complete."))
                return
            next_offset = int(checkpoint.get("next_offset", offset))
            if next_offset <= offset:
                raise CommandError("Historical market backfill checkpoint did not advance")
            offset = next_offset
            universe_hash = str(checkpoint.get("universe_hash") or "")
            batches_run += 1
            if max_batches and batches_run >= max_batches:
                self.stdout.write(
                    self.style.WARNING(f"Stopped at requested batch limit; resume from {offset}.")
                )
                return

    @staticmethod
    def _validated_operator(value: str) -> str:
        """Validate the exact server-issued actor identity used by the task."""

        operator = value.strip()
        if (
            not operator
            or len(operator) > 100
            or operator != value
            or any(character.isspace() for character in operator)
        ):
            raise CommandError("--operator must be a bounded canonical identity")
        return operator

    @staticmethod
    def _validated_target_trade_date(value: str) -> date:
        """Require a completed, provider-backed China trading session."""

        try:
            target = date.fromisoformat(value)
        except ValueError as exc:
            raise CommandError("--target-trade-date must be a canonical ISO date") from exc
        if target.isoformat() != value:
            raise CommandError("--target-trade-date must be a canonical ISO date")
        if target >= timezone.now().astimezone(CN_MARKET_TIMEZONE).date():
            raise CommandError("--target-trade-date must be before the current China date")
        try:
            open_sessions = load_open_cn_market_sessions(target, target)
        except (
            DataFetchError,
            OSError,
            PermissionError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as exc:
            raise CommandError("target-date trading-calendar evidence is unavailable") from exc
        if target not in open_sessions:
            raise CommandError("--target-trade-date is not an open China market session")
        return target
