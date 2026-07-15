"""Catalog and field helpers for TUI workbench."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import timedelta
from typing import Any

from django.utils import timezone

from apps.account.application.interface_services import list_investment_account_options
from apps.terminal.application.tui_workbench_constants import FIELD_LABELS, FIELD_TOKEN_LABELS


class TuiWorkbenchCatalogMixin:
    """Catalog and action payload helpers shared by the TUI workbench service."""

    def _catalog_stats(
        self, metadata: dict[str, Any], visible_actions: list[dict[str, Any]]
    ) -> dict[str, int]:
        stats = {
            "actions": len(visible_actions),
            "published_actions": len(metadata["actions"]),
            "hidden_by_risk": len(metadata["actions"]) - len(visible_actions),
        }
        coverage = metadata.get("coverage_summary") or {}
        deferred = coverage.get("deferred") if isinstance(coverage, dict) else {}
        if isinstance(coverage, dict):
            for key in (
                "safe_read_evidence",
                "direct_safe_read_candidates",
                "parameterized_safe_read_candidates",
                "added_safe_api_actions",
                "added_parameterized_api_actions",
                "smoke_total",
                "smoke_ok",
                "smoke_needs_input",
                "smoke_error",
                "smoke_pruned_auto_actions",
                "business_promoted_actions",
                "approved_operation_actions",
            ):
                try:
                    stats[key] = int(coverage.get(key, 0))
                except (TypeError, ValueError):
                    stats[key] = 0
        if isinstance(deferred, dict):
            for key, value in deferred.items():
                try:
                    stats[f"deferred_{key}"] = int(value)
                except (TypeError, ValueError):
                    stats[f"deferred_{key}"] = 0
        return stats

    def _module_summary(self, module: dict[str, Any]) -> dict[str, Any]:
        return {
            "key": module["key"],
            "label": self._operator_text(module["label"]),
            "group": module["group"],
            "summary": self._operator_text(module["summary"]),
            "status": module.get("status", "online"),
        }

    def _screen_summary(
        self,
        screen: dict[str, Any],
        actions: list[dict[str, Any]],
        *,
        user: Any | None = None,
    ) -> dict[str, Any]:
        return {
            "key": screen["key"],
            "label": self._operator_text(screen["label"]),
            "module_key": screen["module_key"],
            "group": screen["group"],
            "summary": self._operator_text(screen["summary"]),
            "view_type": screen["view_type"],
            "audience": screen.get("audience", "authenticated"),
            "status": screen.get("status", "online"),
            "chrome_mode": str(screen.get("chrome_mode") or ""),
            "default_action_key": self._screen_default_action_key(screen, actions),
            "action_count": len(actions),
            "dashboard_panels": list(screen.get("dashboard_panels") or []),
            "workflow": dict(screen.get("workflow") or {}),
            "user_experience": dict(screen.get("user_experience") or {}),
            "business_context": self._screen_business_context(screen, actions),
            "entry_state": self._screen_entry_state(screen, actions, user=user),
        }

    def _screen_default_action_key(
        self, screen: dict[str, Any], actions: list[dict[str, Any]]
    ) -> str:
        configured_key = str(screen.get("default_action_key") or "")
        if not actions:
            return configured_key

        actions_by_key = {str(action.get("key") or ""): action for action in actions}
        configured_action = actions_by_key.get(configured_key)
        if configured_action:
            return configured_key

        panel_candidates = self._panel_default_action_candidates(screen, actions_by_key)
        if panel_candidates:
            return str(panel_candidates[0].get("key") or configured_key)

        sorted_actions = self._sorted_default_actions(actions)
        same_view_candidates = [
            action
            for action in sorted_actions
            if str(action.get("view_type") or "") == str(screen.get("view_type") or "")
            and not self._action_requires_operator_input(action)
        ]
        if same_view_candidates:
            return str(same_view_candidates[0].get("key") or configured_key)

        no_input_candidates = [
            action
            for action in sorted_actions
            if not self._action_requires_operator_input(action)
        ]
        if no_input_candidates:
            return str(no_input_candidates[0].get("key") or configured_key)

        if configured_action:
            return configured_key
        return str(sorted_actions[0].get("key") or configured_key)

    def _panel_default_action_candidates(
        self,
        screen: dict[str, Any],
        actions_by_key: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        panel_actions = [
            actions_by_key[action_key]
            for action_key in (
                str(panel.get("action_key") or "") for panel in screen.get("dashboard_panels") or []
            )
            if action_key in actions_by_key
        ]
        if not panel_actions:
            return []

        screen_view_type = str(screen.get("view_type") or "")
        same_view = [
            action
            for action in panel_actions
            if str(action.get("view_type") or "") == screen_view_type
            and not self._action_requires_operator_input(action)
        ]
        if same_view:
            return same_view

        return [
            action
            for action in panel_actions
            if not self._action_requires_operator_input(action)
        ]

    def _sorted_default_actions(self, actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(
            actions,
            key=lambda action: (
                int(action.get("sequence", 999)),
                str(action.get("key") or ""),
            ),
        )

    def _action_requires_operator_input(self, action: dict[str, Any]) -> bool:
        return any(
            bool(field.get("required")) and str(field.get("input_type") or "") != "hidden"
            for field in action.get("fields") or []
        )

    def _screen_entry_state(
        self,
        screen: dict[str, Any],
        actions: list[dict[str, Any]],
        *,
        user: Any | None = None,
    ) -> dict[str, Any]:
        default_action_key = self._screen_default_action_key(screen, actions)
        default_action = next(
            (action for action in actions if str(action.get("key") or "") == default_action_key),
            None,
        )
        blocking_fields = self._blocking_required_fields(default_action) if default_action else []
        explicit_mode = str(screen.get("entry_mode") or "").strip().lower()
        mode = explicit_mode if explicit_mode in {"auto_run", "parameter_gate", "dashboard"} else ""
        if not mode:
            if screen.get("dashboard_panels"):
                mode = "dashboard"
            elif blocking_fields:
                mode = "parameter_gate"
            else:
                mode = "auto_run"
        field_key = str(screen.get("entry_field_key") or "").strip()
        if not field_key and blocking_fields:
            field_key = str(blocking_fields[0].get("key") or "").strip()
        return {
            "mode": mode,
            "field_key": field_key,
            "help_steps": self._screen_entry_help_steps(
                screen,
                default_action,
                blocking_fields,
                mode=mode,
            ),
            "empty_copy": self._screen_entry_empty_copy(
                screen,
                default_action,
                blocking_fields,
                mode=mode,
            ),
        }

    def _blocking_required_fields(self, action: dict[str, Any] | None) -> list[dict[str, Any]]:
        if not action:
            return []
        blocking: list[dict[str, Any]] = []
        for field in action.get("fields") or []:
            if not field.get("required"):
                continue
            if str(field.get("input_type") or "").strip().lower() == "hidden":
                continue
            if self._resolved_field_default(action, field) in (None, ""):
                blocking.append(field)
        return blocking

    def _screen_entry_help_steps(
        self,
        screen: dict[str, Any],
        action: dict[str, Any] | None,
        blocking_fields: list[dict[str, Any]],
        *,
        mode: str,
    ) -> list[str]:
        explicit = [
            self._operator_text(item)
            for item in (screen.get("entry_help_steps") or [])
            if str(item or "").strip()
        ]
        if explicit:
            return explicit
        if mode == "dashboard":
            return ["先看中心概览，再从左侧任务进入明细或操作。"]
        if mode == "auto_run":
            label = self._operator_text((action or {}).get("label") or "默认任务")
            return [f"进入屏幕后会自动执行“{label}”。"]
        if not blocking_fields:
            return ["先补充默认任务参数，再继续执行。"]
        field = blocking_fields[0]
        input_type = str(field.get("input_type") or "").strip().lower()
        label = self._operator_text(field.get("label") or field.get("key") or "参数")
        if input_type == "select":
            return [f"先选择{label}，系统会自动进入默认结果。"]
        return [f"先补充{label}，再继续执行默认任务。"]

    def _screen_entry_empty_copy(
        self,
        screen: dict[str, Any],
        action: dict[str, Any] | None,
        blocking_fields: list[dict[str, Any]],
        *,
        mode: str,
    ) -> str:
        explicit = self._operator_text(screen.get("entry_empty_copy") or "")
        if explicit:
            return explicit
        if mode == "dashboard":
            return self._operator_text(screen.get("summary") or "先看当前概览。")
        if mode == "auto_run":
            return "正在准备默认结果。"
        if not blocking_fields:
            return self._operator_text(screen.get("summary") or "先补充参数，再继续执行。")
        field = blocking_fields[0]
        input_type = str(field.get("input_type") or "").strip().lower()
        label = self._operator_text(field.get("label") or field.get("key") or "对象")
        if input_type == "select":
            return f"先选择{label}，再进入本屏默认结果。"
        return f"先补充{label}，再进入本屏默认结果。"

    def _screen_business_context(
        self, screen: dict[str, Any], actions: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Return explicit business context or derive an operator-facing fallback."""

        explicit = dict(screen.get("business_context") or {})
        if (
            explicit.get("objective")
            or explicit.get("decision_output")
            or explicit.get("checkpoints")
        ):
            explicit["objective"] = self._operator_text(explicit.get("objective", ""))
            explicit["decision_output"] = self._operator_text(explicit.get("decision_output", ""))
            explicit["checkpoints"] = [
                self._operator_text(item) for item in explicit.get("checkpoints") or []
            ]
            return explicit

        view_type = str(screen.get("view_type") or "")
        inferred_tiers = [self._runtime_action_tier(action) for action in actions]
        primary_count = sum(1 for tier in inferred_tiers if tier == "primary")
        support_count = sum(1 for tier in inferred_tiers if tier == "support")
        advanced_count = sum(1 for tier in inferred_tiers if tier == "advanced")
        operation_count = sum(1 for tier in inferred_tiers if tier == "operation")

        output_by_view = {
            "datagrid": "可筛选、可翻页、可打开明细的业务列表。",
            "detail": "当前对象或当前任务的结构化摘要。",
            "status": "当前状态、异常信号和后续检查方向。",
            "message": "可读的业务说明或交互结果。",
            "queue_workbench": "队列状态、待处理事项和下一步处理方向。",
        }
        checkpoints = []
        if primary_count:
            checkpoints.append("先按主流程任务读取本屏关键判断。")
        if support_count:
            checkpoints.append("发现矛盾或缺口时展开支撑检查。")
        if advanced_count:
            checkpoints.append("需要定位单条记录时再使用条件查询。")
        if operation_count:
            checkpoints.append("写入或 AI 交互只在证据明确后执行，并接受确认。")
        if not checkpoints:
            checkpoints.append("当前屏暂无已发布任务，等待 metadata 提升后进入主菜单。")

        return {
            "objective": str(screen.get("summary") or screen.get("label") or ""),
            "decision_output": output_by_view.get(view_type, "当前工作区的业务结果和下一步操作。"),
            "checkpoints": checkpoints,
        }

    def _runtime_action_tier(self, action: dict[str, Any]) -> str:
        tier = str(action.get("task_tier") or "").lower()
        if tier in {"primary", "support", "advanced", "operation"}:
            return tier
        risk = str(action.get("risk") or "read").lower()
        if risk in {"write", "ai", "admin"}:
            return "operation"
        key = str(action.get("key") or "")
        group = str(action.get("task_group") or "")
        if key.startswith("param.") or "条件查询" in group:
            return "advanced"
        return "primary"

    def _action_payload(
        self,
        action: dict[str, Any],
        *,
        include_technical: bool = False,
        user: Any | None = None,
    ) -> dict[str, Any]:
        payload = {
            "key": action["key"],
            "ui_key": self._action_ui_key(action),
            "label": self._operator_text(action["label"]),
            "intent": action["intent"],
            "screen_key": action["screen_key"],
            "view_type": action["view_type"],
            "risk": action["risk"],
            "confirmation_required": self._requires_confirmation(action),
            "fields": [
                self._field_payload(field, action=action, user=user)
                for field in action.get("fields") or []
            ],
            "description": self._operator_text(action.get("description", "")),
            "task_group": self._operator_text(action.get("task_group", "")),
            "task_tier": action.get("task_tier", ""),
            "result_semantics": list(action.get("result_semantics") or []),
            "sequence": int(action.get("sequence", 999)),
        }
        if include_technical:
            payload.update(
                {
                    "method": action["method"],
                    "endpoint": action["endpoint"],
                    "module_key": action["module_key"],
                    "source": action.get("source", "published"),
                    "raw_debug": bool(action.get("raw_debug", True)),
                    "view_model": dict(action.get("view_model") or {}),
                }
            )
        return payload

    def _action_ui_key(self, action: dict[str, Any]) -> str:
        digest = hashlib.sha1(str(action.get("key") or "").encode("utf-8")).hexdigest()[:10]
        return f"task-{digest}"

    def _int_from_path(
        self,
        action: dict[str, Any],
        envelope: dict[str, Any] | None,
        key: str,
        *,
        default: int,
    ) -> int:
        if not envelope:
            return default
        path = self._view_model_path(action, key)
        value = self._value_at_path(envelope, path) if path else None
        try:
            return int(value) if value not in (None, "") else default
        except (TypeError, ValueError):
            return default

    def _int_from_params(
        self,
        params: dict[str, Any] | None,
        key: str,
        *,
        default: int,
    ) -> int:
        if not params:
            return default
        try:
            value = params.get(key)
            return int(value) if value not in (None, "") else default
        except (TypeError, ValueError):
            return default

    def _field_payload(
        self,
        field: dict[str, Any],
        *,
        action: dict[str, Any] | None = None,
        user: Any | None = None,
    ) -> dict[str, Any]:
        payload = dict(field)
        key = str(payload.get("key") or "").strip()
        label = str(payload.get("label") or "").strip()
        canonical_label = key in FIELD_LABELS
        if canonical_label or self._is_technical_field_label(key=key, label=label):
            payload["label"] = self._humanize(key)
        resolved_default = (
            self._resolved_field_default(action, field) if action else payload.get("default")
        )
        if resolved_default not in (None, "") and payload.get("default") in (None, ""):
            payload["default"] = resolved_default
        placeholder = str(payload.get("placeholder") or "").strip()
        if payload.get("required") and (
            not placeholder
            or canonical_label
            or self._is_technical_placeholder(key=key, placeholder=placeholder)
        ):
            payload["placeholder"] = f"请输入{payload['label']}"
        self._decorate_dynamic_field_options(payload, action=action, user=user)
        return payload

    def _decorate_dynamic_field_options(
        self,
        payload: dict[str, Any],
        *,
        action: dict[str, Any] | None,
        user: Any | None,
    ) -> None:
        key = str(payload.get("key") or "").strip().lower()
        if key != "account_id":
            return
        account_options = self._account_options_for_user(user)
        if not account_options:
            return
        payload["input_type"] = "select"
        payload["value_type"] = "integer"
        payload["placeholder"] = "请选择账户"
        empty_label = "请选择账户" if payload.get("required") else "不指定账户"
        if (
            action
            and str(action.get("method") or "").upper() == "GET"
            and not payload.get("required")
        ):
            empty_label = "全部账户"
        payload["options"] = [{"value": "", "label": empty_label}, *account_options]

    def _account_options_for_user(self, user: Any | None) -> list[dict[str, Any]]:
        user_id = getattr(user, "id", None)
        if user_id in (None, ""):
            return []
        try:
            normalized_user_id = int(user_id)
        except (TypeError, ValueError):
            return []
        if normalized_user_id not in self._account_options_cache:
            self._account_options_cache[normalized_user_id] = list_investment_account_options(
                normalized_user_id
            )
        return self._account_options_cache[normalized_user_id]

    def _resolved_field_default(
        self,
        action: dict[str, Any] | None,
        field: dict[str, Any],
    ) -> Any:
        default = field.get("default")
        if default not in (None, ""):
            return self._coerce_field_default(field, default)
        if not action or str(action.get("risk") or "") != "read":
            return default
        key = str(field.get("key") or "").strip().lower()
        input_type = str(field.get("input_type") or "").strip().lower()
        if input_type != "date":
            return default
        today = timezone.localdate()
        if key in {"start_date", "start"}:
            return (today - timedelta(days=30)).isoformat()
        if key in {"end_date", "end", "as_of_date", "as_of", "date", "trade_date"}:
            return today.isoformat()
        return default

    def _coerce_field_default(self, field: dict[str, Any], value: Any) -> Any:
        if value in (None, ""):
            return value
        value_type = str(field.get("value_type") or field.get("input_type") or "").strip().lower()
        if not value_type:
            return value
        if value_type == "integer":
            try:
                return int(value)
            except (TypeError, ValueError):
                return value
        if value_type == "float":
            try:
                return float(value)
            except (TypeError, ValueError):
                return value
        if value_type == "boolean":
            if isinstance(value, bool):
                return value
            normalized = str(value).strip().lower()
            if normalized in {"true", "1", "yes", "y", "on"}:
                return True
            if normalized in {"false", "0", "no", "n", "off"}:
                return False
            return value
        if value_type in {"list", "json", "object"} and isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return value
            if value_type == "list" and not isinstance(parsed, list):
                return value
            if value_type == "object" and not isinstance(parsed, dict):
                return value
            return parsed
        return value

    def _is_technical_field_label(self, *, key: str, label: str) -> bool:
        if not label:
            return True
        normalized_label = label.strip().lower().replace(" ", "_").replace("-", "_")
        normalized_key = key.strip().lower().replace("-", "_")
        return normalized_label in {
            normalized_key,
            "pk",
            "id",
            "str",
            "int",
            "uuid",
        }

    def _is_technical_placeholder(self, *, key: str, placeholder: str) -> bool:
        normalized = placeholder.strip().lower().replace(" ", "_").replace("-", "_")
        return normalized in {
            key.strip().lower().replace("-", "_"),
            f"input_{key.strip().lower().replace('-', '_')}",
            f"输入{key}",
        }

    def _empty_datagrid_message(self, action: dict[str, Any], total: int) -> str:
        if total > 0:
            return "当前页没有可显示记录。"
        return f"暂无{self._action_title(action)}数据。"

    def _empty_datagrid_guidance(self, action: dict[str, Any], total: int) -> list[str]:
        if total > 0:
            return [
                "当前页没有记录，但结果集仍有数据。",
                "使用 PgUp/PgDn 或调整页码后继续查看。",
            ]
        visible_fields = [
            self._field_payload(field)
            for field in action.get("fields") or []
            if field.get("input_type") != "hidden"
        ]
        guidance = [
            "先按 F5 刷新，确认不是临时数据延迟。",
        ]
        if visible_fields:
            labels = "、".join(
                str(field.get("label") or field.get("key") or "") for field in visible_fields[:4]
            )
            guidance.append(f"检查筛选条件：{labels}。")
            guidance.append(
                "如果当前表格已有对应记录，可选中一行后按 F9 进入任务区使用“从选中行填参”。"
            )
        else:
            guidance.append("如果这是初始化数据，先到相关配置或同步任务中补齐数据源。")
            guidance.append("也可以按 F9 定位任务区，搜索本屏可用的同步、检查或配置任务。")
        return guidance

    def _humanize(self, value: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            return ""
        if normalized in FIELD_LABELS:
            return FIELD_LABELS[normalized]
        parts = [part for part in normalized.replace("-", "_").split(".") if part]
        labels = [self._humanize_part(part) for part in parts]
        return " / ".join(label for label in labels if label)

    def _humanize_part(self, value: str) -> str:
        if value in FIELD_LABELS:
            return FIELD_LABELS[value]
        expanded = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", value).replace("-", "_")
        tokens = [token for token in expanded.split("_") if token]
        if not tokens:
            return value
        translated = [
            FIELD_TOKEN_LABELS.get(
                token.lower(), token.upper() if token.lower() == "id" else token.title()
            )
            for token in tokens
        ]
        return "".join(translated)
