"""Validate that persisted encrypted values are readable in this environment."""

from __future__ import annotations

import json
from argparse import ArgumentParser
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from core.encryption_readiness import collect_encryption_readiness


class Command(BaseCommand):
    """Check that the configured encryption key matches persisted data."""

    help = "Check encrypted MCP, AI provider, and backup credentials for key mismatch."

    def add_arguments(self, parser: ArgumentParser) -> None:
        """Register output options."""

        parser.add_argument("--json", action="store_true", dest="as_json")

    def handle(self, *args: Any, **options: Any) -> None:
        """Print readiness and fail when encrypted data is unreadable."""

        result = collect_encryption_readiness()
        as_json = options.get("as_json")
        if not isinstance(as_json, bool):
            raise CommandError("--json option must be boolean")
        if as_json:
            self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
        else:
            self.stdout.write(
                self.style.SUCCESS("Encryption readiness: ready")
                if result["status"] == "ready"
                else self.style.ERROR("Encryption readiness: blocked")
            )
            for failure in result["failures"]:
                self.stdout.write(f"- {failure}")
        if result["status"] != "ready":
            raise CommandError("Encryption key does not match persisted encrypted data.")
