"""Runtime TUI metadata for manual trade import and decision replay."""

from __future__ import annotations

from typing import Any

_SCREEN = "execution.audit"
_MODULE = "execution"
_SOURCE = "approved:runtime-manual-trade-review"


def _field(
    key: str,
    label: str,
    *,
    binding: str = "body",
    input_type: str = "text",
    value_type: str = "string",
    required: bool = False,
    default: object | None = None,
    minimum: int | float | None = None,
    maximum: int | float | None = None,
    options: list[str | dict[str, str]] | None = None,
    accept: str | None = None,
    placeholder: str | None = None,
    presentation_semantic: str | None = None,
) -> dict[str, Any]:
    """Build one bounded manual-trade field."""

    field: dict[str, Any] = {
        "key": key,
        "label": label,
        "binding": binding,
        "input_type": input_type,
        "value_type": value_type,
        "required": required,
    }
    if default is not None:
        field["default"] = default
    if minimum is not None:
        field["min"] = minimum
    if maximum is not None:
        field["max"] = maximum
    if options is not None:
        field["options"] = options
    if accept is not None:
        field["accept"] = accept
    if placeholder is not None:
        field["placeholder"] = placeholder
    if presentation_semantic is not None:
        field["presentation_semantic"] = presentation_semantic
    return field


