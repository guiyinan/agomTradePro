"""Collect measured full-universe provider capacity release evidence."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import DatabaseError

from apps.data_center.infrastructure.full_universe_capacity_runner import (
    collect_full_universe_capacity,
)
from apps.data_center.infrastructure.rehearsal_identity import load_rehearsal_identities
from core.exceptions import AgomTradeProException


class Command(BaseCommand):
    """Run the exact full-universe quote and valuation path with runtime instrumentation."""

    help = "Measure provider, deadline, PostgreSQL, lock and memory capacity for one candidate."

    def add_arguments(self, parser: CommandParser) -> None:
        """Register immutable identity, limit and destination inputs."""
        parser.add_argument("--candidate-sha", required=True)
        parser.add_argument("--target-trade-date", required=True, type=date.fromisoformat)
        parser.add_argument("--quote-provider-id", required=True, type=int)
        parser.add_argument("--valuation-provider-id", required=True, type=int)
        parser.add_argument("--provider-identities", required=True, type=Path)
        parser.add_argument("--provider-request-limit", required=True, type=int)
        parser.add_argument("--provider-window-seconds", required=True, type=float)
        parser.add_argument("--task-deadline-seconds", required=True, type=float)
        parser.add_argument("--lock-wait-limit-seconds", required=True, type=float)
        parser.add_argument("--max-dispatches", type=int, default=20)
        parser.add_argument("--output-dir", required=True, type=Path)

    def handle(self, *args: object, **options: Any) -> None:
        """Write success evidence only after all candidate runtime measurements pass."""
        try:
            report = collect_full_universe_capacity(
                quote_provider_id=options["quote_provider_id"],
                valuation_provider_id=options["valuation_provider_id"],
                candidate_sha=options["candidate_sha"],
                target_trade_date=options["target_trade_date"],
                source_root=Path(settings.BASE_DIR),
                output_dir=options["output_dir"],
                provider_identities=load_rehearsal_identities(options["provider_identities"]),
                provider_request_limit_per_window=options["provider_request_limit"],
                provider_window_seconds=options["provider_window_seconds"],
                task_deadline_seconds=options["task_deadline_seconds"],
                lock_wait_limit_seconds=options["lock_wait_limit_seconds"],
                max_dispatches=options["max_dispatches"],
            )
        except (AgomTradeProException, DatabaseError, OSError, ValueError) as exc:
            code = getattr(exc, "code", "REHEARSAL_CAPACITY_COLLECTION_FAILED")
            raise CommandError(str(code)) from exc
        self.stdout.write(
            json.dumps(
                {
                    "outcome": report["outcome"],
                    "artifact": str(options["output_dir"] / "full-universe-capacity.json"),
                },
                ensure_ascii=False,
            )
        )
