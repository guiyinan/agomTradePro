"""
Dashboard Domain Services

仪表盘领域服务。
仅使用 Python 标准库，不依赖 Django、pandas 等外部库。
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Union

from .entities import (
    DashboardCard,
    DashboardWidget,
    DashboardLayout,
    ChartConfig,
    MetricCard,
    AlertConfig,
    DashboardPreferences,
    CardType,
    WidgetType,
    AlertSeverity,
)
from .rules import (
    DashboardCardVisibilityRule,
    RuleEngine,
)


@dataclass
class LayoutResolutionResult:
    """
    布局解析结果

    Attributes:
        visible_cards: 可见卡片列表
        visible_widgets: 可见组件列表
        hidden_count: 隐藏卡片数量
        total_cards: 总卡片数
        layout_metadata: 布局元数据
    """

    visible_cards: List[DashboardCard]
    visible_widgets: List[DashboardWidget]
    hidden_count: int
    total_cards: int
    layout_metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MetricCalculationResult:
    """
    指标计算结果

    Attributes:
        metric_name: 指标名称
        value: 计算值
        formatted_value: 格式化值
        trend: 趋势方向
        trend_value: 趋势值
        severity: 告警级别
        timestamp: 计算时间
        metadata: 元数据
    """

    metric_name: str
    value: Union[float, int, str]
    formatted_value: str
    trend: Optional[str] = None
    trend_value: Optional[float] = None
    severity: Optional[AlertSeverity] = None
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


class DashboardLayoutService:
    """
    仪表盘布局服务

    负责解析和应用仪表盘布局规则。

    Example:
        >>> service = DashboardLayoutService()
        >>> result = service.resolve_layout(layout, user_preferences, context)
    """

    def resolve_layout(
        self,
        layout: DashboardLayout,
        user_preferences: Optional[DashboardPreferences] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> LayoutResolutionResult:
        """
        解析布局

        根据用户偏好和上下文解析仪表盘布局。

        Args:
            layout: 布局配置
            user_preferences: 用户偏好
            context: 上下文数据

        Returns:
            布局解析结果
        """
        context = context or {}
        hidden_cards = set()

        # 应用用户偏好中的隐藏卡片
        if user_preferences:
            hidden_cards.update(user_preferences.hidden_cards)

        # 应用可见性规则
        rule_engine = RuleEngine()
        for card in layout.cards:
            if card.metadata.get("visibility_conditions"):
                rule = DashboardCardVisibilityRule(
                    card_id=card.card_id,
                    conditions=card.metadata["visibility_conditions"]
                )
                rule_engine.add_rule(rule)

        # 评估可见性
        visible_cards = []
        for card in layout.cards:
            if card.card_id in hidden_cards:
                continue

            # 检查卡片自身的可见性
            if not card.is_visible:
                hidden_cards.add(card.card_id)
                continue

            # 检查可见性规则
            if card.metadata.get("visibility_conditions"):
                rule_context = {
                    **context,
                    "card_id": card.card_id,
                }
                if not rule_engine.evaluate_all_pass(rule_context):
                    hidden_cards.add(card.card_id)
                    continue

            visible_cards.append(card)

        # 应用用户偏好中的卡片顺序
        if user_preferences and user_preferences.card_order:
            order_map = {card_id: i for i, card_id in enumerate(user_preferences.card_order)}
            # 按用户偏好排序，但保留未指定顺序的卡片在最后
            visible_cards.sort(
                key=lambda c: (order_map.get(c.card_id, len(user_preferences.card_order)))
            )

        # 收集所有可见组件
        visible_widgets = []
        for card in visible_cards:
            # 检查卡片是否折叠
            is_collapsed = card.is_collapsed
            if user_preferences and card.card_id in user_preferences.collapsed_cards:
                is_collapsed = True

            if not is_collapsed:
                visible_widgets.extend(card.get_visible_widgets())

        return LayoutResolutionResult(
            visible_cards=visible_cards,
            visible_widgets=visible_widgets,
            hidden_count=len(hidden_cards),
            total_cards=len(layout.cards),
            layout_metadata={
                "layout_id": layout.layout_id,
                "columns": layout.columns,
                "row_height": layout.row_height,
                "resolved_at": datetime.now().isoformat(),
            }
        )

    def calculate_card_position(
        self,
        card: DashboardCard,
        layout: DashboardLayout,
        occupied_positions: List[Dict[str, int]],
    ) -> Dict[str, int]:
        """
        计算卡片位置

        为没有位置的卡片计算合适的位置。

        Args:
            card: 卡片
            layout: 布局
            occupied_positions: 已占用的位置

        Returns:
            计算后的位置 {"row": x, "col": y}
        """
        if card.position:
            return card.position

        # 默认卡片尺寸
        width = card.size.get("width", 4) if card.size else 4
        height = card.size.get("height", 3) if card.size else 3

        # 寻找可用位置
        row = 0
        while row < 100:  # 防止无限循环
            col = 0
            while col + width <= layout.columns:
                # 检查是否与已占用位置重叠
                overlaps = False
                for occupied in occupied_positions:
                    if self._positions_overlap(
                        {"row": row, "col": col, "width": width, "height": height},
                        occupied
                    ):
                        overlaps = True
                        break

                if not overlaps:
                    return {"row": row, "col": col}

                col += 1
            row += 1

        # 如果找不到位置，放在最后
        return {"row": len(occupied_positions), "col": 0}

    def _positions_overlap(
        self,
        pos1: Dict[str, int],
        pos2: Dict[str, int],
    ) -> bool:
        """检查两个位置是否重叠"""
        r1, c1, w1, h1 = pos1.get("row", 0), pos1.get("col", 0), pos1.get("width", 1), pos1.get("height", 1)
        r2, c2, w2, h2 = pos2.get("row", 0), pos2.get("col", 0), pos2.get("width", 1), pos2.get("height", 1)

        # 检查矩形重叠
        return not (
            r1 + h1 <= r2 or  # pos1 在 pos2 上方
            r2 + h2 <= r1 or  # pos2 在 pos1 上方
            c1 + w1 <= c2 or  # pos1 在 pos2 左侧
            c2 + w2 <= c1     # pos2 在 pos1 左侧
        )


class DashboardMetricService:
    """
    仪表盘指标服务

    负责计算和格式化仪表盘指标。

    Example:
        >>> service = DashboardMetricService()
        >>> result = service.calculate_metric("total_assets", data, config)
    """

    def calculate_metric(
        self,
        metric_name: str,
        data: Dict[str, Any],
        config: Optional[MetricCard] = None,
        previous_data: Optional[Dict[str, Any]] = None,
    ) -> MetricCalculationResult:
        """
        计算指标

        Args:
            metric_name: 指标名称
            data: 当前数据
            config: 指标配置
            previous_data: 前期数据（用于计算趋势）

        Returns:
            指标计算结果
        """
        # 获取指标值
        value = self._extract_metric_value(metric_name, data)

        # 格式化值
        if config:
            formatted_value = config.get_formatted_value()
        else:
            formatted_value = self._format_value(value)

        # 计算趋势
        trend = None
        trend_value = None
        if previous_data:
            previous_value = self._extract_metric_value(metric_name, previous_data)
            if previous_value is not None and isinstance(value, (int, float)):
                trend_value = float(value) - float(previous_value)
                if trend_value > 0:
                    trend = "up"
                elif trend_value < 0:
                    trend = "down"
                else:
                    trend = "flat"

        # 判断告警级别
        severity = None
        if config:
            severity = config.get_alert_level()

        return MetricCalculationResult(
            metric_name=metric_name,
            value=value,
            formatted_value=formatted_value,
            trend=trend,
            trend_value=trend_value,
            severity=severity,
        )

    def _extract_metric_value(self, metric_name: str, data: Dict[str, Any]) -> Any:
        """从数据中提取指标值"""
        # 支持嵌套路径，如 "portfolio.total_value"
        keys = metric_name.split(".")
        value = data
        for key in keys:
            if isinstance(value, dict):
                value = value.get(key)
            else:
                return None
        return value

    def _format_value(self, value: Any) -> str:
        """格式化值"""
        if isinstance(value, float):
            if abs(value) >= 1_000_000:
                return f"{value / 1_000_000:.2f}M"
            elif abs(value) >= 1_000:
                return f"{value / 1_000:.2f}K"
            else:
                return f"{value:.2f}"
        elif isinstance(value, int):
            return f"{value:,}"
        else:
            return str(value)

    def calculate_change_rate(
        self,
        current_value: float,
        previous_value: float,
    ) -> float:
        """
        计算变化率

        Args:
            current_value: 当前值
            previous_value: 前期值

        Returns:
            变化率（百分比）
        """
        if previous_value == 0:
            return 0.0
        return ((current_value - previous_value) / previous_value) * 100


class DashboardChartService:
    """
    仪表盘图表服务

    负责处理图表数据和配置。

    Example:
        >>> service = DashboardChartService()
        >>> chart_data = service.prepare_chart_data(config, raw_data)
    """

    def prepare_chart_data(
        self,
        config: ChartConfig,
        raw_data: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        准备图表数据

        Args:
            config: 图表配置
            raw_data: 原始数据

        Returns:
            处理后的图表数据
        """
        # 根据图表类型处理数据
        if config.chart_type == WidgetType.LINE_CHART:
            return self._prepare_line_chart_data(config, raw_data)
        elif config.chart_type == WidgetType.BAR_CHART:
            return self._prepare_bar_chart_data(config, raw_data)
        elif config.chart_type == WidgetType.PIE_CHART:
            return self._prepare_pie_chart_data(config, raw_data)
        else:
            return {"data": raw_data}

    def _prepare_line_chart_data(
        self,
        config: ChartConfig,
        raw_data: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """准备折线图数据"""
        # 提取系列数据
        series_data = {}
        x_values = []

        for item in raw_data:
            x_val = item.get(config.x_axis_label or "x")
            if x_val is not None:
                x_values.append(x_val)

            for series in config.series:
                series_name = series.get("name", "value")
                y_key = series.get("y_key", "y")
                if y_key in item:
                    if series_name not in series_data:
                        series_data[series_name] = []
                    series_data[series_name].append(item[y_key])

        return {
            "x": x_values,
            "series": series_data,
            "config": {
                "title": config.title,
                "x_label": config.x_axis_label,
                "y_label": config.y_axis_label,
                "colors": config.colors,
                "show_legend": config.show_legend,
                "show_grid": config.show_grid,
            }
        }

    def _prepare_bar_chart_data(
        self,
        config: ChartConfig,
        raw_data: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """准备柱状图数据"""
        categories = []
        values = []

        for item in raw_data:
            categories.append(item.get(config.x_axis_label or "category", ""))
            values.append(item.get(config.y_axis_label or "value", 0))

        return {
            "categories": categories,
            "values": values,
            "config": {
                "title": config.title,
                "x_label": config.x_axis_label,
                "y_label": config.y_axis_label,
                "colors": config.colors,
            }
        }

    def _prepare_pie_chart_data(
        self,
        config: ChartConfig,
        raw_data: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """准备饼图数据"""
        labels = []
        values = []

        for item in raw_data:
            labels.append(item.get("label", ""))
            values.append(item.get("value", 0))

        return {
            "labels": labels,
            "values": values,
            "config": {
                "title": config.title,
                "colors": config.colors,
                "show_legend": config.show_legend,
            }
        }


class DashboardAlertService:
    """
    仪表盘告警服务

    负责评估和生成告警。

    Example:
        >>> service = DashboardAlertService()
        >>> alerts = service.evaluate_alerts(alert_configs, current_data)
    """

    def evaluate_alerts(
        self,
        alert_configs: List[AlertConfig],
        current_data: Dict[str, Any],
        cooldown_state: Optional[Dict[str, datetime]] = None,
    ) -> List[Dict[str, Any]]:
        """
        评估告警

        Args:
            alert_configs: 告警配置列表
            current_data: 当前数据
            cooldown_state: 冷却状态

        Returns:
            触发的告警列表
        """
        cooldown_state = cooldown_state or {}
        triggered_alerts = []
        now = datetime.now()

        for config in alert_configs:
            if not config.is_enabled:
                continue

            # 检查冷却时间
            if config.alert_id in cooldown_state:
                last_triggered = cooldown_state[config.alert_id]
                if (now - last_triggered).total_seconds() < config.cooldown:
                    continue

            # 评估告警条件
            if config.metric and config.metric in current_data:
                value = current_data[config.metric]
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    continue

                if config.should_alert(value):
                    triggered_alerts.append({
                        "alert_id": config.alert_id,
                        "name": config.name,
                        "severity": config.severity.value,
                        "metric": config.metric,
                        "value": value,
                        "threshold": config.threshold,
                        "message": f"{config.name}: {config.metric} = {value}, 阈值 = {config.threshold}",
                        "triggered_at": now.isoformat(),
                    })
                    # 更新冷却状态
                    cooldown_state[config.alert_id] = now

        return triggered_alerts


# ========== 便捷函数 ==========

def resolve_dashboard_layout(
    layout: DashboardLayout,
    user_preferences: Optional[DashboardPreferences] = None,
    context: Optional[Dict[str, Any]] = None,
) -> LayoutResolutionResult:
    """
    解析仪表盘布局的便捷函数

    Args:
        layout: 布局配置
        user_preferences: 用户偏好
        context: 上下文数据

    Returns:
        布局解析结果
    """
    service = DashboardLayoutService()
    return service.resolve_layout(layout, user_preferences, context)


def calculate_dashboard_metric(
    metric_name: str,
    data: Dict[str, Any],
    config: Optional[MetricCard] = None,
) -> MetricCalculationResult:
    """
    计算仪表盘指标的便捷函数

    Args:
        metric_name: 指标名称
        data: 数据
        config: 指标配置

    Returns:
        指标计算结果
    """
    service = DashboardMetricService()
    return service.calculate_metric(metric_name, data, config)
