"""
估值修复跟踪单元测试

测试 Phase 4 功能：
1. 复合百分位计算
2. 百分位序列构建（扩张窗口，无前视偏差）
3. 修复启动检测
4. 停滞检测
5. 阶段判定
6. 进度、速度、ETA 计算
7. 置信度计算
8. 描述文本生成
9. 整体分析流程
"""

import pytest
from datetime import date, timedelta
from decimal import Decimal

from apps.equity.domain.entities_valuation_repair import (
    ValuationRepairPhase,
    PercentilePoint,
    ValuationRepairStatus
)
from apps.equity.domain.services_valuation_repair import (
    # 常量
    MIN_HISTORY_POINTS,
    DEFAULT_LOOKBACK_DAYS,
    DEFAULT_CONFIRM_WINDOW,
    DEFAULT_MIN_REBOUND,
    DEFAULT_STALL_WINDOW,
    DEFAULT_STALL_MIN_PROGRESS,
    DEFAULT_TARGET_PERCENTILE,
    UNDERVERLUED_THRESHOLD,
    NEAR_TARGET_THRESHOLD,
    OVERVALUED_THRESHOLD,

    # 异常
    InsufficientHistoryError,
    InvalidValuationDataError,

    # 函数
    compute_composite_percentile,
    build_percentile_series,
    detect_repair_start,
    detect_stall,
    determine_phase,
    calculate_repair_progress,
    calculate_repair_speed_per_30d,
    estimate_days_to_target,
    calculate_confidence,
    build_description,
    analyze_repair_status
)


# ==================== 测试数据构建工具 ====================

def make_date(day_offset: int, base_date: date = date(2024, 1, 1)) -> date:
    """生成日期"""
    return base_date + timedelta(days=day_offset)


def make_history_record(
    trade_date: date,
    pe: float,
    pb: float
) -> dict:
    """构建历史记录"""
    return {
        "trade_date": trade_date,
        "pe": pe,
        "pb": pb
    }


def make_sample_history(count: int = 200) -> list:
    """生成样本历史数据

    生成一个有明显底部和修复的历史序列：
    - 前 100 天：估值逐渐下降
    - 第 100-110 天：底部震荡
    - 第 110 天后：估值修复
    """
    history = []
    base_date = date(2023, 1, 1)

    for i in range(count):
        d = base_date + timedelta(days=i)

        # PE: 从 30 降到 10（第 100 天），再升到 20
        if i < 100:
            pe = 30.0 - i * 0.2  # 30 -> 10
        elif i < 110:
            pe = 10.0 + (i - 100) * 0.1  # 10 -> 11
        else:
            pe = 11.0 + (i - 110) * 0.15  # 11 -> 20+

        # PB: 从 3.0 降到 1.0（第 100 天），再升到 2.0
        if i < 100:
            pb = 3.0 - i * 0.02  # 3.0 -> 1.0
        elif i < 110:
            pb = 1.0 + (i - 100) * 0.02  # 1.0 -> 1.2
        else:
            pb = 1.2 + (i - 110) * 0.02  # 1.2 -> 2.0+

        history.append(make_history_record(d, pe, pb))

    return history


# ==================== Test compute_composite_percentile ====================

class TestComputeCompositePercentile:
    """测试复合百分位计算"""

    def test_pe_pb_blend_mode(self):
        """测试 PE+PB 混合模式"""
        pe_pct = 0.5
        pb_pct = 0.3

        composite, method = compute_composite_percentile(pe_pct, pb_pct)

        # 0.5 * 0.6 + 0.3 * 0.4 = 0.3 + 0.12 = 0.42
        assert composite == pytest.approx(0.42)
        assert method == "pe_pb_blend"

    def test_pb_only_mode_when_pe_is_zero(self):
        """测试 PE=0 时使用 PB-only 模式"""
        composite, method = compute_composite_percentile(0.0, 0.3)

        assert composite == 0.3
        assert method == "pb_only"

    def test_pb_only_mode_when_pe_is_negative(self):
        """测试 PE<0 时使用 PB-only 模式"""
        composite, method = compute_composite_percentile(-5.0, 0.3)

        assert composite == 0.3
        assert method == "pb_only"

    def test_pb_only_mode_when_pe_is_none(self):
        """测试 PE=None 时使用 PB-only 模式"""
        composite, method = compute_composite_percentile(None, 0.3)

        assert composite == 0.3
        assert method == "pb_only"

    def test_boundary_values(self):
        """测试边界值"""
        # 最大值
        composite, method = compute_composite_percentile(1.0, 1.0)
        assert composite == 1.0

        # 最小值
        composite, method = compute_composite_percentile(0.0, 0.0)
        assert composite == 0.0


# ==================== Test build_percentile_series ====================

