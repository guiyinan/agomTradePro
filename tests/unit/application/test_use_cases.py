"""
Unit Tests for Application Use Cases

测试 Application 层的 Use Cases，包括：
1. SyncMacroDataUseCase - 宏观数据同步编排
2. GetLatestMacroDataUseCase - 最新数据获取
3. CalculateRegimeUseCase - Regime 计算编排、降级方案
"""

from datetime import date, timedelta
from unittest.mock import MagicMock, Mock, patch

import pytest

from apps.macro.application.use_cases import (
    GetLatestMacroDataRequest,
    GetLatestMacroDataResponse,
    GetLatestMacroDataUseCase,
    MacroDataPoint,
    SyncMacroDataRequest,
    SyncMacroDataResponse,
    SyncMacroDataUseCase,
)
from apps.macro.domain.entities import MacroIndicator, PeriodType
from apps.regime.application.use_cases import (
    CalculateRegimeRequest,
    CalculateRegimeResponse,
    CalculateRegimeUseCase,
    RegimeCalculationError,
)
from apps.regime.domain.entities import RegimeSnapshot

# ============================================================================
# Test SyncMacroDataUseCase
# ============================================================================

@pytest.mark.django_db
class TestSyncMacroDataUseCase:
    """测试 SyncMacroDataUseCase"""

    def test_execute_success(self):
        """测试成功同步数据"""
        # Mock repository
        repository = Mock()
        repository.get_by_code_and_date.return_value = None  # 无现有数据
        repository.save_indicators_batch.return_value = None

        # Mock adapter
        adapter = Mock()
        adapter.supports.return_value = True
        adapter.fetch.return_value = [
            MacroDataPoint(
                code="CN_PMI",
                value=50.5,
                observed_at=date(2024, 1, 1),
                published_at=date(2024, 1, 2),
                source="test",
                unit="指数",
                original_unit="指数"
            )
        ]

        use_case = SyncMacroDataUseCase(
            repository=repository,
            adapters={"test": adapter}
        )

        request = SyncMacroDataRequest(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            indicators=["CN_PMI"]
        )

        response = use_case.execute(request)

        assert response.success
        assert response.synced_count == 1
        assert len(response.errors) == 0
        repository.save_indicators_batch.assert_called_once()

    def test_execute_with_empty_data(self):
        """测试适配器返回空数据"""
        repository = Mock()
        adapter = Mock()
        adapter.supports.return_value = True
        adapter.fetch.return_value = []  # 空数据

        use_case = SyncMacroDataUseCase(
            repository=repository,
            adapters={"test": adapter}
        )

        request = SyncMacroDataRequest(
            start_date=date(2024, 1, 1),
            indicators=["CN_PMI"]
        )

        response = use_case.execute(request)

        assert not response.success
        assert response.synced_count == 0
        assert len(response.errors) == 1
        assert "无数据返回" in response.errors[0]

    def test_execute_deduplicates_existing_data(self):
        """测试去重现有数据"""
        repository = Mock()
        # 第一次调用返回现有数据，第二次返回 None（新数据）
        repository.get_by_code_and_date.side_effect = [
            MacroIndicator(  # 数据已存在（内容相同，应被去重）
                code="CN_PMI",
                value=50.5,
                reporting_period=date(2024, 1, 1),
                published_at=date(2024, 1, 2),
                source="test",
                unit="指数",
                original_unit="指数",
                period_type='M'
            ),
            None    # 数据不存在
        ]
        repository.save_indicators_batch.return_value = None

        adapter = Mock()
        adapter.supports.return_value = True
        adapter.fetch.return_value = [
            MacroDataPoint(
                code="CN_PMI",
                value=50.5,
                observed_at=date(2024, 1, 1),
                published_at=date(2024, 1, 2),
                source="test",
                unit="指数"
            ),
            MacroDataPoint(
                code="CN_PMI",
                value=51.0,
                observed_at=date(2024, 2, 1),
                published_at=date(2024, 2, 2),
                source="test",
                unit="指数"
            )
        ]

        use_case = SyncMacroDataUseCase(
            repository=repository,
            adapters={"test": adapter}
        )

        request = SyncMacroDataRequest(
            start_date=date(2024, 1, 1),
            indicators=["CN_PMI"]
        )

        response = use_case.execute(request)

        # 应该只保存一条新数据（去重后）
        assert response.synced_count == 1
        assert response.skipped_count == 1

    def test_execute_adapter_error_handling(self):
        """测试适配器异常处理"""
        repository = Mock()
        adapter = Mock()
        adapter.supports.return_value = True
        adapter.fetch.side_effect = Exception("Adapter error")

        use_case = SyncMacroDataUseCase(
            repository=repository,
            adapters={"test": adapter}
        )

        request = SyncMacroDataRequest(
            start_date=date(2024, 1, 1),
            indicators=["CN_PMI"]
        )

        response = use_case.execute(request)

        assert not response.success
        assert len(response.errors) == 1
        assert "Adapter error" in response.errors[0]

    def test_execute_with_default_indicators(self):
        """测试使用默认指标列表"""
        repository = Mock()
        repository.get_by_code_and_date.return_value = None
        repository.save_indicators_batch.return_value = None

        adapter = Mock()
        adapter.supports.return_value = True
        adapter.fetch.return_value = []

        use_case = SyncMacroDataUseCase(
            repository=repository,
            adapters={"test": adapter}
        )

        request = SyncMacroDataRequest(
            start_date=date(2024, 1, 1)
            # 未指定 indicators，应使用默认列表
        )

        use_case.execute(request)

        # 验证调用了默认指标列表中的指标
        # 默认列表包含 CN_PMI, CN_CPI 等多个指标
        assert adapter.fetch.call_count > 0

    def test_unit_conversion_for_currency(self):
        """测试货币单位转换"""
        repository = Mock()
        repository.get_by_code_and_date.return_value = None
        repository.save_indicators_batch.return_value = None

        adapter = Mock()
        adapter.supports.return_value = True
        # 新增信贷数据（万亿元）
        adapter.fetch.return_value = [
            MacroDataPoint(
                code="CN_NEW_CREDIT",
                value=3.5,  # 3.5 万亿元
                observed_at=date(2024, 1, 1),
                published_at=date(2024, 1, 15),
                source="test",
                unit="万亿元",
                original_unit="万亿元"
            )
        ]

        use_case = SyncMacroDataUseCase(
            repository=repository,
            adapters={"test": adapter}
        )

        request = SyncMacroDataRequest(
            start_date=date(2024, 1, 1),
            indicators=["CN_NEW_CREDIT"]
        )

        response = use_case.execute(request)

        # 验证保存的数据
        assert response.synced_count == 1
        saved_indicators = repository.save_indicators_batch.call_args[0][0]
        saved = saved_indicators[0]

        # macro 应用层现在只保留原始值/原始单位，canonical 转换在 data_center 入库阶段完成
        assert saved.unit == "万亿元"
        assert saved.value == 3.5
        assert saved.original_unit == "万亿元"


