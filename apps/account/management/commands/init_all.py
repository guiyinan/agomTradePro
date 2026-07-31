"""
AgomTradePro System - Complete Initialization Command

This command initializes all system data in the correct order.
It is a wrapper that calls all individual init commands.

Usage:
    python manage.py init_all
    python manage.py init_all --skip-macro    # Skip macro data sync
    python manage.py init_all --force         # Force overwrite existing data
    python manage.py init_all --yes           # Skip interactive confirmation
"""

from collections.abc import Mapping
from typing import Any, NotRequired, TypedDict

from django.core import management
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import DatabaseError, connection


class InitializationStep(TypedDict):
    """One ordered initialization command and its execution policy."""

    name: str
    command: str
    description: str
    module: str
    optional: NotRequired[bool]


class InitializationResults(TypedDict):
    """Executed, intentionally skipped, and failed initialization steps."""

    success: list[str]
    skipped: list[str]
    failed: list[str]


class Command(BaseCommand):
    help = "Initialize all AgomTradePro system data (one-click setup)"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.init_steps: list[InitializationStep] = [
            # Order matters! Dependencies must be initialized first.
            {
                "name": "Asset Classification & Currencies",
                "command": "init_classification",
                "description": "Initialize asset types, categories, and currencies",
                "module": "apps.account",
            },
            {
                "name": "Investment Rules",
                "command": "init_enhanced_rules",
                "description": "Initialize enhanced investment rules with validation",
                "module": "apps.account",
            },
            {
                "name": "System Documentation",
                "command": "init_docs",
                "description": "Load system help documentation",
                "module": "apps.account",
            },
            {
                "name": "Regime Thresholds",
                "command": "init_regime_thresholds",
                "description": "Initialize regime analysis threshold configurations",
                "module": "apps.regime",
            },
            {
                "name": "Equity Scoring Weights",
                "command": "init_scoring_weights",
                "description": "Initialize stock scoring weight configurations",
                "module": "apps.equity",
            },
            {
                "name": "Prompt Templates",
                "command": "init_prompt_templates",
                "description": "Initialize AI prompt templates and chains",
                "module": "apps.prompt",
            },
            {
                "name": "Scheduler Defaults",
                "command": "init_scheduler_defaults",
                "description": "Initialize database-backed periodic tasks for macro, valuation, and workspace snapshots",
                "module": "apps.task_monitor",
            },
            {
                "name": "Authoritative RSS Sources",
                "command": "init_authoritative_rss_sources",
                "description": "Initialize policy and market news RSSHub sources",
                "module": "apps.policy",
            },
            {
                "name": "Policy Sentiment Gate Defaults",
                "command": "init_policy_sentiment_gate_defaults",
                "description": "Initialize policy and sentiment gate decision defaults",
                "module": "apps.policy",
            },
            {
                "name": "Macro Economic Data",
                "command": "sync_macro_data",
                "description": "Sync macro data (PMI, CPI, PPI) from AKShare",
                "module": "apps.macro",
                "optional": True,  # Can be skipped if network issues
            },
        ]

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--skip-macro",
            action="store_true",
            help="Skip macro data synchronization (requires network)",
        )
        parser.add_argument(
            "-y", "--yes", action="store_true", help="Skip interactive confirmation (assume yes)"
        )
        parser.add_argument("--force", action="store_true", help="Force overwrite existing data")
        parser.add_argument(
            "--step", type=str, help="Run only a specific step (e.g., --step classification)"
        )

    def handle(self, *args: object, **options: Any) -> None:
        """Execute the initialization"""
        self.stdout.write(self.style.SUCCESS("=" * 70))
        self.stdout.write(self.style.SUCCESS("AgomTradePro System - Complete Initialization"))
        self.stdout.write(self.style.SUCCESS("=" * 70))
        self.stdout.write("")

        # Show database info
        self._show_database_info()

        # Show plan
        self._show_plan(options)

        # Confirm
        if not options.get("force") and not options.get("yes"):
            if not self._confirm("Proceed with initialization?"):
                self.stdout.write(self.style.ERROR("Initialization cancelled"))
                return

        # Execute steps
        results = self._execute_steps(options)

        # Summary
        self._show_summary(results)

        if results["failed"]:
            raise CommandError(
                f"Initialization failed in {len(results['failed'])} required step(s)"
            )

        # Next steps
        self._show_next_steps()

    def _show_database_info(self) -> None:
        """Show current database status"""
        self.stdout.write("Database Status:")
        try:
            with connection.cursor() as cursor:
                tables = connection.introspection.table_names(cursor)
                self.stdout.write(f"  Tables: {len(tables)}")
        except DatabaseError as exc:
            self.stdout.write(self.style.WARNING(f"  Unable to read database: {exc}"))
        self.stdout.write("")

    def _show_plan(self, options: Mapping[str, object]) -> None:
        """Show initialization plan"""
        target_command = self._resolve_target_command(options.get("step"))
        self.stdout.write("Initialization Plan:")
        for i, step in enumerate(self.init_steps, 1):
            if step.get("optional") and options.get("skip_macro"):
                status = "[SKIP]"
            elif target_command and target_command != step["command"]:
                status = "[SKIP]"
            else:
                status = "[EXECUTE]"
            self.stdout.write(f'  {i}. {status} {step["name"]}: {step["description"]}')
        self.stdout.write("")

    def _confirm(self, message: str) -> bool:
        """Ask for user confirmation"""
        try:
            response = input(f"{message} (y/N): ")
            return response.lower() == "y"
        except (EOFError, KeyboardInterrupt):
            return False

    def _resolve_target_command(self, raw_step: object) -> str:
        """Resolve one exact command/short alias or reject an unknown selection."""

        if raw_step is None or raw_step == "":
            return ""
        if not isinstance(raw_step, str) or not raw_step.strip():
            raise CommandError("--step must be a non-empty string")
        normalized = raw_step.strip().lower()
        matches = [
            step["command"]
            for step in self.init_steps
            if normalized
            in {
                step["command"].lower(),
                step["command"].lower().removeprefix("init_"),
                "macro" if step["command"] == "sync_macro_data" else "",
            }
        ]
        if len(matches) != 1:
            raise CommandError(f"Unknown or ambiguous initialization step: {raw_step}")
        return matches[0]

    def _execute_steps(self, options: Mapping[str, object]) -> InitializationResults:
        """Execute all initialization steps"""
        results: InitializationResults = {"success": [], "skipped": [], "failed": []}

        target_command = self._resolve_target_command(options.get("step"))
        skip_macro = options.get("skip_macro") is True

        for step in self.init_steps:
            step_name = step["name"]
            command = step["command"]
            is_optional = step.get("optional", False)

            # Skip if specific step requested
            if target_command and target_command != command:
                results["skipped"].append(f"{step_name} (not selected)")
                continue

            # Skip optional steps if requested
            if is_optional and skip_macro:
                results["skipped"].append(f"{step_name} (skipped by --skip-macro)")
                continue

            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS(f"-> Running: {step_name}"))

            try:
                # Build command arguments
                call_options = {}
                if options.get("force") and command == "init_prompt_templates":
                    call_options["force"] = True

                # Execute the management command
                management.call_command(command, **call_options)

                results["success"].append(step_name)
                self.stdout.write(self.style.SUCCESS(f"  [OK] {step_name} completed"))

            except Exception as e:
                if is_optional:
                    # Optional steps can fail without blocking
                    results["skipped"].append(f"{step_name} (failed: {e})")
                    self.stdout.write(self.style.WARNING(f"  [SKIP] {step_name}: {e}"))
                else:
                    results["failed"].append(f"{step_name}: {e}")
                    self.stdout.write(self.style.ERROR(f"  [FAIL] {step_name}: {e}"))

        return results

    def _show_summary(self, results: InitializationResults) -> None:
        """Show initialization summary"""
        self.stdout.write("")
        self.stdout.write("=" * 70)
        self.stdout.write("Initialization Summary:")
        self.stdout.write("=" * 70)

        if results["success"]:
            self.stdout.write(self.style.SUCCESS(f'\n[OK] Success ({len(results["success"])}):'))
            for item in results["success"]:
                self.stdout.write(f"  - {item}")

        if results["skipped"]:
            self.stdout.write(self.style.WARNING(f'\n[SKIP] Skipped ({len(results["skipped"])}):'))
            for item in results["skipped"]:
                self.stdout.write(f"  - {item}")

        if results["failed"]:
            self.stdout.write(self.style.ERROR(f'\n[FAIL] Failed ({len(results["failed"])}):'))
            for item in results["failed"]:
                self.stdout.write(f"  - {item}")

        self.stdout.write("")
        self.stdout.write("=" * 70)

    def _show_next_steps(self) -> None:
        """Show recommended next steps"""
        self.stdout.write("")
        self.stdout.write("Recommended Next Steps:")
        self.stdout.write("  1. Create superuser: python manage.py createsuperuser")
        self.stdout.write("  2. Start server: python manage.py runserver")
        self.stdout.write("  3. Access admin: http://127.0.0.1:8000/admin/")
        self.stdout.write("  4. Access dashboard: http://127.0.0.1:8000/dashboard/")
        self.stdout.write("  5. Access scheduler console: http://127.0.0.1:8000/ops/task-monitor/")
        self.stdout.write("")
        self.stdout.write(
            "For detailed documentation, see: docs/development/system_initialization.md"
        )
        self.stdout.write("")
