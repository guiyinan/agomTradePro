"""
Macro Data Adapter for Prompt Placeholder Resolution.

This adapter fetches macroeconomic data and resolves placeholders
in prompt templates.
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Union

from apps.macro.domain.entities import MacroIndicator
from apps.macro.infrastructure.repositories import DjangoMacroRepository


class MacroDataAdapter:
    """
    宏观数据适配器

    负责将Prompt中的占位符解析为实际宏观数据。

    支持的占位符类型：
    - {{PMI}} -> 最新PMI数值
    - {{CPI}} -> 最新CPI数值
    - {{MACRO_DATA}} -> 结构化宏观数据摘要
    """

    # 默认指标列表
    DEFAULT_INDICATORS = [
        "CN_PMI",    # PMI
        "CN_CPI",    # CPI
        "CN_PPI",    # PPI
        "CN_M2",     # M2
    ]

    # 指标显示名称映射
    INDICATOR_NAMES = {
        "CN_PMI": "PMI",
        "CN_CPI": "CPI",
        "CN_PPI": "PPI",
        "CN_M2": "M2",
        "CN_VALUE_ADDED": "工业增加值",
        "CN_RETAIL_SALES": "社会消费品零售",
        "CN_GDP_DEFLATOR": "GDP平减指数",
        "SHIBOR": "SHIBOR",
    }

    def __init__(self):
        self.macro_repository = DjangoMacroRepository()

    def get_indicator_value(
        self,
        indicator_code: str,
        as_of_date: date | None = None
    ) -> float | None:
        """获取单个指标最新值

        Args:
            indicator_code: 指标代码（如 CN_PMI）
            as_of_date: 截止日期（Point-in-Time查询）

        Returns:
            指标值，不存在返回None
        """
        # 获取最新观测日期
        latest_date = self.macro_repository.get_latest_observation_date(
            code=indicator_code,
            as_of_date=as_of_date
        )

        if not latest_date:
            return None

        # 获取该日期的指标
        indicator = self.macro_repository.get_by_code_and_date(
            code=indicator_code,
            observed_at=latest_date
        )

        return float(indicator.value) if indicator else None

    def get_indicator_series(
        self,
        indicator_code: str,
        start_date: date,
        end_date: date,
        use_pit: bool = True
    ) -> list[dict[str, Any]]:
        """获取指标时序数据

        Args:
            indicator_code: 指标代码
            start_date: 开始日期
            end_date: 结束日期
            use_pit: 是否使用Point-in-Time查询

        Returns:
            时序数据列表，格式：
            [
                {"date": "2024-01-01", "value": 50.8, "published_at": "2024-01-02"},
                ...
            ]
        """
        indicators = self.macro_repository.get_series(
            code=indicator_code,
            start_date=start_date,
            end_date=end_date,
            use_pit=use_pit
        )

        return [
            {
                "date": ind.reporting_period.isoformat(),
                "value": float(ind.value),
                "published_at": ind.published_at.isoformat() if ind.published_at else None
            }
            for ind in indicators
        ]

    def get_macro_summary(
        self,
        as_of_date: date | None = None,
        indicators: list[str] | None = None
    ) -> dict[str, Any]:
        """
        获取宏观指标摘要（用于{{MACRO_DATA}}占位符）

        Args:
            as_of_date: 截止日期
            indicators: 指标代码列表，默认使用DEFAULT_INDICATORS

        Returns:
            结构化摘要数据：
            {
                "as_of_date": "2024-01-15",
                "indicators": {
                    "PMI": {"value": 50.8, "change": "+0.2", "trend": "up"},
                    "CPI": {"value": 2.1, "change": "-0.1", "trend": "down"},
                    ...
                },
                "summary": "PMI回升至50.8，显示制造业温和扩张..."
            }
        """
        if indicators is None:
            indicators = self.DEFAULT_INDICATORS

        indicator_data = {}
        summary_parts = []

        for code in indicators:
            value = self.get_indicator_value(code, as_of_date)
            if value is not None:
                # 计算变化和趋势
                change, trend = self._calculate_change(code, as_of_date)
                display_name = self.INDICATOR_NAMES.get(code, code)

                indicator_data[display_name] = {
                    "value": value,
                    "change": change,
                    "trend": trend
                }

                # 生成摘要文本
                trend_text = "上升" if trend == "up" else "下降" if trend == "down" else "持平"
                summary_parts.append(f"{display_name}为{value}，{trend_text}")

        # 生成汇总文本
        summary = ""
        if summary_parts:
            if len(summary_parts) <= 2:
                summary = "，".join(summary_parts) + "。"
            else:
                summary = "，".join(summary_parts[:-1]) + f"，{summary_parts[-1]}"

        return {
            "as_of_date": (as_of_date or date.today()).isoformat(),
            "indicators": indicator_data,
            "summary": summary
        }

    def resolve_placeholder(
        self,
        placeholder_name: str,
        as_of_date: date | None = None
    ) -> float | dict[str, Any] | None:
        """
        解析占位符

        支持的占位符：
        - PMI, CPI, PPI, M2等 -> 最新值
        - MACRO_DATA -> 完整摘要

        Args:
            placeholder_name: 占位符名称
            as_of_date: 截止日期

        Returns:
            占位符值
        """
        # 处理特殊占位符
        if placeholder_name == "MACRO_DATA":
            return self.get_macro_summary(as_of_date)

        # 处理指标代码
        # 先尝试直接代码
        value = self.get_indicator_value(placeholder_name, as_of_date)
        if value is not None:
            return value

        # 尝试名称映射
        for code, name in self.INDICATOR_NAMES.items():
            if name == placeholder_name:
                return self.get_indicator_value(code, as_of_date)

        return None

    def _calculate_change(
        self,
        indicator_code: str,
        as_of_date: date | None
    ) -> tuple:
        """计算指标变化

        Returns:
            (变化字符串, 趋势方向)
            例如: ("+0.2", "up"), ("-0.1", "down"), ("0.0", "stable")
        """
        # 获取当前值和上一期值
        current_date = self.macro_repository.get_latest_observation_date(
            code=indicator_code,
            as_of_date=as_of_date
        )

        if not current_date:
            return ("0.0", "stable")

        # 获取最近两期数据
        series = self.get_indicator_series(
            indicator_code,
            start_date=current_date - timedelta(days=90),
            end_date=current_date
        )

        if len(series) < 2:
            return ("0.0", "stable")

        current = series[-1]["value"]
        previous = series[-2]["value"]

        change = current - previous
        change_str = f"{change:+.1f}"

        if change > 0.01:
            trend = "up"
        elif change < -0.01:
            trend = "down"
        else:
            trend = "stable"

        return (change_str, trend)


class FunctionExecutor:
    """
    函数执行器

    支持{{TREND(PMI,6m)}}等函数占位符。
    """

    def __init__(self, macro_adapter: MacroDataAdapter):
        self.macro_adapter = macro_adapter
        # 趋势计算器将在Application层注入
        self.trend_calculator = None

    def set_trend_calculator(self, calculator):
        """设置趋势计算器"""
        self.trend_calculator = calculator

    def execute_function(
        self,
        function_name: str,
        params: dict[str, Any]
    ) -> Any:
        """
        执行函数

        支持的函数：
        - TREND(indicator, period): 计算趋势
        - LATEST(indicator): 获取最新值
        - SERIES(indicator, days): 获取时序数据

        Args:
            function_name: 函数名
            params: 参数字典

        Returns:
            函数结果
        """
        if function_name == "LATEST":
            return self._execute_latest(params)
        elif function_name == "SERIES":
            return self._execute_series(params)
        elif function_name == "TREND":
            return self._execute_trend(params)
        else:
            raise ValueError(f"Unknown function: {function_name}")

    def _execute_latest(self, params: dict[str, Any]) -> float | None:
        """执行LATEST函数"""
        indicator = params.get("indicator")
        as_of_date = params.get("as_of_date")

        if not indicator:
            raise ValueError("LATEST function requires 'indicator' parameter")

        return self.macro_adapter.get_indicator_value(indicator, as_of_date)

    def _execute_series(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        """执行SERIES函数"""
        indicator = params.get("indicator")
        days = params.get("days", 30)
        as_of_date = params.get("as_of_date")

        if not indicator:
            raise ValueError("SERIES function requires 'indicator' parameter")

        end_date = as_of_date or date.today()
        start_date = end_date - timedelta(days=days)

        return self.macro_adapter.get_indicator_series(
            indicator, start_date, end_date
        )

    def _execute_trend(self, params: dict[str, Any]) -> dict[str, Any]:
        """执行TREND函数"""
        indicator = params.get("indicator")
        period = params.get("period", "3m")
        as_of_date = params.get("as_of_date")

        if not indicator:
            raise ValueError("TREND function requires 'indicator' parameter")

        # 计算时间范围
        days_map = {
            "1m": 30, "3m": 90, "6m": 180, "1y": 365,
            "2y": 730, "5y": 1825
        }
        days = days_map.get(period, 90)

        end_date = as_of_date or date.today()
        start_date = end_date - timedelta(days=days)

        series = self.macro_adapter.get_indicator_series(
            indicator, start_date, end_date
        )

        if len(series) < 2:
            return {
                "indicator": indicator,
                "period": period,
                "trend": "unknown",
                "change": 0,
                "start_value": None,
                "end_value": None,
            }

        start_value = series[0]["value"]
        end_value = series[-1]["value"]
        change = end_value - start_value
        change_pct = (change / start_value * 100) if start_value != 0 else 0

        # 判断趋势
        if change_pct > 1:
            trend = "up"
        elif change_pct < -1:
            trend = "down"
        else:
            trend = "flat"

        return {
            "indicator": indicator,
            "period": period,
            "trend": trend,
            "change": round(change, 2),
            "change_pct": round(change_pct, 2),
            "start_value": start_value,
            "end_value": end_value,
            "data_points": len(series),
        }
