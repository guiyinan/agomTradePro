"""Runtime TUI metadata for Equity detail, pool, and repair analytics."""

from __future__ import annotations

from typing import Any

from apps.equity.domain.entities_valuation_repair import ValuationRepairPhase

_SCREEN = "research.asset-lab"
_MODULE = "research"
_SOURCE = "approved:runtime-equity-analytics"


def _stock_code_field() -> dict[str, Any]:
    """Build the canonical stock-code path field."""

    return {
        "key": "stock_code",
        "label": "股票代码",
        "binding": "path",
        "input_type": "text",
        "value_type": "string",
        "required": True,
        "default": "",
        "max": 32,
    }


def _integer_query_field(
    key: str,
    label: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> dict[str, Any]:
    """Build one bounded integer query field."""

    return {
        "key": key,
        "label": label,
        "binding": "query",
        "input_type": "number",
        "value_type": "integer",
        "required": False,
        "default": default,
        "min": minimum,
        "max": maximum,
    }


def _action(
    *,
    key: str,
    label: str,
    endpoint: str,
    intent: str,
    view_type: str,
    description: str,
    task_group: str,
    sequence: int,
    fields: list[dict[str, Any]],
    view_model: dict[str, Any],
    method: str = "GET",
    effect: str = "read",
    confirmation_required: bool = False,
) -> dict[str, Any]:
    """Build one authenticated Equity analytical action."""

    action: dict[str, Any] = {
        "key": key,
        "label": label,
        "endpoint": endpoint,
        "method": method,
        "intent": intent,
        "risk": "read" if method == "GET" else "write",
        "audience": "authenticated",
        "effect": effect,
        "screen_key": _SCREEN,
        "module_key": _MODULE,
        "view_type": view_type,
        "description": description,
        "source": _SOURCE,
        "task_group": task_group,
        "sequence": sequence,
        "task_tier": "support",
        "fields": fields,
        "view_model": view_model,
    }
    if confirmation_required:
        action["confirmation_required"] = True
    return action


_TECHNICAL_FIELDS = [
    _stock_code_field(),
    {
        "key": "timeframe",
        "label": "周期",
        "binding": "query",
        "input_type": "select",
        "value_type": "string",
        "required": False,
        "default": "day",
        "options": ["day", "week", "month"],
    },
    _integer_query_field(
        "lookback_days",
        "回看天数",
        default=365,
        minimum=30,
        maximum=2000,
    ),
]
_REPAIR_UNIVERSE_FIELD = {
    "key": "universe",
    "label": "股票范围",
    "binding": "query",
    "input_type": "select",
    "value_type": "string",
    "required": False,
    "default": "all_active",
    "options": ["all_active", "current_pool"],
}


RUNTIME_EQUITY_ANALYTICS_ACTIONS: tuple[dict[str, Any], ...] = (
    _action(
        key="equity.valuation-overview",
        label="个股估值与财务摘要",
        endpoint="/api/equity/valuation/<str:stock_code>/",
        intent="inspect_equity_valuation_overview",
        view_type="detail",
        description="查看基本资料、最新估值、PE/PB 分位和财务指标。",
        task_group="03 个股详情",
        sequence=300,
        fields=[
            _stock_code_field(),
            _integer_query_field(
                "lookback_days",
                "估值回看天数",
                default=252,
                minimum=30,
                maximum=1260,
            ),
        ],
        view_model={
            "kind": "detail",
            "title_path": "stock_name",
            "status_path": "is_undervalued",
        },
    ),
    _action(
        key="equity.technical-price",
        label="价格与均线趋势",
        endpoint="/api/equity/technical/<str:stock_code>/",
        intent="chart_equity_price_and_moving_averages",
        view_type="chart",
        description="按日、周或月查看收盘价和 5/20/60 期均线。",
        task_group="03 个股详情",
        sequence=310,
        fields=list(_TECHNICAL_FIELDS),
        view_model={
            "kind": "chart",
            "chart_type": "line",
            "rows_path": "candles",
            "columns": [
                {"key": "trade_date", "label": "交易日"},
                {"key": "close", "label": "收盘价"},
                {"key": "ma5", "label": "MA5"},
                {"key": "ma20", "label": "MA20"},
                {"key": "ma60", "label": "MA60"},
            ],
        },
    ),
    _action(
        key="equity.technical-momentum",
        label="MACD 与 RSI 动量",
        endpoint="/api/equity/technical/<str:stock_code>/",
        intent="chart_equity_technical_momentum",
        view_type="chart",
        description="查看 MACD、信号线、柱值和 RSI 的同期变化。",
        task_group="03 个股详情",
        sequence=320,
        fields=list(_TECHNICAL_FIELDS),
        view_model={
            "kind": "chart",
            "chart_type": "line",
            "rows_path": "candles",
            "columns": [
                {"key": "trade_date", "label": "交易日"},
                {"key": "macd", "label": "MACD"},
                {"key": "macd_signal", "label": "信号线"},
                {"key": "macd_hist", "label": "MACD 柱"},
                {"key": "rsi", "label": "RSI"},
            ],
        },
    ),
    _action(
        key="equity.intraday-price",
        label="当日分时价格",
        endpoint="/api/equity/intraday/<str:stock_code>/",
        intent="chart_equity_intraday_price",
        view_type="chart",
        description="查看最新交易日的分钟价格和同期均价。",
        task_group="03 个股详情",
        sequence=330,
        fields=[_stock_code_field()],
        view_model={
            "kind": "chart",
            "chart_type": "line",
            "rows_path": "points",
            "columns": [
                {"key": "timestamp", "label": "时间"},
                {"key": "price", "label": "价格"},
                {"key": "avg_price", "label": "均价"},
            ],
        },
    ),
    _action(
        key="equity.regime-correlation",
        label="个股环境表现",
        endpoint="/api/equity/regime-correlation/<str:stock_code>/",
        intent="chart_equity_regime_performance",
        view_type="chart",
        description="比较个股在四类宏观环境下的平均收益与 Beta。",
        task_group="03 个股详情",
        sequence=340,
        fields=[
            _stock_code_field(),
            _integer_query_field(
                "lookback_days",
                "回看天数",
                default=1260,
                minimum=252,
                maximum=2520,
            ),
        ],
        view_model={
            "kind": "chart",
            "chart_type": "bar",
            "rows_path": "regime_performance",
            "columns": [
                {"key": "regime", "label": "宏观环境"},
                {"key": "avg_return", "label": "平均收益"},
                {"key": "beta", "label": "Beta"},
            ],
        },
    ),
    _action(
        key="equity.pool-summary",
        label="股票池摘要",
        endpoint="/api/equity/pool/",
        intent="inspect_equity_pool_summary",
        view_type="detail",
        description="查看当前环境、股票数量、平均 ROE、平均 PE 和更新时间。",
        task_group="04 股票池",
        sequence=400,
        fields=[],
        view_model={
            "kind": "detail",
            "title_path": "regime",
            "status_path": "count",
        },
    ),
    _action(
        key="equity.pool-list",
        label="股票池明细",
        endpoint="/api/equity/pool/",
        intent="browse_equity_pool",
        view_type="datagrid",
        description="查看股票池的行业、盈利、估值、成长和评分。",
        task_group="04 股票池",
        sequence=410,
        fields=[],
        view_model={
            "kind": "datagrid",
            "rows_path": "stocks",
            "total_path": "count",
            "columns": [
                {"key": "code", "label": "股票代码"},
                {"key": "name", "label": "名称"},
                {"key": "sector", "label": "行业"},
                {"key": "roe", "label": "ROE"},
                {"key": "pe", "label": "PE"},
                {"key": "pb", "label": "PB"},
                {"key": "revenue_growth", "label": "营收增长"},
                {"key": "profit_growth", "label": "利润增长"},
            ],
        },
    ),
    _action(
        key="equity.pool-sector-distribution",
        label="股票池行业分布",
        endpoint="/api/equity/pool/",
        intent="chart_equity_pool_sector_distribution",
        view_type="chart",
        description="按行业比较当前股票池的股票数量。",
        task_group="04 股票池",
        sequence=420,
        fields=[],
        view_model={
            "kind": "chart",
            "chart_type": "pie",
            "rows_path": "sector_distribution",
            "columns": [
                {"key": "sector", "label": "行业"},
                {"key": "count", "label": "股票数"},
            ],
        },
    ),
    _action(
        key="equity.pool-refresh",
        label="按当前环境刷新股票池",
        endpoint="/api/equity/pool/refresh/",
        method="POST",
        intent="refresh_equity_pool",
        view_type="detail",
        description="按当前宏观环境重新筛选并保存股票池。",
        task_group="04 股票池",
        sequence=430,
        fields=[],
        view_model={
            "kind": "detail",
            "title_path": "message",
            "status_path": "success",
        },
        effect="execute",
        confirmation_required=True,
    ),
    _action(
        key="equity.valuation-repair-list",
        label="估值修复清单",
        endpoint="/api/equity/valuation-repair-list/",
        intent="browse_equity_valuation_repairs",
        view_type="datagrid",
        description="按股票范围和阶段查看估值修复进度、速度与预计天数。",
        task_group="05 估值修复",
        sequence=500,
        fields=[
            dict(_REPAIR_UNIVERSE_FIELD),
            {
                "key": "phase",
                "label": "修复阶段",
                "binding": "query",
                "input_type": "select",
                "value_type": "string",
                "required": False,
                "default": "",
                "options": ["", *[phase.value for phase in ValuationRepairPhase]],
            },
            _integer_query_field(
                "limit",
                "最多返回数量",
                default=50,
                minimum=1,
                maximum=200,
            ),
        ],
        view_model={
            "kind": "datagrid",
            "rows_path": "results",
            "columns": [
                {"key": "stock_code", "label": "股票代码"},
                {"key": "stock_name", "label": "名称"},
                {"key": "phase", "label": "修复阶段"},
                {"key": "signal", "label": "信号"},
                {"key": "composite_percentile", "label": "综合分位（0-1）"},
                {"key": "repair_progress", "label": "修复进度（0-1）"},
                {"key": "estimated_days_to_target", "label": "预计天数"},
                {"key": "as_of_date", "label": "数据日期"},
            ],
        },
    ),
    _action(
        key="equity.valuation-repair-detail",
        label="估值修复详情",
        endpoint="/api/equity/valuation-repair/<str:stock_code>/",
        intent="inspect_equity_valuation_repair",
        view_type="detail",
        description="查看单只股票的估值分位、修复阶段、进度、速度和信号。",
        task_group="05 估值修复",
        sequence=510,
        fields=[
            _stock_code_field(),
            _integer_query_field(
                "lookback_days",
                "回看天数",
                default=756,
                minimum=30,
                maximum=2520,
            ),
        ],
        view_model={
            "kind": "detail",
            "title_path": "stock_name",
            "status_path": "phase",
        },
    ),
    _action(
        key="equity.valuation-repair-history",
        label="估值分位历史",
        endpoint="/api/equity/valuation-repair/<str:stock_code>/history/",
        intent="chart_equity_valuation_percentile_history",
        view_type="chart",
        description="查看 PE、PB 和综合估值分位的历史变化。",
        task_group="05 估值修复",
        sequence=520,
        fields=[
            _stock_code_field(),
            _integer_query_field(
                "lookback_days",
                "回看天数",
                default=252,
                minimum=30,
                maximum=2520,
            ),
        ],
        view_model={
            "kind": "chart",
            "chart_type": "line",
            "rows_path": "chart_points",
            "columns": [
                {"key": "trade_date", "label": "交易日"},
                {"key": "pe_percentile_percent", "label": "PE 分位（%）"},
                {"key": "pb_percentile_percent", "label": "PB 分位（%）"},
                {
                    "key": "composite_percentile_percent",
                    "label": "综合分位（%）",
                },
            ],
        },
    ),
    _action(
        key="equity.valuation-repair-scan",
        label="扫描估值修复机会",
        endpoint="/api/equity/valuation-repair/scan/",
        method="POST",
        intent="scan_equity_valuation_repairs",
        view_type="detail",
        description="按股票范围批量计算估值修复状态并保存快照。",
        task_group="05 估值修复",
        sequence=530,
        fields=[
            {**_REPAIR_UNIVERSE_FIELD, "binding": "body"},
            {
                **_integer_query_field(
                    "lookback_days",
                    "回看天数",
                    default=756,
                    minimum=120,
                    maximum=1260,
                ),
                "binding": "body",
            },
        ],
        view_model={
            "kind": "detail",
            "title_path": "universe",
            "status_path": "success",
        },
        effect="execute",
        confirmation_required=True,
    ),
)


__all__ = ["RUNTIME_EQUITY_ANALYTICS_ACTIONS"]
