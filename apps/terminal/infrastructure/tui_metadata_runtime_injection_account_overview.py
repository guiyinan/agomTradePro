"""Runtime TUI metadata for account profile and volatility overview."""

from __future__ import annotations

from typing import Any

_SCREEN = "execution.accounts"
_MODULE = "daily-decisions"
_SOURCE = "approved:runtime-account-overview"


def _action(
    *,
    key: str,
    label: str,
    endpoint: str,
    intent: str,
    view_type: str,
    description: str,
    sequence: int,
    view_model: dict[str, Any],
) -> dict[str, Any]:
    """Build one read-only account overview action."""

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
        "task_group": "07 账户概览",
        "sequence": sequence,
        "task_tier": "operation",
        "fields": [],
        "view_model": view_model,
    }


RUNTIME_ACCOUNT_OVERVIEW_ACTIONS: tuple[dict[str, Any], ...] = (
    _action(
        key="account.overview-profile",
        label="我的账户资料",
        endpoint="/api/account/profile/",
        intent="inspect_current_user_account_profile",
        view_type="detail",
        description="查看显示名称、邮箱、风险偏好和账户角色。",
        sequence=760,
        view_model={
            "kind": "detail",
            "title_path": "display_name",
            "status_path": "risk_tolerance",
        },
    ),
    _action(
        key="account.portfolio-volatility-summary",
        label="组合波动率摘要",
        endpoint="/api/account/tui/volatility/",
        intent="inspect_owned_portfolio_volatility",
        view_type="detail",
        description="查看 30/60/90 日波动率、目标区间和降仓建议。",
        sequence=770,
        view_model={"kind": "detail", "status_path": "should_reduce"},
    ),
    _action(
        key="account.portfolio-volatility-chart",
        label="组合波动率趋势",
        endpoint="/api/account/tui/volatility/",
        intent="chart_owned_portfolio_volatility",
        view_type="chart",
        description="以百分比折线比较年化波动率、目标值及目标上下限。",
        sequence=780,
        view_model={
            "kind": "chart",
            "chart_type": "line",
            "rows_path": "history",
            "columns": [
                {"key": "date", "label": "日期"},
                {"key": "annualized_volatility_percent", "label": "年化波动率（%）"},
                {"key": "target_percent", "label": "目标（%）"},
                {"key": "target_upper_percent", "label": "目标上限（%）"},
                {"key": "target_lower_percent", "label": "目标下限（%）"},
            ],
        },
    ),
)
