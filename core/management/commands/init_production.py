"""
Management command: Initialize production data and configurations.

Runs all init scripts in dependency order for a fresh deployment.
Note: This is separate from apps.account's init_all which handles
account-specific initialization (classification, rules, docs).

Usage:
    python manage.py init_production
    python manage.py init_production --dry-run
    python manage.py init_production --skip indicators,thresholds
"""

import importlib
import logging
import sys
import time

from django.core.management.base import BaseCommand, CommandError

logger = logging.getLogger(__name__)

# Init scripts in dependency order.
# Each entry: (module_path, display_name, description)
INIT_SCRIPTS: list[tuple[str, str, str]] = [
    ("scripts.init_indicators", "indicators", "宏观指标配置"),
    ("scripts.init_thresholds", "thresholds", "Regime 阈值配置"),
    ("scripts.init_config", "config", "系统基础配置"),
    ("scripts.init_asset_codes", "asset_codes", "资产代码配置"),
    ("scripts.init_sector_config", "sector_config", "板块配置"),
    ("scripts.init_equity_config", "equity_config", "个股分析配置"),
    ("scripts.init_weight_config", "weight_config", "权重配置"),
    ("scripts.init_fee_configs", "fee_configs", "手续费配置"),
    ("scripts.init_policy_keywords", "policy_keywords", "政策关键词"),
    ("scripts.init_rss_sources", "rss_sources", "RSS 数据源"),
    ("scripts.init_prompt_templates", "prompt_templates", "AI Prompt 模板"),
]


class Command(BaseCommand):
    help = "Initialize all data and configurations for a fresh deployment."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show which scripts would run without executing them.",
        )
        parser.add_argument(
            "--skip",
            type=str,
            default="",
            help="Comma-separated list of script names to skip (e.g. 'indicators,thresholds').",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        skip_names = {s.strip() for s in options["skip"].split(",") if s.strip()}

        self.stdout.write(self.style.MIGRATE_HEADING("AgomTradePro Initialization"))
        self.stdout.write(f"  Total scripts: {len(INIT_SCRIPTS)}")
        if skip_names:
            self.stdout.write(f"  Skipping: {', '.join(skip_names)}")
        self.stdout.write("")

        succeeded = 0
        failed = 0
        skipped = 0

        for module_path, name, description in INIT_SCRIPTS:
            if name in skip_names:
                self.stdout.write(f"  SKIP  {name} ({description})")
                skipped += 1
                continue

            if dry_run:
                self.stdout.write(f"  [DRY] {name} ({description})")
                continue

            self.stdout.write(f"  RUN   {name} ({description}) ... ", ending="")
            self.stdout.flush()

            start = time.monotonic()
            try:
                # Import and execute the init script module
                # Each script auto-initializes on import (runs at module level)
                if module_path in sys.modules:
                    importlib.reload(sys.modules[module_path])
                else:
                    importlib.import_module(module_path)

                elapsed = time.monotonic() - start
                self.stdout.write(self.style.SUCCESS(f"OK ({elapsed:.1f}s)"))
                succeeded += 1
            except Exception as e:
                elapsed = time.monotonic() - start
                self.stdout.write(self.style.ERROR(f"FAIL ({elapsed:.1f}s)"))
                self.stderr.write(f"    Error: {e}")
                logger.exception(f"Init script '{name}' failed: {e}")
                failed += 1

        self.stdout.write("")
        self.stdout.write(
            f"  Results: {succeeded} succeeded, {failed} failed, {skipped} skipped"
        )

        if failed > 0:
            raise CommandError(f"{failed} init script(s) failed. See logs for details.")

        self.stdout.write(self.style.SUCCESS("\nInitialization complete."))
