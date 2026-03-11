"""
估值修复跟踪 Domain 层核心算法

遵循四层架构规范：
- Domain 层禁止导入 django.*、pandas、numpy、requests
- 只使用 Python 标准库和 dataclasses
"""

from dataclasses import dataclass
from datetime import date
from typing import List, Dict, Tuple, Optional
import math

# 导入实体类型
from .entities_valuation_repair import (
    ValuationRepairPhase,
    PercentilePoint,
    ValuationRepairStatus,
    ValuationRepairConfig,
    DEFAULT_VALUATION_REPAIR_CONFIG,
)


# ============== 异常定义 ==============

class InsufficientHistoryError(Exception):
    """历史数据不足"""
    pass


class InvalidValuationDataError(Exception):
    """无效估值数据（如 PB <= 0）"""
    pass


# ============== 核心算法函数 ==============

def compute_composite_percentile(
    pe: Optional[float],
    pb: float,
    config: ValuationRepairConfig = DEFAULT_VALUATION_REPAIR_CONFIG
) -> Tuple[float, str]:
    """计算综合百分位

    Args:
        pe: PE 百分位（可能为 None 或负数）
        pb: PB 百分位
        config: 策略参数配置

    Returns:
        (综合百分位, 方法名)

    规则：
    - 若 pe > 0：composite = pe * pe_weight + pb * pb_weight，method = "pe_pb_blend"
    - 若 pe <= 0 或 pe is None：composite = pb，method = "pb_only"
    """
    if pe is not None and pe > 0:
        composite = pe * config.pe_weight + pb * config.pb_weight
        return composite, "pe_pb_blend"
    else:
        return pb, "pb_only"


def _calculate_percentile(value: float, historical_values: List[float]) -> float:
    """计算单个值的百分位

    Args:
        value: 当前值
        historical_values: 历史值列表（包含当前值）

    Returns:
        百分位（0-1）

    注意：
    - 第一个值只有自己，百分位为 0（因为没有比它小的值）
    - 使用 rank / n 的计算方式
    """
    if not historical_values:
        return 0.5  # 无历史数据时返回中值

    n = len(historical_values)

    # 计算有多少值小于当前值
    rank = sum(1 for v in historical_values if v < value)

    # 相等的值加 0.5 权重
    equal_count = sum(1 for v in historical_values if v == value)
    rank += equal_count * 0.5

    return rank / n


def build_percentile_series(
    history: List[Dict],
    lookback_days: Optional[int] = None,
    config: ValuationRepairConfig = DEFAULT_VALUATION_REPAIR_CONFIG
) -> List[PercentilePoint]:
    """构建百分位时间序列

    Args:
        history: 历史估值数据列表，每个元素包含：
            - trade_date: date
            - pe: float
            - pb: float
        lookback_days: 回看窗口（交易日样本数），None 时使用 config 默认值
        config: 策略参数配置

    Returns:
        PercentilePoint 列表，按日期升序

    Raises:
        InsufficientHistoryError: 历史样本数不足
        InvalidValuationDataError: PB <= 0

    算法：
    1. 截断到最近 lookback_days 条记录
    2. 至少要求 min_history_points 条
    3. 对第 i 个点，仅使用 [0:i] 数据计算百分位（扩张窗口，无前视偏差）
    4. pe <= 0 时该点 pe_percentile = None
    5. pb <= 0 视为无效数据，抛出异常
    """
    if lookback_days is None:
        lookback_days = config.default_lookback_days

    if not history:
        raise InsufficientHistoryError("历史数据为空")

    # 截断到最近 lookback_days 条
    truncated = history[-lookback_days:] if len(history) > lookback_days else history

    if len(truncated) < config.min_history_points:
        raise InsufficientHistoryError(
            f"历史数据不足：需要至少 {config.min_history_points} 条，实际 {len(truncated)} 条"
        )

    points: List[PercentilePoint] = []

    for i, record in enumerate(truncated):
        trade_date = record["trade_date"]
        pe = record["pe"]
        pb = record["pb"]

        # 验证 PB
        if pb is None or pb <= 0:
            raise InvalidValuationDataError(f"PB 必须大于 0，日期 {trade_date} 的 PB = {pb}")

        # 扩张窗口计算百分位
        pe_history = [h["pe"] for h in truncated[:i+1] if h["pe"] is not None and h["pe"] > 0]
        pb_history = [h["pb"] for h in truncated[:i+1]]

        # 计算 PB 百分位
        pb_percentile = _calculate_percentile(pb, pb_history)

        # 计算 PE 百分位（PE <= 0 或 None 时为 None）
        pe_percentile: Optional[float] = None
        if pe is not None and pe > 0:
            pe_percentile = _calculate_percentile(pe, pe_history)

        # 计算综合百分位
        composite_percentile, composite_method = compute_composite_percentile(
            pe_percentile, pb_percentile, config
        )

        points.append(PercentilePoint(
            trade_date=trade_date,
            pe_percentile=pe_percentile,
            pb_percentile=pb_percentile,
            composite_percentile=composite_percentile,
            composite_method=composite_method
        ))

    return points


