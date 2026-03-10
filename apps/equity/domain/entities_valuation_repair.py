"""
估值修复跟踪 Domain 层实体定义

遵循四层架构规范：
- Domain 层禁止导入 django.*、pandas、numpy、requests
- 只使用 Python 标准库和 dataclasses
"""

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Optional


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
