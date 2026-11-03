"""Preview or create one immutable inactive Config Center profile draft."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.config_center.application.runtime_config_drafts import (
    RuntimeConfigDraftRequest,
    RuntimeConfigDraftValueInput,
)
from apps.config_center.application.runtime_public import (
    create_runtime_profile_draft,
    preview_runtime_profile_draft,
)


class Command(BaseCommand):
    """Create-only DRAFT persistence; publication always uses another workflow."""

    help = (
        "Preview a Config Center draft by default. --execute atomically stores a DRAFT profile, "
        "its typed values and revision without creating a runtime snapshot or activating it."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        """Register the explicit input, audit actor and opt-in write flag."""

        parser.add_argument("--draft-file", required=True)
        parser.add_argument("--actor", required=True)
        parser.add_argument("--reason", required=True)
        parser.add_argument("--release-ref", default="")
        parser.add_argument("--execute", action="store_true")

    def handle(self, *args: object, **options: Any) -> None:
        """Run a no-write preview or the requested atomic DRAFT insertion."""

        del args
        try:
            request = _read_request(
                str(options["draft_file"]),
                actor=str(options["actor"]),
                reason=str(options["reason"]),
                release_ref=str(options.get("release_ref") or ""),
            )
            execute = bool(options.get("execute", False))
            if execute:
                result = create_runtime_profile_draft(request)
                profile = result.profile
                values = result.values
                revision = result.revision
            else:
                result = None
                plan = preview_runtime_profile_draft(request)
                profile = plan.profile
                values = plan.values
                revision = plan.revision
        except CommandError:
            raise
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as exc:
            raise CommandError(str(exc)) from exc

        output: dict[str, object] = {
            "mode": "execute" if execute else "dry_run",
            "profile_id": profile.profile_id,
            "profile_key": profile.profile_key,
            "environment": profile.environment,
            "version": profile.version,
            "status": profile.status.value,
            "content_hash": profile.content_hash,
            "value_count": len(values),
            "revision_id": revision.revision_id,
            "created": result.created if result is not None else None,
            "draft_only": True,
            "generic_definition_validation": "passed",
            "consumer_schema_validation": "not_performed",
            "snapshot_created": False,
            "active_pointer_changed": False,
        }
        self.stdout.write(
            json.dumps(output, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )


def _read_request(
    filename: str,
    *,
    actor: str,
    reason: str,
    release_ref: str,
) -> RuntimeConfigDraftRequest:
    """Parse one strict generic Config Center draft envelope."""

    raw: Any = json.loads(
        Path(filename).read_text(encoding="utf-8"),
        parse_constant=_reject_nonstandard_json_number,
    )
    if not isinstance(raw, dict):
        raise CommandError("Draft file must contain a JSON object")
    _require_exact_keys(raw, {"profile_key", "environment", "version", "values"}, "draft")
    profile_key = _required_string(raw["profile_key"], "profile_key")
    environment = _required_string(raw["environment"], "environment")
    version = raw["version"]
    if type(version) is not int or version < 1:
        raise CommandError("version must be a positive exact integer")
    raw_values = raw["values"]
    if not isinstance(raw_values, list) or not raw_values:
        raise CommandError("values must be a nonempty JSON array")
    values: list[RuntimeConfigDraftValueInput] = []
    for index, item in enumerate(raw_values):
        if not isinstance(item, dict):
            raise CommandError(f"values[{index}] must be a JSON object")
        _require_exact_keys(
            item,
            {"definition_key", "value_json", "source"},
            f"values[{index}]",
            optional={"secret_ref"},
        )
        if "value_json" not in item:
            raise CommandError(f"values[{index}].value_json is required")
        values.append(
            RuntimeConfigDraftValueInput(
                definition_key=_required_string(item["definition_key"], "definition_key"),
                value_json=item["value_json"],
                source=_required_string(item["source"], "source"),
                secret_ref=_optional_string(item.get("secret_ref", ""), "secret_ref"),
            )
        )
    return RuntimeConfigDraftRequest(
        profile_key=profile_key,
        environment=environment,
        version=version,
        actor=actor,
        reason=reason,
        values=tuple(values),
        release_ref=release_ref,
    )


def _require_exact_keys(
    value: dict[object, object],
    required: set[str],
    name: str,
    *,
    optional: set[str] | None = None,
) -> None:
    """Reject unknown or missing envelope fields rather than silently dropping them."""

    optional_keys = optional or set()
    keys = {str(key) for key in value}
    if keys != set(value):
        raise CommandError(f"{name} field names must be strings")
    missing = required.difference(keys)
    unknown = keys.difference(required | optional_keys)
    if missing or unknown:
        details = []
        if missing:
            details.append("missing=" + ",".join(sorted(missing)))
        if unknown:
            details.append("unknown=" + ",".join(sorted(unknown)))
        raise CommandError(f"{name} fields invalid: " + "; ".join(details))


def _required_string(value: object, name: str) -> str:
    """Require a non-empty JSON string without trimming or coercing it."""

    if type(value) is not str or not value or value.strip() != value:
        raise CommandError(f"{name} must be non-empty, trimmed text")
    return value


def _optional_string(value: object, name: str) -> str:
    """Narrow an optional JSON string field."""

    if type(value) is not str or value.strip() != value:
        raise CommandError(f"{name} must be trimmed text")
    return value


def _reject_nonstandard_json_number(value: str) -> None:
    """Reject NaN and Infinity, which are not standard JSON numeric values."""

    raise CommandError(f"non-standard JSON number is unsupported: {value}")