def _action(
    *,
    key: str,
    label: str,
    endpoint: str,
    method: str,
    intent: str,
    view_type: str,
    description: str,
    sequence: int,
    fields: list[dict[str, Any]],
    view_model: dict[str, Any],
    risk: str = "read",
    effect: str = "read",
    confirmation_required: bool = False,
    audit_required: bool = False,
    session_auth_required: bool = False,
    result_continuation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one owner-scoped manual-trade action."""

    action: dict[str, Any] = {
        "key": key,
        "label": label,
        "endpoint": endpoint,
        "method": method,
        "intent": intent,
        "risk": risk,
        "audience": "authenticated",
        "effect": effect,
        "screen_key": _SCREEN,
        "module_key": _MODULE,
        "view_type": view_type,
        "description": description,
        "source": _SOURCE,
        "task_group": "08 手动交易复盘",
        "sequence": sequence,
        "task_tier": "operation",
        "fields": fields,
        "view_model": view_model,
    }
    if confirmation_required:
        action["confirmation_required"] = True
    if audit_required:
        action["audit_required"] = True
    if session_auth_required:
        action["session_auth_required"] = True
    if result_continuation is not None:
        action["result_continuation"] = result_continuation
    return action


_PORTFOLIO_ID = _field(
    "portfolio_id",
    "组合 ID",
    input_type="number",
    value_type="integer",
    required=True,
    minimum=1,
)

_IMPORT_FIELDS: list[dict[str, Any]] = [
    _PORTFOLIO_ID,
    _field("broker_name", "成交来源", default="manual", maximum=64),
    _field(
        "file",
        "UTF-8 CSV 文件",
        input_type="file",
        required=True,
        accept=".csv,text/csv",
    ),
]

_CONFIRM_IMPORT_FIELDS: list[dict[str, Any]] = [
    *_IMPORT_FIELDS,
    _field(
        "baseline_decision",
        "成交相对当前余额的选择",
        input_type="select",
        required=True,
        default="pending",
        options=[
            {
                "value": "pending",
                "label": "待核对：只保存成交事实，不改持仓数量（默认）",
            },
            {
                "value": "included",
                "label": "已包含：成交已计入当前余额，不重复增减数量",
            },
            {
                "value": "excluded",
                "label": "未包含：余额复核通过后才按成交更新数量",
            },
        ],
    ),
    _field(
        "baseline_as_of",
        "券商余额快照有效时点（可选）",
        placeholder="例如 2026-10-18T15:30:00+08:00",
    ),
    _field(
        "expected_fact_set_fingerprint",
        "文件预览依据",
        input_type="hidden",
        required=False,
        presentation_semantic="api_token",
    ),
    _field(
        "expected_balance_fingerprint",
        "余额预览依据",
        input_type="hidden",
        required=False,
        presentation_semantic="api_token",
    ),
]

_REPLAY_FIELDS: list[dict[str, Any]] = [
    _PORTFOLIO_ID,
    _field(
        "start_date",
        "开始日期",
        input_type="date",
        value_type="date",
        required=True,
    ),
    _field(
        "end_date",
        "结束日期",
        input_type="date",
        value_type="date",
        required=True,
    ),
    _field(
        "initial_capital",
        "初始资金（元）",
        input_type="number",
        value_type="decimal",
        required=True,
        default="1000000.00",
        minimum=0,
    ),
]


RUNTIME_MANUAL_TRADE_REVIEW_ACTIONS: tuple[dict[str, Any], ...] = (
    _action(
        key="audit.manual-trade-batches",
        label="手动成交导入批次",
        endpoint="/api/audit/tui/manual-trades/",
        method="GET",
        intent="list_owned_manual_trade_import_batches",
        view_type="datagrid",
        description="查看本人最近 20 个券商成交流水导入批次及处理结果。",
        sequence=230,
        fields=[],
        view_model={
            "kind": "datagrid",
            "rows_path": "batches",
            "columns": [
                {"key": "id", "label": "批次"},
                {"key": "portfolio_id", "label": "组合 ID"},
                {"key": "portfolio_name", "label": "组合"},
                {"key": "broker_name", "label": "来源"},
                {"key": "status", "label": "状态"},
                {"key": "imported_rows", "label": "导入"},
                {"key": "skipped_rows", "label": "跳过"},
                {"key": "created_at", "label": "时间"},
            ],
        },
    ),
    _action(
        key="audit.manual-trade-transactions",
        label="最近手动成交",
        endpoint="/api/audit/tui/manual-trades/",
        method="GET",
        intent="list_owned_manual_trade_transactions",
        view_type="datagrid",
        description="查看本人最近 50 条已导入成交，支持从选中行带入组合 ID。",
        sequence=240,
        fields=[],
        view_model={
            "kind": "datagrid",
            "rows_path": "transactions",
            "columns": [
                {"key": "portfolio_id", "label": "组合 ID"},
                {"key": "portfolio_name", "label": "组合"},
                {"key": "asset_code", "label": "证券"},
                {"key": "action", "label": "方向"},
                {"key": "shares", "label": "数量"},
                {"key": "price", "label": "价格"},
                {"key": "notional", "label": "金额"},
                {"key": "traded_at", "label": "成交时间"},
            ],
        },
    ),
    _action(
        key="audit.manual-trade-import-preview",
        label="预览 CSV 成交流水",
        endpoint="/api/account/tui/broker-trades/preview/",
        method="POST",
        intent="preview_owned_manual_trade_csv",
        view_type="datagrid",
        description="预览不超过 2 MiB 的 UTF-8 CSV 和每证券当前余额；此步骤不写入事实或持仓。确认时需再次选择同一 CSV。",
        sequence=250,
        fields=_IMPORT_FIELDS,
        view_model={
            "kind": "datagrid",
            "rows_path": "rows",
            "columns": [
                {"key": "row_number", "label": "来源行"},
                {"key": "traded_at", "label": "成交时间"},
                {"key": "asset_code", "label": "证券"},
                {"key": "action", "label": "方向"},
                {"key": "shares", "label": "数量"},
                {"key": "price", "label": "价格"},
                {"key": "duplicate", "label": "重复"},
                {"key": "status", "label": "状态"},
                {"key": "balance_total_shares", "label": "当前总数量"},
                {"key": "balance_available_quantity", "label": "可卖数量"},
                {"key": "balance_available_status", "label": "可卖数量是否已知"},
                {"key": "balance_average_cost", "label": "本地成本"},
                {"key": "balance_reference_mark", "label": "参考估值"},
                {"key": "balance_valuation_status", "label": "估值状态"},
                {"key": "balance_observed_at", "label": "余额读取时间"},
            ],
        },
        session_auth_required=True,
        result_continuation={
            "target_action_key": "audit.manual-trade-import",
            "field_map": {
                "expected_fact_set_fingerprint": "expected_fact_set_fingerprint",
                "expected_balance_fingerprint": "expected_balance_fingerprint",
            },
        },
    ),
    _action(
        key="audit.manual-trade-import",
        label="确认导入 CSV 成交流水",
        endpoint="/api/account/tui/broker-trades/import/",
        method="POST",
        intent="import_owned_manual_trade_csv",
        view_type="datagrid",
        description="请再次选择刚才预览的同一 CSV。默认只保存成交事实待核对；已包含表示不改数量，未包含仅在预览余额未变化且复核通过后投影。可填写券商余额快照有效时点。",
        sequence=260,
        fields=_CONFIRM_IMPORT_FIELDS,
        view_model={
            "kind": "datagrid",
            "rows_path": "rows",
            "columns": [
                {"key": "row_number", "label": "来源行 / 汇总"},
                {"key": "summary", "label": "导入汇总"},
                {"key": "transaction_id", "label": "成交事实号"},
                {"key": "traded_at", "label": "成交时间"},
                {"key": "asset_code", "label": "证券"},
                {"key": "action", "label": "方向"},
                {"key": "shares", "label": "数量"},
                {"key": "price", "label": "价格"},
                {"key": "commission", "label": "佣金"},
                {"key": "stamp_duty", "label": "印花税"},
                {"key": "transfer_fee", "label": "过户费"},
                {"key": "fee_status", "label": "费用是否已知"},
                {"key": "status", "label": "处理结果"},
                {"key": "reconciliation_status", "label": "核对状态"},
                {"key": "projection_status", "label": "持仓处理"},
                {"key": "status_reason", "label": "处理说明"},
            ],
        },
        risk="write",
        effect="create",
        confirmation_required=True,
        audit_required=True,
        session_auth_required=True,
    ),
    _action(
        key="audit.manual-trade-execution-links",
        label="推荐执行关联",
        endpoint="/api/audit/execution-links/",
        method="GET",
        intent="list_owned_manual_trade_execution_links",
        view_type="datagrid",
        description="核对手动成交、推荐计划与实际执行之间的 owner-scoped 关联。",
        sequence=270,
        fields=[
            _field(
                "limit",
                "最多返回",
                binding="query",
                input_type="number",
                value_type="integer",
                default=50,
                minimum=1,
                maximum=500,
            )
        ],
        view_model={
            "kind": "datagrid",
            "rows_path": "links",
            "columns": [
                {"key": "recommendation_id", "label": "推荐"},
                {"key": "transaction_source", "label": "成交来源"},
                {"key": "transaction_id", "label": "成交"},
                {"key": "account_id", "label": "账户"},
                {"key": "security_code", "label": "证券"},
                {"key": "actual_action", "label": "方向"},
                {"key": "match_method", "label": "匹配方法"},
                {"key": "created_at", "label": "时间"},
            ],
        },
    ),
    _action(
        key="audit.manual-trade-replay",
        label="运行四分支决策复盘",
        endpoint="/api/backtest/tui/decision-replay/",
        method="POST",
        intent="run_owned_manual_trade_decision_replay",
        view_type="table_chart",
        description="确认后运行四个固定分支，以净值曲线和指标表同时比较结果。",
        sequence=280,
        fields=_REPLAY_FIELDS,
        view_model={
            "kind": "table_chart",
            "chart_type": "line",
            "table_rows_path": "branches",
            "chart_rows_path": "equity_curve",
            "table_columns": [
                {"key": "branch_type", "label": "分支"},
                {"key": "backtest_id", "label": "回测"},
                {"key": "final_capital", "label": "期末资金（元）"},
                {"key": "total_return_percent", "label": "总收益（%）"},
                {"key": "max_drawdown_percent", "label": "最大回撤（%）"},
                {"key": "warning_count", "label": "警告"},
            ],
            "chart_columns": [
                {"key": "date", "label": "日期"},
                {"key": "actual", "label": "实际操作（元）"},
                {"key": "no_action", "label": "不操作（元）"},
                {"key": "system_plan", "label": "系统建议（元）"},
                {"key": "delayed_1d", "label": "延迟一天（元）"},
            ],
        },
        risk="write",
        effect="create",
        confirmation_required=True,
        audit_required=True,
    ),
)