class TestBuildPercentileSeries:
    """测试百分位序列构建"""

    def test_expanding_window_no_lookahead_bias(self):
        """测试扩张窗口无前视偏差"""
        # 创建一个单调递增的序列
        history = []
        base_date = date(2024, 1, 1)

        for i in range(150):
            pe = 10.0 + i * 0.1
            pb = 1.0 + i * 0.05
            history.append(make_history_record(
                base_date + timedelta(days=i),
                pe,
                pb
            ))

        series = build_percentile_series(history, lookback_days=150)

        # 最后一个点的百分位应该接近 1.0（因为所有历史值都小于等于它）
        assert series[-1].pe_percentile == pytest.approx(1.0, abs=0.05)
        assert series[-1].pb_percentile == pytest.approx(1.0, abs=0.05)

        # 第一个点的百分位应该是 0.5（只有自己，处于中间位置）
        # 在扩张窗口中，第一个值只有它自己，所以百分位应该是 0.5
        assert series[0].pe_percentile == pytest.approx(0.5)
        assert series[0].pb_percentile == pytest.approx(0.5)

    def test_insufficient_history_raises_error(self):
        """测试历史数据不足"""
        history = []

        for i in range(100):  # 少于 MIN_HISTORY_POINTS (120)
            history.append(make_history_record(
                make_date(i),
                10.0 + i * 0.1,
                1.0 + i * 0.05
            ))

        with pytest.raises(InsufficientHistoryError) as exc_info:
            build_percentile_series(history)

        assert "历史数据不足" in str(exc_info.value)

    def test_empty_history_raises_error(self):
        """测试空历史数据"""
        with pytest.raises(InsufficientHistoryError):
            build_percentile_series([])

    def test_pb_le_zero_raises_error(self):
        """测试 PB <= 0 抛出异常"""
        history = []

        for i in range(150):
            pb = 1.0 + i * 0.05
            # 在中间插入一个 PB <= 0 的记录
            if i == 75:
                pb = 0.0
            history.append(make_history_record(
                make_date(i),
                10.0 + i * 0.1,
                pb
            ))

        with pytest.raises(InvalidValuationDataError) as exc_info:
            build_percentile_series(history)

        assert "PB 必须大于 0" in str(exc_info.value)

    def test_negative_pb_raises_error(self):
        """测试 PB < 0 抛出异常"""
        history = []

        for i in range(150):
            pb = 1.0 + i * 0.05
            if i == 75:
                pb = -0.5
            history.append(make_history_record(
                make_date(i),
                10.0 + i * 0.1,
                pb
            ))

        with pytest.raises(InvalidValuationDataError):
            build_percentile_series(history)

    def test_negative_pe_sets_pe_percentile_to_none(self):
        """测试负 PE 仅影响 PE 百分位，不影响整体序列"""
        history = []

        for i in range(150):
            # 前 50 天 PE 为负，之后为正
            pe = -5.0 if i < 50 else 10.0 + (i - 50) * 0.1
            pb = 1.0 + i * 0.05
            history.append(make_history_record(
                make_date(i),
                pe,
                pb
            ))

        series = build_percentile_series(history, lookback_days=150)

        # 前 50 天的 PE 百分位应该为 None
        for point in series[:50]:
            assert point.pe_percentile is None

        # 之后应该有 PE 百分位
        for point in series[50:]:
            assert point.pe_percentile is not None

        # 所有点都应该有 PB 百分位和综合百分位
        for point in series:
            assert point.pb_percentile is not None
            assert point.composite_percentile is not None

    def test_pe_zero_sets_pe_percentile_to_none(self):
        """测试 PE=0 时 PE 百分位为 None"""
        history = []

        for i in range(150):
            pe = 0.0 if i < 50 else 10.0 + (i - 50) * 0.1
            pb = 1.0 + i * 0.05
            history.append(make_history_record(
                make_date(i),
                pe,
                pb
            ))

        series = build_percentile_series(history, lookback_days=150)

        # 前 50 天使用 pb_only
        for point in series[:50]:
            assert point.pe_percentile is None
            assert point.composite_method == "pb_only"

        # 之后使用 pe_pb_blend
        for point in series[50:]:
            assert point.pe_percentile is not None
            assert point.composite_method == "pe_pb_blend"

    def test_lookback_truncation(self):
        """测试 lookback_days 截断"""
        # 创建 300 条记录
        history = []

        for i in range(300):
            history.append(make_history_record(
                make_date(i),
                10.0 + i * 0.01,
                1.0 + i * 0.005
            ))

        # 只取最近 200 条
        series = build_percentile_series(history, lookback_days=200)

        assert len(series) == 200

    def test_returns_points_in_ascending_date_order(self):
        """测试返回的点按日期升序排列"""
        history = []

        for i in range(150):
            history.append(make_history_record(
                make_date(i),
                10.0 + i * 0.1,
                1.0 + i * 0.05
            ))

        series = build_percentile_series(history)

        # 检查日期是递增的
        dates = [p.trade_date for p in series]
        assert dates == sorted(dates)


# ==================== Test detect_repair_start ====================

