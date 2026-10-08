"""Append an externally reviewed financial capacity ceiling to the runtime database."""

from __future__ import annotations

import json
from argparse import ArgumentParser
from getpass import getpass
from pathlib import Path
from typing import Literal, cast

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction

from apps.data_center.application.financial_capacity_contracts import (
    FinancialCapacityWorkflowError,
    GovernedFinancialCapacityRehearsalCeiling,
    GovernedFinancialProductionCeiling,
    GovernedFinancialQualificationCeiling,
)
from apps.data_center.application.financial_capacity_governance import (
    parse_financial_capacity_governance_record,
)
from apps.data_center.infrastructure.financial_capacity_build_identity import (
    FileFinancialCapacityBuildIdentitySource,
)
from apps.data_center.models import FinancialCapacityGovernanceRecordModel

_MAX_RECORD_BYTES = 64 * 1024
_STAGES = ("qualification", "capacity_rehearsal", "production")


class Command(BaseCommand):
    """Record supplied approval content without generating or modifying its authority."""

    help = "Append an externally reviewed financial capacity ceiling to the runtime database."

    def add_arguments(self, parser: ArgumentParser) -> None:
        """Require the external record, explicit stage, and a registered superuser actor."""

        parser.add_argument("--record-file", required=True, type=Path)
        parser.add_argument("--stage", required=True, choices=_STAGES)
        parser.add_argument("--actor", required=True, help="Username of the reviewing superuser")

    def handle(
        self,
        *args: object,
        record_file: Path,
        stage: str,
        actor: str,
        **options: object,
    ) -> str:
        """Validate and append one approved payload bound to the running source revision."""

        user_model = get_user_model()
        username_field = user_model.USERNAME_FIELD
        try:
            actor_password = getpass("Superuser password: ")
        except (EOFError, OSError) as exc:
            raise CommandError(
                "financial capacity governance requires interactive superuser auth"
            ) from exc
        actor_user = authenticate(
            request=None,
            **{username_field: actor, "password": actor_password},
        )
        if actor_user is None or actor_user.is_superuser is not True:
            raise CommandError("financial capacity governance entry requires a Django superuser")
        if stage not in _STAGES:
            raise CommandError("financial capacity governance stage is invalid")
        try:
            content = record_file.read_bytes()
        except OSError as exc:
            raise CommandError("financial capacity approval file cannot be read") from exc
        if not content or len(content) > _MAX_RECORD_BYTES:
            raise CommandError("financial capacity approval file size is invalid")
        try:
            payload: object = json.loads(content.decode("utf-8"))
            parsed = parse_financial_capacity_governance_record(
                stage=cast(Literal["qualification", "capacity_rehearsal", "production"], stage),
                record=payload,
            )
        except (UnicodeError, json.JSONDecodeError, FinancialCapacityWorkflowError) as exc:
            raise CommandError("financial capacity approval record is invalid") from exc
        if not isinstance(payload, dict):
            raise CommandError("financial capacity approval record must be a JSON object")
        if stage == "qualification" and not isinstance(
            parsed,
            GovernedFinancialQualificationCeiling,
        ):
            raise CommandError("financial capacity record does not match qualification stage")
        if stage == "capacity_rehearsal" and not isinstance(
            parsed,
            GovernedFinancialCapacityRehearsalCeiling,
        ):
            raise CommandError("financial capacity record does not match capacity rehearsal stage")
        if stage == "production" and not isinstance(parsed, GovernedFinancialProductionCeiling):
            raise CommandError("financial capacity record does not match production stage")
        recorder = actor_user.get_username()
        if recorder.casefold() == parsed.approved_by.casefold():
            raise CommandError(
                "financial capacity approval recorder must differ from the approving owner"
            )
        try:
            source_commit = FileFinancialCapacityBuildIdentitySource(
                Path(settings.AGOM_BUILD_IDENTITY_PATH)
            ).source_commit()
        except FinancialCapacityWorkflowError as exc:
            raise CommandError("financial capacity runtime build identity is unavailable") from exc
        if parsed.binding.candidate_sha != source_commit:
            raise CommandError(
                "financial capacity approval candidate does not match the running build identity"
            )
        try:
            with transaction.atomic():
                FinancialCapacityGovernanceRecordModel._default_manager.create(
                    approval_id=parsed.approval_id,
                    stage=stage,
                    record=cast(dict[str, object], payload),
                    created_by=recorder,
                )
        except IntegrityError as exc:
            raise CommandError(
                "financial capacity approval ID already exists; records are append-only"
            ) from exc
        message = f"Recorded reviewed financial capacity {stage} ceiling {parsed.approval_id}."
        self.stdout.write(self.style.SUCCESS(message))
        return message
