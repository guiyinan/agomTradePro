"""Owner-facing simulated corporate-action workflow actions for the dedicated TUI screen."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from apps.terminal.infrastructure.tui_metadata_runtime_injection_corporate_action_consent import (
    RUNTIME_CORPORATE_ACTION_CONSENT_ACTIONS,
)

_SCREEN = "execution.corporate-actions"
_MODULE = "daily-decisions"
_SOURCE = "approved:runtime-simulated-corporate-action-workflow"
_ENDPOINT = "/api/simulated-trading/accounts/<int:account_id>/corporate-actions/"

CORPORATE_ACTION_WORKFLOW_READ_ACTION_KEY = "simulated-trading.corporate-action-workflow-read"
CORPORATE_ACTION_WORKFLOW_PREPARE_ACTION_KEY = "simulated-trading.corporate-action-workflow-prepare"
CORPORATE_ACTION_WORKFLOW_CONFIRM_ACTION_KEY = "simulated-trading.corporate-action-workflow-confirm"
CORPORATE_ACTION_WORKFLOW_REFRESH_ACTION_KEY = "simulated-trading.corporate-action-workflow-refresh"
CORPORATE_ACTION_WORKFLOW_EVENTS_ACTION_KEY = "simulated-trading.corporate-action-workflow-events"
CORPORATE_ACTION_WORKFLOW_AUDIT_RECEIPTS_ACTION_KEY = (
    "simulated-trading.corporate-action-workflow-audit-receipts"
)


def _account_id_field() -> dict[str, Any]:
    """Carry only the selected URL account identity into this owner-scoped action."""
    return {
        "key": "account_id",
        "label": "选择本人模拟账户",
        "binding": "path",
        "input_type": "number",
        "value_type": "integer",
        "required": True,
        "min": 1,
        "presentation_semantic": "identifier",
    }


def _hidden_continuation_field(
    key: str, label: str, *, maximum: int | None = None
) -> dict[str, Any]:
    """Declare a protected handoff value that stays out of ordinary display fields."""
    field: dict[str, Any] = {
        "key": key,
        "label": label,
        "binding": "body",
        "input_type": "hidden",
        "value_type": "string",
        "required": True,
        "presentation_semantic": "api_token",
    }
    if maximum is not None:
        field["max"] = maximum
    return field


def _confirmation_field(label: str) -> dict[str, Any]:
    """Require the user to choose explicit confirmation or cancellation."""
    return {
        "key": "confirmed",
        "label": label,
        "binding": "body",
        "input_type": "select",
        "value_type": "boolean",
        "required": True,
        "options": [
            {"value": "", "label": "请选择"},
            {"value": "true", "label": "确认本次操作"},
            {"value": "false", "label": "取消，不提交"},
        ],
        "placeholder": "只有明确选择确认才会提交本次单项操作。",
    }


def _base_action(
    *,
    key: str,
    label: str,
    endpoint: str,
    method: str,
    intent: str,
    risk: str,
    effect: str,
    description: str,
    sequence: int,
    fields: list[dict[str, Any]],
    confirmation_required: bool = False,
    view_type: str = "detail",
    view_model: dict[str, Any] | None = None,
    task_tier: str = "operation",
) -> dict[str, Any]:
    """Build one authenticated account action with no raw debug surface."""
    action: dict[str, Any] = {
        "key": key,
        "label": label,
        "endpoint": endpoint,
        "method": method,
        "intent": intent,
        "risk": risk,
        "audience": "authenticated",
        "effect": effect,
        "confirmation_required": confirmation_required,
        "audit_required": risk == "write",
        "requires_password": False,
        "session_auth_required": True,
        "sensitive_level": "high" if risk == "write" else "none",
        "raw_debug": False,
        "screen_key": _SCREEN,
        "module_key": _MODULE,
        "view_type": view_type,
        "description": description,
        "source": _SOURCE,
        "task_group": "07 公司行为处理",
        "sequence": sequence,
        "task_tier": task_tier,
        "submit_label": label,
        "fields": fields,
        "view_model": view_model or {"kind": "detail"},
    }
    return action


def _relocate_consent_action(action: dict[str, Any]) -> dict[str, Any]:
    """Move an existing consent action without changing its API or authority fields."""
    relocated = deepcopy(action)
    relocated["screen_key"] = _SCREEN
    relocated["module_key"] = _MODULE
    relocated["task_group"] = "07 公司行为处理"
    if action.get("key") == "simulated-trading.corporate-action-consent-prepare":
        relocated["result_panel_key"] = "corporate-action-consent-result"
    elif action.get("key") == "simulated-trading.corporate-action-consent-withdraw-prepare":
        relocated["result_panel_key"] = "corporate-action-withdrawal-result"
    return relocated


def _consent_actions_on_workflow_screen() -> tuple[dict[str, Any], ...]:
    """Reuse the four existing consent actions on the single owner workflow screen."""
    return tuple(
        _relocate_consent_action(action) for action in RUNTIME_CORPORATE_ACTION_CONSENT_ACTIONS
    )


RUNTIME_CORPORATE_ACTION_WORKFLOW_ACTIONS: tuple[dict[str, Any], ...] = (
    _base_action(
        key=CORPORATE_ACTION_WORKFLOW_READ_ACTION_KEY,
        label="读取公司行为与账户回执",
        endpoint=_ENDPOINT,
        method="GET",
        intent="read_owner_corporate_action_workflow",
        risk="read",
        effect="read",
        description=(
            "读取本人模拟账户的资金与持仓摘要、来源时间、可办理事件和原始审计回执。"
            "未知金额保持空值；此读取不构成交易或投资建议。"
        ),
        sequence=840,
        fields=[_account_id_field()],
    ),
    _base_action(
        key=CORPORATE_ACTION_WORKFLOW_PREPARE_ACTION_KEY,
        label="准备公司行为办理",
        endpoint=f"{_ENDPOINT}prepare/",
        method="POST",
        intent="prepare_owner_corporate_action_workflow",
        risk="read",
        effect="read",
        description=(
            "选择首次办理、继续下一阶段或按新披露整批更正；填写来源事件、办理项目和必要日期。"
            "核对本人账户、当前来源、权限与审计依据后再确认。不得输入金额或数量。"
        ),
        sequence=841,
        fields=[
            _account_id_field(),
            {
                "key": "event_id",
                "label": "来源事件编号",
                "binding": "body",
                "input_type": "text",
                "value_type": "string",
                "required": True,
                "max": 192,
                "placeholder": "从当前事件列表选择的事件编号",
            },
            {
                "key": "action",
                "label": "办理项目（更正时核对整批已办阶段）",
                "binding": "body",
                "input_type": "select",
                "value_type": "string",
                "required": True,
                "options": [
                    {"value": "cash_entitlement", "label": "记录现金分红权益"},
                    {"value": "cash_payment", "label": "模拟登记现金到账"},
                    {"value": "share_entitlement", "label": "记录送股或转增权益"},
                    {"value": "share_delivery", "label": "模拟股份交付"},
                    {"value": "share_sellable_release", "label": "模拟股份可售解禁"},
                    {"value": "rights_not_exercised", "label": "记录不参与本次配股"},
                    {"value": "tax_assess", "label": "评估股息红利税额"},
                    {"value": "tax_recognize", "label": "确认应缴股息红利税"},
                    {"value": "tax_collect", "label": "模拟扣缴股息红利税"},
                ],
            },
            {
                "key": "correction_mode",
                "label": "办理方式",
                "binding": "body",
                "input_type": "select",
                "value_type": "string",
                "required": False,
                "default": "ordinary",
                "options": [
                    {"value": "ordinary", "label": "首次办理或继续下一阶段"},
                    {"value": "correct_existing", "label": "按新披露整批更正已办事项"},
                ],
            },
            {
                "key": "settlement_date",
                "label": "本次结算日期（仅在事件要求时填写）",
                "binding": "body",
                "input_type": "date",
                "value_type": "date",
                "required": False,
            },
        ],
    ),
    _base_action(
        key=CORPORATE_ACTION_WORKFLOW_CONFIRM_ACTION_KEY,
        label="明确确认本次办理",
        endpoint=f"{_ENDPOINT}confirm/",
        method="POST",
        intent="confirm_owner_corporate_action_workflow",
        risk="write",
        effect="update",
        description=(
            "再次核对事件、账户、当前来源和阻断后明确提交这一项模拟操作；"
            "确认不会扩大授权范围或提交真实交易。"
        ),
        sequence=842,
        fields=[
            _hidden_continuation_field("account_id", "本人账户编号"),
            _hidden_continuation_field(
                "continuation_token",
                "本次确认凭证",
                maximum=65536,
            ),
            _confirmation_field("确认提交本次单项模拟操作"),
        ],
        confirmation_required=True,
    ),
    _base_action(
        key=CORPORATE_ACTION_WORKFLOW_REFRESH_ACTION_KEY,
        label="刷新本人账户与官方资料",
        endpoint=f"{_ENDPOINT}refresh/",
        method="POST",
        intent="refresh_owner_corporate_action_workflow",
        risk="write",
        effect="update",
        description=(
            "明确确认后重新核对本人模拟账户资料，再刷新相关证券的官方公告窗口。"
            "结果分别说明账户资料与官方资料是否完整刷新；不改资金或持仓，不创建授权。"
        ),
        sequence=843,
        fields=[_account_id_field(), _confirmation_field("确认刷新账户与官方资料")],
        confirmation_required=True,
    ),
    _base_action(
        key=CORPORATE_ACTION_WORKFLOW_EVENTS_ACTION_KEY,
        label="查看公司行为事件列表",
        endpoint=f"{_ENDPOINT}events/",
        method="GET",
        intent="read_owner_corporate_action_events",
        risk="read",
        effect="read",
        description="只读查看本人模拟账户对应的当前来源事件，并可从事件行准备单项操作。",
        sequence=844,
        fields=[_account_id_field()],
        view_type="datagrid",
        view_model={
            "kind": "datagrid",
            "rows_path": "events",
            "columns": [
                {"key": "event_id", "label": "事件编号"},
                {"key": "asset_code", "label": "标的"},
                {"key": "title", "label": "事件"},
                {"key": "event_type", "label": "类型"},
                {"key": "announced_on", "label": "公告日"},
                {"key": "record_date", "label": "登记日"},
                {"key": "effective_date", "label": "生效日"},
                {"key": "source_observed_at", "label": "来源时间"},
                {"key": "status", "label": "状态"},
                {"key": "blocking_reason", "label": "阻断原因"},
            ],
        },
        task_tier="support",
    ),
    _base_action(
        key=CORPORATE_ACTION_WORKFLOW_AUDIT_RECEIPTS_ACTION_KEY,
        label="查看公司行为审计回执",
        endpoint=_ENDPOINT,
        method="GET",
        intent="read_owner_corporate_action_audit_receipts",
        risk="read",
        effect="read",
        description="只读查看本人模拟账户的公司行为模拟账本与关联审计回执。",
        sequence=845,
        fields=[_account_id_field()],
        view_type="datagrid",
        view_model={
            "kind": "datagrid",
            "rows_path": "audit_receipts",
            "columns": [
                {"key": "receipt_id", "label": "回执编号"},
                {"key": "recorded_at", "label": "记录时间"},
                {"key": "asset_code", "label": "标的"},
                {"key": "stage_label", "label": "操作阶段"},
                {"key": "cash_delta", "label": "现金变化"},
                {"key": "share_delta", "label": "股份变化"},
                {"key": "summary", "label": "说明"},
            ],
        },
        task_tier="support",
    ),
    *_consent_actions_on_workflow_screen(),
)

_prepare_action = next(
    action
    for action in RUNTIME_CORPORATE_ACTION_WORKFLOW_ACTIONS
    if action["key"] == CORPORATE_ACTION_WORKFLOW_PREPARE_ACTION_KEY
)
_prepare_action["result_continuation"] = {
    "target_action_key": CORPORATE_ACTION_WORKFLOW_CONFIRM_ACTION_KEY,
    "field_map": {
        "account_id": "account_id",
        "continuation_token": "continuation_token",
    },
}
_prepare_action["result_panel_key"] = "corporate-action-workflow-result"

__all__: tuple[str, ...] = (
    "CORPORATE_ACTION_WORKFLOW_AUDIT_RECEIPTS_ACTION_KEY",
    "CORPORATE_ACTION_WORKFLOW_CONFIRM_ACTION_KEY",
    "CORPORATE_ACTION_WORKFLOW_EVENTS_ACTION_KEY",
    "CORPORATE_ACTION_WORKFLOW_PREPARE_ACTION_KEY",
    "CORPORATE_ACTION_WORKFLOW_READ_ACTION_KEY",
    "CORPORATE_ACTION_WORKFLOW_REFRESH_ACTION_KEY",
    "RUNTIME_CORPORATE_ACTION_WORKFLOW_ACTIONS",
)