# ============================================================================
# Test GetLatestMacroDataUseCase
# ============================================================================

@pytest.mark.django_db
class TestGetLatestMacroDataUseCase:
    """测试 GetLatestMacroDataUseCase"""

    def test_execute_success(self):
        """测试成功获取最新数据"""
        repository = Mock()
        repository.get_latest_observation_date.return_value = date(2024, 1, 1)
        repository.get_by_code_and_date.return_value = MacroIndicator(
            code="CN_PMI",
            value=50.5,
            reporting_period=date(2024, 1, 1),
            period_type=PeriodType.MONTH,
            unit="指数",
            original_unit="指数",
            published_at=date(2024, 1, 2),
            source="test"
        )

        use_case = GetLatestMacroDataUseCase(repository=repository)

        request = GetLatestMacroDataRequest(
            indicator_codes=["CN_PMI", "CN_CPI"],
            as_of_date=date(2024, 1, 31)
        )

        response = use_case.execute(request)

        assert "CN_PMI" in response.data
        assert response.data["CN_PMI"].value == 50.5

    def test_execute_with_missing_data(self):
        """测试数据缺失"""
        repository = Mock()
        # CN_PMI 有数据
        repository.get_latest_observation_date.side_effect = lambda code, as_of_date: (
            date(2024, 1, 1) if code == "CN_PMI" else None
        )
        repository.get_by_code_and_date.return_value = MacroIndicator(
            code="CN_PMI",
            value=50.5,
            reporting_period=date(2024, 1, 1),
            period_type=PeriodType.MONTH,
            unit="指数",
            original_unit="指数",
            published_at=date(2024, 1, 2),
            source="test"
        )

        use_case = GetLatestMacroDataUseCase(repository=repository)

        request = GetLatestMacroDataRequest(
            indicator_codes=["CN_PMI", "CN_CPI"]  # CN_CPI 无数据
        )

        response = use_case.execute(request)

        assert "CN_PMI" in response.data
        assert "CN_CPI" in response.missing

    def test_execute_without_as_of_date(self):
        """测试不指定截止日期（使用当前）"""
        repository = Mock()
        repository.get_latest_observation_date.return_value = date(2024, 1, 1)
        repository.get_by_code_and_date.return_value = MacroIndicator(
            code="CN_PMI",
            value=50.5,
            reporting_period=date(2024, 1, 1),
            period_type=PeriodType.MONTH,
            unit="指数",
            original_unit="指数",
            published_at=date(2024, 1, 2),
            source="test"
        )

        use_case = GetLatestMacroDataUseCase(repository=repository)

        request = GetLatestMacroDataRequest(
            indicator_codes=["CN_PMI"]
            # 未指定 as_of_date
        )

        response = use_case.execute(request)

        # repository 应该被调用
        repository.get_latest_observation_date.assert_called_once()


