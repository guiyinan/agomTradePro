"""Set the persistent global gate for decision-facing interfaces."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandParser
from django.utils.dateparse import parse_datetime

from apps.config_center.application.use_cases import UpdateDecisionRuntimeStateUseCase


class Command(BaseCommand):
    """Persist an audited decision-runtime state transition."""

    help = "Set active, maintenance, validating, or blocked decision runtime state."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "status",
            choices=("active", "maintenance", "validating", "blocked"),
        )
        parser.add_argument("--reason", default="")
        parser.add_argument("--changed-by", required=True)
        parser.add_argument("--release-ref", default="")
        parser.add_argument("--expected-resume-at", default="")

    def handle(self, *args: object, **options: Any) -> None:
        expected_resume_raw = str(options["expected_resume_at"] or "").strip()
        expected_resume_at = parse_datetime(expected_resume_raw) if expected_resume_raw else None
        if expected_resume_raw and expected_resume_at is None:
            raise ValueError("--expected-resume-at must be an ISO-8601 datetime")
        state = UpdateDecisionRuntimeStateUseCase().execute(
            status=str(options["status"]),
            reason=str(options["reason"]),
            changed_by=str(options["changed_by"]),
            release_ref=str(options["release_ref"]),
            expected_resume_at=expected_resume_at,
        )
        self.stdout.write(self.style.SUCCESS(str(state.to_dict())))
