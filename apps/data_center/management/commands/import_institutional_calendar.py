"""Import explicitly qualified, already retained NBS originals without network access."""

from __future__ import annotations

import hashlib
import json
from argparse import ArgumentParser
from datetime import UTC, datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.data_center.application.institutional_calendar_sources import (
    RetainedInstitutionalOriginal,
)
from apps.data_center.infrastructure.institutional_calendar_configuration import (
    decode_institutional_source_policy,
)
from apps.data_center.institutional_calendar_import import import_nbs_calendar_originals
from core.exceptions import AgomTradeProException


class Command(BaseCommand):
    """Offer an operator entry with explicit qualification, hashes and receipt clocks."""

    help = "Import retained qualified NBS schedule/actual HTML; no network, orders or tasks."

    def add_arguments(self, parser: ArgumentParser) -> None:
        """Require source configuration and exact original identities from the operator."""
        for key in (
            "policy",
            "catalogue",
            "schedule",
            "schedule-sha256",
            "schedule-url",
            "schedule-first-seen",
            "content-title",
            "event-id-prefix",
        ):
            parser.add_argument("--" + key, required=True)
        for key in ("actual", "actual-sha256", "actual-url", "actual-first-seen"):
            parser.add_argument("--" + key)

    def handle(self, *args: object, **options: object) -> str:
        """Verify retained input identities before one atomic import and print counts."""

        def text(key: str) -> str:
            value = options.get(key)
            if not isinstance(value, str) or not value:
                raise CommandError(f"Explicit --{key.replace('_', '-')} is required.")
            return value

        try:
            policy = decode_institutional_source_policy(
                json.loads(Path(text("policy")).read_text(encoding="utf-8"))
            )
            catalogue = Path(text("catalogue")).read_bytes()
            if hashlib.sha256(catalogue).hexdigest() != policy.catalogue_sha256:
                raise CommandError("Source catalogue digest differs from the qualified policy.")
            recorded_at = datetime.now(UTC)

            def original(prefix: str) -> RetainedInstitutionalOriginal:
                body = Path(text(prefix)).read_bytes()
                return RetainedInstitutionalOriginal(
                    policy=policy,
                    url=text(prefix + "_url"),
                    body=body,
                    sha256=text(prefix + "_sha256"),
                    first_seen_at=datetime.fromisoformat(text(prefix + "_first_seen")),
                    recorded_at=recorded_at,
                )

            events = import_nbs_calendar_originals(
                schedule=original("schedule"),
                actual=original("actual") if options.get("actual") else None,
                content_title=text("content_title"),
                event_id_prefix=text("event_id_prefix"),
            )
        except (OSError, ValueError, AgomTradeProException) as error:
            raise CommandError(str(error)) from error
        return f"Retained and verified {len(events)} exact event versions; read-only research reference."