class TestDetectRepairStart:
    """测试修复启动检测"""

    def test_clear_bottom_with_rebound_detects_start(self):
        """测试明确底部反弹成功检测"""
        # 创建一个有明确底部的序列
        series = []

        # 底部前：下降
        for i in range(100):
            composite = 0.5 - i * 0.004  # 0.5 -> 0.1
            series.append(PercentilePoint(
                trade_date=make_date(i),
                pe_percentile=composite,
                pb_percentile=composite,
                composite_percentile=composite,
                composite_method="pe_pb_blend"
            ))

        # 底部点（最低）
        bottom_composite = 0.1
        series.append(PercentilePoint(
            trade_date=make_date(100),
            pe_percentile=bottom_composite,
            pb_percentile=bottom_composite,
            composite_percentile=bottom_composite,
            composite_method="pe_pb_blend"
        ))

        # 反弹
        for i in range(101, 130):
            composite = 0.1 + (i - 100) * 0.01  # 0.1 -> 0.4
            series.append(PercentilePoint(
                trade_date=make_date(i),
                pe_percentile=composite,
                pb_percentile=composite,
                composite_percentile=composite,
                composite_method="pe_pb_blend"
            ))

        start_date, start_pct = detect_repair_start(series)

        assert start_date == make_date(100)
        assert start_pct == pytest.approx(0.1)

    def test_only_new_low_no_rebound_no_start(self):
        """测试仅创新低未反弹，不判定启动"""
        series = []

        # 持续下降
        for i in range(100):
            composite = 0.5 - i * 0.004
            series.append(PercentilePoint(
                trade_date=make_date(i),
                pe_percentile=composite,
                pb_percentile=composite,
                composite_percentile=composite,
                composite_method="pe_pb_blend"
            ))

        start_date, start_pct = detect_repair_start(series)

        # 最低点在最后，且没有足够反弹
        assert start_date is None
        assert start_pct is None

    def test_bottom_too_close_to_tail_no_start(self):
        """测试最低点过近序列尾部，不判定启动"""
        series = []

        # 普通数据
        for i in range(100):
            composite = 0.3 + i * 0.001
            series.append(PercentilePoint(
                trade_date=make_date(i),
                pe_percentile=composite,
                pb_percentile=composite,
                composite_percentile=composite,
                composite_method="pe_pb_blend"
            ))

        # 最近的最低点（在最后 10 天内）
        for i in range(100, 120):
            composite = 0.4 - (i - 100) * 0.01  # 下降
            series.append(PercentilePoint(
                trade_date=make_date(i),
                pe_percentile=composite,
                pb_percentile=composite,
                composite_percentile=composite,
                composite_method="pe_pb_blend"
            ))

        start_date, start_pct = detect_repair_start(series)

        # 最低点在最后 20 天内，不判定
        assert start_date is None

    def test_multiple_bottoms_selects_global_minimum(self):
        """测试多个低点时选全局最低点"""
        series = []

        # 第一个局部低点
        for i in range(50):
            composite = 0.5 - i * 0.005  # 0.5 -> 0.25
            series.append(PercentilePoint(
                trade_date=make_date(i),
                pe_percentile=composite,
                pb_percentile=composite,
                composite_percentile=composite,
                composite_method="pe_pb_blend"
            ))

        # 反弹
        for i in range(50, 70):
            composite = 0.25 + (i - 50) * 0.01
            series.append(PercentilePoint(
                trade_date=make_date(i),
                pe_percentile=composite,
                pb_percentile=composite,
                composite_percentile=composite,
                composite_method="pe_pb_blend"
            ))

        # 再下降到更低点
        for i in range(70, 120):
            composite = 0.45 - (i - 70) * 0.008  # 0.45 -> 0.05
            series.append(PercentilePoint(
                trade_date=make_date(i),
                pe_percentile=composite,
                pb_percentile=composite,
                composite_percentile=composite,
                composite_method="pe_pb_blend"
            ))

        # 反弹超过 0.05
        for i in range(120, 150):  # 延长到 150 确保足够反弹
            composite = 0.05 + (i - 120) * 0.01
            series.append(PercentilePoint(
                trade_date=make_date(i),
                pe_percentile=composite,
                pb_percentile=composite,
                composite_percentile=composite,
                composite_method="pe_pb_blend"
            ))

        start_date, start_pct = detect_repair_start(series)

        # 应该选择更低的第二个底部（在 index 119 附近）
        # 最低点应该在 index 119 (0.05 左右)
        # 检查是否在确认窗口内 (index 119 + 20 = 139)
        # 反弹从 index 120 开始，到 index 139 时会达到 0.05 + 19*0.01 = 0.24
        # 0.24 - 0.05 = 0.19 > 0.05，满足反弹条件
        assert start_date is not None  # 应该检测到修复启动
        # 最低点约在 index 119
        assert start_pct < 0.10  # 应该是较低的值

    def test_empty_series_returns_none(self):
        """测试空序列返回 None"""
        start_date, start_pct = detect_repair_start([])

        assert start_date is None
        assert start_pct is None


# ==================== Test detect_stall ====================

