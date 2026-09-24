"""Run a bounded, read-only real-provider rehearsal before release evaluation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import DatabaseError

from apps.data_center.infrastructure.market_rehearsal_runner import (
    market_rehearsal_source_digest,
    run_market_provider_rehearsal,
)
from core.exceptions import AgomTradeProException


class Command(BaseCommand):
    """Expose only provider reads; no execute/write/publication mode exists."""

    help = (
        "Collect real quote/valuation rehearsal evidence using a read-only PostgreSQL transaction."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        """Register explicit candidate, provider, budget and artifact inputs."""
        parser.add_argument("--source-digest", action="store_true")
        parser.add_argument("--candidate-sha")
        parser.add_argument("--quote-provider-id", type=int)
        parser.add_argument("--valuation-provider-id", type=int)
        parser.add_argument("--sample-size", type=int, default=50)
        parser.add_argument("--max-dispatches", type=int, default=100)
        parser.add_argument("--max-seconds", type=float, default=180.0)
        parser.add_argument("--output", type=Path)

    def handle(self, *args: object, **options: Any) -> None:
        """Write one new evidence file; never treat provider success as release approval."""
        root = Path(settings.BASE_DIR)
        if options["source_digest"]:
            self.stdout.write(market_rehearsal_source_digest(root))
            return
        if any(
            options.get(name) is None
            for name in ("candidate_sha", "quote_provider_id", "valuation_provider_id", "output")
        ):
            raise CommandError("candidate SHA, both provider IDs and --output are required")
        destination: Path = options["output"]
        if destination.exists():
            raise CommandError("refusing to overwrite existing rehearsal evidence")
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            report = run_market_provider_rehearsal(
                quote_provider_id=options["quote_provider_id"],
                valuation_provider_id=options["valuation_provider_id"],
                candidate_sha=options["candidate_sha"],
                source_root=root,
                sample_size=options["sample_size"],
                max_dispatches=options["max_dispatches"],
                max_seconds=options["max_seconds"],
            )
        except (AgomTradeProException, DatabaseError, ValueError, OSError) as exc:
            # Retain a machine-visible failure without transport exception text or credentials.
            report = {
                "schema": "market.provider-rehearsal.v1",
                "outcome": "blocked",
                "release_ready": False,
                "error_code": "REHEARSAL_SETUP_UNAVAILABLE",
                "error_type": type(exc).__name__,
                "stored": 0,
                "publication_updated": False,
            }
        with destination.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
        self.stdout.write(
            json.dumps(
                {
                    "outcome": report["outcome"],
                    "release_ready": False,
                    "artifact": str(destination),
                },
                ensure_ascii=False,
            )
        )
        if report["outcome"] != "success":
            raise CommandError("rehearsal blocked; inspect the safe evidence artifact")
