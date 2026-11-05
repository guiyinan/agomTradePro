"""Runtime metadata for the single owner-facing simulated rebalance-plan task."""

from __future__ import annotations

from typing import Any

_SCREEN = "task.rebalance-plan"
_MODULE = "daily-decisions"
_SOURCE = "approved:ash08-owner-rebalance-plan-journey"


def _account_selector() -> dict[str, Any]:
    """Carry a server-scoped account selected from the owner account list."""

    return {
        "key": "account_id",
        "label": "选择本人模拟账户",
        "binding": "path",
        "input_type": "hidden",
        "value_type": "integer",
        "required": True,
        "default": "",
        "presentation_semantic": "identifier",
    }


def _revision_pin_fields() -> list[dict[str, Any]]:
    """Carry exact revision pins as hidden action parameters, never visible copy."""

    return [
        {
            "key": "plan_version",
            "label": "计划版本",
            "binding": "query",
            "input_type": "hidden",
            "value_type": "integer",
            "required": True,
            "presentation_semantic": "identifier",
        },
        {
            "key": "revision_hash",
            "label": "计划版本校验",
            "binding": "query",
            "input_type": "hidden",
            "value_type": "string",
            "required": True,
            "presentation_semantic": "api_token",
        },
    ]


def _order_preview_fields() -> list[dict[str, Any]]:
    """Carry exact order pins and collect only the user's quantity/limit intent."""

    return [
        _account_selector(),
        {
            "key": "plan_id",
            "label": "计划编号",
            "binding": "path",
            "input_type": "hidden",
            "value_type": "string",
            "required": True,
            "presentation_semantic": "api_token",
        },
        {
            "key": "order_ordinal",
            "label": "计划订单序号",
            "binding": "path",
            "input_type": "hidden",
            "value_type": "integer",
            "required": True,
            "presentation_semantic": "identifier",
        },
        {
            "key": "plan_version",
            "label": "计划版本",
            "binding": "body",
            "input_type": "hidden",
            "value_type": "integer",
            "required": True,
            "presentation_semantic": "identifier",
        },
        {
            "key": "revision_hash",
            "label": "计划版本校验",
            "binding": "body",
            "input_type": "hidden",
            "value_type": "string",
            "required": True,
            "presentation_semantic": "api_token",
        },
        {
            "key": "order_content_hash",
            "label": "计划订单校验",
            "binding": "body",
            "input_type": "hidden",
            "value_type": "string",
            "required": True,
            "presentation_semantic": "api_token",
        },
        {
            "key": "plan_order_binding_id",
            "label": "订单绑定校验",
            "binding": "body",
            "input_type": "hidden",
            "value_type": "string",
            "required": True,
            "presentation_semantic": "api_token",
        },
        {
            "key": "quantity",
            "label": "本次数量（按计划单位；须为正整数且不超过当前可办理余量）",
            "binding": "body",
            "input_type": "text",
            "value_type": "string",
            "required": True,
            "max": 32,
            "placeholder": "请输入本次要预览的数量",
        },
        {
            "key": "limit_price",
            "label": "本次限价（金额单位按计划显示）",
            "binding": "body",
            "input_type": "text",
            "value_type": "string",
            "required": True,
            "max": 32,
            "placeholder": "请输入限价；计划参考价不会自动填入",
        },
        {
            "key": "reason",
            "label": "本次说明（可选）",
            "binding": "body",
            "input_type": "text",
            "value_type": "string",
            "required": False,
            "max": 200,
        },
    ]


