"""Collect production provider-policy parity evidence for the S6 rehearsal."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.data_center.infrastructure.policy_parity_rehearsal_runner import (
    collect_production_policy_parity,
)
from core.exceptions import AgomTradeProException


class Command(BaseCommand):
    """Evaluate the production bulk-route gate against a policy snapshot."""

    help = (
        "Evaluate the read-only production provider policy preflight against an "
        "explicit provider settings snapshot and write the parity report; fail "
        "closed when the bulk route gate blocks."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        """Register immutable candidate, scope and snapshot inputs."""

        parser.add_argument("--candidate-sha", required=True)
        parser.add_argument("--target-trade-date", required=True, type=date.fromisoformat)
        parser.add_argument("--universe-sha256", required=True)
        parser.add_argument("--provider-identities-sha256", required=True)
        parser.add_argument("--expected-provider-settings-raw-file-sha256", required=True)
        parser.add_argument("--expected-provider-settings-canonical-payload-sha256", required=True)
        parser.add_argument("--provider-identities", required=True, type=Path)
        parser.add_argument("--provider-settings-json", required=True, type=Path)
        parser.add_argument("--output-dir", required=True, type=Path)

    def handle(self, *args: object, **options: Any) -> None:
        """Write the parity report only when the preflight check passes."""

        del args
        try:
            report = collect_production_policy_parity(
                candidate_sha=options["candidate_sha"],
                target_trade_date=options["target_trade_date"],
                universe_sha256=options["universe_sha256"],
                provider_identities_sha256=options["provider_identities_sha256"],
                expected_provider_settings_raw_file_sha256=(
                    options["expected_provider_settings_raw_file_sha256"]
                ),
                expected_provider_settings_canonical_payload_sha256=(
                    options["expected_provider_settings_canonical_payload_sha256"]
                ),
                provider_identities_path=options["provider_identities"],
                provider_settings_path=options["provider_settings_json"],
                output_dir=options["output_dir"],
            )
        except (AgomTradeProException, OSError, ValueError) as exc:
            code = getattr(exc, "code", None) or str(exc)
            raise CommandError(str(code)) from exc
        self.stdout.write(
            json.dumps(
                {
                    "outcome": report["outcome"],
                    "provider_settings_raw_file_sha256": (
                        report["provider_settings_raw_file_sha256"]
                    ),
                    "provider_settings_canonical_payload_sha256": (
                        report["provider_settings_canonical_payload_sha256"]
                    ),
                },
                ensure_ascii=False,
            )
        )