def detect_repair_start(
    series: List[PercentilePoint],
    confirm_window: Optional[int] = None,
    min_rebound: Optional[float] = None,
    config: ValuationRepairConfig = DEFAULT_VALUATION_REPAIR_CONFIG
) -> Tuple[Optional[date], Optional[float]]:
    """检测修复启动点

    Args:
        series: 百分位时间序列
        confirm_window: 确认窗口（交易日），None 时使用 config 默认值
        min_rebound: 最小反弹幅度，None 时使用 config 默认值
        config: 策略参数配置

    Returns:
        (修复启动日期, 修复启动百分位)

    算法：
    1. 找到窗口内 composite_percentile 全局最低点
    2. 若最低点处于序列最后 confirm_window 以内，不判定为已启动
    3. 若从最低点往后最多 confirm_window 个交易日内，
       任一日 composite - bottom >= min_rebound，则确认修复启动
    """
    if confirm_window is None:
        confirm_window = config.confirm_window
    if min_rebound is None:
        min_rebound = config.min_rebound
    if not series:
        return None, None

    # 找全局最低点
    bottom_idx = 0
    bottom_value = series[0].composite_percentile

    for i, point in enumerate(series):
        if point.composite_percentile < bottom_value:
            bottom_idx = i
            bottom_value = point.composite_percentile

    # 最低点是否过于接近序列尾部
    if bottom_idx >= len(series) - confirm_window:
        return None, None

    # 检查确认窗口内是否有足够反弹
    search_end = min(bottom_idx + confirm_window, len(series))

    for i in range(bottom_idx + 1, search_end):
        rebound = series[i].composite_percentile - bottom_value
        if rebound >= min_rebound:
            return series[bottom_idx].trade_date, bottom_value

    return None, None


def detect_stall(
    series: List[PercentilePoint],
    repair_start_date: date,
    stall_window: Optional[int] = None,
    stall_min_progress: Optional[float] = None,
    config: ValuationRepairConfig = DEFAULT_VALUATION_REPAIR_CONFIG
) -> Tuple[bool, Optional[date], int]:
    """检测修复停滞

    Args:
        series: 百分位时间序列
        repair_start_date: 修复启动日期
        stall_window: 停滞检测窗口（交易日），None 时使用 config 默认值
        stall_min_progress: 停滞最小进展阈值，None 时使用 config 默认值
        config: 策略参数配置

    Returns:
        (是否停滞, 停滞开始日期, 停滞持续交易日数)

    前提：
    - 只有已识别 repair_start_date 才做停滞检测

    判定逻辑：
    1. 取 repair_start_date 之后到当前的序列
    2. 若样本数不足 stall_window，则 is_stalled = False
    3. 观察最近 stall_window 个交易日：
       - max - min < stall_min_progress 则为停滞
       - stall_start_date = 窗口起点
    """
    if stall_window is None:
        stall_window = config.stall_window
    if stall_min_progress is None:
        stall_min_progress = config.stall_min_progress

    if not repair_start_date:
        return False, None, 0

    # 找到修复起始点在序列中的位置
    start_idx = None
    for i, point in enumerate(series):
        if point.trade_date == repair_start_date:
            start_idx = i
            break

    if start_idx is None:
        return False, None, 0

    # 修复起始点之后的序列
    repair_series = series[start_idx:]

    if len(repair_series) < stall_window:
        return False, None, 0

    # 观察最近 stall_window 个交易日
    window = repair_series[-stall_window:]

    window_values = [p.composite_percentile for p in window]
    max_pctl = max(window_values)
    min_pctl = min(window_values)

    if max_pctl - min_pctl < stall_min_progress:
        # 停滞
        stall_start_date = window[0].trade_date
        stall_duration = len(window)
        return True, stall_start_date, stall_duration

    return False, None, 0