def _order_grid_action() -> dict[str, Any]:
    """Read one exact saved revision as a grid of independently previewable rows."""

    return {
        "key": "rebalance-plan.orders",
        "label": "查看计划订单与单笔办理余量",
        "endpoint": (
            "/api/simulated-trading/accounts/<int:account_id>/rebalance-plans/" "<str:plan_id>/"
        ),
        "method": "GET",
        "intent": "read_exact_rebalance_plan_orders_and_progress",
        "risk": "read",
        "audience": "authenticated",
        "effect": "read",
        "screen_key": _SCREEN,
        "module_key": _MODULE,
        "view_type": "datagrid",
        "description": (
            "逐行核对批准目标、真实成交、有效预留和未预留余量。已预留订单的详情、撮合、回执和撤销"
            "仍在既有 TUI“本人模拟下单”任务中逐单处理，不由计划自动执行。"
        ),
        "source": _SOURCE,
        "task_group": "01 计划与对账",
        "sequence": 25,
        "task_tier": "support",
        "session_auth_required": True,
        "raw_debug": False,
        "fields": [
            _account_selector(),
            {
                "key": "plan_id",
                "label": "计划编号",
                "binding": "path",
                "input_type": "hidden",
                "value_type": "string",
                "required": True,
                "presentation_semantic": "api_token",
            },
            *_revision_pin_fields(),
        ],
        "view_model": {
            "kind": "datagrid",
            "columns": [
                {"key": "order_label", "label": "计划订单"},
                {"key": "approved_label", "label": "批准数量"},
                {"key": "filled_label", "label": "已核实成交"},
                {"key": "in_flight_label", "label": "有效预留"},
                {"key": "released_label", "label": "已释放"},
                {"key": "remaining_label", "label": "尚未预留余量"},
                {"key": "price_label", "label": "计划参考价（非限价）"},
                {"key": "limit_label", "label": "批准限价"},
                {"key": "capability_label", "label": "当前单笔预览资格"},
            ],
        },
        "result_panel_key": "rebalance-plan-order-grid",
    }


def _order_handoff_field(key: str, label: str) -> dict[str, Any]:
    """Bind a private owner-order locator without presenting it as user input."""

    return {
        "key": key,
        "label": label,
        "binding": "body",
        "input_type": "hidden",
        "value_type": "string",
        "required": True,
        "presentation_semantic": "api_token",
    }


def _owner_order_confirm_action() -> dict[str, Any]:
    """Expose the existing confirmed owner-order API on this screen for handoff."""

    return {
        "key": "rebalance-plan.order-confirm",
        "label": "确认单笔模拟订单预留",
        "endpoint": (
            "/api/simulated-trading/accounts/<int:account_id>/orders/"
            "by-key/<str:order_key>/confirm/"
        ),
        "method": "POST",
        "intent": "confirm_owner_local_simulated_order_reservation",
        "risk": "write",
        "audience": "authenticated",
        "effect": "create",
        "confirmation_required": True,
        "audit_required": True,
        "session_auth_required": True,
        "screen_key": _SCREEN,
        "module_key": _MODULE,
        "view_type": "detail",
        "description": "只确认原单笔模拟预览对应的本地预留；不会提交券商订单。",
        "source": _SOURCE,
        "task_group": "02 计划操作",
        "sequence": 56,
        "task_tier": "operation",
        "raw_debug": False,
        "fields": [
            _order_handoff_field("account_id", "模拟账户"),
            _order_handoff_field("order_key", "原模拟订单"),
            _order_handoff_field("preview_token", "原预览凭证"),
            {
                "key": "confirmed",
                "label": "明确确认模拟预留",
                "binding": "body",
                "input_type": "hidden",
                "value_type": "boolean",
                "required": True,
                "default": True,
            },
        ],
        "view_model": {"kind": "detail"},
    }


def _owner_order_readback_action() -> dict[str, Any]:
    """Expose the existing read-only order lookup on this screen for recovery."""

    return {
        "key": "rebalance-plan.order-by-key",
        "label": "核对原单笔模拟订单",
        "endpoint": "/api/simulated-trading/accounts/<int:account_id>/orders/by-key/<str:order_key>/",
        "method": "GET",
        "intent": "read_owned_original_simulated_order",
        "risk": "read",
        "audience": "authenticated",
        "effect": "read",
        "screen_key": _SCREEN,
        "module_key": _MODULE,
        "view_type": "detail",
        "description": "只读取同一原单的已保存预留状态，不重新读行情或创建订单。",
        "source": _SOURCE,
        "task_group": "01 计划与对账",
        "sequence": 26,
        "task_tier": "support",
        "session_auth_required": True,
        "raw_debug": False,
        "fields": [
            _order_handoff_field("account_id", "模拟账户"),
            _order_handoff_field("order_key", "原模拟订单"),
        ],
        "view_model": {"kind": "detail"},
    }