class TestDetectStall:
    """测试停滞检测"""

    def test_stall_detected_in_recent_window(self):
        """测试最近窗口内检测到停滞"""
        series = []

        base_date = date(2024, 1, 1)

        # 修复起点
        start_date = base_date + timedelta(days=0)

        # 修复初期：上升
        for i in range(40):
            composite = 0.1 + i * 0.005
            series.append(PercentilePoint(
                trade_date=base_date + timedelta(days=i),
                pe_percentile=composite,
                pb_percentile=composite,
                composite_percentile=composite,
                composite_method="pe_pb_blend"
            ))

        # 最近 40 天：停滞（波动 < 0.02）
        for i in range(40, 80):
            composite = 0.3 + (i % 5) * 0.003  # 0.3 ~ 0.312
            series.append(PercentilePoint(
                trade_date=base_date + timedelta(days=i),
                pe_percentile=composite,
                pb_percentile=composite,
                composite_percentile=composite,
                composite_method="pe_pb_blend"
            ))

        is_stalled, stall_start, duration = detect_stall(
            series, start_date, stall_window=40, stall_min_progress=0.02
        )

        assert is_stalled is True
        assert stall_start == base_date + timedelta(days=40)
        assert duration == 40

    def test_stall_released_after_significant_rise(self):
        """测试显著上升后停滞自动解除"""
        series = []
        base_date = date(2024, 1, 1)

        start_date = base_date + timedelta(days=0)

        # 上升
        for i in range(40):
            composite = 0.1 + i * 0.005
            series.append(PercentilePoint(
                trade_date=base_date + timedelta(days=i),
                pe_percentile=composite,
                pb_percentile=composite,
                composite_percentile=composite,
                composite_method="pe_pb_blend"
            ))

        # 停滞
        for i in range(40, 60):
            composite = 0.3 + (i % 3) * 0.003
            series.append(PercentilePoint(
                trade_date=base_date + timedelta(days=i),
                pe_percentile=composite,
                pb_percentile=composite,
                composite_percentile=composite,
                composite_method="pe_pb_blend"
            ))

        # 重新大幅上升
        for i in range(60, 100):
            composite = 0.3 + (i - 60) * 0.02
            series.append(PercentilePoint(
                trade_date=base_date + timedelta(days=i),
                pe_percentile=composite,
                pb_percentile=composite,
                composite_percentile=composite,
                composite_method="pe_pb_blend"
            ))

        is_stalled, stall_start, duration = detect_stall(
            series, start_date, stall_window=40, stall_min_progress=0.02
        )

        # 最近 40 天上升显著，不再停滞
        assert is_stalled is False

    def test_insufficient_samples_no_stall(self):
        """测试样本数不足时不停滞"""
        series = []
        base_date = date(2024, 1, 1)

        start_date = base_date + timedelta(days=0)

        # 只有 30 个样本
        for i in range(30):
            composite = 0.1 + i * 0.001  # 很小的上升
            series.append(PercentilePoint(
                trade_date=base_date + timedelta(days=i),
                pe_percentile=composite,
                pb_percentile=composite,
                composite_percentile=composite,
                composite_method="pe_pb_blend"
            ))

        is_stalled, stall_start, duration = detect_stall(
            series, start_date, stall_window=40, stall_min_progress=0.02
        )

        # 样本不足，不判定停滞
        assert is_stalled is False
        assert stall_start is None
        assert duration == 0

    def test_no_repair_start_no_stall(self):
        """测试无修复起点时不停滞"""
        series = []

        for i in range(100):
            composite = 0.3 + i * 0.001
            series.append(PercentilePoint(
                trade_date=make_date(i),
                pe_percentile=composite,
                pb_percentile=composite,
                composite_percentile=composite,
                composite_method="pe_pb_blend"
            ))

        is_stalled, stall_start, duration = detect_stall(series, None)

        assert is_stalled is False
        assert stall_start is None
        assert duration == 0


# ==================== Test determine_phase ====================

