"""Configure explicit policy publication inputs without publishing policy or authority."""

import json
from datetime import UTC, datetime
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import DatabaseError

from apps.account.application.single_owner_policy_publication_settings import (
    SINGLE_OWNER_POLICY_PUBLICATION_SETTINGS_KEY,
    SINGLE_OWNER_POLICY_PUBLICATION_SETTINGS_SCHEMA_VERSION,
    decode_single_owner_policy_publication_settings,
)
from core.integration.config_center_runtime import activate_runtime_profile_patch

_TEXT_FIELDS = (
    "owner_username",
    "tenant_id",
    "owner_id",
    "authorization_source_id",
    "authorization_source_version",
    "authorization_content_hash",
)


def _metadata(value: object, name: str) -> str:
    """Validate operator metadata without treating its actor label as authentication."""
    if type(value) is not str or not value or value.strip() != value:
        raise CommandError(f"--{name} must be an explicit non-empty string")
    if name != "reason" and any(character.isspace() for character in value):
        raise CommandError(f"--{name} must be a canonical token")
    return value


class Command(BaseCommand):
    """Activate a complete settings snapshot; later publication still verifies its sources."""

    help = "Configure single-owner policy publication inputs; does not grant access."

    def add_arguments(self, parser: CommandParser) -> None:
        """Require every setting and change-record field explicitly."""
        for name in ("environment", "actor", "reason", *_TEXT_FIELDS):
            parser.add_argument("--" + name.replace("_", "-"), required=True)
        parser.add_argument("--ttl-seconds", required=True, type=int)

    def handle(self, *args: object, **options: Any) -> None:
        """Validate and write only the dedicated Config Center settings key."""
        del args
        environment = _metadata(options.get("environment"), "environment")
        actor = _metadata(options.get("actor"), "actor")
        reason = _metadata(options.get("reason"), "reason")
        payload: dict[str, object] = {name: options.get(name) for name in _TEXT_FIELDS}
        payload.update(
            {
                "schema_version": SINGLE_OWNER_POLICY_PUBLICATION_SETTINGS_SCHEMA_VERSION,
                "ttl_seconds": options.get("ttl_seconds"),
            }
        )
        try:
            settings = decode_single_owner_policy_publication_settings(payload)
            settings.deadline_at(datetime.now(UTC))
        except (TypeError, ValueError) as error:
            raise CommandError("single-owner policy publication settings are invalid") from error
        try:
            result = activate_runtime_profile_patch(
                environment=environment,
                patch={SINGLE_OWNER_POLICY_PUBLICATION_SETTINGS_KEY: settings.to_payload()},
                bootstrap_values=None,
                actor=actor,
                reason=reason,
            )
        except (DatabaseError, RuntimeError, TypeError, ValueError) as error:
            raise CommandError("policy publication settings activation failed") from error
        self.stdout.write(
            json.dumps(
                {
                    "definition_key": SINGLE_OWNER_POLICY_PUBLICATION_SETTINGS_KEY,
                    "policy_published": False,
                    "authority_granted": False,
                    "activation": result,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
