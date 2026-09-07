"""Preview or explicitly execute one canonical Account actor capture."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.account.account_actor_authority_capture_composition import (
    build_account_actor_authority_capture,
)
from apps.account.infrastructure.account_actor_authority_capture_request import (
    parse_actor_authority_capture_request,
)


class Command(BaseCommand):
    """Validate a capture request by default and write only with explicit opt-in."""

    help = "Preview or explicitly capture one canonical Account actor authority source."
    requires_system_checks: list[str] = []

    def add_arguments(self, parser: CommandParser) -> None:
        """Register the required request path and explicit write opt-in."""

        parser.add_argument("--input", required=True, type=str)
        parser.add_argument("--execute", action="store_true")

    def handle(self, *args: Any, **options: Any) -> None:
        """Parse one local request and optionally invoke the existing writer."""

        del args
        input_path = options.get("input")
        execute = options.get("execute")
        if type(input_path) is not str or not input_path:
            raise CommandError("input must be an exact path string")
        if type(execute) is not bool:
            raise CommandError("execute must be an exact boolean")
        try:
            request = parse_actor_authority_capture_request(Path(input_path).read_bytes())
        except (OSError, UnicodeError, TypeError, ValueError) as error:
            raise CommandError("capture request could not be validated") from error
        if not execute:
            self._write(
                {
                    "outcome": "noop",
                    "mode": "dry_run",
                    "capture_executed": False,
                    "upstream_authority_verified": False,
                    "runtime_enabled": False,
                    "reason": "request_validated_only",
                    "source_id": request.command.source_id,
                    "source_version": request.command.source_version,
                }
            )
            return
        try:
            source = build_account_actor_authority_capture(
                recorder_service_id=request.recorder.service_id,
                validity_period=request.validity_period,
                using=request.database_alias,
            ).execute(request.command)
        except (OSError, UnicodeError, TypeError, ValueError) as error:
            raise CommandError("actor authority capture failed validation") from error
        self._write(
            {
                "outcome": "success",
                "mode": "execute",
                "capture_executed": True,
                "upstream_authority_verified": False,
                "reason": "canonical_capture_returned_current_authority_not_checked",
                "runtime_enabled": False,
                "source_id": source.source_id,
                "source_version": source.source_version,
                "content_hash": source.content_hash,
            }
        )

    def _write(self, payload: dict[str, object]) -> None:
        """Write one stable secret-free JSON result."""

        self.stdout.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))


__all__ = ["Command"]