class TestDeterminePhase:
    """测试阶段判定"""

    def test_overshooting_highest_priority(self):
        """测试 OVERSHOOTING 最高优先级"""
        phase = determine_phase(
            composite_percentile=0.85,  # >= 0.80
            repair_start_date=None,
            repair_start_percentile=None,
            is_stalled=False
        )

        assert phase == ValuationRepairPhase.OVERSHOOTING.value

    def test_overshouting_even_with_stall(self):
        """测试超涨时即使停滞也判定为超涨"""
        phase = determine_phase(
            composite_percentile=0.85,
            repair_start_date=date(2024, 1, 1),
            repair_start_percentile=0.1,
            is_stalled=True  # 停滞但优先级低于超涨
        )

        assert phase == ValuationRepairPhase.OVERSHOOTING.value

    def test_completed(self):
        """测试 COMPLETED 阶段"""
        phase = determine_phase(
            composite_percentile=0.60,  # >= 0.50 且 < 0.80
            repair_start_date=date(2024, 1, 1),
            repair_start_percentile=0.1,
            is_stalled=False
        )

        assert phase == ValuationRepairPhase.COMPLETED.value

    def test_completed_requires_repair_start(self):
        """测试 COMPLETED 需要有修复起点"""
        phase = determine_phase(
            composite_percentile=0.60,
            repair_start_date=None,  # 无修复起点
            repair_start_percentile=None,
            is_stalled=False
        )

        # 无修复起点，不判定为完成
        assert phase != ValuationRepairPhase.COMPLETED.value

    def test_near_target(self):
        """测试 NEAR_TARGET 阶段"""
        phase = determine_phase(
            composite_percentile=0.47,  # >= 0.45 且 < 0.50
            repair_start_date=date(2024, 1, 1),
            repair_start_percentile=0.1,
            is_stalled=False
        )

        assert phase == ValuationRepairPhase.NEAR_TARGET.value

    def test_near_target_requires_repair_start(self):
        """测试 NEAR_TARGET 需要有修复起点"""
        phase = determine_phase(
            composite_percentile=0.47,
            repair_start_date=None,
            repair_start_percentile=None,
            is_stalled=False
        )

        assert phase != ValuationRepairPhase.NEAR_TARGET.value

    def test_stalled(self):
        """测试 STALLED 阶段"""
        phase = determine_phase(
            composite_percentile=0.30,  # < 0.45
            repair_start_date=date(2024, 1, 1),
            repair_start_percentile=0.1,
            is_stalled=True
        )

        assert phase == ValuationRepairPhase.STALLED.value

    def test_stalled_requires_composite_below_045(self):
        """测试停滞需要综合分位 < 0.45"""
        # 即使停滞，但综合分位已 >= 0.45
        phase = determine_phase(
            composite_percentile=0.50,  # >= 0.45
            repair_start_date=date(2024, 1, 1),
            repair_start_percentile=0.1,
            is_stalled=True
        )

        # 应该判定为 COMPLETED 而非 STALLED
        assert phase == ValuationRepairPhase.COMPLETED.value

    def test_repairing(self):
        """测试 REPAIRING 阶段"""
        phase = determine_phase(
            composite_percentile=0.30,  # >= start + 0.10 且 < 0.45
            repair_start_date=date(2024, 1, 1),
            repair_start_percentile=0.15,  # start = 0.15, current = 0.30 > 0.25
            is_stalled=False
        )

        assert phase == ValuationRepairPhase.REPAIRING.value

    def test_repairing_requires_sufficient_progress(self):
        """测试 REPAIRING 需要足够进展"""
        phase = determine_phase(
            composite_percentile=0.20,  # < start + 0.10
            repair_start_date=date(2024, 1, 1),
            repair_start_percentile=0.15,
            is_stalled=False
        )

        # 进展不足，应该是 REPAIR_STARTED
        assert phase == ValuationRepairPhase.REPAIR_STARTED.value

    def test_repair_started(self):
        """测试 REPAIR_STARTED 阶段"""
        phase = determine_phase(
            composite_percentile=0.20,  # < start + 0.10
            repair_start_date=date(2024, 1, 1),
            repair_start_percentile=0.15,
            is_stalled=False
        )

        assert phase == ValuationRepairPhase.REPAIR_STARTED.value

    def test_under_valued(self):
        """测试 UNDERVALUED 阶段"""
        phase = determine_phase(
            composite_percentile=0.15,  # < 0.20
            repair_start_date=None,
            repair_start_percentile=None,
            is_stalled=False
        )

        assert phase == ValuationRepairPhase.UNDERVALUED.value

    def test_no_repair_needed(self):
        """测试 NO_REPAIR_NEEDED 阶段"""
        phase = determine_phase(
            composite_percentile=0.40,  # >= 0.20 但无修复起点
            repair_start_date=None,
            repair_start_percentile=None,
            is_stalled=False
        )

        assert phase == ValuationRepairPhase.NO_REPAIR_NEEDED.value

    def test_all_phase_boundaries(self):
        """测试所有阶段边界值"""
        test_cases = [
            # (composite, start_pct, is_stalled, expected_phase)
            (0.80, None, False, "overshooting"),      # >= 0.80
            (0.50, 0.1, False, "completed"),         # >= 0.50
            (0.45, 0.1, False, "near_target"),       # >= 0.45
            (0.25, 0.1, True, "stalled"),            # 停滞且 < 0.45
            (0.25, 0.1, False, "repairing"),         # >= start + 0.10
            (0.15, 0.1, False, "repair_started"),    # 有起点但进展小
            (0.15, None, False, "undervalued"),      # < 0.20 无起点
            (0.40, None, False, "no_repair_needed"), # 其他
        ]

        for composite, start_pct, is_stalled, expected in test_cases:
            start_date = date(2024, 1, 1) if start_pct is not None else None
            phase = determine_phase(composite, start_date, start_pct, is_stalled)
            assert phase == expected, f"composite={composite}, expected={expected}, got={phase}"


# ==================== Test calculate_repair_progress ====================

class TestCalculateRepairProgress:
    """测试修复进度计算"""

    def test_normal_progress(self):
        """测试正常进度"""
        progress = calculate_repair_progress(
            current_percentile=0.35,
            start_percentile=0.10,
            target_percentile=0.50
        )

        # (0.35 - 0.10) / (0.50 - 0.10) = 0.25 / 0.40 = 0.625
        assert progress == pytest.approx(0.625)

    def test_progress_clipped_to_one_when_above_target(self):
        """测试超过目标时裁剪为 1"""
        progress = calculate_repair_progress(
            current_percentile=0.60,
            start_percentile=0.10,
            target_percentile=0.50
        )

        assert progress == 1.0

    def test_progress_clipped_to_zero_when_below_start(self):
        """测试低于起点时裁剪为 0"""
        progress = calculate_repair_progress(
            current_percentile=0.05,
            start_percentile=0.10,
            target_percentile=0.50
        )

        assert progress == 0.0

    def test_zero_denominator_returns_none(self):
        """测试分母为 0 时返回 None"""
        progress = calculate_repair_progress(
            current_percentile=0.30,
            start_percentile=0.50,
            target_percentile=0.50
        )

        assert progress is None

    def test_negative_denominator_returns_none(self):
        """测试分母为负时返回 None"""
        progress = calculate_repair_progress(
            current_percentile=0.30,
            start_percentile=0.60,
            target_percentile=0.50
        )

        assert progress is None

    def test_at_start_returns_zero(self):
        """测试在起点时返回 0"""
        progress = calculate_repair_progress(
            current_percentile=0.10,
            start_percentile=0.10,
            target_percentile=0.50
        )

        assert progress == 0.0

    def test_at_target_returns_one(self):
        """测试达到目标时返回 1"""
        progress = calculate_repair_progress(
            current_percentile=0.50,
            start_percentile=0.10,
            target_percentile=0.50
        )

        assert progress == 1.0


# ==================== Test calculate_repair_speed_per_30d ====================

