"""Preview or atomically publish one Config Center corrective successor."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TypedDict

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.config_center.application.runtime_public import (
    activate_runtime_profile_patch_payload,
    preview_runtime_profile_patch,
)


class _PatchArguments(TypedDict):
    """Typed application arguments narrowed from management-command options."""

    environment: str
    patch: dict[str, object]
    secret_ref_patch: dict[str, str]
    bootstrap_values: dict[str, object]
    bootstrap_secret_refs: dict[str, str]
    actor: str
    reason: str
    expected_active_profile_id: str | None
    expected_active_profile_version: int | None
    expected_active_profile_hash: str | None
    expected_active_snapshot_hash: str | None


class Command(BaseCommand):
    """Expose the fail-closed corrective profile workflow."""

    help = (
        "Preview a corrective successor from a JSON patch; use --execute only "
        "with the approved active profile and public snapshot hashes."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        """Register dry-run-first corrective activation arguments."""

        parser.add_argument("--environment", required=True)
        parser.add_argument("--patch-file", required=True)
        parser.add_argument("--actor", required=True)
        parser.add_argument("--reason", required=True)
        parser.add_argument("--release-ref", default="")
        parser.add_argument("--execute", action="store_true")
        parser.add_argument("--expected-profile-id", default="")
        parser.add_argument("--expected-profile-version", type=int)
        parser.add_argument("--expected-profile-hash", default="")
        parser.add_argument("--expected-snapshot-hash", default="")

    def handle(self, *args: object, **options: Any) -> None:
        """Run a read-only preview or a hash-bound successor activation."""

        del args
        execute = bool(options.get("execute", False))
        expected_profile_id = str(options.get("expected_profile_id") or "").strip() or None
        raw_profile_version = options.get("expected_profile_version")
        expected_profile_version = (
            raw_profile_version if isinstance(raw_profile_version, int) else None
        )
        expected_profile_hash = str(options.get("expected_profile_hash") or "").strip() or None
        expected_snapshot_hash = str(options.get("expected_snapshot_hash") or "").strip() or None
        if execute:
            missing = [
                name
                for name, value in (
                    ("--expected-profile-id", expected_profile_id),
                    ("--expected-profile-version", expected_profile_version),
                    ("--expected-profile-hash", expected_profile_hash),
                    ("--expected-snapshot-hash", expected_snapshot_hash),
                )
                if value is None
            ]
            if missing:
                raise CommandError(
                    "Corrective execution requires approved predecessor bindings: "
                    + ", ".join(missing)
                )

        patch, secret_ref_patch, bootstrap_values, bootstrap_secret_refs = _read_patch_file(
            str(options["patch_file"])
        )
        common: _PatchArguments = {
            "environment": str(options["environment"]),
            "patch": patch,
            "secret_ref_patch": secret_ref_patch,
            "bootstrap_values": bootstrap_values,
            "bootstrap_secret_refs": bootstrap_secret_refs,
            "actor": str(options["actor"]),
            "reason": str(options["reason"]),
            "expected_active_profile_id": expected_profile_id,
            "expected_active_profile_version": expected_profile_version,
            "expected_active_profile_hash": expected_profile_hash,
            "expected_active_snapshot_hash": expected_snapshot_hash,
        }
        try:
            if execute:
                payload = {
                    "mode": "execute",
                    **activate_runtime_profile_patch_payload(
                        **common,
                        release_ref=str(options.get("release_ref") or ""),
                    ),
                }
            else:
                payload = {
                    "mode": "dry_run",
                    "preview": preview_runtime_profile_patch(**common),
                }
        except (RuntimeError, TypeError, ValueError, OSError, json.JSONDecodeError) as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
        )


def _read_patch_file(
    filename: str,
) -> tuple[
    dict[str, object],
    dict[str, str],
    dict[str, object],
    dict[str, str],
]:
    """Read a typed patch envelope without echoing values or secret references."""

    raw: Any = json.loads(Path(filename).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise CommandError("Patch file must contain a JSON object")
    patch_raw: Any = raw.get("patch", raw)
    patch = _object_mapping(patch_raw, "patch")
    secret_ref_patch = _string_mapping(raw.get("secret_ref_patch", {}), "secret_ref_patch")
    bootstrap_values = _object_mapping(raw.get("bootstrap_values", {}), "bootstrap_values")
    bootstrap_secret_refs = _string_mapping(
        raw.get("bootstrap_secret_refs", {}),
        "bootstrap_secret_refs",
    )
    return patch, secret_ref_patch, bootstrap_values, bootstrap_secret_refs


def _object_mapping(value: Any, name: str) -> dict[str, object]:
    """Narrow one JSON object to a typed value mapping."""

    if not isinstance(value, dict):
        raise CommandError(f"{name} must be a JSON object")
    return {str(key): item for key, item in value.items()}


def _string_mapping(value: Any, name: str) -> dict[str, str]:
    """Narrow one JSON object to a string reference mapping."""

    if not isinstance(value, dict):
        raise CommandError(f"{name} must be a JSON object")
    result: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(item, str) or not item.strip():
            raise CommandError(f"{name} values must be non-empty strings")
        result[str(key)] = item
    return result
