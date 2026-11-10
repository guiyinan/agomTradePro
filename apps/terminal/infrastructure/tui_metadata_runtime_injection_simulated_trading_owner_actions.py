"""Account action metadata for simulated-trading tasks."""

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


def build_holding_reference_actions(
    account_id_field: dict[str, Any],
) -> tuple[dict[str, Any], ...]:
    """Build the positions action and its scoped disclosure support action."""

    return (
        {
            "key": "simulated-trading.positions",
            "label": "查看账户持仓",
            "endpoint": "/api/simulated-trading/accounts/<int:account_id>/positions/",
            "method": "GET",
            "intent": "read_owned_account_positions",
            "risk": "read",
            "audience": "authenticated",
            "screen_key": "execution.accounts",
            "module_key": "daily-decisions",
            "view_type": "datagrid",
            "description": "查看本人账户的持仓、可用数量、成本、市值和未实现盈亏。",
            "source": "approved:runtime-simulated-trading",
            "task_group": "06 模拟交易记录",
            "sequence": 720,
            "task_tier": "operation",
            "fields": [account_id_field],
            "view_model": {
                "kind": "datagrid",
                "rows_path": "positions",
                "columns": [
                    {"key": "asset_code", "label": "资产代码"},
                    {"key": "asset_name", "label": "资产名称"},
                    {"key": "quantity", "label": "数量"},
                    {"key": "avg_cost", "label": "成本价"},
                    {"key": "current_price", "label": "现价"},
                    {"key": "market_value", "label": "市值"},
                    {"key": "unrealized_pnl", "label": "未实现盈亏"},
                    {"key": "unrealized_pnl_pct", "label": "盈亏率"},
                ],
            },
        },
        {
            "key": "simulated-trading.holding-disclosures",
            "label": "查看持仓证券财报披露资料",
            "endpoint": ("/api/simulated-trading/accounts/<int:account_id>/holding-disclosures/"),
            "method": "GET",
            "intent": "read_owned_holding_financial_disclosures",
            "risk": "read",
            "audience": "authenticated",
            "effect": "read",
            "screen_key": "execution.accounts",
            "module_key": "daily-decisions",
            "view_type": "detail",
            "description": (
                "只读查看本人有权查看的模拟账户及其持仓证券已发布的财务指标、数据来源与各自来源时点。"
                "资料范围不完整，仅供查阅，不用于投资决策或交易执行；不会推断公司行为生效或到账日，"
                "不会计算、分配或入账现金、股份及税费。"
            ),
            "source": "approved:runtime-simulated-trading",
            "task_group": "06 模拟交易记录",
            "sequence": 725,
            "task_tier": "support",
            "raw_debug": False,
            "session_auth_required": True,
            "fields": [
                {
                    "key": "account_id",
                    "label": "模拟账户 ID",
                    "binding": "path",
                    "input_type": "number",
                    "value_type": "integer",
                    "required": True,
                    "presentation_semantic": "primary_selector",
                    "min": 1,
                },
                {
                    "key": "asset_code",
                    "label": "持仓证券代码",
                    "binding": "query",
                    "input_type": "text",
                    "value_type": "string",
                    "required": True,
                    "placeholder": "请输入该账户当前持仓中的证券代码，例如 600000.SH",
                },
            ],
            "view_model": {"kind": "detail"},
        },
    )
