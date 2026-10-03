"""Run the read-only full-market publication preflight and print JSON."""

from __future__ import annotations

import json
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

    def handle(self, *args: object, **options: Any) -> None:
        """Print the aggregated JSON report and fail on any blocked check."""

        del args, options
        report = build_full_market_publication_preflight_use_case().execute()
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
