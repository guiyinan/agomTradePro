"""Run the read-only full-market publication preflight and print JSON."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.data_center.full_market_publication_preflight_composition import (
    build_full_market_publication_preflight_use_case,
)


class Command(BaseCommand):
    """Expose only read-only preflight checks; no write or provider mode exists."""

    help = (
        "Run the read-only full-market publication preflight (provider policy and "
        "routes, current publication gates, Account authority capture, Task "
        "Monitor attempt identity) and print a JSON report; exit 1 when any "
        "check is blocked."
    )

    def add_arguments(self, parser: Any) -> None:
        """Register the read-only snapshot and check-selection options."""

        parser.add_argument(
            "--provider-settings-json",
            type=str,
            default=None,
            help=(
                "Optional path to an explicit provider settings snapshot. When "
                "given, the provider policy check evaluates this snapshot "
                "instead of the live Config Center payload."
            ),
        )
        parser.add_argument(
            "--checks",
            type=str,
            nargs="+",
            default=None,
            help=(
                "Optional subset of preflight checks to run "
                "(provider_policy_and_routes current_publication_gates "
                "account_authority_capture task_attempt_identity)."
            ),
        )

    def handle(self, *args: object, **options: Any) -> None:
        """Print the aggregated JSON report and fail on any blocked check."""

        del args
        override = self._load_provider_settings_override(options.get("provider_settings_json"))
        checks = options.get("checks")
        try:
            use_case = build_full_market_publication_preflight_use_case(
                provider_settings_override=override,
            )
            report = use_case.execute(checks=tuple(checks) if checks else None)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            json.dumps(
                report.to_dict(),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
        )
        if report.outcome != "pass":
            raise CommandError(
                "full-market publication preflight blocked: " + ",".join(report.blocked_codes)
            )

    def _load_provider_settings_override(self, raw_path: object) -> dict[str, object] | None:
        """Read and validate an explicit provider settings snapshot file."""

        if raw_path is None:
            return None
        path = Path(str(raw_path))
        if path.is_symlink() or not path.is_file():
            raise CommandError(f"provider settings snapshot is not a regular file: {path}")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CommandError(f"provider settings snapshot is not valid JSON: {path}") from exc
        if not isinstance(payload, dict):
            raise CommandError("provider settings snapshot must be a JSON object")
        return {str(key): value for key, value in payload.items()}
