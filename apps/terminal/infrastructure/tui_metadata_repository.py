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
from .tui_metadata_runtime_constants import (
    RUNTIME_ACTION_PATCHES,
    RUNTIME_REDUNDANT_SCREEN_ACTION_KEYS,
    RUNTIME_SCREEN_PATCHES,
)
from .tui_metadata_runtime_injection_registry import (
    RUNTIME_METADATA_INJECTIONS,
    RuntimeMetadataInjectionBundle,
)


class PublishedTuiMetadataRepository:
    """Load and publish reviewed TUI operation metadata."""

    def __init__(self, *, published_path: Path | None = None) -> None:
        self.published_path = published_path or (
            Path(settings.BASE_DIR)
            / "config"
            / "tui"
            / "published"
            / "tui_operation_graph.published.json"
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
            return self._normalize_runtime_payload(validate_tui_metadata(dict(model.payload or {})))

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
        compacted = compact_tui_metadata_payload(self._normalize_runtime_payload(validated))
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
        if previous_model is not None and self._is_same_published_payload(
            previous_model=previous_model,
            compacted_payload=compacted,
            source_hash=source_hash,
        ):
            previous_model._publish_was_noop = True
            return previous_model
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

    @staticmethod
    def _is_same_published_payload(
        *,
        previous_model: TuiMetadataRegistryORM,
        compacted_payload: dict[str, Any],
        source_hash: str,
    ) -> bool:
        """Return True when the latest published payload already matches the requested publish."""

        previous_payload = dict(previous_model.payload or {})
        previous_source_hash = str(previous_model.source_hash or "").strip()
        return previous_payload == compacted_payload or (
            bool(previous_source_hash) and previous_source_hash == source_hash
        )

    def _load_published_file(self) -> dict[str, Any]:
        if not self.published_path.exists():
            raise FileNotFoundError(f"Published TUI metadata not found: {self.published_path}")
        payload = json.loads(self.published_path.read_text(encoding="utf-8"))
        return self._normalize_runtime_payload(validate_tui_metadata(payload))

    def _normalize_runtime_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Prune duplicated actions that are not operator-usable in runtime screens."""

        redundant_map = RUNTIME_REDUNDANT_SCREEN_ACTION_KEYS
        patches = RUNTIME_ACTION_PATCHES
        screen_patches = RUNTIME_SCREEN_PATCHES

        normalized = dict(payload)
        groups = list(payload.get("groups") or [])
        modules = list(payload.get("modules") or [])
        screens = list(payload.get("screens") or [])
        actions = list(normalized.get("actions") or [])
        injected_counts = self._apply_runtime_injections(
            groups=groups,
            modules=modules,
            screens=screens,
            actions=actions,
        )
        injected = sum(injected_counts.values())
        normalized["groups"] = groups
        normalized["modules"] = modules
        normalized["screens"] = screens
        normalized["actions"] = actions
        patched_screens = self._apply_screen_patches(
            screens,
            screen_patches,
            action_keys={str(action.get("key") or "") for action in actions},
            screen_keys={str(screen.get("key") or "") for screen in screens},
        )
        if patched_screens:
            normalized["screens"] = screens

        if not redundant_map and not patches and patched_screens == 0 and injected == 0:
            return payload

        actions = list(normalized.get("actions") or [])
        kept: list[dict[str, Any]] = []
        removed = 0
        patched = 0
        for action in actions:
            screen_key = str(action.get("screen_key") or "")
            action_key = str(action.get("key") or "")
            if action_key in redundant_map.get(screen_key, set()):
                removed += 1
                continue
            patch = patches.get(action_key)
            if patch:
                updated, changed = self._apply_runtime_patch(action, patch)
                kept.append(updated)
                if changed:
                    patched += 1
                continue
            kept.append(action)
        if removed == 0 and patched == 0:
            if injected == 0:
                if patched_screens:
                    coverage = dict(normalized.get("coverage_summary") or {})
                    coverage["runtime_patched_screens"] = patched_screens + int(
                        coverage.get("runtime_patched_screens", 0) or 0
                    )
                    normalized["coverage_summary"] = coverage
                    return validate_tui_metadata(normalized)
                return payload
            coverage = self._merge_runtime_coverage(
                normalized.get("coverage_summary"),
                injected_counts=injected_counts,
            )
            if patched_screens:
                coverage["runtime_patched_screens"] = patched_screens + int(
                    coverage.get("runtime_patched_screens", 0) or 0
                )
            normalized["coverage_summary"] = coverage
            return validate_tui_metadata(normalized)

        normalized["actions"] = kept
        coverage = dict(normalized.get("coverage_summary") or {})
        coverage["runtime_pruned_redundant_screen_actions"] = removed + int(
            coverage.get("runtime_pruned_redundant_screen_actions", 0) or 0
        )
        coverage["runtime_patched_actions"] = patched + int(
            coverage.get("runtime_patched_actions", 0) or 0
        )
        if patched_screens:
            coverage["runtime_patched_screens"] = patched_screens + int(
                coverage.get("runtime_patched_screens", 0) or 0
            )
        coverage = self._merge_runtime_coverage(
            coverage,
            injected_counts=injected_counts,
        )
        normalized["coverage_summary"] = coverage
        return validate_tui_metadata(normalized)

    @staticmethod
    def _merge_runtime_coverage(
        coverage_summary: Any,
        *,
        injected_counts: dict[str, int],
    ) -> dict[str, Any]:
        """Merge runtime injection counters into coverage_summary."""

        coverage = dict(coverage_summary or {})
        for coverage_key, injected_count in injected_counts.items():
            if injected_count <= 0:
                continue
            coverage[coverage_key] = injected_count + int(coverage.get(coverage_key, 0) or 0)
        return coverage

    @staticmethod
    def _apply_screen_patches(
        screens: list[dict[str, Any]],
        patches: dict[str, dict[str, Any]],
        *,
        action_keys: set[str],
        screen_keys: set[str],
    ) -> int:
        """Apply runtime screen patches and return the changed screen count."""

        changed = 0
        for index, screen in enumerate(screens):
            patch = patches.get(str(screen.get("key") or ""))
            if not patch:
                continue
            resolved_patch = PublishedTuiMetadataRepository._resolve_screen_patch(
                patch,
                action_keys=action_keys,
                screen_keys=screen_keys,
            )
            updated = dict(screen)
            for key, value in resolved_patch.items():
                updated[key] = value
            if updated != screen:
                screens[index] = updated
                changed += 1
        return changed

    @staticmethod
    def _resolve_screen_patch(
        patch: dict[str, Any],
        *,
        action_keys: set[str],
        screen_keys: set[str],
    ) -> dict[str, Any]:
        resolved = dict(patch)
        panels = patch.get("dashboard_panels")
        if not isinstance(panels, list):
            return resolved
        resolved["dashboard_panels"] = [
            panel
            for panel in panels
            if not isinstance(panel, dict)
            or str(panel.get("action_key") or "").strip() == ""
            or str(panel.get("action_key") or "").strip() in action_keys
            if str(panel.get("target_screen") or "").strip() == ""
            or str(panel.get("target_screen") or "").strip() in screen_keys
        ]
        return resolved

    @staticmethod
    def _apply_runtime_injections(
        *,
        groups: list[dict[str, Any]],
        modules: list[dict[str, Any]],
        screens: list[dict[str, Any]],
        actions: list[dict[str, Any]],
    ) -> dict[str, int]:
        """Inject all runtime bundles and return per-bundle injected counts."""

        return {
            bundle.coverage_key: PublishedTuiMetadataRepository._inject_runtime_bundle(
                bundle=bundle,
                groups=groups,
                modules=modules,
                screens=screens,
                actions=actions,
            )
            for bundle in RUNTIME_METADATA_INJECTIONS
        }

    @staticmethod
    def _inject_runtime_bundle(
        *,
        bundle: RuntimeMetadataInjectionBundle,
        groups: list[dict[str, Any]],
        modules: list[dict[str, Any]],
        screens: list[dict[str, Any]],
        actions: list[dict[str, Any]],
    ) -> int:
        """Inject one runtime metadata bundle and report the added item count."""

        injected = 0
        injected += PublishedTuiMetadataRepository._append_unique_payloads(
            payloads=groups,
            additions=bundle.groups,
        )
        injected += PublishedTuiMetadataRepository._append_unique_payloads(
            payloads=modules,
            additions=bundle.modules,
        )
        injected += PublishedTuiMetadataRepository._append_unique_payloads(
            payloads=screens,
            additions=bundle.screens,
        )

        screen_keys = {str(screen.get("key") or "") for screen in screens}
        action_keys = {str(action.get("key") or "") for action in actions}
        for action in bundle.actions:
            action_key = str(action.get("key") or "")
            screen_key = str(action.get("screen_key") or "")
            if action_key in action_keys:
                continue
            if screen_key and screen_key not in screen_keys:
                continue
            actions.append(dict(action))
            action_keys.add(action_key)
            injected += 1
        return injected

    @staticmethod
    def _append_unique_payloads(
        *,
        payloads: list[dict[str, Any]],
        additions: tuple[dict[str, Any], ...],
    ) -> int:
        """Append payloads by unique key and return the number of inserted items."""

        existing_keys = {str(payload.get("key") or "") for payload in payloads}
        inserted = 0
        for addition in additions:
            addition_key = str(addition.get("key") or "")
            if addition_key in existing_keys:
                continue
            payloads.append(dict(addition))
            existing_keys.add(addition_key)
            inserted += 1
        return inserted

    @staticmethod
    def _apply_runtime_patch(
        action: dict[str, Any],
        patch: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        """Apply one runtime patch and report whether it changed the action."""

        updated = dict(action)
        changed = False
        for key, value in patch.items():
            if key == "view_model":
                current_view_model = dict(action.get("view_model") or {})
                merged_view_model = {
                    **current_view_model,
                    **dict(value or {}),
                }
                if merged_view_model != current_view_model:
                    changed = True
                updated["view_model"] = merged_view_model
                continue
            if updated.get(key) != value:
                changed = True
            updated[key] = value
        return updated, changed

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
