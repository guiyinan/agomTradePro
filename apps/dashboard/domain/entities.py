"""
Dashboard Domain Entities

仪表盘领域实体定义。
仅使用 Python 标准库，不依赖 Django、pandas 等外部库。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional, Union


class CardType(Enum):
    """卡片类型"""
    METRIC = "metric"  # 指标卡片
    CHART = "chart"  # 图表卡片
    LIST = "list"  # 列表卡片
    ALERT = "alert"  # 告警卡片
    TABLE = "table"  # 表格卡片
    CUSTOM = "custom"  # 自定义卡片


class WidgetType(Enum):
    """组件类型"""
    LINE_CHART = "line_chart"
    BAR_CHART = "bar_chart"
    PIE_CHART = "pie_chart"
    GAUGE = "gauge"
    PROGRESS = "progress"
    SPARKLINE = "sparkline"
    HEATMAP = "heatmap"
    TREEMAP = "treemap"
    STAT_CARD = "stat_card"
    INFO_CARD = "info_card"


class ChartDataType(Enum):
    """图表数据类型"""
    TIME_SERIES = "time_series"
    CATEGORICAL = "categorical"
    DISTRIBUTION = "distribution"
    HIERARCHICAL = "hierarchical"


class AlertSeverity(Enum):
    """告警级别"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class DataSourceType(Enum):
    """数据源类型"""
    LIVE = "live"  # 实时数据
    CACHED = "cached"  # 缓存数据
    STATIC = "static"  # 静态数据


@dataclass(frozen=True)
class MetricCard:
    """
    指标卡片

    显示单个关键指标的卡片组件。

    Attributes:
        title: 卡片标题
        value: 当前值
        unit: 单位
        prefix: 前缀（如 ¥）
        suffix: 后缀（如 %）
        trend: 趋势方向（up/down/flat）
        trend_value: 趋势变化值
        trend_period: 趋势周期
        comparison_value: 对比值（用于计算变化率）
        comparison_label: 对比标签
        format_pattern: 格式化模式
        icon: 图标
        color: 颜色（hex 或颜色名）
        threshold_warning: 警告阈值
        threshold_critical: 严重阈值
        data_source: 数据源
        last_updated: 最后更新时间
    """

    title: str
    value: Union[float, int, str, Decimal]
    unit: Optional[str] = None
    prefix: Optional[str] = None
    suffix: Optional[str] = None
    trend: Optional[str] = None  # "up", "down", "flat"
    trend_value: Optional[float] = None
    trend_period: Optional[str] = None  # "1d", "1w", "1m"
    comparison_value: Optional[float] = None
    comparison_label: Optional[str] = None
    format_pattern: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    threshold_warning: Optional[float] = None
    threshold_critical: Optional[float] = None
    data_source: Optional[str] = None
    last_updated: Optional[datetime] = None

    def get_formatted_value(self) -> str:
        """
        获取格式化的值

        Returns:
            格式化后的字符串
        """
        if self.format_pattern:
            try:
                if isinstance(self.value, (int, float, Decimal)):
                    return self.format_pattern.format(self.value)
            except (KeyError, ValueError, TypeError):
                pass

        parts = []
        if self.prefix:
            parts.append(self.prefix)
        parts.append(str(self.value))
        if self.suffix:
            parts.append(self.suffix)
        return "".join(parts)

    def get_alert_level(self) -> Optional[AlertSeverity]:
        """
        获取告警级别

        Returns:
            告警级别，如果没有超过阈值则返回 None
        """
        if not isinstance(self.value, (int, float, Decimal)):
            return None

        value = float(self.value)

        if self.threshold_critical is not None:
            if value >= self.threshold_critical:
                return AlertSeverity.CRITICAL
            elif self.threshold_warning is not None and value >= self.threshold_warning:
                return AlertSeverity.WARNING

        return None


@dataclass(frozen=True)
class ChartConfig:
    """
    图表配置

    定义图表的配置参数。

    Attributes:
        chart_type: 图表类型
        data_type: 数据类型
        title: 图表标题
        x_axis_label: X轴标签
        y_axis_label: Y轴标签
        series: 数据系列配置
        colors: 颜色配置
        show_legend: 是否显示图例
        show_grid: 是否显示网格
        interactive: 是否交互式
        height: 图表高度（px）
        width: 图表宽度（px 或 %）
        options: 其他选项
    """

    chart_type: WidgetType
    data_type: ChartDataType = ChartDataType.TIME_SERIES
    title: Optional[str] = None
    x_axis_label: Optional[str] = None
    y_axis_label: Optional[str] = None
    series: List[Dict[str, Any]] = field(default_factory=list)
    colors: Dict[str, str] = field(default_factory=dict)
    show_legend: bool = True
    show_grid: bool = True
    interactive: bool = True
    height: int = 300
    width: str = "100%"
    options: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DashboardWidget:
    """
    仪表盘组件

    仪表盘上的单个组件。

    Attributes:
        widget_id: 组件ID
        widget_type: 组件类型
        title: 组件标题
        config: 组件配置
        data_source: 数据源
        refresh_interval: 刷新间隔（秒）
        cache_ttl: 缓存时间（秒）
        is_visible: 是否可见
        is_collapsed: 是否折叠
        is_loading: 是否加载中
        error_message: 错误消息
        metadata: 元数据
    """

    widget_id: str
    widget_type: WidgetType
    title: Optional[str] = None
    config: Optional[Union[ChartConfig, MetricCard, Dict]] = None
    data_source: Optional[str] = None
    refresh_interval: int = 60  # 默认60秒刷新
    cache_ttl: int = 300  # 默认缓存5分钟
    is_visible: bool = True
    is_collapsed: bool = False
    is_loading: bool = False
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def get_cache_key(self) -> str:
        """
        获取缓存键

        Returns:
            缓存键
        """
        return f"dashboard:widget:{self.widget_id}"


