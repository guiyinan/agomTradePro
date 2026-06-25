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

RUNTIME_REDUNDANT_SCREEN_ACTION_KEYS: dict[str, set[str]] = {
    "ai-ops.capabilities": {
        "param.api.get.api.ai-capability.capabilities.pk",
    },
}

RUNTIME_ADVISOR_SCREEN: dict[str, Any] = {
    "key": "command-center.auto-advisor",
    "label": "自动投顾",
    "module_key": "command-center",
    "group": "workflow",
    "summary": "按账户读取持仓驱动的今日建议单和建议订单清单。",
    "view_type": "datagrid",
    "default_action_key": "advisor.today_sheet",
    "business_context": {
        "objective": "确认一个账户今天是否行动、下多少单、每单怎么下。",
        "decision_output": "账户级结论、持仓摘要、建议订单清单和阻断项。",
        "checkpoints": [
            "先输入账户 ID 读取该账户持仓。",
            "优先检查减仓、清仓和阻断项。",
            "新增买入只在现金、价格和风控允许时展示。",
        ],
    },
}

RUNTIME_ADVISOR_ACTION: dict[str, Any] = {
    "key": "advisor.today_sheet",
    "label": "今日自动投顾建议单",
    "endpoint": "/api/decision/advisor/sheet/",
    "method": "GET",
    "intent": "auto_safe_read_candidate",
    "risk_level": "read",
    "screen_key": "command-center.auto-advisor",
    "view_type": "datagrid",
    "description": "按 account_id 读取账户级持仓、配置偏离和建议订单清单。",
    "source": "approved:runtime-advisor",
    "task_group": "01 自动投顾",
    "sequence": 100,
    "task_tier": "primary",
    "fields": [
        {
            "key": "account_id",
            "label": "账户 ID",
            "input_type": "text",
            "required": True,
            "default": "",
            "placeholder": "输入账户 ID",
            "binding": "query",
            "value_type": "string",
        }
    ],
    "view_model": {
        "kind": "datagrid",
        "rows_path": "data.order_intents",
        "total_path": "data.order_summary.total",
        "status_path": "data.today_conclusion",
        "title_path": "data.account.account_name",
    },
}

RUNTIME_ACTION_PATCHES: dict[str, dict[str, Any]] = {
    "auto.api.get.api.dashboard.alpha.history": {
        "view_type": "datagrid",
        "view_model": {
            "rows_path": "data",
        },
    },
    "auto.api.get.api.system.list": {
        "view_type": "datagrid",
        "view_model": {
            "rows_path": "items",
            "total_path": "total",
        },
    },
    "param.api.get.api.account.accounts.int.account_id.performance": {
        "screen_key": "execution.accounts",
    },
    "param.api.get.api.account.accounts.int.account_id.performance-report": {
        "screen_key": "execution.accounts",
    },
    "param.api.get.api.account.accounts.int.account_id.valuation-snapshot": {
        "screen_key": "execution.accounts",
    },
    "param.api.get.api.account.accounts.int.account_id.valuation-timeline": {
        "screen_key": "execution.accounts",
    },
    "param.api.get.api.account.accounts.int.account_id.benchmarks": {
        "screen_key": "execution.accounts",
    },
    "param.api.get.api.account.accounts.int.account_id.equity-curve": {
        "screen_key": "execution.accounts",
    },
    "param.api.get.api.account.accounts.int.account_id.inspections": {
        "screen_key": "execution.accounts",
    },
    "auto.api.get.api.strategy.assignments.by_portfolio": {
        "screen_key": "execution.portfolio-performance",
    },
    "auto.api.get.api.strategy.execution-logs.by_portfolio": {
        "screen_key": "execution.portfolio-performance",
    },
    "param.api.get.api.audit.operation-logs.str.log_id": {
        "fields": [
            {
                "key": "log_id",
                "label": "日志 ID",
                "input_type": "text",
                "required": True,
                "default": "",
                "placeholder": "输入日志 ID",
                "binding": "path",
                "value_type": "string",
            },
        ],
    },
    "param.api.get.api.audit.decision-traces.str.request_id": {
        "fields": [
            {
                "key": "request_id",
                "label": "请求ID",
                "input_type": "text",
                "required": True,
                "default": "",
                "placeholder": "请输入请求ID",
                "binding": "path",
                "value_type": "string",
            },
        ],
    },
}


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
        return self._normalize_runtime_payload(validate_tui_metadata(payload))

    def _normalize_runtime_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Prune duplicated actions that are not operator-usable in runtime screens."""

        redundant_map = RUNTIME_REDUNDANT_SCREEN_ACTION_KEYS
        patches = RUNTIME_ACTION_PATCHES

        normalized = dict(payload)
        screens = list(payload.get("screens") or [])
        actions = list(normalized.get("actions") or [])
        injected = self._inject_advisor_metadata(screens=screens, actions=actions)
        normalized["screens"] = screens
        normalized["actions"] = actions

        if not redundant_map and not patches and injected == 0:
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
                return payload
            coverage = dict(normalized.get("coverage_summary") or {})
            coverage["runtime_injected_advisor_metadata"] = injected + int(
                coverage.get("runtime_injected_advisor_metadata", 0) or 0
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
        coverage["runtime_injected_advisor_metadata"] = injected + int(
            coverage.get("runtime_injected_advisor_metadata", 0) or 0
        )
        normalized["coverage_summary"] = coverage
        return validate_tui_metadata(normalized)

    @staticmethod
    def _inject_advisor_metadata(
        *,
        screens: list[dict[str, Any]],
        actions: list[dict[str, Any]],
    ) -> int:
        """Inject the account auto-advisor screen/action when absent."""

        injected = 0
        if not any(screen.get("key") == RUNTIME_ADVISOR_SCREEN["key"] for screen in screens):
            screens.append(dict(RUNTIME_ADVISOR_SCREEN))
            injected += 1
        if not any(action.get("key") == RUNTIME_ADVISOR_ACTION["key"] for action in actions):
            actions.append(dict(RUNTIME_ADVISOR_ACTION))
            injected += 1
        return injected

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
