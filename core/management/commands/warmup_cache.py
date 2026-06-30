"""
Management command: Warm up critical caches after deployment.

Pre-loads frequently accessed data into cache to avoid cold-start latency.

Usage:
    python manage.py warmup_cache
    python manage.py warmup_cache --only regime,macro
"""

import logging
import time

from django.core.cache import cache
from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Warm up caches for regime state, macro indicators, and alpha scores."

    def add_arguments(self, parser):
        parser.add_argument(
            "--only",
            type=str,
            default="",
            help="Comma-separated list of caches to warm (regime, macro, alpha). Default: all.",
        )

    def handle(self, *args, **options):
        only = {s.strip() for s in options["only"].split(",") if s.strip()}
        targets = only or {"regime", "macro", "alpha"}

        self.stdout.write(self.style.MIGRATE_HEADING("Cache Warmup"))

        if "regime" in targets:
            self._warmup_regime()

        if "macro" in targets:
            self._warmup_macro()

        if "alpha" in targets:
            self._warmup_alpha()

        self.stdout.write(self.style.SUCCESS("\nCache warmup complete."))

    def _warmup_regime(self):
        """Load current regime state into cache."""
        self.stdout.write("  Warming regime state ... ", ending="")
        self.stdout.flush()
        start = time.monotonic()
        try:
            from apps.regime.application.query_services import get_latest_regime_cache_payload

            latest = get_latest_regime_cache_payload()
            if latest is not None:
                cache.set("regime:current", latest, timeout=3600)
                elapsed = time.monotonic() - start
                self.stdout.write(self.style.SUCCESS(f"OK ({elapsed:.1f}s) - {latest['regime']}"))
            else:
                self.stdout.write(self.style.WARNING("SKIP - no regime data"))
        except Exception as e:
            elapsed = time.monotonic() - start
            self.stdout.write(self.style.ERROR(f"FAIL ({elapsed:.1f}s) - {e}"))
            logger.warning(f"Regime cache warmup failed: {e}")

    def _warmup_macro(self):
        """Load latest macro indicators into cache."""
        self.stdout.write("  Warming macro indicators ... ", ending="")
        self.stdout.flush()
        start = time.monotonic()
        try:
            from apps.data_center.application.query_services import (
                list_latest_macro_indicator_payloads,
            )

            count = 0
            for entry in list_latest_macro_indicator_payloads(limit=50):
                cache.set(
                    f"macro:latest:{entry['indicator_code']}",
                    {"value": entry["value"], "date": entry["reporting_period"]},
                    timeout=3600,
                )
                count += 1

            elapsed = time.monotonic() - start
            self.stdout.write(self.style.SUCCESS(f"OK ({elapsed:.1f}s) - {count} indicators"))
        except Exception as e:
            elapsed = time.monotonic() - start
            self.stdout.write(self.style.ERROR(f"FAIL ({elapsed:.1f}s) - {e}"))
            logger.warning(f"Macro cache warmup failed: {e}")

    def _warmup_alpha(self):
        """Load latest alpha scores into cache."""
        self.stdout.write("  Warming alpha scores ... ", ending="")
        self.stdout.flush()
        start = time.monotonic()
        try:
            from apps.alpha.application.query_services import (
                list_recent_alpha_score_cache_payloads,
            )

            count = 0
            for score in list_recent_alpha_score_cache_payloads(limit=100):
                cache.set(
                    f"alpha:score:{score['universe_id']}",
                    {
                        "provider": score["provider"],
                        "asof_date": score["asof_date"],
                        "status": score["status"],
                    },
                    timeout=3600,
                )
                count += 1

            elapsed = time.monotonic() - start
            self.stdout.write(self.style.SUCCESS(f"OK ({elapsed:.1f}s) - {count} scores"))
        except Exception as e:
            elapsed = time.monotonic() - start
            self.stdout.write(self.style.ERROR(f"FAIL ({elapsed:.1f}s) - {e}"))
            logger.warning(f"Alpha cache warmup failed: {e}")