class TestCalculateRepairSpeedPer30d:
    """测试修复速度计算"""

    def test_normal_speed(self):
        """测试正常速度"""
        speed = calculate_repair_speed_per_30d(
            current_percentile=0.30,
            start_percentile=0.10,
            repair_duration_trading_days=60
        )

        # (0.30 - 0.10) / 60 * 30 = 0.20 / 60 * 30 = 0.10
        assert speed == pytest.approx(0.10)

    def test_negative_speed(self):
        """测试负速度（退化）"""
        speed = calculate_repair_speed_per_30d(
            current_percentile=0.05,
            start_percentile=0.10,
            repair_duration_trading_days=30
        )

        # (0.05 - 0.10) / 30 * 30 = -0.05
        assert speed == pytest.approx(-0.05)

    def test_single_day_returns_none(self):
        """测试单日返回 None"""
        speed = calculate_repair_speed_per_30d(
            current_percentile=0.15,
            start_percentile=0.10,
            repair_duration_trading_days=1
        )

        assert speed is None

    def test_zero_days_returns_none(self):
        """测试 0 天返回 None"""
        speed = calculate_repair_speed_per_30d(
            current_percentile=0.10,
            start_percentile=0.10,
            repair_duration_trading_days=0
        )

        assert speed is None


# ==================== Test estimate_days_to_target ====================

class TestEstimateDaysToTarget:
    """测试估算到达目标天数"""

    def test_normal_estimation(self):
        """测试正常估算"""
        eta = estimate_days_to_target(
            current_percentile=0.30,
            target_percentile=0.50,
            speed_per_30d=0.10
        )

        # remaining = 0.20, speed_per_day = 0.10 / 30 = 0.00333...
        # days = 0.20 / 0.00333... = 60
        assert eta == 60

    def test_already_at_target_returns_zero(self):
        """测试已达到目标返回 0"""
        eta = estimate_days_to_target(
            current_percentile=0.50,
            target_percentile=0.50,
            speed_per_30d=0.10
        )

        assert eta == 0

    def test_above_target_returns_zero(self):
        """测试超过目标返回 0"""
        eta = estimate_days_to_target(
            current_percentile=0.60,
            target_percentile=0.50,
            speed_per_30d=0.10
        )

        assert eta == 0

    def test_zero_speed_returns_none(self):
        """测试零速度返回 None"""
        eta = estimate_days_to_target(
            current_percentile=0.30,
            target_percentile=0.50,
            speed_per_30d=0.0
        )

        assert eta is None

    def test_negative_speed_returns_none(self):
        """测试负速度返回 None"""
        eta = estimate_days_to_target(
            current_percentile=0.30,
            target_percentile=0.50,
            speed_per_30d=-0.05
        )

        assert eta is None

    def test_none_speed_returns_none(self):
        """测试 None 速度返回 None"""
        eta = estimate_days_to_target(
            current_percentile=0.30,
            target_percentile=0.50,
            speed_per_30d=None
        )

        assert eta is None

    def test_large_eta_capped_at_999(self):
        """测试大 ETA 上限为 999"""
        eta = estimate_days_to_target(
            current_percentile=0.10,
            target_percentile=0.50,
            speed_per_30d=0.001  # 非常慢
        )

        # remaining = 0.40, speed_per_day = 0.001 / 30
        # days = 0.40 / (0.001 / 30) = 12000 -> 裁剪到 999
        assert eta == 999


# ==================== Test calculate_confidence ====================

class TestCalculateConfidence:
    """测试置信度计算"""

    def test_maximum_confidence(self):
        """测试最大置信度"""
        confidence = calculate_confidence(
            sample_count=500,
            composite_method="pe_pb_blend",
            has_repair_start=True,
            is_stalled=False
        )

        # 0.4 + 0.2 + 0.15 + 0.15 + 0.1 = 1.0 -> 裁剪到 1.0
        assert confidence == 1.0

    def test_minimum_confidence(self):
        """测试最小置信度"""
        confidence = calculate_confidence(
            sample_count=100,
            composite_method="pb_only",
            has_repair_start=False,
            is_stalled=True
        )

        # 只有基础值 0.4
        assert confidence == 0.4

    def test_high_sample_count_bonus(self):
        """测试大样本加分"""
        confidence = calculate_confidence(
            sample_count=300,  # >= 252
            composite_method="pb_only",
            has_repair_start=False,
            is_stalled=False
        )

        # 0.4 + 0.2 (样本数) + 0.1 (非停滞) = 0.7
        assert confidence == pytest.approx(0.7)  # 使用 approx 处理浮点数

    def test_low_sample_count_no_bonus(self):
        """测试小样本无加分"""
        confidence = calculate_confidence(
            sample_count=200,  # < 252
            composite_method="pb_only",
            has_repair_start=False,
            is_stalled=False
        )

        assert confidence == 0.5  # 0.4 + 0.1

    def test_pe_pb_blend_bonus(self):
        """测试 PE+PB 混合加分"""
        confidence = calculate_confidence(
            sample_count=100,
            composite_method="pe_pb_blend",
            has_repair_start=False,
            is_stalled=False
        )

        assert confidence == 0.65  # 0.4 + 0.15 + 0.1

    def test_repair_start_bonus(self):
        """测试修复起点加分"""
        confidence = calculate_confidence(
            sample_count=100,
            composite_method="pb_only",
            has_repair_start=True,
            is_stalled=False
        )

        assert confidence == 0.65  # 0.4 + 0.15 + 0.1

    def test_not_stalled_bonus(self):
        """测试非停滞加分"""
        confidence = calculate_confidence(
            sample_count=100,
            composite_method="pb_only",
            has_repair_start=False,
            is_stalled=False
        )

        assert confidence == 0.5  # 0.4 + 0.1

    def test_stalled_no_bonus(self):
        """测试停滞无加分"""
        confidence = calculate_confidence(
            sample_count=100,
            composite_method="pb_only",
            has_repair_start=False,
            is_stalled=True
        )

        assert confidence == 0.4  # 只有基础值


