"""Builders and shared fields for broker-execution runtime TUI metadata."""

from __future__ import annotations

from typing import Any

_ORDER_ID_FIELD = {
    "key": "client_order_id",
    "label": "订单编号",
    "input_type": "text",
    "required": True,
    "default": "",
    "placeholder": "从订单列表选择",
    "binding": "path",
    "value_type": "string",
}
_REASON_FIELD = {
    "key": "reason",
    "label": "操作原因",
    "input_type": "textarea",
    "required": True,
    "default": "",
    "placeholder": "说明复核结论或处置原因",
    "binding": "body",
    "value_type": "string",
}


def _order_action(
    key: str, label: str, action: str, *, preview: bool, sequence: int
) -> dict[str, Any]:
    """Build one governed order preview or confirmation action."""

    return {
        "key": key,
        "label": label,
        "endpoint": f"/api/broker-execution/orders/<uuid:client_order_id>/{action}/",
        "method": "POST",
        "intent": key.replace("-", "_"),
        "risk": "write" if not preview else "read",
        "screen_key": "broker-execution.overview",
        "module_key": "daily-decisions",
        "view_type": "detail",
        "description": f"{'预览' if preview else '确认'}{label}，并保留权限与审计证据。",
        "source": "approved:runtime-broker-execution",
        "task_group": "02 实盘订单处置",
        "task_tier": "primary",
        "sequence": sequence,
        "confirmation_required": not preview,
        "audit_required": not preview,
        "fields": [
            dict(_ORDER_ID_FIELD),
            dict(_REASON_FIELD),
            {
                "key": "preview_only",
                "label": "仅预览",
                "input_type": "hidden",
                "required": True,
                "default": preview,
                "binding": "body",
                "value_type": "boolean",
            },
            *(
                []
                if preview
                else [
                    {
                        "key": "expected_version",
                        "label": "预览中的订单版本",
                        "input_type": "number",
                        "required": True,
                        "default": 0,
                        "placeholder": "填写刚才预览返回的版本",
                        "binding": "body",
                        "value_type": "integer",
                    },
                    {
                        "key": "idempotency_key",
                        "label": "请求幂等键",
                        "input_type": "text",
                        "required": True,
                        "default": "",
                        "placeholder": "每次确认使用唯一值",
                        "binding": "body",
                        "value_type": "string",
                    },
                ]
            ),
        ],
    }


def _admin_preview_commit_actions(
    *,
    key_prefix: str,
    label: str,
    endpoint: str,
    method: str,
    intent: str,
    sequence: int,
    fields: list[dict[str, Any]],
    commit_fields: list[dict[str, Any]] | None = None,
    effect: str = "update",
    result_semantics: list[str] | None = None,
    screen_key: str = "broker-execution.overview",
    task_group: str = "05 实盘接入治理",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build one admin-only preview/commit pair."""

    shared = {
        "endpoint": endpoint,
        "method": method,
        "audience": "admin",
        "screen_key": screen_key,
        "module_key": "daily-decisions",
        "view_type": "detail",
        "source": "approved:runtime-broker-execution",
        "task_group": task_group,
        "task_tier": "support",
    }
    preview = {
        **shared,
        "key": f"{key_prefix}-preview",
        "label": f"预览{label}",
        "intent": f"preview_{intent}",
        "risk": "read",
        "sequence": sequence,
        "description": f"预览{label}的影响，不产生状态变化。",
        "fields": [
            *fields,
            {
                "key": "preview_only",
                "label": "仅预览",
                "input_type": "hidden",
                "required": True,
                "default": True,
                "binding": "body",
                "value_type": "boolean",
            },
        ],
    }
    commit: dict[str, Any] = {
        **shared,
        "key": key_prefix,
        "label": f"确认{label}",
        "intent": intent,
        "risk": "admin",
        "effect": effect,
        "sequence": sequence + 1,
        "description": f"确认{label}并保留权限、幂等与审计证据。",
        "confirmation_required": True,
        "audit_required": True,
        "fields": [
            *fields,
            *(commit_fields or []),
            {
                "key": "preview_only",
                "label": "确认执行",
                "input_type": "hidden",
                "required": True,
                "default": False,
                "binding": "body",
                "value_type": "boolean",
            },
            {
                "key": "idempotency_key",
                "label": "请求幂等键",
                "input_type": "text",
                "required": True,
                "default": "",
                "binding": "body",
                "value_type": "string",
            },
        ],
    }
    if result_semantics:
        commit["result_semantics"] = result_semantics
    return preview, commit


_ACCOUNT_ID_FIELD = {
    "key": "account_id",
    "label": "实盘账户 ID",
    "input_type": "number",
    "required": True,
    "binding": "body",
    "value_type": "integer",
    "min": 1,
}
_AGENT_ID_FIELD = {
    "key": "agent_id",
    "label": "Agent ID",
    "input_type": "text",
    "required": True,
    "binding": "body",
    "value_type": "string",
    "max": 64,
}
