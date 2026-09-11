"""Activate one complete Account creation-evidence runtime settings package."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import DatabaseError

from apps.account.application.creation_evidence_settings import (
    ACCOUNT_CREATION_EVIDENCE_SETTINGS_KEY,
    ACCOUNT_CREATION_EVIDENCE_SETTINGS_SCHEMA_VERSION,
    decode_canonical_account_creation_evidence_settings,
)
from core.integration.config_center_runtime import activate_runtime_profile_patch


def _required_text(value: object, option: str, *, allow_spaces: bool) -> str:
    """Require explicit command text without coercing missing values."""

    if type(value) is not str or not value or value.strip() != value:
        raise CommandError(f"--{option} must be a non-empty explicit string")
    if not allow_spaces and any(character.isspace() for character in value):
        raise CommandError(f"--{option} must be a single canonical token")
    return value


class Command(BaseCommand):
    """Publish one fully specified recorder-chain settings snapshot."""

    help = "Activate explicit Account creation-evidence recorder settings."

    def add_arguments(self, parser: CommandParser) -> None:
        """Register all settings and activation metadata as required arguments."""

        parser.add_argument("--environment", required=True)
        parser.add_argument("--actor", required=True)
        parser.add_argument("--reason", required=True)
        parser.add_argument("--ttl-seconds", required=True, type=int)
        parser.add_argument("--allocation-recorder-service-id", required=True)
        parser.add_argument("--physical-v2-recorder-service-id", required=True)
        parser.add_argument("--allocated-v3-recorder-service-id", required=True)
        parser.add_argument("--binding-recorder-service-id", required=True)

    def handle(self, *args: object, **options: Any) -> None:
        """Validate once, activate through the Core bridge, and report the revision."""

        del args
        environment = _required_text(options.get("environment"), "environment", allow_spaces=False)
        actor = _required_text(options.get("actor"), "actor", allow_spaces=False)
        reason = _required_text(options.get("reason"), "reason", allow_spaces=True)
        settings_payload: dict[str, object] = {
            "schema_version": ACCOUNT_CREATION_EVIDENCE_SETTINGS_SCHEMA_VERSION,
            "ttl_seconds": options.get("ttl_seconds"),
            "allocation_recorder_service_id": options.get("allocation_recorder_service_id"),
            "physical_v2_recorder_service_id": options.get("physical_v2_recorder_service_id"),
            "allocated_v3_recorder_service_id": options.get("allocated_v3_recorder_service_id"),
            "binding_recorder_service_id": options.get("binding_recorder_service_id"),
        }
        try:
            checked = decode_canonical_account_creation_evidence_settings(settings_payload)
            checked.deadline_at(datetime.now(UTC))
        except (TypeError, ValueError) as error:
            message = str(error).replace("ttl_seconds", "--ttl-seconds")
            raise CommandError(f"creation evidence settings are invalid: {message}") from error

        try:
            result = activate_runtime_profile_patch(
                environment=environment,
                patch={ACCOUNT_CREATION_EVIDENCE_SETTINGS_KEY: checked.to_payload()},
                bootstrap_values=None,
                actor=actor,
                reason=reason,
            )
        except (DatabaseError, RuntimeError, TypeError, ValueError):
            raise CommandError("creation evidence settings activation failed") from None

        self.stdout.write(
            json.dumps(
                {"definition_key": ACCOUNT_CREATION_EVIDENCE_SETTINGS_KEY, **result},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )


__all__ = ["Command"]
