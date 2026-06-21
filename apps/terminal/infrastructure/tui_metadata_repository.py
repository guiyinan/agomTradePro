"""Published TUI metadata repository implementations."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from django.conf import settings
from django.db import OperationalError, ProgrammingError
from django.utils import timezone

from apps.terminal.application.tui_metadata import (
    compact_tui_metadata_payload,
    validate_tui_metadata,
)

from .models import TuiMetadataRegistryORM


class PublishedTuiMetadataRepository:
    """Load and publish reviewed TUI operation metadata."""

    def __init__(self, *, published_path: Path | None = None) -> None:
        self.published_path = published_path or (
            Path(settings.BASE_DIR) / "config" / "tui" / "published" / "tui_operation_graph.published.json"
        )

    def load_published(self, registry_key: str = "default") -> dict[str, Any]:
        """Return the active published TUI metadata payload.

        Database records override the repo JSON fallback so production can
        promote reviewed metadata without changing deployed source files.
        """

        try:
            model = (
                TuiMetadataRegistryORM._default_manager.filter(
                    registry_key=registry_key,
                    status="published",
                )
                .order_by("-published_at", "-updated_at")
                .first()
            )
        except (OperationalError, ProgrammingError):
            model = None
        if model is not None:
            return validate_tui_metadata(dict(model.payload or {}))

        return self._load_published_file()

    def publish_payload(
        self,
        *,
        payload: dict[str, Any],
        registry_key: str = "default",
        approved_by: Any | None = None,
        review_note: str = "",
        generation_source: str = "mixed",
        backend_version: str = "",
        source_evidence_hash: str = "",
        changed_fields: list[str] | None = None,
        rollback_of: TuiMetadataRegistryORM | None = None,
    ) -> TuiMetadataRegistryORM:
        """Validate and publish one metadata payload to the database."""

        validated = validate_tui_metadata(dict(payload))
        validated["status"] = "published"
        compacted = compact_tui_metadata_payload(validated)
        source_hash = self.payload_hash(compacted)
        now = timezone.now()
        previous_model = (
            TuiMetadataRegistryORM._default_manager.filter(
                registry_key=registry_key,
                status="published",
            )
            .order_by("-published_at", "-updated_at")
            .first()
        )
        previous_payload = dict(previous_model.payload or {}) if previous_model is not None else {}
        resolved_changed_fields = changed_fields
        if resolved_changed_fields is None:
            resolved_changed_fields = self.changed_fields(previous_payload, compacted)
        TuiMetadataRegistryORM._default_manager.filter(
            registry_key=registry_key,
            status="published",
        ).update(status="archived", updated_at=now)
        return TuiMetadataRegistryORM._default_manager.create(
            registry_key=registry_key,
            version=str(validated.get("version", "tui-workbench.v2")),
            schema_version=str(validated.get("schema_version", "tui-metadata.v3")),
            status="published",
            review_status="approved",
            generation_source=generation_source,
            backend_version=backend_version,
            payload=compacted,
            source_hash=source_hash,
            source_evidence_hash=source_evidence_hash,
            changed_fields=resolved_changed_fields,
            review_note=review_note,
            approved_by=approved_by if getattr(approved_by, "is_authenticated", False) else None,
            rollback_of=rollback_of,
            published_at=now,
        )

    def _load_published_file(self) -> dict[str, Any]:
        if not self.published_path.exists():
            raise FileNotFoundError(f"Published TUI metadata not found: {self.published_path}")
        payload = json.loads(self.published_path.read_text(encoding="utf-8"))
        return validate_tui_metadata(payload)

    @staticmethod
    def payload_hash(payload: dict[str, Any]) -> str:
        """Return a deterministic hash for audit/diff checks."""

        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def changed_fields(previous: dict[str, Any], current: dict[str, Any]) -> list[str]:
        """Return top-level and action-level metadata changes for audit review."""

        if not previous:
            return ["initial_publish"]
        changes: list[str] = []
        for key in sorted(set(previous) | set(current)):
            if key == "actions":
                continue
            if previous.get(key) != current.get(key):
                changes.append(key)

        previous_actions = {
            str(action.get("key")): action
            for action in previous.get("actions", [])
            if isinstance(action, dict)
        }
        current_actions = {
            str(action.get("key")): action
            for action in current.get("actions", [])
            if isinstance(action, dict)
        }
        for key in sorted(set(previous_actions) - set(current_actions)):
            changes.append(f"actions.removed.{key}")
        for key in sorted(set(current_actions) - set(previous_actions)):
            changes.append(f"actions.added.{key}")
        for key in sorted(set(previous_actions) & set(current_actions)):
            if previous_actions[key] != current_actions[key]:
                changes.append(f"actions.changed.{key}")
        return changes


def get_tui_metadata_repository() -> PublishedTuiMetadataRepository:
    """Return the default published TUI metadata repository."""

    return PublishedTuiMetadataRepository()
