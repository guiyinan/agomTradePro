"""Result view-model helpers for TUI workbench."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from apps.terminal.application.tui_workbench_collection_result_models import (
    TuiWorkbenchCollectionResultMixin,
)
from apps.terminal.application.tui_workbench_constants import (
    STATUS_LABELS,
)
from apps.terminal.application.tui_workbench_detail_result_models import (
    TuiWorkbenchDetailResultMixin,
)
from apps.terminal.application.tui_workbench_result_models_specialized import (
    TuiWorkbenchSpecializedResultMixin,
)


class TuiWorkbenchResultModelMixin(
    TuiWorkbenchCollectionResultMixin,
    TuiWorkbenchDetailResultMixin,
    TuiWorkbenchSpecializedResultMixin,
):
    """View-model rendering helpers shared by the TUI workbench service."""

    if TYPE_CHECKING:

        def _int_from_path(
            self,
            action: dict[str, Any],
            envelope: dict[str, Any] | None,
            key: str,
            *,
            default: int,
        ) -> int: ...

        def _int_from_params(
            self,
            params: dict[str, Any] | None,
            key: str,
            *,
            default: int,
        ) -> int: ...

        def _empty_datagrid_message(
            self,
            action: dict[str, Any],
            total: int,
        ) -> str: ...

        def _empty_datagrid_guidance(
            self,
            action: dict[str, Any],
            total: int,
        ) -> list[str]: ...

        def _humanize(self, value: str) -> str: ...

    def _resolve_asset_names(self, codes: list[str]) -> dict[str, str]:
        raise NotImplementedError

    def _to_view_model(
        self,
        *,
        action: dict[str, Any],
        payload: Any,
        status_code: int,
        request_params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        data = self._unwrap_payload(payload)
        custom_model = self._custom_view_model(
            action,
            data,
            status_code,
            request_params=request_params,
        )
        if custom_model is not None:
            return self._finalize_view_model(
                action,
                custom_model,
                payload=data,
                status_code=status_code,
            )
        forced_kind = self._view_model_path(action, "kind")
        if isinstance(data, dict) and self._is_endpoint_directory(data):
            return self._finalize_view_model(
                action,
                self._endpoint_directory_model(action, data, status_code),
                payload=data,
                status_code=status_code,
            )
        if forced_kind == "detail" and isinstance(data, dict):
            return self._finalize_view_model(
                action,
                self._detail_model(action, data, status_code),
                payload=data,
                status_code=status_code,
            )
        if forced_kind == "message":
            return self._finalize_view_model(
                action,
                {
                    "kind": "message",
                    "title": self._action_title(action),
                    "status": self._status_label(status_code),
                    "message": self._display_value(data),
                    "raw_hint": "原始响应只在调试抽屉中查看。",
                },
                payload=data,
                status_code=status_code,
            )
        if forced_kind == "chart":
            return self._finalize_view_model(
                action,
                self._chart_model(action, data, status_code),
                payload=data,
                status_code=status_code,
            )
        if forced_kind == "table_chart":
            return self._finalize_view_model(
                action,
                self._table_chart_model(action, data, status_code),
                payload=data,
                status_code=status_code,
            )
        if forced_kind == "datagrid":
            if isinstance(data, list):
                return self._finalize_view_model(
                    action,
                    self._datagrid_model(action, data, status_code, request_params=request_params),
                    payload=data,
                    status_code=status_code,
                )
            if isinstance(data, dict):
                rows_path = self._view_model_path(action, "rows_path")
                if not rows_path and self._looks_like_detail_payload(data):
                    return self._finalize_view_model(
                        action,
                        self._detail_model(action, data, status_code),
                        payload=data,
                        status_code=status_code,
                    )
                explicit_value = self._value_at_path(data, rows_path) if rows_path else None
                list_value = (
                    explicit_value
                    if isinstance(explicit_value, list)
                    else self._find_list_value(data)
                )
                if list_value is not None:
                    return self._finalize_view_model(
                        action,
                        self._datagrid_model(
                            action,
                            list_value,
                            status_code,
                            envelope=data,
                            request_params=request_params,
                        ),
                        payload=data,
                        status_code=status_code,
                    )
        if isinstance(data, list):
            return self._finalize_view_model(
                action,
                self._datagrid_model(action, data, status_code, request_params=request_params),
                payload=data,
                status_code=status_code,
            )
        if isinstance(data, dict):
            html_text = self._dominant_html_text(data)
            if html_text:
                return self._finalize_view_model(
                    action,
                    self._message_model(action, html_text, status_code),
                    payload=data,
                    status_code=status_code,
                )
            if str(action.get("view_type")) in {"status", "detail", "queue_workbench"}:
                return self._finalize_view_model(
                    action,
                    self._detail_model(action, data, status_code),
                    payload=data,
                    status_code=status_code,
                )
            if str(action.get("view_type")) == "datagrid" and self._looks_like_detail_payload(data):
                return self._finalize_view_model(
                    action,
                    self._detail_model(action, data, status_code),
                    payload=data,
                    status_code=status_code,
                )
            rows_path = self._view_model_path(action, "rows_path")
            explicit_value = self._value_at_path(data, rows_path) if rows_path else None
            list_value = (
                explicit_value if isinstance(explicit_value, list) else self._find_list_value(data)
            )
            if list_value is not None:
                return self._finalize_view_model(
                    action,
                    self._datagrid_model(
                        action,
                        list_value,
                        status_code,
                        envelope=data,
                        request_params=request_params,
                    ),
                    payload=data,
                    status_code=status_code,
                )
            return self._finalize_view_model(
                action,
                self._detail_model(action, data, status_code),
                payload=data,
                status_code=status_code,
            )
        if self._looks_like_html(data):
            return self._finalize_view_model(
                action,
                self._message_model(action, self._html_to_text(str(data)), status_code),
                payload=data,
                status_code=status_code,
            )
        return self._finalize_view_model(
            action,
            {
                "kind": "message",
                "title": self._action_title(action),
                "status": self._status_label(status_code),
                "message": self._display_value(data),
                "raw_hint": "原始响应只在调试抽屉中查看。",
            },
            payload=data,
            status_code=status_code,
        )

    def _finalize_view_model(
        self,
        action: dict[str, Any],
        view_model: dict[str, Any],
        *,
        payload: Any,
        status_code: int,
    ) -> dict[str, Any]:
        model = dict(view_model)
        model.setdefault(
            "business_summary",
            self._default_business_summary(action, model, payload, status_code),
        )
        model.setdefault("blocking_reason", self._default_blocking_reason(payload, status_code))
        next_steps = model.get("next_steps")
        model["next_steps"] = list(next_steps) if isinstance(next_steps, list) else []
        debug_hidden_fields = model.get("debug_hidden_fields")
        model["debug_hidden_fields"] = (
            list(debug_hidden_fields) if isinstance(debug_hidden_fields, list) else []
        )
        if self._view_model_is_empty(model):
            if 200 <= int(status_code) < 300:
                model["status"] = STATUS_LABELS["EMPTY"]
            action_view_model = action.get("view_model")
            configured_model = action_view_model if isinstance(action_view_model, dict) else {}
            configured_message = str(configured_model.get("empty_message") or "").strip()
            model["empty_message"] = (
                configured_message
                or str(model.get("empty_message") or "").strip()
                or f"暂无{self._action_title(action)}数据。"
            )
            existing_guidance = model.get("empty_guidance")
            guidance_values = list(existing_guidance) if isinstance(existing_guidance, list) else []
            runtime_guidance = action.get("_empty_state_guidance")
            if isinstance(runtime_guidance, list):
                guidance_values = [*runtime_guidance, *guidance_values]
            model["empty_guidance"] = list(
                dict.fromkeys(str(item).strip() for item in guidance_values if str(item).strip())
            )
        action_view_model = action.get("view_model")
        field_presentations = (
            action_view_model.get("field_presentations", {})
            if isinstance(action_view_model, dict)
            else {}
        )
        fields = model.get("fields")
        if isinstance(fields, list):
            normalized_fields = []
            for field in fields:
                if not isinstance(field, dict):
                    continue
                presentation = (
                    field.get("presentation")
                    or field_presentations.get(str(field.get("key") or ""))
                    or "metadata"
                )
                normalized_fields.append({**field, "presentation": str(presentation)})
            model["fields"] = normalized_fields
        return model

    def _view_model_is_empty(self, view_model: dict[str, Any]) -> bool:
        """Return whether a portable result represents a reviewed empty state."""

        if str(view_model.get("status") or "") == STATUS_LABELS["EMPTY"]:
            return True
        kind = str(view_model.get("kind") or "")
        if kind == "datagrid":
            pager = view_model.get("pager")
            return int((pager if isinstance(pager, dict) else {}).get("total_rows") or 0) == 0
        if kind == "chart":
            return int(view_model.get("point_count") or 0) == 0
        if kind == "table_chart":
            table = view_model.get("table")
            chart = view_model.get("chart")
            table_payload = table if isinstance(table, dict) else {}
            chart_payload = chart if isinstance(chart, dict) else {}
            pager = table_payload.get("pager")
            table_total = int((pager if isinstance(pager, dict) else {}).get("total_rows") or 0)
            return table_total == 0 and int(chart_payload.get("point_count") or 0) == 0
        if kind == "detail":
            return not list(view_model.get("fields") or []) and not list(
                view_model.get("nested") or []
            )
        if kind == "message":
            return not str(view_model.get("message") or "").strip()
        return False

    def _action_title(self, action: dict[str, Any]) -> str:
        return self._operator_text(action.get("label") or "")

    def _unwrap_payload(self, payload: Any) -> Any:
        if isinstance(payload, dict):
            if "data" in payload and len(payload) <= 4:
                return payload.get("data")
        return payload

    def _view_model_path(self, action: dict[str, Any], key: str) -> str:
        view_model = action.get("view_model") or {}
        if not isinstance(view_model, dict):
            return ""
        return str(view_model.get(key) or "").strip()

    def _value_at_path(self, payload: Any, path: str) -> Any:
        if not path:
            return None
        current = payload
        for part in path.split("."):
            if not part:
                return None
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list) and part.isdigit():
                index = int(part)
                current = current[index] if 0 <= index < len(current) else None
            else:
                return None
        return current

    def _find_list_value(self, payload: dict[str, Any]) -> list[Any] | None:
        candidates = self._list_candidates(payload)
        if not candidates:
            return None
        return sorted(candidates, key=lambda item: item[0], reverse=True)[0][1]

    def _default_business_summary(
        self,
        action: dict[str, Any],
        view_model: dict[str, Any],
        payload: Any,
        status_code: int,
    ) -> str:
        if view_model.get("kind") == "datagrid":
            total = int((view_model.get("pager") or {}).get("total_rows") or 0)
            return f"{self._action_title(action)}：{total} 行。"
        if view_model.get("kind") == "detail":
            fields = list(view_model.get("fields") or [])
            if fields:
                return "；".join(
                    f"{self._operator_text(item.get('label') or '')} {self._display_value(item.get('value'))}"
                    for item in fields[:2]
                )
        if view_model.get("kind") == "message":
            return self._operator_text(view_model.get("message") or "")
        return self._status_label(status_code, payload)

    def _default_blocking_reason(self, payload: Any, status_code: int) -> str:
        if 200 <= int(status_code) < 300:
            return ""
        if isinstance(payload, dict):
            for key in ("detail", "error", "message"):
                text = self._operator_text(payload.get(key) or "")
                if text:
                    return text
        return ""

    def _empty_next_steps(self, action: dict[str, Any], total: int) -> list[dict[str, Any]]:
        if total > 0:
            return []
        if str(action.get("screen_key") or "") != "macro-regime.strategy":
            return []
        return [
            {
                "label": "仓位规则",
                "action_key": "auto.api.get.api.strategy.position-rules",
                "hint": "先确认当前仓位规则是否已配置。",
            },
            {
                "label": "策略绑定",
                "action_key": "auto.api.get.api.strategy.assignments",
                "hint": "核对策略是否已绑定到账户或组合。",
            },
            {
                "label": "相关配置/同步任务",
                "action_key": "auto.api.get.api.strategy.script-configs",
                "hint": "打开策略配置，继续补齐同步或脚本配置。",
            },
        ]

    def _status_label(self, status_code: int, payload: Any | None = None) -> str:
        if 200 <= int(status_code) < 300:
            return STATUS_LABELS["OK"]
        if 300 <= int(status_code) < 400:
            return STATUS_LABELS["REDIRECT"]
        if self._looks_like_password_challenge(status_code, payload):
            return "需要密码"
        if self._looks_like_empty_state(status_code, payload):
            return STATUS_LABELS["EMPTY"]
        return STATUS_LABELS["ERROR"]

    def _looks_like_password_challenge(self, status_code: int, payload: Any | None) -> bool:
        if int(status_code) != 401 or not isinstance(payload, dict):
            return False
        if bool(payload.get("requires_password")):
            return True
        for key in ("detail", "error", "message"):
            value = payload.get(key)
            if isinstance(value, str) and "密码" in value:
                return True
        return False

    def _looks_like_empty_state(self, status_code: int, payload: Any | None) -> bool:
        if int(status_code) != 404 or not isinstance(payload, dict):
            return False
        detail = payload.get("detail")
        if not isinstance(detail, str):
            return False
        normalized = detail.strip().lower()
        if not normalized:
            return False
        empty_markers = (
            "没有",
            "暂无",
            "not found",
            "does not have",
            "missing",
            "不存在",
            "未配置",
        )
        return any(marker in normalized for marker in empty_markers)
