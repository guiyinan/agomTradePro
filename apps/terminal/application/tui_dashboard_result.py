"""Dashboard overview presentation and numeric formatting for TUI results."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any


class TuiDashboardResultMixin:
    """Project dashboard summaries through the shared workbench display helpers."""

    if TYPE_CHECKING:

        def _action_title(self, action: dict[str, Any]) -> str: ...

        def _display_value(self, value: Any) -> str: ...

        def _status_label(self, status_code: int, payload: Any | None = None) -> str: ...

        @staticmethod
        def _mapping(value: Any) -> dict[str, Any]: ...

    def _dashboard_overview_result_model(
        self,
        action: dict[str, Any],
        payload: dict[str, Any],
        status_code: int,
    ) -> dict[str, Any]:
        """Project the command overview into a concise investor-facing summary."""

        summary = self._mapping(payload.get("summary"))
        regime = self._display_value(summary.get("current_regime"))
        invested_ratio = self._dashboard_percentage(summary.get("invested_ratio_percent"))
        active_signals = self._dashboard_count(summary.get("active_signal_count"))
        pending_reviews = self._dashboard_count(summary.get("pending_review_count"))
        health = {
            "healthy": "数据健康",
            "degraded": "数据降级",
            "fallback": "使用备用数据",
            "unavailable": "数据不可用",
        }.get(
            str(summary.get("regime_data_health") or "unknown").strip().lower(),
            "数据状态待确认",
        )
        return {
            "kind": "detail",
            "title": self._action_title(action),
            "status": self._status_label(status_code, payload),
            "fields": [
                {"key": "current_regime", "label": "当前环境", "value": regime},
                {
                    "key": "regime_confidence",
                    "label": "环境置信度",
                    "value": self._dashboard_percentage(summary.get("regime_confidence_percent")),
                },
                {
                    "key": "total_assets",
                    "label": "总资产",
                    "value": self._dashboard_money(summary.get("total_assets")),
                },
                {
                    "key": "total_return",
                    "label": "累计收益",
                    "value": self._dashboard_money(summary.get("total_return")),
                },
                {
                    "key": "total_return_percent",
                    "label": "累计收益率",
                    "value": self._dashboard_percentage(summary.get("total_return_percent")),
                },
                {
                    "key": "cash_balance",
                    "label": "可用现金",
                    "value": self._dashboard_money(summary.get("cash_balance")),
                },
                {
                    "key": "invested_value",
                    "label": "已投资市值",
                    "value": self._dashboard_money(summary.get("invested_value")),
                },
                {"key": "invested_ratio", "label": "已投资比例", "value": invested_ratio},
                {
                    "key": "active_signal_count",
                    "label": "活跃信号",
                    "value": f"{active_signals} 个",
                },
                {
                    "key": "pending_review_count",
                    "label": "待复核事项",
                    "value": f"{pending_reviews} 项",
                },
                {"key": "regime_data_health", "label": "环境数据", "value": health},
            ],
            "nested": [],
            "business_summary": (
                f"当前环境 {regime}；仓位 {invested_ratio}；"
                f"活跃信号 {active_signals} 个；待复核 {pending_reviews} 项。"
            ),
            "blocking_reason": "" if health == "数据健康" else health,
            "next_steps": [],
            "debug_hidden_fields": ["display_name", "allocation", "performance"],
        }

    def _dashboard_money(self, value: Any) -> str:
        """Format one dashboard amount for direct user display."""

        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return self._display_value(value)
        if not math.isfinite(number):
            return self._display_value(value)
        return f"{number:,.2f} 元"

    def _dashboard_percentage(self, value: Any) -> str:
        """Format an API percentage that is already expressed on a 0-100 scale."""

        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return self._display_value(value)
        if not math.isfinite(number):
            return self._display_value(value)
        return f"{number:.1f}%"

    @staticmethod
    def _dashboard_count(value: Any) -> int:
        """Return a non-negative integer count for dashboard summaries."""

        if isinstance(value, bool):
            return 0
        try:
            return max(0, int(value))
        except (TypeError, ValueError, OverflowError):
            return 0