def _plan_read_action() -> dict[str, Any]:
    """Open one exact saved revision selected from the plan list."""

    return {
        "key": "rebalance-plan.read",
        "label": "查看计划详情",
        "endpoint": (
            "/api/simulated-trading/accounts/<int:account_id>/rebalance-plans/" "<str:plan_id>/"
        ),
        "method": "GET",
        "intent": "read_exact_owned_or_delegated_rebalance_plan",
        "risk": "read",
        "audience": "authenticated",
        "effect": "read",
        "screen_key": _SCREEN,
        "module_key": _MODULE,
        "view_type": "detail",
        "description": "读取所选计划的原批准目标、来源时点、限制和当前成交进度。",
        "source": _SOURCE,
        "task_group": "01 计划与对账",
        "sequence": 20,
        "task_tier": "support",
        "session_auth_required": True,
        "raw_debug": False,
        "fields": [
            _account_selector(),
            {
                "key": "plan_id",
                "label": "计划编号",
                "binding": "path",
                "input_type": "hidden",
                "value_type": "string",
                "required": True,
                "presentation_semantic": "api_token",
            },
            *_revision_pin_fields(),
        ],
        "view_model": {"kind": "detail"},
        "result_panel_key": "rebalance-plan-detail",
    }


def _reconciliation_action() -> dict[str, Any]:
    """Read actual fills, active reservations, and unresolved remainder."""

    return {
        "key": "rebalance-plan.reconcile",
        "label": "刷新成交与余量",
        "endpoint": (
            "/api/simulated-trading/accounts/<int:account_id>/rebalance-plans/"
            "<str:plan_id>/reconciliation/"
        ),
        "method": "GET",
        "intent": "read_exact_rebalance_plan_reconciliation",
        "risk": "read",
        "audience": "authenticated",
        "effect": "read",
        "screen_key": _SCREEN,
        "module_key": _MODULE,
        "view_type": "detail",
        "description": "刷新真实成交、仍有效预留、已释放数量和当前可处理余量。",
        "source": _SOURCE,
        "task_group": "01 计划与对账",
        "sequence": 30,
        "task_tier": "support",
        "session_auth_required": True,
        "raw_debug": False,
        "fields": [
            _account_selector(),
            {
                "key": "plan_id",
                "label": "计划编号",
                "binding": "path",
                "input_type": "hidden",
                "value_type": "string",
                "required": True,
                "presentation_semantic": "api_token",
            },
            *_revision_pin_fields(),
        ],
        "view_model": {"kind": "detail"},
        "result_panel_key": "rebalance-plan-reconciliation",
    }


def _account_list_action() -> dict[str, Any]:
    """Open only the signed-in user's simulated accounts as the journey entry."""

    return {
        "key": "rebalance-plan.accounts",
        "label": "选择模拟账户",
        "endpoint": "/api/simulated-trading/accounts/?active_only=true&account_type=simulated",
        "method": "GET",
        "intent": "list_owned_active_simulated_accounts_for_rebalance_journey",
        "risk": "read",
        "audience": "authenticated",
        "effect": "read",
        "screen_key": _SCREEN,
        "module_key": _MODULE,
        "view_type": "datagrid",
        "description": "只列出本人活跃的模拟账户；从账户行进入同一账户的计划与资金摘要。",
        "source": _SOURCE,
        "task_group": "00 选择账户",
        "sequence": 5,
        "task_tier": "support",
        "raw_debug": False,
        "fields": [],
        "view_model": {
            "kind": "datagrid",
            "rows_path": "accounts",
            "columns": [
                {"key": "account_name", "label": "模拟账户"},
                {"key": "current_cash", "label": "账面现金（单位待核对）"},
                {"key": "current_market_value", "label": "持仓估值（时点待核对）"},
                {"key": "cash_reconciliation_status", "label": "现金核对"},
            ],
        },
    }


def _account_detail_action() -> dict[str, Any]:
    """Read the existing owner account summary without claiming price freshness."""

    return {
        "key": "rebalance-plan.account-detail",
        "label": "查看选定账户摘要",
        "endpoint": "/api/simulated-trading/accounts/<int:account_id>/",
        "method": "GET",
        "intent": "read_owned_simulated_account_summary_for_rebalance",
        "risk": "read",
        "audience": "authenticated",
        "effect": "read",
        "screen_key": _SCREEN,
        "module_key": _MODULE,
        "view_type": "detail",
        "description": "查看账面现金和持仓估值；单位或估值时点缺失时明确保留未知。",
        "source": _SOURCE,
        "task_group": "00 选择账户",
        "sequence": 6,
        "task_tier": "support",
        "raw_debug": False,
        "fields": [_account_selector()],
        "view_model": {"kind": "detail"},
        "result_panel_key": "rebalance-plan-account-detail",
    }


