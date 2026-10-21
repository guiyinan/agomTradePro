"""Runtime TUI metadata for the dashboard command overview charts."""

from __future__ import annotations

from typing import Any

_SCREEN = "command-center.overview"
_MODULE = "command-center"
_SOURCE = "approved:runtime-dashboard-overview"


def _action(
    *,
    key: str,
    label: str,
    intent: str,
    view_type: str,
    description: str,
    sequence: int,
    view_model: dict[str, Any],
    task_tier: str = "support",
    endpoint: str = "/api/dashboard/tui/overview/",
    fields: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build one read-only dashboard action."""

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
        "task_group": "01 指挥概览",
        "sequence": sequence,
        "task_tier": task_tier,
        "fields": fields or [],
        "view_model": view_model,
    }


RUNTIME_DASHBOARD_OVERVIEW_ACTIONS: tuple[dict[str, Any], ...] = (
    _action(
        key="dashboard.overview-summary",
        label="投资指挥摘要",
        intent="inspect_investment_command_summary",
        view_type="detail",
        description="查看环境、资产、收益、仓位、信号和数据健康的 P0 摘要。",
        sequence=40,
        view_model={"kind": "detail"},
        task_tier="primary",
    ),
    _action(
        key="dashboard.asset-allocation",
        label="资产配置",
        intent="chart_owned_asset_allocation",
        view_type="chart",
        description="以占比饼图查看本人当前资产配置。",
        sequence=50,
        view_model={
            "kind": "chart",
            "chart_type": "pie",
            "rows_path": "allocation",
            "columns": [
                {"key": "asset_class", "label": "资产类别"},
                {"key": "weight_percent", "label": "配置占比（%）"},
            ],
        },
    ),
    _action(
        key="dashboard.portfolio-performance",
        label="组合表现",
        intent="chart_owned_portfolio_performance",
        view_type="chart",
        description="按时间范围查看本人全部账户的历史总资产（元）；无历史时不补造观测点。",
        sequence=60,
        endpoint="/api/dashboard/v1/equity-curve/",
        fields=[
            {
                "key": "range",
                "label": "历史范围",
                "input_type": "select",
                "value_type": "string",
                "binding": "query",
                "required": False,
                "default": "ALL",
                "options": ["1M", "3M", "6M", "1Y", "ALL"],
            }
        ],
        view_model={
            "kind": "chart",
            "chart_type": "line",
            "rows_path": "series",
            "columns": [
                {"key": "date", "label": "日期"},
                {"key": "portfolio_value", "label": "账户总资产（元）"},
            ],
        },
    ),
)
