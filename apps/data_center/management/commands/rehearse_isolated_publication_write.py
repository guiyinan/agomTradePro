"""Collect isolated PostgreSQL publication write and rollback evidence."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import DatabaseError

from apps.data_center.infrastructure.isolated_write_rehearsal_runner import (
    collect_isolated_write_rehearsal,
    preflight_isolated_write_rehearsal,
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
        parser.add_argument("--expected-database-name", required=True)
        parser.add_argument("--expected-database-host", required=True)
        parser.add_argument("--output-dir", required=True, type=Path)
        parser.add_argument(
            "--initialize-reviewed-catalog",
            action="store_true",
            help=(
                "Synchronize repository-reviewed Data Center manifests after the "
                "disposable PostgreSQL scope is verified."
            ),
        )

    def handle(self, *args: object, **options: Any) -> None:
        """Write success artifacts only after PostgreSQL confirms zero residual rows."""
        try:
            if options["initialize_reviewed_catalog"]:
                preflight_isolated_write_rehearsal(
                    candidate_sha=options["candidate_sha"],
                    source_root=Path(settings.BASE_DIR),
                    expected_database_name=options["expected_database_name"],
                    expected_database_host=options["expected_database_host"],
                    require_ephemeral_host=True,
                )
                call_command("initialize_data_center_catalog", verbosity=0)
            report = collect_isolated_write_rehearsal(
                candidate_sha=options["candidate_sha"],
                target_trade_date=options["target_trade_date"],
                universe_sha256=options["universe_sha256"],
                provider_identities_sha256=options["provider_identities_sha256"],
                output_dir=options["output_dir"],
                source_root=Path(settings.BASE_DIR),
                expected_database_name=options["expected_database_name"],
                expected_database_host=options["expected_database_host"],
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
