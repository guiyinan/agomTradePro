"""Install the exact independently reviewed isolated scope report as current capacity input."""

from __future__ import annotations

import json
from argparse import ArgumentParser
from collections.abc import Mapping
from getpass import getpass
from pathlib import Path

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.data_center.application.financial_scope_capacity_input import (
    FinancialScopeCapacityInputError,
    install_financial_scope_manifest_pointer,
)
from apps.data_center.infrastructure.financial_capacity_build_identity import (
    FileFinancialCapacityBuildIdentitySource,
)
from apps.data_center.infrastructure.financial_scope_discovery_governance import (
    DjangoFinancialScopeManifestReviewSource,
)
from apps.data_center.infrastructure.financial_scope_manifest_current_pointer import (
    DjangoFinancialScopeManifestCurrentPointerSource,
)

_MAX_REPORT_BYTES = 16 * 1024 * 1024


class Command(BaseCommand):
    """Install a reviewed S6 report for isolated capacity input without running refresh."""

    help = "Install one reviewed isolated financial scope report as current capacity input."

    def add_arguments(self, parser: ArgumentParser) -> None:
        """Require an exact report file and a separately authenticated superuser actor."""

        parser.add_argument("--report-file", required=True, type=Path)
        parser.add_argument("--actor", required=True, help="Username of the governance superuser")

    def handle(
        self,
        *args: object,
        report_file: Path,
        actor: str,
        **options: object,
    ) -> str:
        """Verify the running candidate and review events before atomically moving the pointer."""

        actor_name = self._authenticate_actor(actor)
        if report_file.is_symlink() or not report_file.is_file():
            raise CommandError("financial scope report file is unavailable")
        try:
            content = report_file.read_bytes()
        except OSError as exc:
            raise CommandError("financial scope report file cannot be read") from exc
        if not content or len(content) > _MAX_REPORT_BYTES:
            raise CommandError("financial scope report file size is invalid")
        try:
            report_payload: object = json.loads(content.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise CommandError("financial scope report JSON is invalid") from exc
        if not isinstance(report_payload, Mapping):
            raise CommandError("financial scope report must be a JSON object")
        candidate_sha = report_payload.get("candidate_sha")
        if type(candidate_sha) is not str:
            raise CommandError("financial scope report candidate identity is invalid")
        try:
            source_commit = FileFinancialCapacityBuildIdentitySource(
                Path(settings.AGOM_BUILD_IDENTITY_PATH)
            ).source_commit()
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            raise CommandError("financial scope runtime build identity is unavailable") from exc
        if candidate_sha != source_commit:
            raise CommandError("financial scope report does not match the running build identity")
        try:
            pointer = install_financial_scope_manifest_pointer(
                pointer_source=DjangoFinancialScopeManifestCurrentPointerSource(),
                review_source=DjangoFinancialScopeManifestReviewSource(),
                report_payload=report_payload,
                environment="isolated",
                updated_by=actor_name,
                now=timezone.now(),
            )
        except FinancialScopeCapacityInputError as exc:
            raise CommandError(exc.code.lower()) from None
        message = (
            "Installed reviewed isolated financial scope pointer "
            f"revision {pointer.revision} ({pointer.report_sha256})."
        )
        self.stdout.write(self.style.SUCCESS(message))
        return message

    @staticmethod
    def _authenticate_actor(actor: str) -> str:
        """Require a valid interactive Django superuser without logging credentials."""

        user_model = get_user_model()
        try:
            password = getpass("Superuser password: ")
        except (EOFError, OSError) as exc:
            raise CommandError(
                "financial scope pointer requires interactive superuser auth"
            ) from exc
        user = authenticate(
            request=None,
            **{user_model.USERNAME_FIELD: actor, "password": password},
        )
        if user is None or user.is_superuser is not True:
            raise CommandError("financial scope pointer requires a Django superuser")
        return user.get_username()


__all__ = ["Command"]
