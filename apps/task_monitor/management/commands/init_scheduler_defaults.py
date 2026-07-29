"""Initialize default database-backed scheduler tasks."""

from io import StringIO
from typing import Any

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

SCHEDULER_COMMANDS = (
    "setup_macro_daily_sync",
    "setup_equity_valuation_sync",
    "setup_decision_quote_refresh",
    "setup_workspace_snapshot_refresh",
    "setup_account_risk_tasks",
    "setup_auto_advisor_weekly_report",
    "setup_personal_readiness_daily",
)


class Command(BaseCommand):
    help = "Initialize all default django-celery-beat periodic tasks in one step."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--disable",
            action="store_true",
            help="Create/update all defaults but mark them disabled.",
        )

    def handle(self, *args: str, **options: Any) -> None:
        disable = bool(options.get("disable"))
        executed: list[str] = []
        outputs: list[str] = []
        current_command = ""

        try:
            with transaction.atomic():
                for command_name in SCHEDULER_COMMANDS:
                    current_command = command_name
                    buffer = StringIO()
                    kwargs: dict[str, object] = {
                        "stdout": buffer,
                        "stderr": buffer,
                    }
                    if disable:
                        kwargs["disable"] = True
                    call_command(command_name, **kwargs)
                    executed.append(command_name)
                    output = buffer.getvalue().strip()
                    if output:
                        outputs.append(output)
        except Exception as exc:
            failed_command = current_command or "unknown"
            raise CommandError(
                "Scheduler defaults initialization failed at "
                f"{failed_command} ({exc.__class__.__name__})"
            ) from exc

        for output in outputs:
            self.stdout.write(output)

        status = "disabled" if disable else "enabled"
        self.stdout.write(
            self.style.SUCCESS(f"Scheduler defaults initialized ({status}): {', '.join(executed)}")
        )