# ==================== Test build_description ====================

class TestBuildDescription:
    """测试描述文本生成"""

    def test_undervalued_description(self):
        """测试低估描述"""
        desc = build_description(
            stock_code="000001.SZ",
            phase=ValuationRepairPhase.UNDERVALUED.value,
            composite_percentile=0.15,
            repair_start_date=None,
            repair_progress=None,
            stall_duration_trading_days=0,
            estimated_days_to_target=None
        )

        assert "000001.SZ" in desc
        assert "0.15" in desc
        assert "低估" in desc

    def test_repairing_with_progress_and_eta(self):
        """测试修复中描述（含进度和 ETA）"""
        desc = build_description(
            stock_code="000001.SZ",
            phase=ValuationRepairPhase.REPAIRING.value,
            composite_percentile=0.35,
            repair_start_date=date(2024, 1, 15),
            repair_progress=0.625,
            stall_duration_trading_days=0,
            estimated_days_to_target=60
        )

        assert "000001.SZ" in desc
        assert "0.35" in desc
        assert "正在修复" in desc
        assert "2024-01-15" in desc
        assert "62%" in desc or "63%" in desc  # 取决于四舍五入
        assert "60 个交易日" in desc

    def test_stalled_description(self):
        """测试停滞描述"""
        desc = build_description(
            stock_code="000001.SZ",
            phase=ValuationRepairPhase.STALLED.value,
            composite_percentile=0.25,
            repair_start_date=date(2024, 1, 15),
            repair_progress=0.3,
            stall_duration_trading_days=40,
            estimated_days_to_target=None
        )

        assert "000001.SZ" in desc
        assert "修复停滞" in desc
        assert "40 个交易日修复停滞" in desc

    def test_completed_description(self):
        """测试完成描述"""
        desc = build_description(
            stock_code="000001.SZ",
            phase=ValuationRepairPhase.COMPLETED.value,
            composite_percentile=0.55,
            repair_start_date=date(2024, 1, 15),
            repair_progress=1.0,
            stall_duration_trading_days=0,
            estimated_days_to_target=0
        )

        assert "修复完成" in desc
        assert "已修复 100%" in desc

    def test_no_repair_needed_description(self):
        """测试无需修复描述"""
        desc = build_description(
            stock_code="000001.SZ",
            phase=ValuationRepairPhase.NO_REPAIR_NEEDED.value,
            composite_percentile=0.40,
            repair_start_date=None,
            repair_progress=None,
            stall_duration_trading_days=0,
            estimated_days_to_target=None
        )

        assert "无需修复" in desc

    def test_unknown_phase_fallback(self):
        """测试未知阶段回退"""
        desc = build_description(
            stock_code="000001.SZ",
            phase="unknown_phase",
            composite_percentile=0.30,
            repair_start_date=None,
            repair_progress=None,
            stall_duration_trading_days=0,
            estimated_days_to_target=None
        )

        assert "unknown_phase" in desc  # 直接使用阶段值


# ==================== Test analyze_repair_status (Integration) ====================

