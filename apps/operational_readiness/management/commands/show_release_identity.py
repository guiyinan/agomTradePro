"""Show and optionally assert the running deployment release identity."""

from __future__ import annotations

import json
import re
from argparse import ArgumentParser
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.operational_readiness.composition import make_get_release_identity_use_case

_COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")


class Command(BaseCommand):
    """Display the verified release identity and fail on provenance mismatch."""

    help = "Show the verified Git/image identity for the current application process."

    def add_arguments(self, parser: ArgumentParser | CommandParser) -> None:
        """Register optional deployment assertion arguments."""

        parser.add_argument("--expected-commit", default="")
        parser.add_argument("--json", action="store_true", dest="as_json")

    def handle(self, *args: Any, **options: Any) -> None:
        """Print release identity and reject unverified deployment provenance."""

        del args
        payload = make_get_release_identity_use_case().execute()
        expected_commit = str(options.get("expected_commit") or "")
        if expected_commit and _COMMIT_PATTERN.fullmatch(expected_commit) is None:
            raise CommandError("--expected-commit must be an exact lowercase 40-hex commit")
        if payload["status"] != "verified":
            raise CommandError(
                str(payload["blocked_reason"] or "current release identity is not verified")
            )
        if expected_commit and payload["source_commit"] != expected_commit:
            raise CommandError("verified release identity does not match expected commit")

        if bool(options.get("as_json")):
            self.stdout.write(json.dumps(payload, ensure_ascii=True, sort_keys=True))
            return
        self.stdout.write(
            self.style.SUCCESS(
                f"verified release {payload['release_tag']} at {payload['source_commit']}"
            )
        )
