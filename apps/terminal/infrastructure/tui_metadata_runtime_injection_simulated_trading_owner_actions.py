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


def _portfolio_risk_account_id_field() -> dict[str, Any]:
    """Bind an explicitly selected owner account to the risk task path."""

    return {
        "key": "account_id",
        "label": "模拟账户编号",
        "binding": "path",
        "input_type": "number",
        "value_type": "integer",
        "required": True,
        "presentation_semantic": "primary_selector",
        "min": 1,
    }


def build_owner_risk_actions() -> tuple[dict[str, Any], ...]:
    """Build the owner's report, pressure run and existing stop-loss actions in order."""

    return (
        build_portfolio_risk_report_action(),
        build_portfolio_pressure_run_action(),
        build_account_stop_loss_check_action(),
    )


def build_portfolio_risk_report_action() -> dict[str, Any]:
    """Build an owner-scoped, read-only account risk report action."""

    return {
        "key": "simulated-trading.portfolio-risk-report",
        "label": "读取已授权模拟账户风险",
        "endpoint": "/api/simulated-trading/accounts/<int:account_id>/portfolio-risk/",
        "method": "GET",
        "intent": "read_owner_portfolio_risk_constraints",
        "risk": "read",
        "audience": "authenticated",
        "effect": "read",
        "screen_key": "execution.accounts",
        "module_key": "daily-decisions",
        "view_type": "detail",
        "description": (
            "只读展示有权查看的模拟账户风险约束、版本、来源时点、覆盖和未知原因；"
            "不会运行情景或改变账户。"
        ),
        "source": "approved:runtime-simulated-trading",
        "task_group": "06 模拟交易记录",
        "sequence": 788,
        "task_tier": "support",
        "raw_debug": False,
        "fields": [_portfolio_risk_account_id_field()],
        "view_model": {"kind": "detail"},
    }


def build_portfolio_pressure_run_action() -> dict[str, Any]:
    """Build a separately confirmed simulation-only pressure evidence action."""

    return {
        "key": "simulated-trading.portfolio-pressure-run",
        "label": "明确运行模拟退出压力核对",
        "endpoint": (
            "/api/simulated-trading/accounts/<int:account_id>/portfolio-risk/pressure-run/"
        ),
        "method": "POST",
        "intent": "run_owner_portfolio_exit_pressure",
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
            "对本人模拟账户明确运行一个已审批压力情景，只保存情景核对证据；"
            "不下单、不撮合、不释放预留或改写账户。"
        ),
        "source": "approved:runtime-simulated-trading",
        "task_group": "06 模拟交易记录",
        "sequence": 789,
        "task_tier": "support",
        "raw_debug": False,
        "fields": [
            _portfolio_risk_account_id_field(),
            {
                "key": "scenario_version_id",
                "label": "已审批压力情景",
                "binding": "body",
                "input_type": "select",
                "value_type": "string",
                "required": True,
                "presentation_semantic": "primary_selector",
                "options": [],
                "options_lookup": "approved_portfolio_pressure_scenarios",
                "placeholder": "先选择模拟账户，再选择情景名称和业务版本",
            },
            confirmed_body_field(),
        ],
        "view_model": {"kind": "detail"},
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
