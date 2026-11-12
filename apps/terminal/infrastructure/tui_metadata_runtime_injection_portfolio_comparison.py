"""Runtime metadata for the read-only two-portfolio comparison task."""

from typing import Any

_SCREEN = "task.portfolio-comparison"
_MODULE = "daily-decisions"
_SOURCE = "approved:runtime-portfolio-comparison"
_ENDPOINT = "/api/simulated-trading/portfolio-comparison/"


def _comparison_fields() -> list[dict[str, Any]]:
    """Build the common two-account and date-range inputs."""

    return [
        {
            "key": "left_account_id",
            "label": "组合 A 账户 ID",
            "binding": "query",
            "input_type": "number",
            "value_type": "integer",
            "required": True,
            "min": 1,
        },
        {
            "key": "right_account_id",
            "label": "组合 B 账户 ID",
            "binding": "query",
            "input_type": "number",
            "value_type": "integer",
            "required": True,
            "min": 1,
        },
        {
            "key": "start_date",
            "label": "开始日期",
            "binding": "query",
            "input_type": "date",
            "value_type": "date",
            "required": True,
        },
        {
            "key": "end_date",
            "label": "结束日期",
            "binding": "query",
            "input_type": "date",
            "value_type": "date",
            "required": True,
        },
    ]


def _action(
    *,
    key: str,
    label: str,
    description: str,
    view_type: str,
    view_model: dict[str, Any],
    sequence: int,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "endpoint": _ENDPOINT,
        "method": "GET",
        "intent": "compare_authorized_portfolios",
        "risk": "read",
        "audience": "authenticated",
        "screen_key": _SCREEN,
        "module_key": _MODULE,
        "view_type": view_type,
        "description": description,
        "source": _SOURCE,
        "task_group": "07 双组合对比",
        "sequence": sequence,
        "task_tier": "operation",
        "fields": _comparison_fields(),
        "view_model": view_model,
    }


RUNTIME_PORTFOLIO_COMPARISON_ACTIONS: tuple[dict[str, Any], ...] = (
    {
        "key": "portfolio-comparison.accounts",
        "label": "查看可对比组合",
        "endpoint": "/api/simulated-trading/accounts/",
        "method": "GET",
        "intent": "read_owned_accounts",
        "risk": "read",
        "audience": "authenticated",
        "screen_key": _SCREEN,
        "module_key": _MODULE,
        "view_type": "datagrid",
        "description": "查看本人账户编号和名称，用于选择两个不同的对比组合。",
        "source": _SOURCE,
        "task_group": "07 双组合对比",
        "sequence": 700,
        "task_tier": "operation",
        "fields": [],
        "view_model": {
            "kind": "datagrid",
            "rows_path": "accounts",
            "columns": [
                {"key": "account_id", "label": "账户 ID"},
                {"key": "account_name", "label": "组合名称"},
                {"key": "account_type", "label": "类型"},
                {"key": "total_value", "label": "总资产（元）"},
            ],
        },
    },
    _action(
        key="portfolio-comparison.metrics",
        label="对比收益与净值曲线",
        description="按共同区间比较两个组合的现金流调整收益、风险指标和归一化 TWR 曲线。",
        view_type="table_chart",
        sequence=710,
        view_model={
            "kind": "table_chart",
            "chart_type": "line",
            "table_rows_path": "metrics",
            "chart_rows_path": "curve",
            "table_columns": [
                {"key": "metric_label", "label": "指标"},
                {"key": "left", "label": "组合 A"},
                {"key": "right", "label": "组合 B"},
                {"key": "difference", "label": "A 减 B"},
            ],
            "chart_columns": [
                {"key": "date", "label": "日期"},
                {"key": "left", "label": "组合 A 归一化净值（期初=100）"},
                {"key": "right", "label": "组合 B 归一化净值（期初=100）"},
            ],
        },
    ),
    _action(
        key="portfolio-comparison.holdings",
        label="对比当前持仓与重合度",
        description="比较当前共同持仓和独有持仓，并用共同权重的较低值汇总重合度；估值未知时保持未知。",
        view_type="table_chart",
        sequence=720,
        view_model={
            "kind": "table_chart",
            "chart_type": "bar",
            "table_rows_path": "holdings.rows",
            "chart_rows_path": "holdings.overlap_rows",
            "table_columns": [
                {"key": "asset_code", "label": "证券代码"},
                {"key": "asset_name", "label": "证券名称"},
                {"key": "left_weight_percentage", "label": "组合 A 权重（%）"},
                {"key": "right_weight_percentage", "label": "组合 B 权重（%）"},
                {"key": "difference_percentage_points", "label": "权重差（百分点）"},
            ],
            "chart_columns": [
                {"key": "overlap_label", "label": "重合度口径"},
                {"key": "overlap_percentage", "label": "当前持仓重合度（%）"},
            ],
        },
    ),
    _action(
        key="portfolio-comparison.industries",
        label="对比当前行业配置",
        description="按当前持仓市值比较行业权重；缺少行业分类的资产单列，不作推断。",
        view_type="datagrid",
        sequence=730,
        view_model={
            "kind": "datagrid",
            "rows_path": "holdings.industry_rows",
            "columns": [
                {"key": "industry", "label": "行业"},
                {"key": "left_weight_percentage", "label": "组合 A 权重（%）"},
                {"key": "right_weight_percentage", "label": "组合 B 权重（%）"},
                {"key": "difference_percentage_points", "label": "权重差（百分点）"},
            ],
        },
    ),
)

RUNTIME_PORTFOLIO_COMPARISON_SCREEN: dict[str, Any] = {
    "key": _SCREEN,
    "dashboard_panels": [
        {
            "key": "portfolio-comparison-accounts",
            "title": "一、选择两个组合",
            "kind": "datagrid",
            "action_key": "portfolio-comparison.accounts",
            "user_priority": "p0",
            "presentation_semantic": "primary_list",
            "empty_message": "至少需要两个本人或获授权查看的组合。",
            "error_message": "组合目录读取失败，请稍后重试。",
        },
        {
            "key": "portfolio-comparison-performance",
            "title": "二、绩效与归一化曲线",
            "kind": "table_chart",
            "action_key": "portfolio-comparison.metrics",
            "user_priority": "p0",
            "presentation_semantic": "supporting_detail",
            "empty_message": "填写两个组合 ID 和共同区间后开始对比。",
            "error_message": "本次对比未完成，请检查账户权限、日期和净值历史。",
            "stale_message": "净值或费用更正可能已更新，请重新读取。",
        },
        {
            "key": "portfolio-comparison-holdings",
            "title": "三、当前持仓与重合度",
            "kind": "table_chart",
            "action_key": "portfolio-comparison.holdings",
            "user_priority": "p1",
            "presentation_semantic": "supporting_detail",
            "empty_message": "完成绩效对比后，可继续使用相同条件读取当前持仓差异。",
            "error_message": "当前持仓对比读取失败。",
        },
        {
            "key": "portfolio-comparison-industries",
            "title": "四、当前行业差异",
            "kind": "datagrid",
            "action_key": "portfolio-comparison.industries",
            "user_priority": "p1",
            "presentation_semantic": "supporting_detail",
            "empty_message": "行业分类未知的资产会单独显示。",
            "error_message": "当前行业对比读取失败。",
        },
    ],
}
