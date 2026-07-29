"""
Management command: Health check for deployment verification.

Returns exit code 0 if healthy, 1 if unhealthy.
Suitable for Docker HEALTHCHECK and CI pipelines.

Usage:
    python manage.py healthcheck
    python manage.py healthcheck --json
"""

import json
import sys
from argparse import ArgumentParser
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from core.health_checks import is_healthy, run_readiness_checks


class Command(BaseCommand):
    help = "Run health checks and exit 0 (healthy) or 1 (unhealthy)."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--json",
            action="store_true",
            help="Output results as JSON.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        checks = run_readiness_checks()
        healthy = is_healthy(checks)
        public_checks = _public_checks(checks)
        as_json = options.get("json")
        if not isinstance(as_json, bool):
            raise CommandError("--json option must be boolean")

        if as_json:
            output = {"healthy": healthy, "checks": public_checks}
            self.stdout.write(json.dumps(output, indent=2, default=str))
        else:
            self.stdout.write(f"Healthy: {healthy}")
            for name, result in public_checks.items():
                status = result.get("status", "unknown")
                if status == "ok":
                    self.stdout.write(f"  {name}: {self.style.SUCCESS(status)}")
                elif status in ("skipped", "warning"):
                    self.stdout.write(f"  {name}: {self.style.WARNING(status)}")
                    reason = result.get("reason") or result.get("empty_tables", "")
                    if reason:
                        self.stdout.write(f"    {reason}")
                else:
                    self.stdout.write(f"  {name}: {self.style.ERROR(status)}")
                    error = result.get("error", "")
                    if error:
                        self.stdout.write(f"    {error}")

        if not healthy:
            sys.exit(1)


def _public_checks(checks: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Return health evidence without exception text or connection details."""

    safe_keys = frozenset({"status", "source", "workers", "empty_tables", "readiness_status"})
    return {
        str(name): {key: value for key, value in result.items() if key in safe_keys}
        for name, result in checks.items()
    }
