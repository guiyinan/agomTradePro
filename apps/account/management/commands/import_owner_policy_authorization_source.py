"""Import exact declaration bytes without publishing authority."""

import base64
import json
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import DatabaseError

from apps.account.application.owner_policy_authorization_source import (
    OWNER_POLICY_AUTHORIZATION_SOURCE_KEY,
    OWNER_POLICY_AUTHORIZATION_SOURCE_MAX_DOCUMENT_BYTES,
    OWNER_POLICY_AUTHORIZATION_SOURCE_SCHEMA_VERSION,
    decode_owner_policy_authorization_source,
)
from core.integration.config_center_runtime import activate_runtime_profile_patch


def _text(value: object, name: str) -> str:
    """Validate explicit operator metadata; actor is an audit label only."""
    if type(value) is not str or not value or value.strip() != value:
        raise CommandError(f"--{name} must be an explicit non-empty string")
    if name not in {"reason", "file"} and any(char.isspace() for char in value):
        raise CommandError(f"--{name} must be a canonical token")
    return value


class Command(BaseCommand):
    """Store a verified source package for a later authenticated publisher."""

    help = "Import owner declaration bytes; does not authenticate or grant access."

    def add_arguments(self, parser: CommandParser) -> None:
        """Require the source path, explicit digest and change metadata."""
        for name in (
            "file",
            "expected-sha256",
            "source-id",
            "source-version",
            "environment",
            "actor",
            "reason",
        ):
            parser.add_argument("--" + name, required=True)

    def handle(self, *args: object, **options: Any) -> None:
        """Read bounded bytes, validate their supplied seal and activate only source."""
        del args
        path = _text(options.get("file"), "file")
        environment = _text(options.get("environment"), "environment")
        actor = _text(options.get("actor"), "actor")
        reason = _text(options.get("reason"), "reason")
        try:
            with open(path, "rb") as document:
                raw = document.read(OWNER_POLICY_AUTHORIZATION_SOURCE_MAX_DOCUMENT_BYTES + 1)
            source = decode_owner_policy_authorization_source(
                {
                    "schema_version": OWNER_POLICY_AUTHORIZATION_SOURCE_SCHEMA_VERSION,
                    "source_id": options.get("source_id"),
                    "source_version": options.get("source_version"),
                    "content_hash": options.get("expected_sha256"),
                    "document_base64": base64.b64encode(raw).decode("ascii"),
                }
            )
        except (OSError, TypeError, ValueError) as error:
            raise CommandError("owner declaration source import validation failed") from error
        try:
            result = activate_runtime_profile_patch(
                environment=environment,
                patch={OWNER_POLICY_AUTHORIZATION_SOURCE_KEY: source.to_payload()},
                bootstrap_values=None,
                actor=actor,
                reason=reason,
            )
        except (DatabaseError, RuntimeError, TypeError, ValueError) as error:
            raise CommandError("owner declaration source activation failed") from error
        self.stdout.write(
            json.dumps(
                {
                    "definition_key": OWNER_POLICY_AUTHORIZATION_SOURCE_KEY,
                    "policy_published": False,
                    "authority_granted": False,
                    "activation": result,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