def determine_phase(
    composite_percentile: float,
    repair_start_date: Optional[date],
    repair_start_percentile: Optional[float],
    is_stalled: bool,
    config: ValuationRepairConfig = DEFAULT_VALUATION_REPAIR_CONFIG
) -> str:
    """确定修复阶段

    Args:
        composite_percentile: 当前综合百分位
        repair_start_date: 修复启动日期
        repair_start_percentile: 修复启动百分位
        is_stalled: 是否停滞
        config: 策略参数配置

    Returns:
        阶段字符串值

    状态优先级（从高到低）：
    1. OVERSHOOTING: composite >= overvalued_threshold
    2. COMPLETED: target_percentile <= composite < overvalued_threshold 且有 repair_start_date
    3. NEAR_TARGET: near_target_threshold <= composite < target_percentile 且有 repair_start_date
    4. STALLED: 有 repair_start_date 且 is_stalled=True 且 composite < near_target_threshold
    5. REPAIRING: 有 repair_start_date 且 composite >= start + repairing_threshold 且 < near_target_threshold
    6. REPAIR_STARTED: 有 repair_start_date 且 < start + repairing_threshold
    7. UNDERVALUED: 无 repair_start_date 且 composite < undervalued_threshold
    8. NO_REPAIR_NEEDED: 其余情况
    """
    # 1. OVERSHOOTING（最高优先级）
    if composite_percentile >= config.overvalued_threshold:
        return ValuationRepairPhase.OVERSHOOTING.value

    # 2. COMPLETED
    if (repair_start_date is not None and
        config.target_percentile <= composite_percentile < config.overvalued_threshold):
        return ValuationRepairPhase.COMPLETED.value

    # 3. NEAR_TARGET
    if (repair_start_date is not None and
        config.near_target_threshold <= composite_percentile < config.target_percentile):
        return ValuationRepairPhase.NEAR_TARGET.value

    # 4. STALLED
    if (repair_start_date is not None and
        is_stalled and
        composite_percentile < config.near_target_threshold):
        return ValuationRepairPhase.STALLED.value

    # 5. REPAIRING
    if (repair_start_date is not None and
        repair_start_percentile is not None and
        composite_percentile >= repair_start_percentile + config.repairing_threshold and
        composite_percentile < config.near_target_threshold):
        return ValuationRepairPhase.REPAIRING.value

    # 6. REPAIR_STARTED
    if repair_start_date is not None:
        return ValuationRepairPhase.REPAIR_STARTED.value

    # 7. UNDERVALUED
    if composite_percentile < config.undervalued_threshold:
        return ValuationRepairPhase.UNDERVALUED.value

    # 8. NO_REPAIR_NEEDED
    return ValuationRepairPhase.NO_REPAIR_NEEDED.value


def _map_phase_to_signal(phase: str) -> str:
    """将阶段映射为投资信号

    Args:
        phase: 阶段字符串

    Returns:
        信号字符串

    映射规则：
    - UNDERVALUED/REPAIR_STARTED -> "opportunity"
    - REPAIRING -> "in_progress"
    - NEAR_TARGET -> "near_exit"
    - COMPLETED/OVERSHOOTING -> "take_profit"
    - STALLED -> "stalled"
    - NO_REPAIR_NEEDED -> "none"
    """
    signal_map = {
        ValuationRepairPhase.UNDERVALUED.value: "opportunity",
        ValuationRepairPhase.REPAIR_STARTED.value: "opportunity",
        ValuationRepairPhase.REPAIRING.value: "in_progress",
        ValuationRepairPhase.NEAR_TARGET.value: "near_exit",
        ValuationRepairPhase.COMPLETED.value: "take_profit",
        ValuationRepairPhase.OVERSHOOTING.value: "take_profit",
        ValuationRepairPhase.STALLED.value: "stalled",
        ValuationRepairPhase.NO_REPAIR_NEEDED.value: "none",
    }
    return signal_map.get(phase, "none")


def calculate_repair_progress(
    current_percentile: float,
    start_percentile: float,
    target_percentile: Optional[float] = None,
    config: ValuationRepairConfig = DEFAULT_VALUATION_REPAIR_CONFIG
) -> Optional[float]:
    """计算修复进度

    Args:
        current_percentile: 当前百分位
        start_percentile: 启动百分位
        target_percentile: 目标百分位，None 时使用 config 默认值
        config: 策略参数配置

    Returns:
        进度（0-1），若分母 <= 0 则返回 None
    """
    if target_percentile is None:
        target_percentile = config.target_percentile

    denominator = target_percentile - start_percentile

    if denominator <= 0:
        return None

    progress = (current_percentile - start_percentile) / denominator
    return max(0.0, min(1.0, progress))


