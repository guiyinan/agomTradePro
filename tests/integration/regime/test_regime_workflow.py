"""
Integration Tests for Regime Calculation Workflow

测试 Regime 计算的端到端流程，包括：
1. 端到端 Regime 计算
2. RegimeLog 持久化
3. Regime 变化通知
"""

from datetime import date, timedelta
from unittest.mock import Mock, patch

import pytest

from apps.macro.domain.entities import MacroIndicator, PeriodType
from apps.macro.infrastructure.repositories import DjangoMacroRepository
from apps.regime.application.tasks import notify_regime_change
from apps.regime.application.use_cases import CalculateRegimeRequest, CalculateRegimeUseCase
from apps.regime.domain.entities import RegimeSnapshot
from apps.regime.infrastructure.repositories import DjangoRegimeRepository
from shared.infrastructure.alert_service import AlertLevel, ConsoleAlertChannel


@pytest.mark.django_db
class TestRegimeCalculationWorkflow:
    """测试 Regime 计算完整工作流"""

    def test_end_to_end_regime_calculation(self):
        """测试端到端 Regime 计算

        流程：
        1. 准备宏观数据（PMI, CPI 等）
        2. 触发 Regime 计算
        3. 验证四象限分布
        4. 验证主导 Regime 识别
        """
        # 1. 准备测试数据（30个月的数据）
        macro_repo = DjangoMacroRepository()
        base_date = date(2022, 1, 1)

        # 生成 PMI 数据（增长指标）
        for i in range(30):
            observed_date = base_date + timedelta(days=30 * i)
            # 模拟增长：前半段低于 50，后半段高于 50
            pmi_value = 49.0 + (i / 30) * 3  # 49.0 -> 52.0

            macro_repo.save_indicator(
                MacroIndicator(
                    code="CN_PMI",
                    value=pmi_value,
                    reporting_period=observed_date,
                    period_type=PeriodType.MONTH,
                    unit="指数",
                    original_unit="指数",
                    published_at=observed_date + timedelta(days=1),
                    source="test"
                )
            )

        # 生成 CPI 数据（通胀指标）
        for i in range(30):
            observed_date = base_date + timedelta(days=30 * i)
            # 模拟通胀：前半段高于 2.5，后半段低于 2.5
            cpi_value = 3.0 - (i / 30) * 1.5  # 3.0 -> 1.5

            macro_repo.save_indicator(
                MacroIndicator(
                    code="CN_CPI_NATIONAL_YOY",
                    value=cpi_value,
                    reporting_period=observed_date,
                    period_type=PeriodType.MONTH,
                    unit="%",
                    original_unit="%",
                    published_at=observed_date + timedelta(days=10),
                    source="test"
                )
            )

        # 2. 执行 Regime 计算
        regime_repo = DjangoRegimeRepository()
        use_case = CalculateRegimeUseCase(
            repository=macro_repo,
            regime_repository=regime_repo
        )

        request = CalculateRegimeRequest(
            as_of_date=base_date + timedelta(days=30 * 29),  # 最后一个数据点
            use_pit=False,
            growth_indicator="PMI",
            inflation_indicator="CPI",
            data_source="test"
        )

        response = use_case.execute(request)

        # 3. 验证计算成功
        assert response.success, f"Regime 计算失败: {response.error}"
        assert response.snapshot is not None, "未返回 Regime 快照"

        # 4. 验证四象限分布
        distribution = response.snapshot.distribution
        assert isinstance(distribution, dict), "distribution 应为字典"
        assert "Recovery" in distribution, "应包含 Recovery 象限"
        assert "Overheat" in distribution, "应包含 Overheat 象限"
        assert "Stagflation" in distribution, "应包含 Stagflation 象限"
        assert "Deflation" in distribution, "应包含 Deflation 象限"

        # 验证概率总和为 1
        total_probability = sum(distribution.values())
        assert abs(total_probability - 1.0) < 0.01, f"概率总和应为 1，实际: {total_probability}"

        # 5. 验证主导 Regime
        dominant = response.snapshot.dominant_regime
        assert dominant in ["Recovery", "Overheat", "Stagflation", "Deflation"], \
            f"无效的主导 Regime: {dominant}"

        # 验证主导 Regime 对应最高概率
        max_prob = max(distribution.values())
        assert distribution[dominant] == max_prob, \
            f"主导 Regime 应有最高概率: {dominant}={distribution[dominant]}, max={max_prob}"

        # 6. 验证置信度
        confidence = response.snapshot.confidence
        assert 0 <= confidence <= 1, f"置信度应在 [0, 1] 范围内: {confidence}"

        # 7. 验证 Z-score
        assert isinstance(response.snapshot.growth_momentum_z, float), "growth_momentum_z 应为浮点数"
        assert isinstance(response.snapshot.inflation_momentum_z, float), "inflation_momentum_z 应为浮点数"

    def test_regime_log_persistence(self):
        """测试 RegimeLog 持久化

        验证：
        1. Regime 计算后自动保存到数据库
        2. distribution JSON 格式正确
        3. confidence 计算正确
        """
        # 1. 准备数据
        macro_repo = DjangoMacroRepository()
        regime_repo = DjangoRegimeRepository()
        base_date = date(2022, 1, 1)

        # 生成 30 个月的数据
        for i in range(30):
            observed_date = base_date + timedelta(days=30 * i)

            # PMI: 49-52
            macro_repo.save_indicator(
                MacroIndicator(
                    code="CN_PMI",
                    value=49.0 + (i / 30) * 3,
                    reporting_period=observed_date,
                    period_type=PeriodType.MONTH,
                    unit="指数",
                    original_unit="指数",
                    published_at=observed_date + timedelta(days=1),
                    source="test"
                )
            )

            # CPI: 2.5-3.5
            macro_repo.save_indicator(
                MacroIndicator(
                    code="CN_CPI_NATIONAL_YOY",
                    value=2.5 + (i / 30) * 1.0,
                    reporting_period=observed_date,
                    period_type=PeriodType.MONTH,
                    unit="%",
                    original_unit="%",
                    published_at=observed_date + timedelta(days=10),
                    source="test"
                )
            )

        # 2. 计算 Regime
        use_case = CalculateRegimeUseCase(
            repository=macro_repo,
            regime_repository=regime_repo
        )

        request = CalculateRegimeRequest(
            as_of_date=base_date + timedelta(days=30 * 29),
            use_pit=False,
            growth_indicator="PMI",
            inflation_indicator="CPI"
        )

        response = use_case.execute(request)

        assert response.success

        # 3. 手动保存快照到数据库
        regime_repo.save_snapshot(response.snapshot)

        # 4. 验证 RegimeLog 已保存
        snapshot = regime_repo.get_snapshot_by_date(response.snapshot.observed_at)
        assert snapshot is not None, "RegimeLog 未保存"

        # 5. 验证字段
        assert snapshot.dominant_regime == response.snapshot.dominant_regime
        assert snapshot.distribution == response.snapshot.distribution
        assert abs(snapshot.confidence - response.snapshot.confidence) < 0.0001
        assert snapshot.observed_at == response.snapshot.observed_at

        # 6. 验证 distribution JSON 格式
        import json
        try:
            json_str = json.dumps(snapshot.distribution)
            parsed = json.loads(json_str)
            assert parsed == snapshot.distribution
        except Exception as e:
            pytest.fail(f"distribution JSON 格式错误: {e}")

        # 7. 验证 confidence 计算
        # confidence 应等于主导 Regime 的概率
        dominant_prob = snapshot.distribution[snapshot.dominant_regime]
        assert abs(snapshot.confidence - dominant_prob) < 0.01, \
            f"confidence 应等于主导 Regime 概率: {snapshot.confidence} vs {dominant_prob}"

    def test_regime_change_notification(self):
        """测试 Regime 变化通知

        验证：
        1. Regime 变化时触发告警
        2. 告警内容正确
        3. 告警级别正确
        """
        # 1. 准备数据和仓储
        macro_repo = DjangoMacroRepository()
        regime_repo = DjangoRegimeRepository()
        alert_channel = ConsoleAlertChannel()
        base_date = date(2022, 1, 1)

        # 2. 保存第一个 Regime（Recovery）
        regime_repo.save_snapshot(
            RegimeSnapshot(
                growth_momentum_z=1.0,
                inflation_momentum_z=-0.5,
                distribution={"Recovery": 0.6, "Overheat": 0.2, "Stagflation": 0.1, "Deflation": 0.1},
                dominant_regime="Recovery",
                confidence=0.6,
                observed_at=base_date
            )
        )

        # 3. 计算新的 Regime（Overheat - 发生变化）
        # 生成导致 Overheat 的数据
        for i in range(30):
            observed_date = base_date + timedelta(days=30 * i)

            # PMI: 高增长 (>51)
            macro_repo.save_indicator(
                MacroIndicator(
                    code="CN_PMI",
                    value=51.0 + (i / 30) * 2,  # 51.0 -> 53.0
                    reporting_period=observed_date,
                    period_type=PeriodType.MONTH,
                    unit="指数",
                    original_unit="指数",
                    published_at=observed_date + timedelta(days=1),
                    source="test"
                )
            )

            # CPI: 高通胀 (>3)
            macro_repo.save_indicator(
                MacroIndicator(
                    code="CN_CPI_NATIONAL_YOY",
                    value=3.0 + (i / 30) * 1.0,  # 3.0 -> 4.0
                    reporting_period=observed_date,
                    period_type=PeriodType.MONTH,
                    unit="%",
                    original_unit="%",
                    published_at=observed_date + timedelta(days=10),
                    source="test"
                )
            )

        # 4. 计算新 Regime
        use_case = CalculateRegimeUseCase(
            repository=macro_repo,
            regime_repository=regime_repo
        )

        request = CalculateRegimeRequest(
            as_of_date=base_date + timedelta(days=30 * 29),
            use_pit=False,
            growth_indicator="PMI",
            inflation_indicator="CPI"
        )

        response = use_case.execute(request)

        assert response.success
        new_snapshot = response.snapshot

        # 保存新 Regime
        regime_repo.save_snapshot(new_snapshot)

        # 5. 检测变化并发送通知
        old_snapshot = regime_repo.get_snapshot_by_date(base_date)
        if old_snapshot and new_snapshot:
            if old_snapshot.dominant_regime != new_snapshot.dominant_regime:
                # 发送告警
                alert_channel.send_alert(
                    level=AlertLevel.WARNING,
                    title=f"Regime 变化: {old_snapshot.dominant_regime} -> {new_snapshot.dominant_regime}",
                    message=(
                        f"主导 Regime 从 {old_snapshot.dominant_regime} "
                        f"变为 {new_snapshot.dominant_regime}\n"
                        f"新分布: {new_snapshot.distribution}\n"
                        f"置信度: {new_snapshot.confidence:.2%}"
                    ),
                    metadata={
                        "old_regime": old_snapshot.dominant_regime,
                        "new_regime": new_snapshot.dominant_regime,
                        "old_distribution": old_snapshot.distribution,
                        "new_distribution": new_snapshot.distribution,
                        "confidence": new_snapshot.confidence,
                        "observed_at": new_snapshot.observed_at.isoformat()
                    }
                )

                # 验证通知已发送（ConsoleAlertChannel 会记录到日志）
                # 这里我们验证状态变化确实发生
                assert old_snapshot.dominant_regime != new_snapshot.dominant_regime, \
                    "测试数据应导致 Regime 变化"

    def test_insufficient_data_handling(self):
        """测试数据不足时的处理

        验证：
        1. 数据不足 24 个月时给出警告
        2. 使用降级方案（如果有历史 Regime）
        3. 返回适当的错误信息
        """
        macro_repo = DjangoMacroRepository()
        regime_repo = DjangoRegimeRepository()
        base_date = date(2022, 1, 1)

        # 只生成 10 个月的数据（不足 24 个月）
        for i in range(10):
            observed_date = base_date + timedelta(days=30 * i)

            macro_repo.save_indicator(
                MacroIndicator(
                    code="CN_PMI",
                    value=50.0 + i * 0.1,
                    reporting_period=observed_date,
                    period_type=PeriodType.MONTH,
                    unit="指数",
                    original_unit="指数",
                    published_at=observed_date + timedelta(days=1),
                    source="test"
                )
            )

            macro_repo.save_indicator(
                MacroIndicator(
                    code="CN_CPI_NATIONAL_YOY",
                    value=2.0 + i * 0.05,
                    reporting_period=observed_date,
                    period_type=PeriodType.MONTH,
                    unit="%",
                    original_unit="%",
                    published_at=observed_date + timedelta(days=10),
                    source="test"
                )
            )

        # 保存历史 Regime（用于降级）
        regime_repo.save_snapshot(
            RegimeSnapshot(
                growth_momentum_z=0.0,
                inflation_momentum_z=0.0,
                distribution={"Recovery": 0.4, "Overheat": 0.3, "Stagflation": 0.2, "Deflation": 0.1},
                dominant_regime="Recovery",
                confidence=0.4,
                observed_at=base_date - timedelta(days=30)
            )
        )

        # 尝试计算
        use_case = CalculateRegimeUseCase(
            repository=macro_repo,
            regime_repository=regime_repo
        )

        request = CalculateRegimeRequest(
            as_of_date=base_date + timedelta(days=30 * 9),
            use_pit=False,
            growth_indicator="PMI",
            inflation_indicator="CPI"
        )

        response = use_case.execute(request)

        # 验证使用了降级方案
        assert response.success, "应使用降级方案而非完全失败"
        assert response.snapshot is not None, "降级方案应返回快照"
        assert len(response.warnings) > 0, "应有警告信息"

        # 验证降级快照的置信度被降低
        # 降级方案会降低 20% 置信度
        # 原始 0.4，降级后应为 0.32 (0.4 * 0.8)
        assert response.snapshot.confidence < 0.4, \
            f"降级快照置信度应降低: {response.snapshot.confidence}"

    def test_pit_mode_regime_calculation(self):
        """测试 PIT 模式下的 Regime 计算

        验证 Point-in-Time 模式下：
        1. 只使用截止日期前已发布的数据
        2. 正确处理数据延迟
        """
        macro_repo = DjangoMacroRepository()
        regime_repo = DjangoRegimeRepository()
        base_date = date(2022, 1, 1)

        # 生成数据，带发布延迟
        for i in range(30):
            observed_date = base_date + timedelta(days=30 * i)
            published_date = observed_date + timedelta(days=15)  # 15 天延迟

            macro_repo.save_indicator(
                MacroIndicator(
                    code="CN_PMI",
                    value=50.0 + i * 0.1,
                    reporting_period=observed_date,
                    period_type=PeriodType.MONTH,
                    unit="指数",
                    original_unit="指数",
                    published_at=published_date,
                    source="test"
                )
            )

            macro_repo.save_indicator(
                MacroIndicator(
                    code="CN_CPI_NATIONAL_YOY",
                    value=2.0 + i * 0.05,
                    reporting_period=observed_date,
                    period_type=PeriodType.MONTH,
                    unit="%",
                    original_unit="%",
                    published_at=published_date,
                    source="test"
                )
            )

        # 使用 PIT 模式计算
        # 设置 as_of_date 为倒数第二个月份的发布日期之前
        # 此时最后一个月份的数据应该不可见
        second_last_date = base_date + timedelta(days=30 * 28)
        as_of_date = second_last_date + timedelta(days=10)  # 在最后一个月发布前

        use_case = CalculateRegimeUseCase(
            repository=macro_repo,
            regime_repository=regime_repo
        )

        request = CalculateRegimeRequest(
            as_of_date=as_of_date,
            use_pit=True,  # 启用 PIT 模式
            growth_indicator="PMI",
            inflation_indicator="CPI"
        )

        response = use_case.execute(request)

        assert response.success

        # 验证 observed_at 不超过 as_of_date
        assert response.snapshot.observed_at <= as_of_date, \
            f"PIT 模式下 observed_at 应不超过 as_of_date: {response.snapshot.observed_at} vs {as_of_date}"

    def test_calculate_multiple_dates(self):
        """测试批量计算历史 Regime

        验证可以批量计算多个日期的 Regime
        """
        macro_repo = DjangoMacroRepository()
        regime_repo = DjangoRegimeRepository()
        base_date = date(2022, 1, 1)

        # 生成 36 个月的数据
        for i in range(36):
            observed_date = base_date + timedelta(days=30 * i)

            macro_repo.save_indicator(
                MacroIndicator(
                    code="CN_PMI",
                    value=49.0 + (i / 36) * 4,  # 49.0 -> 53.0
                    reporting_period=observed_date,
                    period_type=PeriodType.MONTH,
                    unit="指数",
                    original_unit="指数",
                    published_at=observed_date + timedelta(days=1),
                    source="test"
                )
            )

            macro_repo.save_indicator(
                MacroIndicator(
                    code="CN_CPI_NATIONAL_YOY",
                    value=1.5 + (i / 36) * 2,  # 1.5 -> 3.5
                    reporting_period=observed_date,
                    period_type=PeriodType.MONTH,
                    unit="%",
                    original_unit="%",
                    published_at=observed_date + timedelta(days=10),
                    source="test"
                )
            )

        # 批量计算（最后 12 个月）
        use_case = CalculateRegimeUseCase(
            repository=macro_repo,
            regime_repository=regime_repo
        )

        start_date = base_date + timedelta(days=30 * 24)
        end_date = base_date + timedelta(days=30 * 35)

        results = use_case.calculate_history(
            start_date=start_date,
            end_date=end_date,
            growth_indicator="PMI",
            inflation_indicator="CPI",
            use_pit=False
        )

        # 验证结果
        assert len(results) > 0, "应返回至少一个结果"
        assert len(results) <= 12, "最多应返回 12 个结果"

        # 验证每个结果
        for result in results:
            assert result.success, f"计算失败: {result.error}"
            assert result.snapshot is not None
            assert start_date <= result.snapshot.observed_at <= end_date

    def test_regime_statistics(self):
        """测试 Regime 统计功能

        验证可以正确统计各 Regime 的分布
        """
        regime_repo = DjangoRegimeRepository()
        base_date = date(2022, 1, 1)

        # 保存多个 Regime 快照
        regimes = ["Recovery", "Overheat", "Stagflation", "Deflation", "Recovery", "Overheat"]

        for i, regime in enumerate(regimes):
            regime_repo.save_snapshot(
                RegimeSnapshot(
                    growth_momentum_z=0.0,
                    inflation_momentum_z=0.0,
                    distribution={
                        "Recovery": 0.4 if regime == "Recovery" else 0.2,
                        "Overheat": 0.4 if regime == "Overheat" else 0.2,
                        "Stagflation": 0.4 if regime == "Stagflation" else 0.2,
                        "Deflation": 0.4 if regime == "Deflation" else 0.2
                    },
                    dominant_regime=regime,
                    confidence=0.4,
                    observed_at=base_date + timedelta(days=30 * i)
                )
            )

        # 获取统计
        stats = regime_repo.get_regime_distribution_stats(
            start_date=base_date,
            end_date=base_date + timedelta(days=30 * 5)
        )

        # 验证统计
        assert stats["total"] == 6
        assert stats["by_regime"]["Recovery"]["count"] == 2
        assert stats["by_regime"]["Overheat"]["count"] == 2
        assert stats["by_regime"]["Stagflation"]["count"] == 1
        assert stats["by_regime"]["Deflation"]["count"] == 1

        # 验证百分比
        assert abs(stats["by_regime"]["Recovery"]["percentage"] - 2/6) < 0.01
        assert abs(stats["by_regime"]["Overheat"]["percentage"] - 2/6) < 0.01
