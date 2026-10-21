"""Pure presentation helpers for macro-regime workbench results."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from shared.numeric import safe_float


class TuiWorkbenchRegimeResultMixin:
    """Project macro-regime owner results into safe TUI view models."""

    if TYPE_CHECKING:

        @staticmethod
        def _mapping(value: Any) -> dict[str, Any]: ...

        def _action_title(self, action: dict[str, Any]) -> str: ...

        def _display_value(self, value: Any) -> str: ...

        def _operator_text(self, value: Any) -> str: ...

        def _status_label(self, status_code: int, payload: Any | None = None) -> str: ...

    @staticmethod
    def _regime_distribution_rows(
        payload: dict[str, Any], *, available: bool
    ) -> list[dict[str, Any]]:
        """Keep only a complete, normalized four-quadrant percentage distribution."""

        raw_rows = payload.get("distribution")
        if not available or not isinstance(raw_rows, list) or len(raw_rows) != 4:
            return []
        rows: list[dict[str, Any]] = []
        regimes: set[str] = set()
        percentages: list[float] = []
        for raw_row in raw_rows:
            if not isinstance(raw_row, dict):
                return []
            regime = raw_row.get("regime")
            raw_percentage = raw_row.get("probability_percent")
            if not isinstance(regime, str) or not regime or isinstance(raw_percentage, bool):
                return []
            percentage = safe_float(raw_percentage)
            if percentage is None or not 0.0 <= percentage <= 100.0 or regime in regimes:
                return []
            regimes.add(regime)
            percentages.append(percentage)
            rows.append({"regime": regime, "probability_percent": percentage})
        if not math.isclose(math.fsum(percentages), 100.0, rel_tol=0.0, abs_tol=1e-4):
            return []
        return rows

    def _regime_current_result_model(
        self,
        action: dict[str, Any],
        payload: dict[str, Any],
        status_code: int,
    ) -> dict[str, Any]:
        """Project the Regime overview response onto the quadrant renderer contract."""

        summary = self._mapping(payload.get("summary"))
        available = bool(payload.get("available"))
        regime = self._display_value(summary.get("quadrant") or "Unknown")
        confidence = self._display_value(summary.get("confidence_percent"))
        growth_trend = self._regime_trend_label(summary.get("growth_trend"))
        inflation_trend = self._regime_trend_label(summary.get("inflation_trend"))
        trend = f"增长{growth_trend} / 通胀{inflation_trend}"
        observed_at = self._display_value(summary.get("observed_at"))
        as_of_date = self._display_value(summary.get("as_of_date"))
        freshness_status_code = str(summary.get("freshness_status") or "unknown")
        freshness_status_label = {
            "fresh": "数据新鲜",
            "stale": "数据过期",
            "unknown": "新鲜度未知",
        }.get(freshness_status_code, self._display_value(freshness_status_code))
        must_not_use_for_decision = bool(summary.get("must_not_use_for_decision"))
        blocked_reason_code = str(summary.get("blocked_reason") or "")
        observation_context: list[str] = []
        if observed_at != "—":
            observation_context.append(f"源观测 {observed_at}")
        if as_of_date != "—":
            observation_context.append(f"分析截至 {as_of_date}")
        if freshness_status_code:
            observation_context.append(f"新鲜度 {freshness_status_label}")
        if observation_context:
            trend = f"{trend}；{'；'.join(observation_context)}"
        raw_warnings = summary.get("warnings")
        warnings = (
            [self._operator_text(item) for item in raw_warnings]
            if isinstance(raw_warnings, list)
            else []
        )
        error = self._operator_text(summary.get("error") or "")
        warning = error or (warnings[0] if warnings else "无")
        status_payload = {
            **payload,
            "must_not_use_for_decision": must_not_use_for_decision,
        }
        status = self._status_label(status_code, status_payload)
        quadrant_distribution = self._regime_distribution_rows(payload, available=available)
        return {
            "kind": "detail",
            "title": self._action_title(action),
            "status": status,
            "freshness_status": freshness_status_code,
            "freshness_status_label": freshness_status_label,
            "confidence_unit": "percent",
            "quadrant_distribution": quadrant_distribution,
            "observed_at": observed_at,
            "as_of_date": as_of_date,
            "must_not_use_for_decision": must_not_use_for_decision,
            "blocked_reason": self._operator_text(blocked_reason_code),
            "blocked_reason_code": blocked_reason_code,
            "fields": [
                {"key": "current_regime", "label": "当前判断", "value": regime},
                {"key": "confidence", "label": "置信度", "value": confidence},
                {"key": "trend", "label": "增长与通胀趋势", "value": trend},
                {"key": "warning", "label": "拐点预警", "value": warning},
                {"key": "observed_at", "label": "源观测日期", "value": observed_at},
                {
                    "key": "freshness_status",
                    "label": "数据新鲜度",
                    "value": freshness_status_label,
                },
                {
                    "key": "must_not_use_for_decision",
                    "label": "决策状态",
                    "value": "不可用于决策" if must_not_use_for_decision else "未阻断",
                },
                {
                    "key": "blocked_reason",
                    "label": "阻断原因",
                    "value": self._operator_text(blocked_reason_code or "无"),
                },
                {
                    "key": "growth_level",
                    "label": "增长水平",
                    "value": self._display_value(summary.get("growth_level")),
                },
                {
                    "key": "inflation_level",
                    "label": "通胀水平",
                    "value": self._display_value(summary.get("inflation_level")),
                },
                {
                    "key": "data_source",
                    "label": "数据来源",
                    "value": self._display_value(summary.get("source")),
                },
                {
                    "key": "as_of_date",
                    "label": "查询截止日",
                    "value": as_of_date,
                },
            ],
            "nested": [],
            "business_summary": (
                f"当前判断 {regime}；置信度 {confidence}%；"
                f"源观测 {observed_at}；分析截止 {as_of_date}"
            ),
            "blocking_reason": error if not available else "",
            "next_steps": [],
            "debug_hidden_fields": ["distribution", "momentum", "history"],
        }

    def _regime_trend_label(self, value: Any) -> str:
        """Translate the bounded Regime trend vocabulary for operator display."""

        normalized = str(value or "flat").strip().lower()
        return {
            "up": "上行",
            "rising": "上行",
            "improving": "改善",
            "down": "下行",
            "falling": "下行",
            "deteriorating": "走弱",
            "flat": "持平",
            "stable": "稳定",
        }.get(normalized, self._display_value(value))