def _positions_action() -> dict[str, Any]:
    """Read the existing owned-account holdings endpoint only on user request."""

    return {
        "key": "rebalance-plan.positions",
        "label": "按需查看当前持仓",
        "endpoint": "/api/simulated-trading/accounts/<int:account_id>/positions/",
        "method": "GET",
        "intent": "read_owned_simulated_positions_with_existing_valuation_flags",
        "risk": "read",
        "audience": "authenticated",
        "effect": "read",
        "screen_key": _SCREEN,
        "module_key": _MODULE,
        "view_type": "datagrid",
        "description": "按需读取当前账本持仓；估值状态和缺失时点按原结果展示。",
        "source": _SOURCE,
        "task_group": "03 账户事实",
        "sequence": 70,
        "task_tier": "support",
        "raw_debug": False,
        "fields": [_account_selector()],
        "view_model": {
            "kind": "datagrid",
            "rows_path": "positions",
            "columns": [
                {"key": "asset_code", "label": "证券"},
                {"key": "quantity", "label": "账面数量"},
                {"key": "available_quantity", "label": "可用数量"},
                {"key": "current_price", "label": "参考价"},
                {"key": "valuation_status", "label": "估值状态"},
                {"key": "last_update_date", "label": "记录日期"},
            ],
        },
    }


def _risk_action() -> dict[str, Any]:
    """Read the existing owner-scoped risk report only when requested."""

    return {
        "key": "rebalance-plan.account-risk",
        "label": "按需查看风险限制与来源时点",
        "endpoint": "/api/simulated-trading/accounts/<int:account_id>/portfolio-risk/",
        "method": "GET",
        "intent": "read_owner_scoped_portfolio_risk_for_rebalance_context",
        "risk": "read",
        "audience": "authenticated",
        "effect": "read",
        "screen_key": _SCREEN,
        "module_key": _MODULE,
        "view_type": "detail",
        "description": "按需查看当前风险结论、来源时点和模拟限制；该报告不提供订单执行授权。",
        "source": _SOURCE,
        "task_group": "03 账户事实",
        "sequence": 71,
        "task_tier": "support",
        "session_auth_required": True,
        "raw_debug": False,
        "fields": [_account_selector()],
        "view_model": {"kind": "detail"},
    }


