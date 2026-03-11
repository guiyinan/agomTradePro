"""
估值修复跟踪 Domain 层实体定义

遵循四层架构规范：
- Domain 层禁止导入 django.*、pandas、numpy、requests
- 只使用 Python 标准库和 dataclasses
"""

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Optional


@dataclass(frozen=True)
class ValuationRepairConfig:
    """估值修复策略参数配置（不可变值对象）

    所有阈值集中管理，便于：
    - 单元测试注入不同配置
    - 未来从 settings 覆盖
    - 最终迁移到数据库配置表

    Attributes:
        min_history_points: 最小历史样本数（低于此值抛异常）
        default_lookback_days: 默认回看交易日数
        confirm_window: 修复确认窗口（交易日）
        min_rebound: 最小反弹幅度（百分位点）
        stall_window: 停滞检测窗口（交易日）
        stall_min_progress: 停滞最小进展阈值
        target_percentile: 目标百分位
        undervalued_threshold: 低估阈值
        near_target_threshold: 接近目标阈值
        overvalued_threshold: 高估阈值
        pe_weight: PE 权重
        pb_weight: PB 权重
        confidence_base: 置信度基础值
        confidence_sample_bonus: 样本数达标奖励
        confidence_sample_threshold: 样本数达标阈值
        confidence_blend_bonus: 使用 pe_pb_blend 奖励
        confidence_repair_start_bonus: 已识别修复起点奖励
        confidence_not_stalled_bonus: 非停滞奖励
        repairing_threshold: REPAIRING 阶段阈值（相对起点）
        eta_max_days: ETA 最大天数
    """
    # 历史数据要求
    min_history_points: int = 120
    default_lookback_days: int = 756

    # 修复确认参数
    confirm_window: int = 20
    min_rebound: float = 0.05

    # 停滞检测参数
    stall_window: int = 40
    stall_min_progress: float = 0.02

    # 阶段判定阈值
    target_percentile: float = 0.50
    undervalued_threshold: float = 0.20
    near_target_threshold: float = 0.45
    overvalued_threshold: float = 0.80

    # 复合百分位权重
    pe_weight: float = 0.6
    pb_weight: float = 0.4

    # 置信度计算参数
    confidence_base: float = 0.4
    confidence_sample_threshold: int = 252
    confidence_sample_bonus: float = 0.2
    confidence_blend_bonus: float = 0.15
    confidence_repair_start_bonus: float = 0.15
    confidence_not_stalled_bonus: float = 0.1

    # 其他阈值
    repairing_threshold: float = 0.10  # REPAIRING 阶段需要相对起点提升
    eta_max_days: int = 999


# 默认配置实例（单例）
DEFAULT_VALUATION_REPAIR_CONFIG = ValuationRepairConfig()


class ValuationRepairPhase(Enum):
    """估值修复阶段枚举

    阶段定义按优先级从高到低：
    1. OVERSHOOTING - 估值超涨（综合分位 >= 0.80）
    2. COMPLETED - 修复完成（综合分位 >= 0.50 且 < 0.80，有修复起点）
    3. NEAR_TARGET - 接近目标（综合分位 >= 0.45 且 < 0.50，有修复起点）
    4. STALLED - 修复停滞（有修复起点且停滞，综合分位 < 0.45）
    5. REPAIRING - 正在修复（有修复起点，综合分位 >= 起点+0.10 且 < 0.45）
    6. REPAIR_STARTED - 刚启动修复（有修复起点，综合分位 < 起点+0.10）
    7. UNDERVALUED - 低估（无修复起点，综合分位 < 0.20）
    8. NO_REPAIR_NEEDED - 无需修复（其余情况）
    """
    NO_REPAIR_NEEDED = "no_repair_needed"
    UNDERVALUED = "undervalued"
    REPAIR_STARTED = "repair_started"
    REPAIRING = "repairing"
    NEAR_TARGET = "near_target"
    COMPLETED = "completed"
    OVERSHOOTING = "overshooting"
    STALLED = "stalled"


@dataclass(frozen=True)
class PercentilePoint:
    """估值百分位时间序列点（值对象）

    Attributes:
        trade_date: 交易日期
        pe_percentile: PE 百分位（PE <= 0 或缺失时为 None）
        pb_percentile: PB 百分位
        composite_percentile: 综合百分位
        composite_method: 综合方法（"pe_pb_blend" 或 "pb_only"）
    """
    trade_date: date
    pe_percentile: Optional[float]
    pb_percentile: float
    composite_percentile: float
    composite_method: str  # "pe_pb_blend" / "pb_only"


@dataclass(frozen=True)
class ValuationRepairStatus:
    """估值修复状态（值对象）

    完整描述单只股票在某个时点的估值修复状态。

    Attributes:
        stock_code: 股票代码
        stock_name: 股票名称
        as_of_date: 分析基准日期

        phase: 修复阶段（字符串值，便于序列化）
        signal: 投资信号（"watch", "opportunity", "in_progress",
                "near_exit", "take_profit", "stalled", "none"）

        current_pe: 当前 PE（PE <= 0 时为 None）
        current_pb: 当前 PB
        pe_percentile: PE 百分位（可能为 None）
        pb_percentile: PB 百分位
        composite_percentile: 综合百分位
        composite_method: 综合方法

        repair_start_date: 修复启动日期（若已识别）
        repair_start_percentile: 修复启动时的百分位（若已识别）
        lowest_percentile: 窗口内最低百分位
        lowest_percentile_date: 最低百分位日期

        repair_progress: 修复进度（0-1，仅在已启动修复时有值）
        target_percentile: 目标百分位（固定为 0.50）
        repair_speed_per_30d: 修复速度（每 30 交易日提升的百分位）
        estimated_days_to_target: 预计到达目标的交易日数

        is_stalled: 是否停滞
        stall_start_date: 停滞开始日期
        stall_duration_trading_days: 停滞持续交易日数
        repair_duration_trading_days: 修复持续交易日数

        lookback_trading_days: 回看窗口交易日数
        confidence: 置信度（0-1）
        description: 状态描述文本
    """
    stock_code: str
    stock_name: str
    as_of_date: date

    phase: str
    signal: str  # "watch", "opportunity", "in_progress", "near_exit", "take_profit", "stalled", "none"

    current_pe: Optional[float]
    current_pb: float
    pe_percentile: Optional[float]
    pb_percentile: float
    composite_percentile: float
    composite_method: str

    repair_start_date: Optional[date]
    repair_start_percentile: Optional[float]
    lowest_percentile: float
    lowest_percentile_date: date

    repair_progress: Optional[float]  # 0-1，仅在已启动修复时有值
    target_percentile: float
    repair_speed_per_30d: Optional[float]
    estimated_days_to_target: Optional[int]

    is_stalled: bool
    stall_start_date: Optional[date]
    stall_duration_trading_days: int
    repair_duration_trading_days: int

    lookback_trading_days: int
    confidence: float
    description: str