@dataclass(frozen=True)
class DashboardCard:
    """
    仪表盘卡片

    仪表盘上的卡片组件，包含多个 Widget。

    Attributes:
        card_id: 卡片ID
        card_type: 卡片类型
        title: 卡片标题
        widgets: 组件列表
        layout: 布局配置
        position: 位置（行列）
        size: 尺寸（宽高）
        is_visible: 是否可见
        is_collapsible: 是否可折叠
        is_collapsed: 是否折叠
        is_draggable: 是否可拖动
        is_resizable: 是否可调整大小
        dependencies: 依赖的其他卡片ID
        metadata: 元数据
    """

    card_id: str
    card_type: CardType
    title: Optional[str] = None
    widgets: List[DashboardWidget] = field(default_factory=list)
    layout: Optional[str] = None
    position: Optional[Dict[str, int]] = None  # {"row": 0, "col": 0}
    size: Optional[Dict[str, int]] = None  # {"width": 4, "height": 3}
    is_visible: bool = True
    is_collapsible: bool = True
    is_collapsed: bool = False
    is_draggable: bool = True
    is_resizable: bool = True
    dependencies: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def get_all_widgets(self) -> List[DashboardWidget]:
        """
        获取所有组件

        Returns:
            组件列表
        """
        return self.widgets

    def get_visible_widgets(self) -> List[DashboardWidget]:
        """
        获取可见组件

        Returns:
            可见组件列表
        """
        return [w for w in self.widgets if w.is_visible]


@dataclass(frozen=True)
class DashboardLayout:
    """
    仪表盘布局

    定义仪表盘的整体布局。

    Attributes:
        layout_id: 布局ID
        name: 布局名称
        description: 描述
        cards: 卡片列表
        columns: 列数
        row_height: 行高
        gutter: 间距
        is_default: 是否默认布局
        metadata: 元数据
    """

    layout_id: str
    name: str
    description: Optional[str] = None
    cards: List[DashboardCard] = field(default_factory=list)
    columns: int = 12  # 使用12列网格
    row_height: int = 60
    gutter: int = 16
    is_default: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def get_visible_cards(self) -> List[DashboardCard]:
        """
        获取可见卡片

        Returns:
            可见卡片列表（按位置排序）
        """
        visible = [c for c in self.cards if c.is_visible]
        # 按位置排序
        return sorted(
            visible,
            key=lambda c: (
                c.position.get("row", 0) if c.position else 0,
                c.position.get("col", 0) if c.position else 0
            )
        )


@dataclass(frozen=True)
class AlertConfig:
    """
    告警配置

    定义告警规则和通知方式。

    Attributes:
        alert_id: 告警ID
        name: 告警名称
        description: 描述
        metric: 监控指标
        condition: 告警条件
        severity: 告警级别
        threshold: 阈值
        notification_channels: 通知渠道
        is_enabled: 是否启用
        cooldown: 冷却时间（秒）
        metadata: 元数据
    """

    alert_id: str
    name: str
    description: Optional[str] = None
    metric: Optional[str] = None
    condition: Optional[str] = None
    severity: AlertSeverity = AlertSeverity.WARNING
    threshold: Optional[float] = None
    notification_channels: List[str] = field(default_factory=list)
    is_enabled: bool = True
    cooldown: int = 300  # 默认5分钟冷却
    metadata: Dict[str, Any] = field(default_factory=dict)

    def should_alert(self, current_value: float) -> bool:
        """
        判断是否应该告警

        Args:
            current_value: 当前值

        Returns:
            是否应该告警
        """
        if not self.is_enabled or self.threshold is None:
            return False

        # 简单阈值判断，实际应该根据 condition 解析
        return current_value >= self.threshold


@dataclass(frozen=True)
class DashboardPreferences:
    """
    仪表盘用户偏好

    用户对仪表盘的个人配置。

    Attributes:
        user_id: 用户ID
        layout_id: 选择的布局ID
        hidden_cards: 隐藏的卡片ID列表
        collapsed_cards: 折叠的卡片ID列表
        card_order: 卡片顺序
        custom_card_config: 自定义卡片配置
        theme: 主题
        refresh_enabled: 是否启用自动刷新
        refresh_interval: 刷新间隔（秒）
        last_updated: 最后更新时间
    """

    user_id: int
    layout_id: str
    hidden_cards: List[str] = field(default_factory=list)
    collapsed_cards: List[str] = field(default_factory=list)
    card_order: List[str] = field(default_factory=list)
    custom_card_config: Dict[str, Any] = field(default_factory=dict)
    theme: str = "light"
    refresh_enabled: bool = True
    refresh_interval: int = 60
    last_updated: Optional[datetime] = None


# ========== 类型别名 ==========

WidgetData = Dict[str, Any]
"""组件数据类型别名"""

CardData = Dict[str, Any]
"""卡片数据类型别名"""
