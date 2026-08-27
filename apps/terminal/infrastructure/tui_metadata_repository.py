"""Published TUI metadata repository implementations."""

from __future__ import annotations

import copy
import hashlib
import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol, cast

from django.conf import settings
from django.core.cache import cache
from django.db import OperationalError, ProgrammingError
from django.utils import timezone

from apps.terminal.application.tui_metadata import (
    TuiMetadataValidationError,
    compact_tui_metadata_payload,
    validate_tui_metadata,
)

from .models import TuiMetadataRegistryORM
from .tui_information_architecture import (
    TUI_IA_PATH,
    load_tui_information_architecture,
    public_screen_spec,
    screen_aliases,
    screen_specs,
)
from .tui_metadata_runtime_constants import (
    RUNTIME_ACTION_PATCHES,
    RUNTIME_REDUNDANT_SCREEN_ACTION_KEYS,
    RUNTIME_SCREEN_PATCHES,
)
from .tui_metadata_runtime_injection_registry import (
    RUNTIME_METADATA_INJECTIONS,
    RuntimeMetadataInjectionBundle,
)


class _PublishNoopMarker(Protocol):
    """Runtime-only marker exposed to the publication command."""

    _publish_was_noop: bool


logger = logging.getLogger(__name__)


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
            raw_payload = dict(model.payload or {})
            source_hash = str(model.source_hash or "") or self.payload_hash(raw_payload)
            source_token = self._database_source_token(model, source_hash=source_hash)
            cached = self._load_runtime_cache(
                registry_key,
                source_kind="database",
                source_token=source_token,
            )
            if cached is not None:
                return cached
            try:
                normalized = self.validate_and_normalize_runtime_payload(raw_payload)
            except (TuiMetadataValidationError, TypeError, ValueError) as exc:
                return self._load_file_fallback(
                    registry_key=registry_key,
                    registry_id=model.pk,
                    error=exc,
                )
            self._store_runtime_cache(
                registry_key=registry_key,
                source_hash=source_hash,
                source_kind="database",
                source_token=source_token,
                payload=normalized,
            )
            return normalized

        source_token = self._file_source_token()
        cached = self._load_runtime_cache(
            registry_key,
            source_kind="file",
            source_token=source_token,
        )
        if cached is not None:
            return cached
        normalized = self._load_published_file()
        self._store_runtime_cache(
            registry_key=registry_key,
            source_hash=self.payload_hash(normalized),
            source_kind="file",
            source_token=source_token,
            payload=normalized,
        )
        return normalized

    def _load_file_fallback(
        self,
        *,
        registry_key: str,
        registry_id: Any,
        error: Exception,
    ) -> dict[str, Any]:
        """Load the reviewed file payload when a DB publication is invalid.

        The invalid database record is never repaired or silently accepted. The
        repository keeps the file payload as the only safe runtime source and
        exposes a bounded health marker for the TUI to surface as a governance
        warning.
        """

        logger.warning(
            "TUI metadata database payload rejected; using file fallback",
            extra={
                "event": "tui_metadata_fallback",
                "registry_key": registry_key,
                "registry_id": registry_id,
                "reason_code": "database_payload_invalid",
                "exception_type": type(error).__name__,
            },
        )
        normalized = self._load_published_file()
        normalized["metadata_health"] = {
            "status": "degraded",
            "source": "file",
            "reason_code": "database_payload_invalid",
            "message": "数据库中的 TUI 配置无法通过校验，当前使用文件版配置；请完成发布记录重校验。",
        }
        return normalized

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

        compacted, source_hash = self.prepare_payload_for_publish(payload)
        validated = validate_tui_metadata(dict(payload))
        validated["status"] = "published"
        now = timezone.now()
        previous_model = self.get_active_registry(registry_key)
        if previous_model is not None and self._is_same_published_payload(
            previous_model=previous_model,
            compacted_payload=compacted,
            source_hash=source_hash,
        ):
            cast(_PublishNoopMarker, previous_model)._publish_was_noop = True
            self._store_runtime_cache(
                registry_key=registry_key,
                source_hash=source_hash,
                source_kind="database",
                source_token=self._database_source_token(
                    previous_model,
                    source_hash=source_hash,
                ),
                payload=self._normalize_runtime_payload(
                    validate_tui_metadata(dict(previous_model.payload or {}))
                ),
            )
            return previous_model
        previous_payload = dict(previous_model.payload or {}) if previous_model is not None else {}
        resolved_changed_fields = changed_fields
        if resolved_changed_fields is None:
            resolved_changed_fields = self.changed_fields(previous_payload, compacted)
        TuiMetadataRegistryORM._default_manager.filter(
            registry_key=registry_key,
            status="published",
        ).update(status="archived", updated_at=now)
        created = TuiMetadataRegistryORM._default_manager.create(
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
            approved_by=(approved_by if getattr(approved_by, "is_authenticated", False) else None),
            rollback_of=rollback_of,
            published_at=now,
        )
        runtime_payload = self._normalize_runtime_payload(
            validate_tui_metadata(dict(created.payload or {}))
        )
        self._store_runtime_cache(
            registry_key=registry_key,
            source_hash=source_hash,
            source_kind="database",
            source_token=self._database_source_token(created, source_hash=source_hash),
            payload=runtime_payload,
        )
        return created

    def prepare_payload_for_publish(
        self,
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], str]:
        """Return the canonical published payload and its deterministic hash."""

        validated = validate_tui_metadata(dict(payload))
        validated["status"] = "published"
        compacted = compact_tui_metadata_payload(self._normalize_runtime_payload(validated))
        return compacted, self.payload_hash(compacted)

    @staticmethod
    def get_active_registry(registry_key: str = "default") -> TuiMetadataRegistryORM | None:
        """Return the active database registry row for one TUI channel."""

        try:
            return (
                TuiMetadataRegistryORM._default_manager.filter(
                    registry_key=registry_key,
                    status="published",
                )
                .order_by("-published_at", "-updated_at")
                .first()
            )
        except (OperationalError, ProgrammingError):
            return None

    def verify_active_payload(
        self,
        *,
        payload: dict[str, Any],
        registry_key: str = "default",
    ) -> tuple[bool, TuiMetadataRegistryORM | None, str]:
        """Verify that the active DB registry matches a reviewed release payload."""

        compacted, expected_hash = self.prepare_payload_for_publish(payload)
        model = self.get_active_registry(registry_key)
        if model is None:
            return False, None, expected_hash
        matches = self._is_same_published_payload(
            previous_model=model,
            compacted_payload=compacted,
            source_hash=expected_hash,
        )
        return matches, model, expected_hash

    @staticmethod
    def invalidate_runtime_cache(registry_key: str = "default") -> None:
        """Invalidate the active runtime snapshot pointer for one registry."""

        published_path = (
            Path(settings.BASE_DIR)
            / "config"
            / "tui"
            / "published"
            / "tui_operation_graph.published.json"
        )
        cache.delete(
            PublishedTuiMetadataRepository._runtime_pointer_key(
                registry_key,
                published_path=published_path,
            )
        )

    @staticmethod
    def _runtime_source_scope(published_path: Path) -> str:
        resolved = str(published_path.resolve()).lower()
        return hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:12]

    @staticmethod
    def _runtime_pointer_key(registry_key: str, *, published_path: Path) -> str:
        scope = PublishedTuiMetadataRepository._runtime_source_scope(published_path)
        return f"terminal:tui:metadata-runtime:v4:{scope}:{registry_key}:active"

    @staticmethod
    def _runtime_payload_key(
        registry_key: str,
        source_hash: str,
        *,
        published_path: Path,
    ) -> str:
        scope = PublishedTuiMetadataRepository._runtime_source_scope(published_path)
        return f"terminal:tui:metadata-runtime:v4:{scope}:{registry_key}:{source_hash}"

    def _load_runtime_cache(
        self,
        registry_key: str,
        *,
        source_kind: str,
        source_token: str,
    ) -> dict[str, Any] | None:
        if not bool(getattr(settings, "TUI_RUNTIME_CACHE_ENABLED", True)):
            return None
        pointer = cache.get(
            self._runtime_pointer_key(registry_key, published_path=self.published_path)
        )
        if not isinstance(pointer, dict):
            return None
        if pointer.get("source_kind") != source_kind or pointer.get("source_token") != source_token:
            return None
        source_hash = str(pointer.get("source_hash") or "")
        if not source_hash:
            return None
        payload = cache.get(
            self._runtime_payload_key(
                registry_key,
                source_hash,
                published_path=self.published_path,
            )
        )
        return payload if isinstance(payload, dict) else None

    def _store_runtime_cache(
        self,
        *,
        registry_key: str,
        source_hash: str,
        source_kind: str,
        source_token: str,
        payload: dict[str, Any],
    ) -> None:
        if not bool(getattr(settings, "TUI_RUNTIME_CACHE_ENABLED", True)):
            return
        timeout = int(getattr(settings, "TUI_RUNTIME_CACHE_TTL_SECONDS", 300))
        cache.set(
            self._runtime_payload_key(
                registry_key,
                source_hash,
                published_path=self.published_path,
            ),
            payload,
            timeout,
        )
        cache.set(
            self._runtime_pointer_key(registry_key, published_path=self.published_path),
            {
                "source_hash": source_hash,
                "source_kind": source_kind,
                "source_token": source_token,
            },
            timeout,
        )

    @staticmethod
    def _database_source_token(
        model: TuiMetadataRegistryORM,
        *,
        source_hash: str,
    ) -> str:
        updated_at = getattr(model, "updated_at", None)
        updated_text = updated_at.isoformat() if updated_at is not None else ""
        contract_token = PublishedTuiMetadataRepository._runtime_contract_token()
        return f"{model.pk}:{updated_text}:{source_hash}:{contract_token}"

    def _file_source_token(self) -> str:
        try:
            stat = self.published_path.stat()
        except FileNotFoundError:
            return "missing"
        return f"{stat.st_mtime_ns}:{stat.st_size}:" f"{self._runtime_contract_token()}"

    @staticmethod
    @lru_cache(maxsize=1)
    def _runtime_contract_token() -> str:
        """Fingerprint runtime metadata code so deployed caches cannot outlive its contract."""

        infrastructure_dir = Path(__file__).resolve().parent
        application_metadata_path = infrastructure_dir.parent / "application" / "tui_metadata.py"
        contract_paths = [
            TUI_IA_PATH,
            application_metadata_path,
            Path(__file__).resolve(),
            infrastructure_dir / "tui_information_architecture.py",
            *sorted(
                infrastructure_dir.glob("tui_metadata_runtime_*.py"),
                key=str,
            ),
        ]
        digest = hashlib.sha256()
        for path in contract_paths:
            digest.update(str(path.name).encode("utf-8"))
            try:
                digest.update(path.read_bytes())
            except FileNotFoundError:
                digest.update(b"<missing>")
        return digest.hexdigest()[:16]

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
        return self.validate_and_normalize_runtime_payload(payload)

    def validate_and_normalize_runtime_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Validate and normalize one payload without mutating its caller-owned data."""

        return self._normalize_runtime_payload(validate_tui_metadata(copy.deepcopy(payload)))

    def _normalize_runtime_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Prune duplicated actions that are not operator-usable in runtime screens."""

        redundant_map = RUNTIME_REDUNDANT_SCREEN_ACTION_KEYS
        patches = RUNTIME_ACTION_PATCHES
        published_screen_keys = {
            str(screen["key"])
            for screen in load_tui_information_architecture()["published_screens"]
        }
        is_ia_payload = self._is_information_architecture_payload(payload)
        screen_patches = {
            key: patch
            for key, patch in RUNTIME_SCREEN_PATCHES.items()
            if not is_ia_payload or key not in published_screen_keys
        }
        ia_aliases = screen_aliases()
        ia_screen_specs = screen_specs()

        normalized = (
            self._apply_information_architecture(payload) if is_ia_payload else dict(payload)
        )
        ia_owned_action_copy: dict[str, dict[str, Any]] = {}
        if is_ia_payload:
            for source_action in payload.get("actions", []):
                if not isinstance(source_action, dict):
                    continue
                action_key = str(source_action.get("key") or "")
                owned_copy = {
                    key: source_action[key]
                    for key in ("label", "description")
                    if key in source_action
                }
                if action_key and owned_copy:
                    ia_owned_action_copy[action_key] = owned_copy
        groups = list(normalized.get("groups") or [])
        modules = list(normalized.get("modules") or [])
        screens = list(normalized.get("screens") or [])
        actions = list(normalized.get("actions") or [])
        injected_counts = self._apply_runtime_injections(
            groups=groups,
            modules=modules,
            screens=screens,
            actions=actions,
            ia_owned_action_copy=ia_owned_action_copy,
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

        if (
            not redundant_map
            and not patches
            and patched_screens == 0
            and injected == 0
            and not is_ia_payload
        ):
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
                target_screen = ia_aliases.get(str(updated.get("screen_key") or ""), "")
                target_spec = ia_screen_specs.get(target_screen)
                current_screen_keys = {
                    str(screen.get("key") or "")
                    for screen in normalized.get("screens", [])
                    if isinstance(screen, dict)
                }
                if target_spec and target_screen in current_screen_keys:
                    updated["screen_key"] = target_screen
                    updated["module_key"] = target_spec["module_key"]
                kept.append(updated)
                if changed:
                    patched += 1
                continue
            kept.append(action)
        normalized["actions"] = kept
        self._repair_runtime_screen_contracts(
            screens=list(normalized.get("screens") or []),
            actions=kept,
        )
        density_demoted = (
            self._enforce_published_action_density(
                screens=list(normalized.get("screens") or []),
                actions=kept,
                published_screen_keys=published_screen_keys,
            )
            if is_ia_payload
            else 0
        )
        if removed == 0 and patched == 0:
            if injected == 0:
                if patched_screens or density_demoted or is_ia_payload:
                    coverage = dict(normalized.get("coverage_summary") or {})
                    coverage["runtime_patched_screens"] = max(
                        patched_screens,
                        int(coverage.get("runtime_patched_screens", 0) or 0),
                    )
                    if density_demoted or "runtime_density_demoted_actions" in coverage:
                        coverage["runtime_density_demoted_actions"] = max(
                            density_demoted,
                            int(coverage.get("runtime_density_demoted_actions", 0) or 0),
                        )
                    normalized["coverage_summary"] = coverage
                    return validate_tui_metadata(normalized)
                return payload
            coverage = self._merge_runtime_coverage(
                normalized.get("coverage_summary"),
                injected_counts=injected_counts,
            )
            if patched_screens:
                coverage["runtime_patched_screens"] = max(
                    patched_screens,
                    int(coverage.get("runtime_patched_screens", 0) or 0),
                )
            if density_demoted or "runtime_density_demoted_actions" in coverage:
                coverage["runtime_density_demoted_actions"] = max(
                    density_demoted,
                    int(coverage.get("runtime_density_demoted_actions", 0) or 0),
                )
            normalized["coverage_summary"] = coverage
            return validate_tui_metadata(normalized)

        coverage = dict(normalized.get("coverage_summary") or {})
        coverage["runtime_pruned_redundant_screen_actions"] = max(
            removed,
            int(coverage.get("runtime_pruned_redundant_screen_actions", 0) or 0),
        )
        coverage["runtime_patched_actions"] = max(
            patched,
            int(coverage.get("runtime_patched_actions", 0) or 0),
        )
        if patched_screens:
            coverage["runtime_patched_screens"] = max(
                patched_screens,
                int(coverage.get("runtime_patched_screens", 0) or 0),
            )
        coverage = self._merge_runtime_coverage(
            coverage,
            injected_counts=injected_counts,
        )
        if density_demoted or "runtime_density_demoted_actions" in coverage:
            coverage["runtime_density_demoted_actions"] = max(
                density_demoted,
                int(coverage.get("runtime_density_demoted_actions", 0) or 0),
            )
        normalized["coverage_summary"] = coverage
        return validate_tui_metadata(normalized)

    @staticmethod
    def _is_information_architecture_payload(payload: dict[str, Any]) -> bool:
        """Identify full catalog payloads without rewriting small test/custom registries."""

        if str(payload.get("ia_version") or "").strip():
            return True
        published_screen_keys = {
            str(screen["key"])
            for screen in load_tui_information_architecture()["published_screens"]
        }
        known_screens = {
            str(screen.get("key") or "")
            for screen in payload.get("screens", [])
            if isinstance(screen, dict)
        }
        return len(known_screens.intersection(published_screen_keys)) >= 8

    @staticmethod
    def _apply_information_architecture(payload: dict[str, Any]) -> dict[str, Any]:
        """Converge file, database and legacy payloads on the configured IA graph."""

        registry = load_tui_information_architecture()
        aliases = screen_aliases(registry)
        specs = screen_specs(registry)
        published_specs = {str(screen["key"]): screen for screen in registry["published_screens"]}
        existing_screens = {
            str(screen.get("key") or ""): screen
            for screen in payload.get("screens", [])
            if isinstance(screen, dict)
        }
        density = registry.get("action_density") or {}
        density_overrides = density.get("screen_limits") or {}
        workflow = list(registry.get("workflow") or [])
        workflow_by_key = {str(step["screen_key"]): index for index, step in enumerate(workflow)}
        runtime_replacement_action_keys = {
            str(action.get("key") or "")
            for bundle in RUNTIME_METADATA_INJECTIONS
            if bundle.replace_existing
            for action in bundle.actions
        }

        screens: list[dict[str, Any]] = []
        for screen_key, configured in published_specs.items():
            screen = dict(existing_screens.get(screen_key) or {})
            screen.update(copy.deepcopy(public_screen_spec(configured)))
            screen["action_density"] = {
                "primary_operation_limit": int(
                    density_overrides.get(
                        screen_key,
                        density.get("default_primary_operation_limit", 10),
                    )
                ),
                "task_group_limit": int(density.get("task_group_limit", 6)),
            }
            screen.pop("workflow", None)
            workflow_index = workflow_by_key.get(screen_key)
            if workflow_index is not None:
                previous_step = workflow[workflow_index - 1] if workflow_index > 0 else None
                next_step = (
                    workflow[workflow_index + 1] if workflow_index + 1 < len(workflow) else None
                )
                screen["workflow"] = {
                    "name": "每日投研流程",
                    "step": workflow_index + 1,
                    "total": len(workflow),
                    "label": workflow[workflow_index]["label"],
                    "role": workflow[workflow_index]["role"],
                    "previous": (
                        {"key": previous_step["screen_key"], "label": previous_step["label"]}
                        if previous_step
                        else {}
                    ),
                    "next": (
                        {"key": next_step["screen_key"], "label": next_step["label"]}
                        if next_step
                        else {}
                    ),
                }
            screens.append(screen)

        actions: list[dict[str, Any]] = []
        for source_action in payload.get("actions", []):
            if not isinstance(source_action, dict):
                continue
            if str(source_action.get("source") or "").startswith("approved:runtime-"):
                continue
            if str(source_action.get("key") or "") in runtime_replacement_action_keys:
                continue
            target = aliases.get(str(source_action.get("screen_key") or ""), "")
            spec = specs.get(target)
            if not spec:
                continue
            action = dict(source_action)
            action["screen_key"] = target
            action["module_key"] = spec["module_key"]
            actions.append(action)

        normalized = dict(payload)
        normalized["groups"] = copy.deepcopy(registry["groups"])
        normalized["modules"] = copy.deepcopy(registry["modules"])
        normalized["screens"] = screens
        normalized["actions"] = actions
        normalized["default_screen"] = "command-center.overview"
        normalized["ia_version"] = str(registry["version"])
        normalized["legacy_screen_aliases"] = {
            source: target for source, target in aliases.items() if source != target
        }
        return normalized

    @staticmethod
    def _enforce_published_action_density(
        *,
        screens: list[dict[str, Any]],
        actions: list[dict[str, Any]],
        published_screen_keys: set[str],
    ) -> int:
        """Demote non-featured overflow actions within reviewed IA budgets."""

        screens_by_key = {
            str(screen.get("key") or ""): screen
            for screen in screens
            if str(screen.get("key") or "") in published_screen_keys
        }
        actions_by_screen: dict[str, list[dict[str, Any]]] = {}
        for action in actions:
            screen_key = str(action.get("screen_key") or "")
            if screen_key in screens_by_key:
                actions_by_screen.setdefault(screen_key, []).append(action)

        changed = 0
        for screen_key in sorted(screens_by_key):
            screen = screens_by_key[screen_key]
            raw_density = screen.get("action_density")
            if not isinstance(raw_density, dict):
                raise TuiMetadataValidationError(f"Invalid TUI action density budget: {screen_key}")
            try:
                screen_limit = int(raw_density.get("primary_operation_limit") or 0)
                task_group_limit = int(raw_density.get("task_group_limit") or 0)
            except (TypeError, ValueError) as exc:
                raise TuiMetadataValidationError(
                    f"Invalid TUI action density budget: {screen_key}"
                ) from exc
            if screen_limit <= 0 or task_group_limit <= 0:
                raise TuiMetadataValidationError(f"Invalid TUI action density budget: {screen_key}")

            protected_action_keys = {str(screen.get("default_action_key") or "").strip()}
            for panel in screen.get("dashboard_panels") or []:
                if isinstance(panel, dict):
                    protected_action_keys.add(str(panel.get("action_key") or "").strip())
            protected_action_keys.discard("")

            budgeted_actions = [
                action
                for action in actions_by_screen.get(screen_key, [])
                if str(action.get("task_tier") or "primary").strip().lower()
                in {"primary", "operation"}
            ]

            def action_order(action: dict[str, Any]) -> tuple[int, int, str, str]:
                task_tier = str(action.get("task_tier") or "primary").strip().lower()
                try:
                    sequence = int(action.get("sequence", 999))
                except (TypeError, ValueError):
                    sequence = 999
                return (
                    0 if task_tier == "primary" else 1,
                    sequence,
                    str(action.get("task_group") or "未分组").strip() or "未分组",
                    str(action.get("key") or ""),
                )

            selected_action_keys: set[str] = set()
            group_counts: dict[str, int] = {}
            protected_actions = sorted(
                (
                    action
                    for action in budgeted_actions
                    if str(action.get("key") or "") in protected_action_keys
                ),
                key=action_order,
            )
            for action in protected_actions:
                action_key = str(action.get("key") or "")
                task_group = str(action.get("task_group") or "未分组").strip() or "未分组"
                selected_action_keys.add(action_key)
                group_counts[task_group] = group_counts.get(task_group, 0) + 1

            optional_actions = sorted(
                (
                    action
                    for action in budgeted_actions
                    if str(action.get("key") or "") not in protected_action_keys
                ),
                key=action_order,
            )
            for action in optional_actions:
                if len(selected_action_keys) >= screen_limit:
                    break
                action_key = str(action.get("key") or "")
                task_group = str(action.get("task_group") or "未分组").strip() or "未分组"
                if group_counts.get(task_group, 0) >= task_group_limit:
                    continue
                selected_action_keys.add(action_key)
                group_counts[task_group] = group_counts.get(task_group, 0) + 1

            for action in budgeted_actions:
                if str(action.get("key") or "") in selected_action_keys:
                    continue
                replacement_tier = (
                    "support"
                    if str(action.get("effect") or "").strip().lower() == "read"
                    else "advanced"
                )
                if action.get("task_tier") != replacement_tier:
                    action["task_tier"] = replacement_tier
                    changed += 1
        return changed

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
            coverage[coverage_key] = max(
                injected_count,
                int(coverage.get(coverage_key, 0) or 0),
            )
        return coverage

    @staticmethod
    def _repair_runtime_screen_contracts(
        *,
        screens: list[dict[str, Any]],
        actions: list[dict[str, Any]],
    ) -> None:
        """Keep screens valid after runtime pruning/injection mutates the action set."""

        action_keys = {
            str(action.get("key") or "") for action in actions if isinstance(action, dict)
        }
        screen_keys = {
            str(screen.get("key") or "") for screen in screens if isinstance(screen, dict)
        }
        actions_by_screen: dict[str, list[str]] = {}
        for action in actions:
            if not isinstance(action, dict):
                continue
            screen_key = str(action.get("screen_key") or "")
            action_key = str(action.get("key") or "")
            if screen_key and action_key:
                actions_by_screen.setdefault(screen_key, []).append(action_key)
        for screen in screens:
            if not isinstance(screen, dict):
                continue
            panels = screen.get("dashboard_panels")
            if isinstance(panels, list):
                screen["dashboard_panels"] = [
                    panel
                    for panel in panels
                    if not isinstance(panel, dict)
                    or str(panel.get("action_key") or "").strip() == ""
                    or str(panel.get("action_key") or "").strip() in action_keys
                    if str(panel.get("target_screen") or "").strip() == ""
                    or str(panel.get("target_screen") or "").strip() in screen_keys
                ]
            default_action_key = str(screen.get("default_action_key") or "").strip()
            if default_action_key and default_action_key not in action_keys:
                fallback_action_key = next(
                    iter(actions_by_screen.get(str(screen.get("key") or ""), [])),
                    "",
                )
                screen["default_action_key"] = fallback_action_key

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
        resolved_panels = [
            panel
            for panel in panels
            if not isinstance(panel, dict)
            or str(panel.get("action_key") or "").strip() == ""
            or str(panel.get("action_key") or "").strip() in action_keys
            if str(panel.get("target_screen") or "").strip() == ""
            or str(panel.get("target_screen") or "").strip() in screen_keys
        ]
        if panels and not resolved_panels:
            return {}
        resolved["dashboard_panels"] = resolved_panels
        return resolved

    @staticmethod
    def _apply_runtime_injections(
        *,
        groups: list[dict[str, Any]],
        modules: list[dict[str, Any]],
        screens: list[dict[str, Any]],
        actions: list[dict[str, Any]],
        ia_owned_action_copy: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, int]:
        """Inject all runtime bundles and return per-bundle injected counts."""

        return {
            bundle.coverage_key: PublishedTuiMetadataRepository._inject_runtime_bundle(
                bundle=bundle,
                groups=groups,
                modules=modules,
                screens=screens,
                actions=actions,
                ia_owned_action_copy=ia_owned_action_copy or {},
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
        ia_owned_action_copy: dict[str, dict[str, Any]] | None = None,
    ) -> int:
        """Inject one runtime bundle and report inserted or replaced item count."""

        owned_action_copy = ia_owned_action_copy or {}
        injected = 0
        injected += PublishedTuiMetadataRepository._append_unique_payloads(
            payloads=groups,
            additions=bundle.groups,
            replace_existing=bundle.replace_existing,
        )
        injected += PublishedTuiMetadataRepository._append_unique_payloads(
            payloads=modules,
            additions=bundle.modules,
            replace_existing=bundle.replace_existing,
        )
        injected += PublishedTuiMetadataRepository._append_unique_payloads(
            payloads=screens,
            additions=bundle.screens,
            replace_existing=bundle.replace_existing,
        )

        screen_keys = {str(screen.get("key") or "") for screen in screens}
        action_index = {str(action.get("key") or ""): index for index, action in enumerate(actions)}
        for action in bundle.actions:
            action_key = str(action.get("key") or "")
            screen_key = str(action.get("screen_key") or "")
            existing_index = action_index.get(action_key)
            if existing_index is not None:
                replacement = dict(action)
                replacement.update(owned_action_copy.get(action_key, {}))
                if bundle.replace_existing and actions[existing_index] != replacement:
                    actions[existing_index] = replacement
                    injected += 1
                elif not bundle.replace_existing:
                    runtime_contract = {
                        key: action[key] for key in ("audience", "effect") if key in action
                    }
                    merged_action = {
                        **actions[existing_index],
                        **runtime_contract,
                    }
                    if merged_action != actions[existing_index]:
                        actions[existing_index] = merged_action
                        injected += 1
                continue
            if screen_key and screen_key not in screen_keys:
                continue
            runtime_action = dict(action)
            runtime_action.update(owned_action_copy.get(action_key, {}))
            actions.append(runtime_action)
            action_index[action_key] = len(actions) - 1
            injected += 1
        return injected

    @staticmethod
    def _append_unique_payloads(
        *,
        payloads: list[dict[str, Any]],
        additions: tuple[dict[str, Any], ...],
        replace_existing: bool = False,
    ) -> int:
        """Upsert payloads by unique key and return the number of changed items."""

        existing_index = {
            str(payload.get("key") or ""): index for index, payload in enumerate(payloads)
        }
        inserted = 0
        for addition in additions:
            addition_key = str(addition.get("key") or "")
            current_index = existing_index.get(addition_key)
            if current_index is not None:
                if replace_existing and payloads[current_index] != addition:
                    payloads[current_index] = dict(addition)
                    inserted += 1
                continue
            payloads.append(dict(addition))
            existing_index[addition_key] = len(payloads) - 1
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


@lru_cache(maxsize=1)
def get_tui_metadata_repository() -> PublishedTuiMetadataRepository:
    """Return the default published TUI metadata repository."""

    return PublishedTuiMetadataRepository()
