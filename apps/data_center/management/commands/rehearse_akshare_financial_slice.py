"""Run one bounded real-provider financial sync for a fresh S6 rehearsal."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError

from apps.data_center.infrastructure.akshare_financial_slice_rehearsal import (
    collect_akshare_financial_slice_rehearsal,
)
from core.exceptions import DataFetchError


class Command(BaseCommand):
    """Execute the S6 AKShare stage behind isolated-environment checks."""

    help = "Collect one isolated PostgreSQL/Redis real-provider financial-slice report."

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Accept only frozen S6 identities and isolation endpoints."""

        parser.add_argument("--candidate-sha", required=True)
        parser.add_argument("--target-trade-date", required=True)
        parser.add_argument("--universe-sha256", required=True)
        parser.add_argument("--provider-identities-sha256", required=True)
        parser.add_argument("--provider-identities", required=True, type=Path)
        parser.add_argument("--expected-database-name", required=True)
        parser.add_argument("--expected-database-host", required=True)
        parser.add_argument("--expected-redis-host", required=True)
        parser.add_argument("--candidate-regression-evidence", required=True, type=Path)
        parser.add_argument("--output-dir", required=True, type=Path)

    def handle(self, *args: Any, **options: Any) -> str | None:
        """Run the report stage and hide provider exceptions from command output."""

        try:
            target_trade_date = date.fromisoformat(str(options["target_trade_date"]))
            if target_trade_date.isoformat() != options["target_trade_date"]:
                raise ValueError("target date is not canonical")
            report = collect_akshare_financial_slice_rehearsal(
                candidate_sha=str(options["candidate_sha"]),
                target_trade_date=target_trade_date,
                universe_sha256=str(options["universe_sha256"]),
                provider_identities_sha256=str(options["provider_identities_sha256"]),
                provider_identities_path=Path(options["provider_identities"]),
                expected_database_name=str(options["expected_database_name"]),
                expected_database_host=str(options["expected_database_host"]),
                expected_redis_host=str(options["expected_redis_host"]),
                candidate_regression_evidence_path=Path(options["candidate_regression_evidence"]),
                output_dir=Path(options["output_dir"]),
            )
        except (DatabaseError, DataFetchError, OSError, TypeError, ValueError, RuntimeError) as exc:
            raise CommandError("REHEARSAL_FINANCIAL_SLICE_FAILED") from exc
        self.stdout.write(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return None
