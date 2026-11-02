"""Owner-confirmed action metadata for simulated-trading tasks."""

from __future__ import annotations

from typing import Any

_LOCAL_MARKET_PURPOSE = "local_simulation_only"
_CLOSE_MARKET_PURPOSE = "close_snapshot_simulation"


def confirmed_body_field() -> dict[str, Any]:
    """Bind the owner's required confirmation flag without an editable field."""

    return {
        "key": "confirmed",
        "label": "已确认操作",
        "binding": "body",
        "input_type": "hidden",
        "value_type": "boolean",
        "required": True,
        "default": True,
    }


def market_purpose_field() -> dict[str, Any]:
    """Require an explicit simulation purpose while retaining the legacy default."""

    return {
        "key": "market_purpose",
        "label": "模拟行情用途",
        "binding": "body",
        "input_type": "select",
        "value_type": "string",
        "required": True,
        "default": _LOCAL_MARKET_PURPOSE,
        "options": [
            {"value": _LOCAL_MARKET_PURPOSE, "label": "盘中模拟（仅限本地）"},
            {
                "value": _CLOSE_MARKET_PURPOSE,
                "label": "收盘快照模拟（非官方收盘价）",
            },
        ],
    }


def _account_stop_loss_scope_field() -> dict[str, Any]:
    """Bind the server-owned stop-loss-only execution branch."""

    return {
        "key": "execution_scope",
        "label": "执行范围",
        "binding": "body",
        "input_type": "hidden",
        "value_type": "string",
        "required": True,
        "default": "account_stop_loss_only",
    }


def build_account_stop_loss_check_action() -> dict[str, Any]:
    """Build the explicitly confirmed account stop-loss check action."""

    return {
        "key": "simulated-trading.account-stop-loss-check",
        "label": "运行本次模拟止损检查",
        "endpoint": "/api/simulated-trading/auto-trading/run/",
        "method": "POST",
        "intent": "run_owner_account_stop_loss_check",
        "risk": "write",
        "audience": "authenticated",
        "effect": "execute",
        "confirmation_required": True,
        "audit_required": True,
        "session_auth_required": True,
        "screen_key": "execution.accounts",
        "module_key": "daily-decisions",
        "view_type": "detail",
        "description": (
            "仅对明确选择的本人模拟账户执行本次止损检查；不会开启自动交易，"
            "不会运行策略或买入。收盘快照仅供本地模拟。"
        ),
        "source": "approved:runtime-simulated-trading",
        "task_group": "06 模拟交易记录",
        "sequence": 790,
        "task_tier": "support",
        "raw_debug": False,
        "fields": [
            {
                "key": "trade_date",
                "label": "交易日期",
                "binding": "body",
                "input_type": "date",
                "value_type": "date",
                "required": True,
            },
            {
                "key": "account_ids",
                "label": "本人模拟账户编号（JSON 数组）",
                "binding": "body",
                "input_type": "textarea",
                "value_type": "list",
                "required": True,
                "placeholder": "仅填写本人模拟账户编号，例如 [123]；不会默认选择其他账户",
            },
            market_purpose_field(),
            _account_stop_loss_scope_field(),
            confirmed_body_field(),
        ],
        "view_model": {"kind": "detail"},
    }