def calculate_repair_speed_per_30d(
    current_percentile: float,
    start_percentile: float,
    repair_duration_trading_days: int
) -> Optional[float]:
    """计算修复速度（每 30 交易日提升的百分位）

    Args:
        current_percentile: 当前百分位
        start_percentile: 启动百分位
        repair_duration_trading_days: 修复持续交易日数

    Returns:
        速度（每 30 交易日提升的百分位），若样本数 < 2 则返回 None
    """
    if repair_duration_trading_days < 2:
        return None

    progress = current_percentile - start_percentile
    speed_per_day = progress / repair_duration_trading_days
    return speed_per_day * 30


def estimate_days_to_target(
    current_percentile: float,
    target_percentile: float,
    speed_per_30d: Optional[float],
    config: ValuationRepairConfig = DEFAULT_VALUATION_REPAIR_CONFIG
) -> Optional[int]:
    """估算到达目标的交易日数

    Args:
        current_percentile: 当前百分位
        target_percentile: 目标百分位
        speed_per_30d: 修复速度（每 30 交易日）
        config: 策略参数配置

    Returns:
        预计交易日数，上限 eta_max_days，若 speed <= 0 则返回 None
    """
    if speed_per_30d is None or speed_per_30d <= 0:
        return None

    if current_percentile >= target_percentile:
        return 0

    remaining = target_percentile - current_percentile
    speed_per_day = speed_per_30d / 30
    estimated_days = remaining / speed_per_day

    # 向上取整，上限 eta_max_days
    return min(config.eta_max_days, math.ceil(estimated_days))


def calculate_confidence(
    sample_count: int,
    composite_method: str,
    has_repair_start: bool,
    is_stalled: bool,
    config: ValuationRepairConfig = DEFAULT_VALUATION_REPAIR_CONFIG
) -> float:
    """计算置信度

    Args:
        sample_count: 样本数
        composite_method: 综合方法
        has_repair_start: 是否有修复起点
        is_stalled: 是否停滞
        config: 策略参数配置

    Returns:
        置信度（0-1）

    启发式评分：
    - 基础值 confidence_base
    - 样本数 >= confidence_sample_threshold 加 confidence_sample_bonus
    - 使用 pe_pb_blend 加 confidence_blend_bonus
    - 已识别 repair start 加 confidence_repair_start_bonus
    - 非 stalled 加 confidence_not_stalled_bonus
    """
    confidence = config.confidence_base

    if sample_count >= config.confidence_sample_threshold:
        confidence += config.confidence_sample_bonus

    if composite_method == "pe_pb_blend":
        confidence += config.confidence_blend_bonus

    if has_repair_start:
        confidence += config.confidence_repair_start_bonus

    if not is_stalled:
        confidence += config.confidence_not_stalled_bonus

    return min(1.0, confidence)


def build_description(
    stock_code: str,
    phase: str,
    composite_percentile: float,
    repair_start_date: Optional[date],
    repair_progress: Optional[float],
    stall_duration_trading_days: int,
    estimated_days_to_target: Optional[int]
) -> str:
    """构建状态描述文本

    Args:
        stock_code: 股票代码
        phase: 阶段
        composite_percentile: 综合百分位
        repair_start_date: 修复启动日期
        repair_progress: 修复进度
        stall_duration_trading_days: 停滞持续天数
        estimated_days_to_target: 预计到达目标天数

    Returns:
        描述文本
    """
    # 阶段标签映射
    phase_labels = {
        ValuationRepairPhase.NO_REPAIR_NEEDED.value: "无需修复",
        ValuationRepairPhase.UNDERVALUED.value: "低估",
        ValuationRepairPhase.REPAIR_STARTED.value: "修复启动",
        ValuationRepairPhase.REPAIRING.value: "正在修复",
        ValuationRepairPhase.NEAR_TARGET.value: "接近目标",
        ValuationRepairPhase.COMPLETED.value: "修复完成",
        ValuationRepairPhase.OVERSHOOTING.value: "估值超涨",
        ValuationRepairPhase.STALLED.value: "修复停滞",
    }

    phase_label = phase_labels.get(phase, phase)

    parts = [
        f"{stock_code} 当前综合估值分位 {composite_percentile:.2f}，阶段为 {phase_label}。"
    ]

    # 修复进度
    if repair_start_date and repair_progress is not None:
        parts.append(f"自 {repair_start_date} 以来已修复 {repair_progress:.0%}。")

    # 停滞信息
    if stall_duration_trading_days > 0:
        parts.append(f"最近 {stall_duration_trading_days} 个交易日修复停滞。")

    # ETA
    if estimated_days_to_target is not None and estimated_days_to_target > 0:
        parts.append(f"按当前速度预计约 {estimated_days_to_target} 个交易日达到目标。")

    return "".join(parts)