class TestAnalyzeRepairStatus:
    """测试整体分析流程"""

    def test_repairing_status_analysis(self):
        """测试修复中的状态分析"""
        # 创建修复中的历史数据
        history = make_sample_history(200)

        status = analyze_repair_status(
            stock_code="000001.SZ",
            stock_name="平安银行",
            history=history,
            as_of_date=date(2023, 7, 20)
        )

        # 验证基本字段
        assert status.stock_code == "000001.SZ"
        assert status.stock_name == "平安银行"
        assert status.as_of_date == date(2023, 7, 20)

        # 验证估值字段
        assert status.current_pe is not None
        assert status.current_pb > 0
        assert 0 <= status.composite_percentile <= 1

        # 验证阶段相关
        assert status.phase in [p.value for p in ValuationRepairPhase]
        assert status.signal in ["opportunity", "in_progress", "near_exit",
                                 "take_profit", "stalled", "none", "watch"]

        # 验证最低点信息
        assert status.lowest_percentile >= 0
        assert status.lowest_percentile_date is not None

    def test_undervalued_no_start_analysis(self):
        """测试低估但未启动修复的分析"""
        # 创建持续下降的历史
        history = []

        for i in range(150):
            pe = 30.0 - i * 0.15  # 持续下降
            pb = 3.0 - i * 0.015
            history.append(make_history_record(
                make_date(i),
                pe,
                pb
            ))

        status = analyze_repair_status(
            stock_code="000001.SZ",
            stock_name="平安银行",
            history=history
        )

        # 应该是低估或无需修复（因为没有反弹确认修复启动）
        assert status.repair_start_date is None
        assert status.repair_progress is None
        assert status.repair_speed_per_30d is None

    def test_completed_analysis(self):
        """测试完成状态分析"""
        # 创建已修复完成的历史
        history = []

        for i in range(150):
            # 前 50 天下降，之后大幅上升
            if i < 50:
                pe = 30.0 - i * 0.3
            else:
                pe = 15.0 + (i - 50) * 0.4  # 大幅上升

            pb = pe / 10  # 简化关系

            history.append(make_history_record(
                make_date(i),
                pe,
                pb
            ))

        status = analyze_repair_status(
            stock_code="000001.SZ",
            stock_name="平安银行",
            history=history
        )

        # 验证已完成修复
        if status.repair_start_date is not None:
            assert status.repair_progress is not None
            if status.composite_percentile >= 0.50:
                assert status.phase in [
                    ValuationRepairPhase.COMPLETED.value,
                    ValuationRepairPhase.OVERSHOOTING.value
                ]

    def test_pe_invalid_but_pb_valid(self):
        """测试 PE 无效但 PB 有效的整体分析"""
        history = []

        for i in range(150):
            # 前 50 天 PE 为负，之后为正
            pe = -5.0 if i < 50 else 5.0 + (i - 50) * 0.05  # 调整为较低的 PE
            pb = 0.5 + i * 0.005  # 从 0.5 开始

            history.append(make_history_record(
                make_date(i),
                pe,
                pb
            ))

        status = analyze_repair_status(
            stock_code="000001.SZ",
            stock_name="平安银行",
            history=history
        )

        # 应该正常返回
        # 最新记录的 PE 是正数，所以 current_pe 不应该为 None
        # 只有当最新记录的 PE <= 0 时才会是 None
        assert status.current_pe > 0  # 最新 PE 是正数
        assert status.current_pb > 0
        assert status.composite_method in ["pb_only", "pe_pb_blend"]

    def test_insufficient_history_raises_error(self):
        """测试历史数据不足抛出异常"""
        history = []

        for i in range(100):  # 少于 MIN_HISTORY_POINTS
            history.append(make_history_record(
                make_date(i),
                10.0 + i * 0.1,
                1.0 + i * 0.05
            ))

        with pytest.raises(InsufficientHistoryError):
            analyze_repair_status(
                stock_code="000001.SZ",
                stock_name="平安银行",
                history=history
            )

    def test_confidence_calculation(self):
        """测试置信度计算"""
        history = make_sample_history(300)  # 大样本

        status = analyze_repair_status(
            stock_code="000001.SZ",
            stock_name="平安银行",
            history=history
        )

        # 置信度应该在合理范围内
        assert 0.0 <= status.confidence <= 1.0

    def test_description_generation(self):
        """测试描述生成"""
        history = make_sample_history(200)

        status = analyze_repair_status(
            stock_code="000001.SZ",
            stock_name="平安银行",
            history=history
        )

        # 描述应该包含股票代码和关键信息
        assert "000001.SZ" in status.description
        assert len(status.description) > 0


# ==================== Test Signal Mapping ====================

class TestSignalMapping:
    """测试信号映射（间接通过 analyze_repair_status）"""

    def test_undervalued_to_opportunity(self):
        """测试低估映射为 opportunity"""
        # 创建低估但未启动修复的数据
        history = []

        for i in range(150):
            pe = 5.0 + i * 0.01  # 低 PE
            pb = 0.5 + i * 0.001  # 低 PB
            history.append(make_history_record(
                make_date(i),
                pe,
                pb
            ))

        status = analyze_repair_status(
            stock_code="000001.SZ",
            stock_name="平安银行",
            history=history
        )

        if status.phase == ValuationRepairPhase.UNDERVALUED.value:
            assert status.signal == "opportunity"

    def test_repairing_to_in_progress(self):
        """测试修复中映射为 in_progress"""
        # 通过创建特定场景来测试
        # 这里简化测试，直接测试阶段对应的信号
        from apps.equity.domain.services_valuation_repair import _map_phase_to_signal

        signal = _map_phase_to_signal(ValuationRepairPhase.REPAIRING.value)
        assert signal == "in_progress"

    def test_near_target_to_near_exit(self):
        """测试接近目标映射为 near_exit"""
        from apps.equity.domain.services_valuation_repair import _map_phase_to_signal

        signal = _map_phase_to_signal(ValuationRepairPhase.NEAR_TARGET.value)
        assert signal == "near_exit"

    def test_completed_to_take_profit(self):
        """测试完成映射为 take_profit"""
        from apps.equity.domain.services_valuation_repair import _map_phase_to_signal

        signal = _map_phase_to_signal(ValuationRepairPhase.COMPLETED.value)
        assert signal == "take_profit"

    def test_overshooting_to_take_profit(self):
        """测试超涨映射为 take_profit"""
        from apps.equity.domain.services_valuation_repair import _map_phase_to_signal

        signal = _map_phase_to_signal(ValuationRepairPhase.OVERSHOOTING.value)
        assert signal == "take_profit"

    def test_stalled_to_stalled(self):
        """测试停滞映射为 stalled"""
        from apps.equity.domain.services_valuation_repair import _map_phase_to_signal

        signal = _map_phase_to_signal(ValuationRepairPhase.STALLED.value)
        assert signal == "stalled"

    def test_no_repair_needed_to_none(self):
        """测试无需修复映射为 none"""
        from apps.equity.domain.services_valuation_repair import _map_phase_to_signal

        signal = _map_phase_to_signal(ValuationRepairPhase.NO_REPAIR_NEEDED.value)
        assert signal == "none"