# ============================================================================
# Test CalculateRegimeUseCase
# ============================================================================

@pytest.mark.django_db
class TestCalculateRegimeUseCase:
    """测试 CalculateRegimeUseCase"""

    def test_execute_success(self):
        """测试成功计算 Regime"""
        repository = Mock()
        repository.GROWTH_INDICATORS = {"PMI": "CN_PMI"}
        repository.INFLATION_INDICATORS = {"CPI": "CN_CPI"}

        # 模拟 24 个月的数据
        growth_series = [50.0 + i * 0.1 for i in range(24)]
        inflation_series = [2.0 + i * 0.05 for i in range(24)]

        repository.get_growth_series.return_value = growth_series
        repository.get_inflation_series.return_value = inflation_series

        # 模拟完整指标数据
        growth_full = [
            MacroIndicator(
                code="CN_PMI",
                value=50.0 + i * 0.1,
                reporting_period=date(2022, 1, 1) + timedelta(days=30 * i),
                period_type=PeriodType.MONTH,
                unit="指数",
                original_unit="指数",
                published_at=date(2022, 1, 2) + timedelta(days=30 * i),
                source="test"
            )
            for i in range(24)
        ]
        inflation_full = [
            MacroIndicator(
                code="CN_CPI",
                value=2.0 + i * 0.05,
                reporting_period=date(2022, 1, 1) + timedelta(days=30 * i),
                period_type=PeriodType.MONTH,
                unit="%",
                original_unit="%",
                published_at=date(2022, 1, 12) + timedelta(days=30 * i),
                source="test"
            )
            for i in range(24)
        ]

        repository.get_growth_series_full.return_value = growth_full
        repository.get_inflation_series_full.return_value = inflation_full

        use_case = CalculateRegimeUseCase(repository=repository)

        request = CalculateRegimeRequest(
            as_of_date=date(2024, 1, 1),
            growth_indicator="PMI",
            inflation_indicator="CPI"
        )

        response = use_case.execute(request)

        assert response.success
        assert response.snapshot is not None
        assert response.error is None

    def test_execute_insufficient_data_with_fallback(self):
        """测试数据不足时使用降级方案"""
        repository = Mock()
        repository.GROWTH_INDICATORS = {"PMI": "CN_PMI"}
        repository.INFLATION_INDICATORS = {"CPI": "CN_CPI"}
        repository.get_growth_series.return_value = []  # 无数据
        repository.get_inflation_series.return_value = []
        repository.get_growth_series_full.return_value = []
        repository.get_inflation_series_full.return_value = []

        # Mock regime repository for fallback
        regime_repository = Mock()
        regime_repository.get_latest_snapshot.return_value = RegimeSnapshot(
            growth_momentum_z=1.0,
            inflation_momentum_z=-0.5,
            distribution={"Recovery": 0.6, "Overheat": 0.2, "Stagflation": 0.1, "Deflation": 0.1},
            dominant_regime="Recovery",
            confidence=0.6,
            observed_at=date(2023, 12, 31)
        )

        use_case = CalculateRegimeUseCase(
            repository=repository,
            regime_repository=regime_repository
        )

        request = CalculateRegimeRequest(
            as_of_date=date(2024, 1, 1)
        )

        response = use_case.execute(request)

        # 应该使用降级方案
        assert response.success
        assert response.snapshot is not None
        assert response.snapshot.dominant_regime == "Recovery"
        assert response.snapshot.confidence < 0.6  # 置信度应降低
        assert "降级方案" in str(response.warnings)

    def test_execute_no_fallback_available(self):
        """测试无降级方案可用"""
        repository = Mock()
        repository.GROWTH_INDICATORS = {"PMI": "CN_PMI"}
        repository.INFLATION_INDICATORS = {"CPI": "CN_CPI"}
        repository.get_growth_series.return_value = []
        repository.get_inflation_series.return_value = []
        repository.get_growth_series_full.return_value = []
        repository.get_inflation_series_full.return_value = []

        # 无 regime repository
        use_case = CalculateRegimeUseCase(repository=repository)

        request = CalculateRegimeRequest(
            as_of_date=date(2024, 1, 1)
        )

        response = use_case.execute(request)

        # 应该失败
        assert not response.success
        assert response.snapshot is None
        assert response.error is not None

    def test_execute_with_forward_fill(self):
        """测试前值填充"""
        repository = Mock()
        repository.GROWTH_INDICATORS = {"PMI": "CN_PMI"}
        repository.INFLATION_INDICATORS = {"CPI": "CN_CPI"}

        # 增长系列不足 24 个点
        growth_series = [50.0 + i * 0.1 for i in range(12)]
        inflation_series = [2.0 + i * 0.05 for i in range(24)]

        repository.get_growth_series.return_value = growth_series
        repository.get_inflation_series.return_value = inflation_series

        # Mock 前值填充
        repository.get_latest_observation.return_value = MacroIndicator(
            code="CN_PMI",
            value=49.9,
            reporting_period=date(2023, 11, 1),
            period_type=PeriodType.MONTH,
            unit="指数",
            original_unit="指数",
            published_at=date(2023, 11, 2),
            source="test"
        )

        growth_full = [
            MacroIndicator(
                code="CN_PMI",
                value=50.0 + i * 0.1,
                reporting_period=date(2023, 2, 1) + timedelta(days=30 * i),
                period_type=PeriodType.MONTH,
                unit="指数",
                original_unit="指数",
                published_at=date(2023, 2, 2) + timedelta(days=30 * i),
                source="test"
            )
            for i in range(12)
        ]
        inflation_full = [
            MacroIndicator(
                code="CN_CPI",
                value=2.0 + i * 0.05,
                reporting_period=date(2022, 2, 1) + timedelta(days=30 * i),
                period_type=PeriodType.MONTH,
                unit="%",
                original_unit="%",
                published_at=date(2022, 2, 12) + timedelta(days=30 * i),
                source="test"
            )
            for i in range(24)
        ]

        repository.get_growth_series_full.return_value = growth_full
        repository.get_inflation_series_full.return_value = inflation_full

        # Mock regime repository for fallback
        regime_repository = Mock()
        regime_repository.get_latest_snapshot.return_value = RegimeSnapshot(
            growth_momentum_z=1.0,
            inflation_momentum_z=-0.5,
            distribution={"Recovery": 0.6},
            dominant_regime="Recovery",
            confidence=0.6,
            observed_at=date(2023, 12, 31)
        )

        use_case = CalculateRegimeUseCase(
            repository=repository,
            regime_repository=regime_repository
        )

        request = CalculateRegimeRequest(
            as_of_date=date(2024, 1, 1)
        )

        response = use_case.execute(request)

        # 应该成功（使用降级方案），并使用前值填充
        assert response.success
        assert response.snapshot is not None
        # 应该有前值填充警告
        assert any("前值填充" in w for w in response.warnings)

    def test_execute_with_pit_mode(self):
        """测试 PIT 模式"""
        repository = Mock()
        repository.GROWTH_INDICATORS = {"PMI": "CN_PMI"}
        repository.INFLATION_INDICATORS = {"CPI": "CN_CPI"}

        growth_series = [50.0 + i * 0.1 for i in range(24)]
        inflation_series = [2.0 + i * 0.05 for i in range(24)]

        repository.get_growth_series.return_value = growth_series
        repository.get_inflation_series.return_value = inflation_series

        growth_full = [
            MacroIndicator(
                code="CN_PMI",
                value=50.0 + i * 0.1,
                reporting_period=date(2022, 1, 1) + timedelta(days=30 * i),
                period_type=PeriodType.MONTH,
                unit="指数",
                original_unit="指数",
                published_at=date(2022, 1, 2) + timedelta(days=30 * i),
                source="test"
            )
            for i in range(24)
        ]
        inflation_full = [
            MacroIndicator(
                code="CN_CPI",
                value=2.0 + i * 0.05,
                reporting_period=date(2022, 1, 1) + timedelta(days=30 * i),
                period_type=PeriodType.MONTH,
                unit="%",
                original_unit="%",
                published_at=date(2022, 1, 12) + timedelta(days=30 * i),
                source="test"
            )
            for i in range(24)
        ]

        repository.get_growth_series_full.return_value = growth_full
        repository.get_inflation_series_full.return_value = inflation_full

        use_case = CalculateRegimeUseCase(repository=repository)

        request = CalculateRegimeRequest(
            as_of_date=date(2024, 1, 1),
            use_pit=True  # 启用 PIT 模式
        )

        response = use_case.execute(request)

        # 验证使用了 PIT 模式
        assert response.success
        repository.get_growth_series.assert_called_with(
            indicator_code="PMI",
            end_date=date(2024, 1, 1),
            use_pit=True,
            source=None
        )

    def test_calculate_history(self):
        """测试批量历史计算"""
        repository = Mock()
        repository.GROWTH_INDICATORS = {"PMI": "CN_PMI"}
        repository.INFLATION_INDICATORS = {"CPI": "CN_CPI"}

        growth_series = [50.0 + i * 0.1 for i in range(24)]
        inflation_series = [2.0 + i * 0.05 for i in range(24)]

        repository.get_growth_series.return_value = growth_series
        repository.get_inflation_series.return_value = inflation_series
        repository.get_growth_series_full.return_value = []
        repository.get_inflation_series_full.return_value = []

        # 模拟可用日期
        repository.get_available_dates.return_value = [
            date(2024, 1, 1),
            date(2024, 2, 1),
            date(2024, 3, 1)
        ]

        use_case = CalculateRegimeUseCase(repository=repository)

        results = use_case.calculate_history(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 3, 31)
        )

        # 应该返回 3 个结果
        assert len(results) == 3
        assert all(isinstance(r, CalculateRegimeResponse) for r in results)

    def test_data_completeness_check(self):
        """测试数据完整性检查"""
        repository = Mock()
        repository.GROWTH_INDICATORS = {"PMI": "CN_PMI"}
        repository.INFLATION_INDICATORS = {"CPI": "CN_CPI"}

        # 数据不足 24 个点
        growth_series = [50.0 + i * 0.1 for i in range(10)]
        inflation_series = [2.0 + i * 0.05 for i in range(10)]

        repository.get_growth_series.return_value = growth_series
        repository.get_inflation_series.return_value = inflation_series
        repository.get_latest_observation.return_value = None  # 无前值可用
        repository.get_growth_series_full.return_value = []
        repository.get_inflation_series_full.return_value = []

        use_case = CalculateRegimeUseCase(repository=repository)

        request = CalculateRegimeRequest(
            as_of_date=date(2024, 1, 1)
        )

        response = use_case.execute(request)

        # 由于无前值且无 regime_repository，应该失败
        assert not response.success

    def test_fallback_count_limit(self):
        """测试降级次数限制（防止无限循环）"""
        repository = Mock()
        repository.GROWTH_INDICATORS = {"PMI": "CN_PMI"}
        repository.INFLATION_INDICATORS = {"CPI": "CN_CPI"}
        repository.get_growth_series.return_value = []  # 持续无数据
        repository.get_inflation_series.return_value = []
        repository.get_growth_series_full.return_value = []
        repository.get_inflation_series_full.return_value = []

        # Mock regime repository for fallback
        regime_repository = Mock()
        regime_repository.get_latest_snapshot.return_value = RegimeSnapshot(
            growth_momentum_z=1.0,
            inflation_momentum_z=-0.5,
            distribution={"Recovery": 0.6, "Overheat": 0.2, "Stagflation": 0.1, "Deflation": 0.1},
            dominant_regime="Recovery",
            confidence=0.6,
            observed_at=date(2023, 12, 31)
        )

        use_case = CalculateRegimeUseCase(
            repository=repository,
            regime_repository=regime_repository
        )

        # 第一次降级 - 应该成功
        request = CalculateRegimeRequest(as_of_date=date(2024, 1, 1))
        response = use_case.execute(request)
        assert response.success, "First fallback should succeed"
        assert response.snapshot.confidence < 0.6, "Confidence should be reduced"

        # 第二次降级 - 应该成功
        response = use_case.execute(request)
        assert response.success, "Second fallback should succeed"

        # 第三次降级 - 应该成功（达到限制边界）
        response = use_case.execute(request)
        assert response.success, "Third fallback should succeed"

        # 第四次降级 - 应该失败（超过限制）
        # 直接调用 _fallback_regime_estimation 来模拟第4次连续降级
        with pytest.raises(RegimeCalculationError, match="Maximum fallback count"):
            # 模拟已经降级了3次，这是第4次
            use_case._consecutive_fallback_count = 3
            use_case._fallback_regime_estimation(date(2024, 1, 1))

    def test_fallback_count_reset_on_success(self):
        """测试成功计算后重置降级计数器"""
        repository = Mock()
        repository.GROWTH_INDICATORS = {"PMI": "CN_PMI"}
        repository.INFLATION_INDICATORS = {"CPI": "CN_CPI"}

        regime_repository = Mock()
        regime_repository.get_latest_snapshot.return_value = RegimeSnapshot(
            growth_momentum_z=1.0,
            inflation_momentum_z=-0.5,
            distribution={"Recovery": 0.6, "Overheat": 0.2, "Stagflation": 0.1, "Deflation": 0.1},
            dominant_regime="Recovery",
            confidence=0.6,
            observed_at=date(2023, 12, 31)
        )

        use_case = CalculateRegimeUseCase(
            repository=repository,
            regime_repository=regime_repository
        )

        # 第一次：降级
        repository.get_growth_series.return_value = []
        repository.get_inflation_series.return_value = []
        repository.get_growth_series_full.return_value = []
        repository.get_inflation_series_full.return_value = []
        request = CalculateRegimeRequest(as_of_date=date(2024, 1, 1))
        response = use_case.execute(request)
        assert response.success, "First fallback should succeed"
        assert use_case._consecutive_fallback_count == 1

        # 第二次：数据恢复，正常计算
        growth_series = [50.0 + i * 0.1 for i in range(24)]
        inflation_series = [2.0 + i * 0.05 for i in range(24)]
        repository.get_growth_series.return_value = growth_series
        repository.get_inflation_series.return_value = inflation_series
        repository.get_growth_series_full.return_value = []
        repository.get_inflation_series_full.return_value = []
        response = use_case.execute(request)
        assert response.success, "Normal calculation should succeed"
        # 成功计算后计数器应被重置
        assert use_case._consecutive_fallback_count == 0, "Fallback counter should reset after success"