RUNTIME_REBALANCE_PLAN_SCREENS: tuple[dict[str, Any], ...] = (
    {
        "key": _SCREEN,
        "dashboard_panels": [
            {
                "key": "rebalance-plan-accounts",
                "title": "选择本人模拟账户",
                "kind": "datagrid",
                "action_key": "rebalance-plan.accounts",
                "hidden_columns": ["account_id"],
                "columns": [
                    {"key": "account_name", "label": "模拟账户"},
                    {"key": "current_cash", "label": "账面现金（单位待核对）"},
                    {"key": "current_market_value", "label": "持仓估值（时点待核对）"},
                    {"key": "cash_reconciliation_status", "label": "现金核对"},
                ],
                "row_actions": [
                    {
                        "action_key": "rebalance-plan.account-detail",
                        "label_template": "查看 {account_name} 资金与规则说明",
                        "param_map": {"account_id": "account_id"},
                        "result_panel_key": "rebalance-plan-account-detail",
                    },
                    {
                        "action_key": "rebalance-plan.list",
                        "label_template": "打开 {account_name} 的计划",
                        "param_map": {"account_id": "account_id"},
                        "result_panel_key": "rebalance-plan-list",
                    },
                    {
                        "action_key": "rebalance-plan.create",
                        "label_template": "为 {account_name} 生成调仓计划",
                        "param_map": {"account_id": "account_id"},
                        "result_panel_key": "rebalance-plan-detail",
                    },
                ],
                "empty_message": "没有可访问的活跃模拟账户。",
                "user_priority": "p0",
                "presentation_semantic": "primary_list",
            },
            {
                "key": "rebalance-plan-list",
                "title": "已保存的调仓计划",
                "kind": "datagrid",
                "action_key": "rebalance-plan.list",
                "hidden_columns": ["account_id", "plan_id", "plan_version", "revision_hash_id"],
                "columns": [
                    {"key": "version_label", "label": "计划版本"},
                    {"key": "recorded_label", "label": "生成时间"},
                    {"key": "status_label", "label": "计划状态"},
                    {"key": "orders_label", "label": "订单数量"},
                    {"key": "progress_label", "label": "成交与余量"},
                    {"key": "validity_label", "label": "有效期限"},
                ],
                "row_actions": [
                    {
                        "action_key": "rebalance-plan.read",
                        "label_template": "查看 {version_label} 计划",
                        "param_map": {
                            "account_id": "account_id",
                            "plan_id": "plan_id",
                            "plan_version": "plan_version",
                            "revision_hash": "revision_hash_id",
                        },
                        "result_panel_key": "rebalance-plan-detail",
                    },
                    {
                        "action_key": "rebalance-plan.orders",
                        "label_template": "查看 {version_label} 的计划订单",
                        "param_map": {
                            "account_id": "account_id",
                            "plan_id": "plan_id",
                            "plan_version": "plan_version",
                            "revision_hash": "revision_hash_id",
                        },
                        "result_panel_key": "rebalance-plan-order-grid",
                    },
                    {
                        "action_key": "rebalance-plan.reconcile",
                        "label_template": "刷新 {version_label} 成交与余量",
                        "param_map": {
                            "account_id": "account_id",
                            "plan_id": "plan_id",
                            "plan_version": "plan_version",
                            "revision_hash": "revision_hash_id",
                        },
                        "result_panel_key": "rebalance-plan-reconciliation",
                    },
                    {
                        "action_key": "rebalance-plan.review",
                        "label_template": "提交 {version_label} 的人工复核申请",
                        "param_map": {
                            "account_id": "account_id",
                            "plan_id": "plan_id",
                            "plan_version": "plan_version",
                            "revision_hash": "revision_hash_id",
                        },
                        "result_panel_key": "rebalance-plan-detail",
                        "refresh_panel_key": "rebalance-plan-list",
                    },
                    {
                        "action_key": "rebalance-plan.successor",
                        "label_template": "按新事实重新生成 {version_label} 的后继计划",
                        "param_map": {
                            "account_id": "account_id",
                            "plan_id": "plan_id",
                            "plan_version": "plan_version",
                            "revision_hash": "revision_hash_id",
                        },
                        "result_panel_key": "rebalance-plan-detail",
                        "refresh_panel_key": "rebalance-plan-list",
                    },
                ],
                "empty_message": "当前账户还没有已保存的调仓计划。",
                "user_priority": "p1",
                "presentation_semantic": "supporting_list",
            },
            {
                "key": "rebalance-plan-order-grid",
                "title": "所选版本的订单与实际进度",
                "kind": "datagrid",
                "action_key": "rebalance-plan.orders",
                "hidden_columns": [
                    "account_id",
                    "plan_id",
                    "plan_version",
                    "revision_hash_id",
                    "order_ordinal",
                    "order_content_hash",
                    "plan_order_binding_id",
                ],
                "columns": [
                    {"key": "order_label", "label": "计划订单"},
                    {"key": "approved_label", "label": "批准数量"},
                    {"key": "filled_label", "label": "已核实成交"},
                    {"key": "in_flight_label", "label": "有效预留"},
                    {"key": "released_label", "label": "已释放"},
                    {"key": "remaining_label", "label": "尚未预留余量"},
                    {"key": "price_label", "label": "计划参考价（非限价）"},
                    {"key": "limit_label", "label": "批准限价"},
                    {"key": "capability_label", "label": "当前单笔预览资格"},
                ],
                "row_actions": [
                    {
                        "action_key": "rebalance-plan.preview-order",
                        "label_template": "重新核对 {order_label} 的本次数量和限价",
                        "visible_when": {
                            "field": "capability_label",
                            "values": ["可进入当前单笔预览"],
                        },
                        "param_map": {
                            "account_id": "account_id",
                            "plan_id": "plan_id",
                            "order_ordinal": "order_ordinal",
                            "plan_version": "plan_version",
                            "revision_hash": "revision_hash_id",
                            "order_content_hash": "order_content_hash",
                            "plan_order_binding_id": "plan_order_binding_id",
                        },
                        "result_panel_key": "rebalance-plan-order-preview",
                    }
                ],
                "empty_message": "该计划没有可展示的订单行。",
                "user_priority": "p1",
                "presentation_semantic": "supporting_list",
            },
            {
                "key": "rebalance-plan-account-detail",
                "title": "账户资金与规则",
                "kind": "detail",
                "user_priority": "p2",
                "presentation_semantic": "supporting_detail",
            },
            {
                "key": "rebalance-plan-detail",
                "title": "计划详情与复核结果",
                "kind": "detail",
                "user_priority": "p2",
                "presentation_semantic": "supporting_detail",
            },
            {
                "key": "rebalance-plan-reconciliation",
                "title": "实际成交与余量对账",
                "kind": "detail",
                "user_priority": "p2",
                "presentation_semantic": "supporting_detail",
            },
            {
                "key": "rebalance-plan-order-preview",
                "title": "单笔模拟订单预览",
                "kind": "detail",
                "user_priority": "p2",
                "presentation_semantic": "supporting_detail",
            },
        ],
    },
)

