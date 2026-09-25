"""Replay retained market responses offline without launching provider or business tasks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.data_center.infrastructure.rehearsal_replay_collector import collect_response_replay


class Command(BaseCommand):
    """Require hash-pinned capture and unit contract inputs; write only new evidence files."""

    help = "Collect offline replay evidence from retained real-provider response bytes."

    def add_arguments(self, parser: CommandParser) -> None:
        """Register explicit identity, input hashes and exclusive output directory."""
        parser.add_argument("--probe", required=True, type=Path)
        parser.add_argument("--probe-sha256", required=True)
        parser.add_argument("--unit-contract", required=True, type=Path)
        parser.add_argument("--unit-contract-sha256", required=True)
        parser.add_argument("--candidate-sha", required=True)
        parser.add_argument("--target-trade-date", required=True)
        parser.add_argument("--output-dir", required=True, type=Path)

    def handle(self, *args: object, **options: Any) -> None:
        """Emit safe failure information, never raw response content or exception text."""
        try:
            report = collect_response_replay(
                probe_path=options["probe"],
                expected_probe_sha256=options["probe_sha256"],
                unit_contract_path=options["unit_contract"],
                expected_unit_contract_sha256=options["unit_contract_sha256"],
                candidate_sha=options["candidate_sha"],
                target_trade_date=options["target_trade_date"],
                source_root=Path(settings.BASE_DIR),
                output_dir=options["output_dir"],
            )
        except (ValueError, OSError, TypeError, KeyError) as exc:
            self.stdout.write(
                json.dumps(
                    {
                        "outcome": "blocked",
                        "release_ready": False,
                        "error_code": "REHEARSAL_OFFLINE_REPLAY_FAILED",
                        "error_type": type(exc).__name__,
                    }
                )
            )
            raise CommandError(
                "offline replay blocked; no successful release report was produced"
            ) from None
        self.stdout.write(
            json.dumps(
                {
                    "outcome": report["outcome"],
                    "release_ready": False,
                    "artifact": str(options["output_dir"] / "real-response-unit-replay.json"),
                }
            )
        )