def analyze_repair_status(
    stock_code: str,
    stock_name: str,
    history: List[Dict],
    as_of_date: Optional[date] = None,
    lookback_days: Optional[int] = None,
    confirm_window: Optional[int] = None,
    min_rebound: Optional[float] = None,
    stall_window: Optional[int] = None,
    stall_min_progress: Optional[float] = None,
    config: ValuationRepairConfig = DEFAULT_VALUATION_REPAIR_CONFIG
) -> ValuationRepairStatus:
    """分析估值修复状态（主入口）

    Args:
        stock_code: 股票代码
        stock_name: 股票名称
        history: 历史估值数据列表，每个元素包含：
            - trade_date: date
            - pe: float
            - pb: float
        as_of_date: 分析基准日期（默认使用最新记录日期）
        lookback_days: 回看窗口（交易日样本数），None 使用 config 默认值
        confirm_window: 修复确认窗口，None 使用 config 默认值
        min_rebound: 最小反弹幅度，None 使用 config 默认值
        stall_window: 停滞检测窗口，None 使用 config 默认值
        stall_min_progress: 停滞最小进展阈值，None 使用 config 默认值
        config: 策略参数配置

    Returns:
        ValuationRepairStatus

    Raises:
        InsufficientHistoryError: 历史数据不足
        InvalidValuationDataError: 估值数据无效
    """
    # 1. 构建百分位序列
    series = build_percentile_series(history, lookback_days, config)

    # 2. 获取当前状态（最新记录）
    latest = series[-1]
    if as_of_date is None:
        as_of_date = latest.trade_date

    # 3. 检测修复起点
    repair_start_date, repair_start_percentile = detect_repair_start(
        series, confirm_window, min_rebound, config
    )

    # 4. 找全局最低点
    lowest_point = min(series, key=lambda p: p.composite_percentile)

    # 5. 检测停滞
    is_stalled, stall_start_date, stall_duration = detect_stall(
        series, repair_start_date or as_of_date, stall_window, stall_min_progress, config
    )

    # 6. 确定阶段
    phase = determine_phase(
        latest.composite_percentile,
        repair_start_date,
        repair_start_percentile,
        is_stalled,
        config
    )

    # 7. 计算进度、速度、ETA
    repair_progress: Optional[float] = None
    repair_speed: Optional[float] = None
    eta: Optional[int] = None

    if repair_start_date and repair_start_percentile is not None:
        # 计算修复持续天数
        repair_duration = sum(
            1 for p in series
            if p.trade_date >= repair_start_date
        )

        repair_progress = calculate_repair_progress(
            latest.composite_percentile,
            repair_start_percentile,
            config.target_percentile,
            config
        )

        repair_speed = calculate_repair_speed_per_30d(
            latest.composite_percentile,
            repair_start_percentile,
            repair_duration
        )

        eta = estimate_days_to_target(
            latest.composite_percentile,
            config.target_percentile,
            repair_speed,
            config
        )
    else:
        repair_duration = 0

    # 8. 计算置信度
    confidence = calculate_confidence(
        len(series),
        latest.composite_method,
        repair_start_date is not None,
        is_stalled,
        config
    )

    # 9. 映射信号
    signal = _map_phase_to_signal(phase)

    # 10. 获取当前 PE/PB 值
    latest_record = history[-1]
    current_pe = latest_record["pe"] if latest_record["pe"] is not None and latest_record["pe"] > 0 else None
    current_pb = latest_record["pb"]

    # 11. 构建描述
    description = build_description(
        stock_code,
        phase,
        latest.composite_percentile,
        repair_start_date,
        repair_progress,
        stall_duration,
        eta
    )

    return ValuationRepairStatus(
        stock_code=stock_code,
        stock_name=stock_name,
        as_of_date=as_of_date,
        phase=phase,
        signal=signal,
        current_pe=current_pe,
        current_pb=current_pb,
        pe_percentile=latest.pe_percentile,
        pb_percentile=latest.pb_percentile,
        composite_percentile=latest.composite_percentile,
        composite_method=latest.composite_method,
        repair_start_date=repair_start_date,
        repair_start_percentile=repair_start_percentile,
        lowest_percentile=lowest_point.composite_percentile,
        lowest_percentile_date=lowest_point.trade_date,
        repair_progress=repair_progress,
        target_percentile=config.target_percentile,
        repair_speed_per_30d=repair_speed,
        estimated_days_to_target=eta,
        is_stalled=is_stalled,
        stall_start_date=stall_start_date,
        stall_duration_trading_days=stall_duration,
        repair_duration_trading_days=repair_duration if repair_start_date else 0,
        lookback_trading_days=len(series),
        confidence=confidence,
        description=description
    )
