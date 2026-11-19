"""Initialize an exact, immutable frozen research document through Application."""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.research.domain.event_study_control import EventStudyControlError
from apps.research.event_study_control_composition import build_event_study_control


class Command(BaseCommand):
    """Explicit operator entrypoint for versioned research parameters."""

    help = "Register retained frozen event-study specification bytes and their expected SHA-256."

    def add_arguments(self, parser: CommandParser) -> None:
        """Require explicit original path, expected identity and authenticated actor."""
        parser.add_argument("--file", required=True)
        parser.add_argument("--expected-sha256", required=True)
        parser.add_argument("--actor-user-id", type=int, required=True)

    def handle(self, *args: str, **options: object) -> str:
        """Read original bytes and delegate all authorization and writes."""
        path, expected, actor = (
            options["file"],
            options["expected_sha256"],
            options["actor_user_id"],
        )
        if not isinstance(path, str) or not isinstance(expected, str) or type(actor) is not int:
            raise CommandError("Explicit file, expected SHA-256 and actor are required.")
        try:
            document = Path(path).read_bytes().decode("utf-8")
            digest = build_event_study_control().register_spec(
                document, expected, actor_user_id=actor
            )
        except (OSError, UnicodeError, EventStudyControlError) as exc:
            raise CommandError(str(exc)) from exc
        return digest