RUNTIME_REBALANCE_PLAN_ACTIONS: tuple[dict[str, Any], ...] = (
    _account_list_action(),
    _account_detail_action(),
    _positions_action(),
    _risk_action(),
    {
        "key": "rebalance-plan.list",
        "label": "查看计划和当前进度",
        "endpoint": "/api/simulated-trading/accounts/<int:account_id>/rebalance-plans/",
        "method": "GET",
        "intent": "list_owned_or_delegated_rebalance_plan_revisions",
        "risk": "read",
        "audience": "authenticated",
        "effect": "read",
        "screen_key": _SCREEN,
        "module_key": _MODULE,
        "view_type": "datagrid",
        "description": "读取本人或已授权查看的模拟调仓计划及实际进度；不创建或提交订单。",
        "source": _SOURCE,
        "task_group": "01 计划与对账",
        "sequence": 10,
        "task_tier": "primary",
        "session_auth_required": True,
        "raw_debug": False,
        "fields": [_account_selector()],
        "view_model": {
            "kind": "datagrid",
            "rows_path": "plans",
            "total_path": "total",
            "columns": [
                {"key": "version_label", "label": "计划版本"},
                {"key": "recorded_label", "label": "生成时间"},
                {"key": "status_label", "label": "计划状态"},
                {"key": "orders_label", "label": "订单数量"},
                {"key": "progress_label", "label": "成交与余量"},
                {"key": "validity_label", "label": "有效期限"},
            ],
            "empty_message": "当前账户还没有已保存的调仓计划。",
        },
    },
    {
        "key": "rebalance-plan.create",
        "label": "生成调仓计划",
        "endpoint": "/api/simulated-trading/accounts/<int:account_id>/rebalance-plans/",
        "method": "POST",
        "intent": "create_persisted_simulated_rebalance_plan_revision",
        "risk": "write",
        "audience": "authenticated",
        "effect": "create",
        "screen_key": _SCREEN,
        "module_key": _MODULE,
        "view_type": "detail",
        "description": "提交目标意图后，由服务器按当前账户、来源、风险和费用规则生成并保存计划版本。",
        "source": _SOURCE,
        "task_group": "02 计划操作",
        "sequence": 40,
        "task_tier": "operation",
        "confirmation_required": True,
        "audit_required": True,
        "session_auth_required": True,
        "raw_debug": False,
        "fields": [
            _account_selector(),
            {
                "key": "target_weights",
                "label": "证券目标（每行：代码,目标百分比）",
                "binding": "body",
                "input_type": "textarea",
                "value_type": "string",
                "required": True,
                "max": 2048,
                "placeholder": "例如：600000.SH,60；留空不得用于创建。",
            },
            {
                "key": "reference_price_basis",
                "label": "计划参考价格",
                "binding": "body",
                "input_type": "select",
                "value_type": "string",
                "required": True,
                "options": [
                    {"value": "market", "label": "当前合格市场参考"},
                    {"value": "published_close", "label": "已发布收盘参考"},
                ],
            },
        ],
        "view_model": {"kind": "detail"},
        "result_panel_key": "rebalance-plan-detail",
    },
    _plan_read_action(),
    _order_grid_action(),
    _owner_order_readback_action(),
    _owner_order_confirm_action(),
    _reconciliation_action(),
    {
        "key": "rebalance-plan.review",
        "label": "提交人工复核申请",
        "endpoint": (
            "/api/simulated-trading/accounts/<int:account_id>/rebalance-plans/"
            "<str:plan_id>/review/"
        ),
        "method": "POST",
        "intent": "request_staff_review_of_exact_rebalance_plan_revision",
        "risk": "write",
        "audience": "authenticated",
        "effect": "create",
        "screen_key": _SCREEN,
        "module_key": _MODULE,
        "view_type": "detail",
        "description": "提交对当前精确版本的人工复核申请；批准仍需既有独立审批，不会由此开通下单。",
        "source": _SOURCE,
        "task_group": "02 计划操作",
        "sequence": 50,
        "task_tier": "operation",
        "confirmation_required": True,
        "audit_required": True,
        "session_auth_required": True,
        "raw_debug": False,
        "fields": [
            _account_selector(),
            {
                "key": "plan_id",
                "label": "计划编号",
                "binding": "path",
                "input_type": "hidden",
                "value_type": "string",
                "required": True,
                "presentation_semantic": "api_token",
            },
            *_revision_pin_fields(),
            {
                "key": "confirmed",
                "label": "我已核对原目标、限制和实际余量，并申请人工复核",
                "binding": "body",
                "input_type": "checkbox",
                "value_type": "boolean",
                "required": True,
                "default": False,
            },
        ],
        "view_model": {"kind": "detail"},
        "result_panel_key": "rebalance-plan-detail",
    },
    {
        "key": "rebalance-plan.successor",
        "label": "按新事实重新复核",
        "endpoint": (
            "/api/simulated-trading/accounts/<int:account_id>/rebalance-plans/"
            "<str:plan_id>/successor/"
        ),
        "method": "POST",
        "intent": "create_reapproved_successor_from_current_fills_and_sources",
        "risk": "write",
        "audience": "authenticated",
        "effect": "create",
        "screen_key": _SCREEN,
        "module_key": _MODULE,
        "view_type": "detail",
        "description": "根据实际成交和当前资料生成全新的后继版本，旧版本不会沿用成交授权。",
        "source": _SOURCE,
        "task_group": "02 计划操作",
        "sequence": 60,
        "task_tier": "operation",
        "confirmation_required": True,
        "audit_required": True,
        "session_auth_required": True,
        "raw_debug": False,
        "fields": [
            _account_selector(),
            {
                "key": "plan_id",
                "label": "父计划编号",
                "binding": "path",
                "input_type": "hidden",
                "value_type": "string",
                "required": True,
                "presentation_semantic": "api_token",
            },
            *_revision_pin_fields(),
            {
                "key": "target_weights",
                "label": "新的证券目标（可选）",
                "binding": "body",
                "input_type": "textarea",
                "value_type": "string",
                "required": False,
                "max": 2048,
            },
            {
                "key": "confirmed",
                "label": "我确认按当前成交和来源重新生成计划",
                "binding": "body",
                "input_type": "checkbox",
                "value_type": "boolean",
                "required": True,
                "default": False,
            },
        ],
        "view_model": {"kind": "detail"},
        "result_panel_key": "rebalance-plan-detail",
    },
    {
        "key": "rebalance-plan.preview-order",
        "label": "预览本次计划订单",
        "endpoint": (
            "/api/simulated-trading/accounts/<int:account_id>/rebalance-plans/"
            "<str:plan_id>/orders/<int:order_ordinal>/preview/"
        ),
        "method": "POST",
        "intent": "preview_one_exact_plan_order_with_explicit_user_quantity_and_limit",
        "risk": "read",
        "audience": "authenticated",
        "effect": "read",
        "screen_key": _SCREEN,
        "module_key": _MODULE,
        "view_type": "detail",
        "description": "只重新核对一个计划订单；不会建立预留。确认仍需使用普通模拟订单确认步骤。",
        "source": _SOURCE,
        "task_group": "02 计划操作",
        "sequence": 55,
        "task_tier": "operation",
        "session_auth_required": True,
        "raw_debug": False,
        "fields": _order_preview_fields(),
        "view_model": {"kind": "detail"},
        "result_continuation": {
            "target_action_key": "rebalance-plan.order-confirm",
            "field_map": {
                "account_id": "account_id",
                "order_key": "order_key",
                "preview_token": "preview_token",
            },
            "reuse_source_idempotency_key": True,
            "readback_action_key": "rebalance-plan.order-by-key",
        },
        "result_panel_key": "rebalance-plan-order-preview",
    },
)


__all__ = ["RUNTIME_REBALANCE_PLAN_ACTIONS", "RUNTIME_REBALANCE_PLAN_SCREENS"]
