"""Runtime TUI metadata for Macro and Regime analytical route migration."""

from __future__ import annotations

from typing import Any

_SCREEN = "macro-regime.overview"
_MODULE = "macro-regime"
_SOURCE = "approved:runtime-macro-regime-analytics"


def _field(
    key: str,
    label: str,
    *,
    input_type: str = "text",
    value_type: str = "string",
    required: bool = False,
    default: str | int = "",
    options: list[str] | None = None,
    minimum: int | None = None,
    maximum: int | None = None,
) -> dict[str, Any]:
    """Build one typed query field for an analytical read."""

    field: dict[str, Any] = {
        "key": key,
        "label": label,
        "binding": "query",
        "input_type": input_type,
        "value_type": value_type,
        "required": required,
        "default": default,
    }
    if options is not None:
        field["options"] = options
    if minimum is not None:
        field["min"] = minimum
    if maximum is not None:
        field["max"] = maximum
    return field


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
) -> dict[str, Any]:
    """Build one read-only Macro/Regime analytical action."""

    return {
        "key": key,
        "label": label,
        "endpoint": endpoint,
        "method": "GET",
        "intent": intent,
        "risk": "read",
        "audience": "authenticated",
        "effect": "read",
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


_INDICATOR_FIELD = _field(
    "indicator_code",
    "指标代码",
    maximum=80,
)
_AS_OF_DATE_FIELD = _field(
    "as_of_date",
    "分析日期",
    input_type="date",
    value_type="date",
)
_SOURCE_FIELD = _field(
    "source",
    "数据源",
    input_type="select",
    options=["", "akshare", "tushare"],
)
_MONTHS_FIELD = _field(
    "months",
    "历史月数",
    input_type="number",
    value_type="integer",
    default=12,
    minimum=1,
    maximum=60,
)


RUNTIME_MACRO_REGIME_ANALYTICS_ACTIONS: tuple[dict[str, Any], ...] = (
    _action(
        key="macro.overview-summary",
        label="宏观数据摘要",
        endpoint="/api/macro/tui/overview/",
        intent="inspect_macro_data_overview",
        view_type="detail",
        description="查看指标覆盖、当前环境、脉搏、市场温度和决策可用性摘要。",
        task_group="04 宏观数据",
        sequence=410,
        fields=[],
        view_model={
            "kind": "detail",
            "title_path": "summary.selected_indicator_name",
        },
    ),
    _action(
        key="macro.indicator-trend",
        label="宏观指标趋势",
        endpoint="/api/macro/tui/overview/",
        intent="chart_macro_indicator_trend",
        view_type="chart",
        description="按指标代码查看标准化宏观序列及其新鲜度。",
        task_group="04 宏观数据",
        sequence=420,
        fields=[_INDICATOR_FIELD],
        view_model={
            "kind": "chart",
            "chart_type": "line",
            "rows_path": "series",
            "columns": [
                {"key": "period", "label": "报告期"},
                {"key": "value", "label": "指标值"},
            ],
        },
    ),
    _action(
        key="macro.risk-timeline",
        label="宏观风险时序",
        endpoint="/api/macro/tui/overview/",
        intent="chart_macro_risk_timeline",
        view_type="chart",
        description="联合查看市场温度与标准化脉搏的近期变化。",
        task_group="04 宏观数据",
        sequence=430,
        fields=[],
        view_model={
            "kind": "chart",
            "chart_type": "line",
            "rows_path": "risk_timeline",
            "columns": [
                {"key": "date", "label": "日期"},
                {"key": "market_temperature", "label": "市场温度"},
                {"key": "pulse_normalized", "label": "脉搏（标准化）"},
            ],
        },
    ),
    _action(
        key="regime.current",
        label="当前宏观象限",
        endpoint="/api/regime/tui/overview/",
        intent="read_macro_state",
        view_type="detail",
        description="查看指定时点的象限、置信度、增长与通胀状态及告警。",
        task_group="01 环境状态",
        sequence=110,
        fields=[_AS_OF_DATE_FIELD, _SOURCE_FIELD],
        view_model={
            "kind": "detail",
            "title_path": "summary.quadrant",
        },
    ),
    _action(
        key="regime.distribution-chart",
        label="象限概率分布",
        endpoint="/api/regime/tui/overview/",
        intent="chart_regime_distribution",
        view_type="chart",
        description="以百分比饼图比较当前四象限判定概率。",
        task_group="01 环境状态",
        sequence=120,
        fields=[_AS_OF_DATE_FIELD, _SOURCE_FIELD],
        view_model={
            "kind": "chart",
            "chart_type": "pie",
            "rows_path": "distribution",
            "columns": [
                {"key": "regime", "label": "象限"},
                {"key": "probability_percent", "label": "概率（%）"},
            ],
        },
    ),
    _action(
        key="regime.momentum-chart",
        label="增长与通胀动量",
        endpoint="/api/regime/tui/overview/",
        intent="chart_regime_growth_inflation_momentum",
        view_type="chart",
        description="查看用于象限判断的近期增长与通胀序列。",
        task_group="01 环境状态",
        sequence=130,
        fields=[_AS_OF_DATE_FIELD, _SOURCE_FIELD],
        view_model={
            "kind": "chart",
            "chart_type": "line",
            "rows_path": "momentum",
            "columns": [
                {"key": "date", "label": "日期"},
                {"key": "growth", "label": "增长"},
                {"key": "inflation", "label": "通胀"},
            ],
        },
    ),
    _action(
        key="regime.navigator_history",
        label="环境切换历史",
        endpoint="/api/regime/tui/overview/",
        intent="read_regime_transition_history",
        view_type="chart",
        description="联合查看历史脉搏、风险预算和主要资产权重。",
        task_group="03 切换历史",
        sequence=310,
        fields=[_AS_OF_DATE_FIELD, _MONTHS_FIELD],
        view_model={
            "kind": "chart",
            "chart_type": "line",
            "rows_path": "history",
            "columns": [
                {"key": "date", "label": "日期"},
                {"key": "pulse", "label": "综合脉搏"},
                {"key": "risk_budget_percent", "label": "风险预算（%）"},
                {"key": "equity_weight_percent", "label": "权益权重（%）"},
                {"key": "bond_weight_percent", "label": "债券权重（%）"},
                {"key": "cash_weight_percent", "label": "现金权重（%）"},
            ],
        },
    ),
)
