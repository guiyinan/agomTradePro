"""Append an authenticated owner event for an existing financial capacity ceiling."""

from __future__ import annotations

import hashlib
import json
from argparse import ArgumentParser
from collections.abc import Mapping
from getpass import getpass
from pathlib import Path
from typing import Literal, cast
from uuid import uuid4

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.data_center.application.financial_capacity_contracts import (
    FinancialCapacityWorkflowError,
)
from apps.data_center.application.financial_capacity_governance import (
    parse_financial_capacity_governance_record,
)
from apps.data_center.infrastructure.financial_capacity_build_identity import (
    FileFinancialCapacityBuildIdentitySource,
)
from apps.data_center.infrastructure.models import (
    FinancialCapacityGovernanceRecordModel,
    FinancialCapacityOwnerApprovalEventModel,
)

_STAGES = ("qualification", "capacity_rehearsal", "production")


class Command(BaseCommand):
    """Record an independently authenticated owner signature for one canonical payload."""

    help = "Append an authenticated owner approval event for a financial capacity ceiling."

    def add_arguments(self, parser: ArgumentParser) -> None:
        """Require the exact existing approval and its expected owner account."""

        parser.add_argument("--approval-id", required=True)
        parser.add_argument("--owner", required=True, help="Django username in approved_by")

    def handle(
        self,
        *args: object,
        approval_id: str,
        owner: str,
        **options: object,
    ) -> str:
        """Authenticate the named owner and append one exact, non-revoked approval event."""

        user_model = get_user_model()
        username_field = user_model.USERNAME_FIELD
        try:
            password = getpass("Capacity owner password: ")
        except (EOFError, OSError) as exc:
            raise CommandError("owner approval requires interactive Django authentication") from exc
        owner_user = authenticate(
            request=None,
            **{username_field: owner, "password": password},
        )
        if (
            owner_user is None
            or owner_user.is_active is not True
            or owner_user.is_superuser is not True
            or owner_user.get_username() != owner
        ):
            raise CommandError(
                "financial capacity owner approval requires the exact Django owner account"
            )

        try:
            with transaction.atomic():
                row = (
                    FinancialCapacityGovernanceRecordModel._default_manager.select_for_update()
                    .filter(approval_id=approval_id, revocation__isnull=True)
                    .first()
                )
                if row is None:
                    raise CommandError("financial capacity approval is missing or revoked")
                if not isinstance(row.record, Mapping):
                    raise CommandError("financial capacity approval payload is invalid")
                raw_record = cast(dict[str, object], row.record)
                try:
                    parsed = parse_financial_capacity_governance_record(
                        stage=cast(
                            Literal["qualification", "capacity_rehearsal", "production"],
                            row.stage,
                        ),
                        record=raw_record,
                    )
                except (FinancialCapacityWorkflowError, TypeError, ValueError) as exc:
                    raise CommandError("financial capacity approval payload is invalid") from exc
                if parsed.approval_id != row.approval_id:
                    raise CommandError(
                        "financial capacity approval payload identity is inconsistent"
                    )
                if parsed.approved_by != owner_user.get_username():
                    raise CommandError(
                        "authenticated owner does not match the approved_by identity"
                    )
                if parsed.approved_by.casefold() == row.created_by.casefold():
                    raise CommandError(
                        "capacity approval recorder and owner must be different users"
                    )
                if FinancialCapacityOwnerApprovalEventModel._default_manager.filter(
                    governance_record=row
                ).exists():
                    raise CommandError("financial capacity approval already has an owner event")

                try:
                    source_commit = FileFinancialCapacityBuildIdentitySource(
                        Path(settings.AGOM_BUILD_IDENTITY_PATH)
                    ).source_commit()
                except FinancialCapacityWorkflowError as exc:
                    raise CommandError(
                        "financial capacity runtime build identity is unavailable"
                    ) from exc
                if parsed.binding.candidate_sha != source_commit:
                    raise CommandError(
                        "approval candidate does not match the running build identity"
                    )

                now = timezone.now()
                ceiling = parsed
                if ceiling.approved_at > now or ceiling.expires_at <= now:
                    raise CommandError(
                        "capacity owner approval time is future or ceiling is expired"
                    )
                canonical_payload = json.dumps(
                    raw_record,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
                FinancialCapacityOwnerApprovalEventModel._default_manager.create(
                    governance_record=row,
                    event_id=f"financial-capacity-owner:{uuid4()}",
                    approved_by=owner_user.get_username(),
                    approved_at=ceiling.approved_at,
                    approval_receipt_sha256=ceiling.approval_receipt_sha256,
                    record_sha256=hashlib.sha256(canonical_payload).hexdigest(),
                )
        except IntegrityError as exc:
            raise CommandError("financial capacity owner event already exists") from exc

        message = (
            f"Recorded authenticated owner event for financial capacity approval {approval_id}."
        )
        self.stdout.write(self.style.SUCCESS(message))
        return message
