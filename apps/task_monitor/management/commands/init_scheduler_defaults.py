"""Initialize default database-backed scheduler tasks."""

from io import StringIO

from django.core.management import call_command
from django.core.management.base import BaseCommand

SCHEDULER_COMMANDS = (
    "setup_macro_daily_sync",
    "setup_equity_valuation_sync",
    "setup_workspace_snapshot_refresh",
)


class Command(BaseCommand):
    help = "Initialize all default django-celery-beat periodic tasks in one step."

    def add_arguments(self, parser):
        parser.add_argument(
            "--disable",
            action="store_true",
            help="Create/update all defaults but mark them disabled.",
        )

    def handle(self, *args, **options):
        disable = bool(options.get("disable"))
        executed: list[str] = []

        for command_name in SCHEDULER_COMMANDS:
            buffer = StringIO()
            kwargs = {"stdout": buffer, "stderr": buffer}
            if disable:
                kwargs["disable"] = True
            call_command(command_name, **kwargs)
            executed.append(command_name)
            output = buffer.getvalue().strip()
            if output:
                self.stdout.write(output)

        status = "disabled" if disable else "enabled"
        self.stdout.write(
            self.style.SUCCESS(
                f"Scheduler defaults initialized ({status}): {', '.join(executed)}"
            )
        )
