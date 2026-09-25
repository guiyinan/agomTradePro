"""Collect isolated PostgreSQL publication write and rollback evidence."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import DatabaseError

from apps.data_center.infrastructure.isolated_write_rehearsal_runner import (
    collect_isolated_write_rehearsal,
)
from core.exceptions import AgomTradeProException


class Command(BaseCommand):
    """Expose the fail-closed isolated write rehearsal as a management command."""

    help = "Write/read/rollback one candidate-bound publication in isolated PostgreSQL."

    def add_arguments(self, parser: CommandParser) -> None:
        """Register immutable candidate and artifact inputs."""
        parser.add_argument("--candidate-sha", required=True)
        parser.add_argument("--target-trade-date", required=True, type=date.fromisoformat)
        parser.add_argument("--universe-sha256", required=True)
        parser.add_argument("--provider-identities-sha256", required=True)
        parser.add_argument("--output-dir", required=True, type=Path)

    def handle(self, *args: object, **options: Any) -> None:
        """Write success artifacts only after PostgreSQL confirms zero residual rows."""
        try:
            report = collect_isolated_write_rehearsal(
                candidate_sha=options["candidate_sha"],
                target_trade_date=options["target_trade_date"],
                universe_sha256=options["universe_sha256"],
                provider_identities_sha256=options["provider_identities_sha256"],
                output_dir=options["output_dir"],
                source_root=Path(settings.BASE_DIR),
            )
        except (AgomTradeProException, DatabaseError, OSError, ValueError) as exc:
            code = getattr(exc, "code", "REHEARSAL_WRITE_COLLECTION_FAILED")
            raise CommandError(str(code)) from exc
        self.stdout.write(
            json.dumps(
                {
                    "outcome": report["outcome"],
                    "artifact": str(options["output_dir"] / "isolated-write-rehearsal.json"),
                },
                ensure_ascii=False,
            )
        )
