"""
Unit Tests for Data Adapters

测试 Infrastructure 层的数据适配器，包括：
1. Base adapter 验证和工具方法
2. TushareAdapter API 调用（Mock）
3. AKShareAdapter API 调用（Mock）
4. FailoverAdapter 主备切换、一致性校验、容差阈值
5. MultiSourceAdapter 多源聚合
"""

import pytest
from datetime import date, timedelta
from unittest.mock import Mock, patch, MagicMock

from apps.macro.infrastructure.adapters.base import (
    MacroDataPoint,
    PublicationLag,
    PUBLICATION_LAGS,
    DataSourceUnavailableError,
    DataValidationError,
    BaseMacroAdapter,
    MacroAdapterProtocol
)
from apps.macro.infrastructure.adapters.failover_adapter import (
    FailoverAdapter,
    MultiSourceAdapter
)


# ============================================================================
# Test MacroDataPoint
# ============================================================================

class TestMacroDataPoint:
    """测试 MacroDataPoint 数据类"""

    def test_auto_calculate_published_at(self):
        """测试自动计算发布时间"""
        point = MacroDataPoint(
            code="CN_PMI",
            value=50.5,
            observed_at=date(2024, 1, 1),
            source="test"
        )
        # PMI 的发布延迟是 1 天
        assert point.published_at == date(2024, 1, 2)

    def test_custom_published_at(self):
        """测试自定义发布时间"""
        custom_date = date(2024, 1, 5)
        point = MacroDataPoint(
            code="CN_PMI",
            value=50.5,
            observed_at=date(2024, 1, 1),
            published_at=custom_date,
            source="test"
        )
        assert point.published_at == custom_date

    def test_unknown_indicator_no_lag(self):
        """测试未知指标无延迟配置"""
        point = MacroDataPoint(
            code="UNKNOWN_INDICATOR",
            value=100.0,
            observed_at=date(2024, 1, 1),
            source="test"
        )
        # 未知指标不会有发布时间
        assert point.published_at is None

    def test_publication_lags_config(self):
        """测试发布延迟配置"""
        assert "CN_PMI" in PUBLICATION_LAGS
        assert PUBLICATION_LAGS["CN_PMI"].days == 1
        assert PUBLICATION_LAGS["CN_CPI"].days == 10
        assert PUBLICATION_LAGS["CN_SHIBOR"].days == 0


# ============================================================================
# Test BaseMacroAdapter
# ============================================================================

class MockAdapter(BaseMacroAdapter):
    """Mock adapter for testing BaseMacroAdapter"""

    source_name = "mock"

    def __init__(self, fetch_data=None):
        self.fetch_data = fetch_data or []

    def supports(self, indicator_code: str) -> bool:
        return indicator_code.startswith("MOCK_")

    def fetch(self, indicator_code: str, start_date: date, end_date: date):
        return self.fetch_data


class TestBaseMacroAdapter:
    """测试 BaseMacroAdapter 基类"""

    def test_validate_data_point_success(self):
        """测试数据验证成功"""
        adapter = MockAdapter()
        point = MacroDataPoint(
            code="TEST_INDICATOR",
            value=100.0,
            observed_at=date(2024, 1, 1),
            source="test"
        )
        # 不应抛出异常
        adapter._validate_data_point(point)

    def test_validate_data_point_empty_code(self):
        """测试空代码验证失败"""
        adapter = MockAdapter()
        point = MacroDataPoint(
            code="",
            value=100.0,
            observed_at=date(2024, 1, 1),
            source="test"
        )
        with pytest.raises(DataValidationError, match="指标代码不能为空"):
            adapter._validate_data_point(point)

    def test_validate_data_point_invalid_value_type(self):
        """测试非数值类型验证失败"""
        adapter = MockAdapter()
        point = MacroDataPoint(
            code="TEST_INDICATOR",
            value="not_a_number",  # type: ignore
            observed_at=date(2024, 1, 1),
            source="test"
        )
        with pytest.raises(DataValidationError, match="指标值必须是数值类型"):
            adapter._validate_data_point(point)

    def test_validate_data_point_invalid_date_type(self):
        """测试非日期类型验证失败"""
        adapter = MockAdapter()
        point = MacroDataPoint(
            code="TEST_INDICATOR",
            value=100.0,
            observed_at="2024-01-01",  # type: ignore
            source="test"
        )
        with pytest.raises(DataValidationError, match="观测日期必须是 date 类型"):
            adapter._validate_data_point(point)

    def test_sort_and_deduplicate(self):
        """测试排序和去重"""
        adapter = MockAdapter()
        points = [
            MacroDataPoint(code="TEST", value=1.0, observed_at=date(2024, 1, 3), source="test"),
            MacroDataPoint(code="TEST", value=2.0, observed_at=date(2024, 1, 1), source="test"),
            MacroDataPoint(code="TEST", value=3.0, observed_at=date(2024, 1, 2), source="test"),
            MacroDataPoint(code="TEST", value=4.0, observed_at=date(2024, 1, 1), source="test"),  # 重复
        ]

        result = adapter._sort_and_deduplicate(points)

        assert len(result) == 3
        assert result[0].observed_at == date(2024, 1, 1)
        assert result[1].observed_at == date(2024, 1, 2)
        assert result[2].observed_at == date(2024, 1, 3)
        # 验证重复日期保留的是第一个（先入为主）
        assert result[0].value == 2.0


# ============================================================================
# Test FailoverAdapter
# ============================================================================

class TestFailoverAdapter:
    """测试 FailoverAdapter 容错切换"""

    def test_init_no_adapters(self):
        """测试无适配器初始化失败"""
        with pytest.raises(ValueError, match="至少需要一个适配器"):
            FailoverAdapter(adapters=[])

    def test_primary_source_success(self):
        """测试主数据源成功"""
        primary = Mock(spec=MacroAdapterProtocol)
        primary.source_name = "primary"
        primary.supports.return_value = True
        primary.fetch.return_value = [
            MacroDataPoint(code="TEST", value=100.0, observed_at=date(2024, 1, 1), source="primary")
        ]

        adapter = FailoverAdapter(adapters=[primary], validate_consistency=False)
        result = adapter.fetch("TEST", date(2024, 1, 1), date(2024, 1, 31))

        assert len(result) == 1
        assert result[0].source == "primary"
        primary.fetch.assert_called_once()

    def test_failover_to_secondary(self):
        """测试切换到备用源"""
        primary = Mock(spec=MacroAdapterProtocol)
        primary.source_name = "primary"
        primary.supports.return_value = True
        primary.fetch.side_effect = DataSourceUnavailableError("Primary unavailable")

        secondary = Mock(spec=MacroAdapterProtocol)
        secondary.source_name = "secondary"
        secondary.supports.return_value = True
        secondary.fetch.return_value = [
            MacroDataPoint(code="TEST", value=100.0, observed_at=date(2024, 1, 1), source="secondary")
        ]

        adapter = FailoverAdapter(adapters=[primary, secondary], validate_consistency=False)
        result = adapter.fetch("TEST", date(2024, 1, 1), date(2024, 1, 31))

        assert len(result) == 1
        assert result[0].source == "secondary"
        secondary.fetch.assert_called_once()

    def test_all_sources_fail(self):
        """测试所有数据源失败"""
        primary = Mock(spec=MacroAdapterProtocol)
        primary.source_name = "primary"
        primary.supports.return_value = True
        primary.fetch.side_effect = DataSourceUnavailableError("Primary error")

        secondary = Mock(spec=MacroAdapterProtocol)
        secondary.source_name = "secondary"
        secondary.supports.return_value = True
        secondary.fetch.side_effect = DataSourceUnavailableError("Secondary error")

        adapter = FailoverAdapter(adapters=[primary, secondary])

        with pytest.raises(DataSourceUnavailableError, match="所有数据源均无法获取"):
            adapter.fetch("TEST", date(2024, 1, 1), date(2024, 1, 31))

    def test_validate_consistency_pass(self):
        """测试一致性校验通过"""
        primary = Mock(spec=MacroAdapterProtocol)
        primary.source_name = "primary"
        primary.supports.return_value = True
        primary.fetch.return_value = [
            MacroDataPoint(code="TEST", value=100.0, observed_at=date(2024, 1, 1), source="primary")
        ]

        secondary = Mock(spec=MacroAdapterProtocol)
        secondary.source_name = "secondary"
        secondary.supports.return_value = True
        secondary.fetch.return_value = [
            MacroDataPoint(code="TEST", value=100.5, observed_at=date(2024, 1, 1), source="secondary")
        ]

        adapter = FailoverAdapter(
            adapters=[primary, secondary],
            validate_consistency=True,
            tolerance=0.01  # 1% 容差
        )
        result = adapter.fetch("TEST", date(2024, 1, 1), date(2024, 1, 31))

        # 差异是 0.5%，在 1% 容差内，应返回主源数据
        assert len(result) == 1
        assert result[0].source == "primary"

    def test_validate_consistency_fail(self):
        """测试一致性校验失败"""
        primary = Mock(spec=MacroAdapterProtocol)
        primary.source_name = "primary"
        primary.supports.return_value = True
        primary.fetch.return_value = [
            MacroDataPoint(code="TEST", value=100.0, observed_at=date(2024, 1, 1), source="primary")
        ]

        secondary = Mock(spec=MacroAdapterProtocol)
        secondary.source_name = "secondary"
        secondary.supports.return_value = True
        secondary.fetch.return_value = [
            MacroDataPoint(code="TEST", value=105.0, observed_at=date(2024, 1, 1), source="secondary")
        ]

        adapter = FailoverAdapter(
            adapters=[primary, secondary],
            validate_consistency=True,
            tolerance=0.01  # 1% 容差
        )
        result = adapter.fetch("TEST", date(2024, 1, 1), date(2024, 1, 31))

        # 差异是 5%，超过 1% 容差，但仍应返回主源数据（只记录警告）
        assert len(result) == 1
        assert result[0].source == "primary"

    def test_supports_any_adapter(self):
        """测试 supports 方法（任一适配器支持即可）"""
        primary = Mock(spec=MacroAdapterProtocol)
        primary.supports.return_value = False

        secondary = Mock(spec=MacroAdapterProtocol)
        secondary.supports.return_value = True

        adapter = FailoverAdapter(adapters=[primary, secondary])

        assert adapter.supports("TEST") is True

    def test_skip_unsupported_adapter(self):
        """测试跳过不支持的适配器"""
        primary = Mock(spec=MacroAdapterProtocol)
        primary.source_name = "primary"
        primary.supports.return_value = False

        secondary = Mock(spec=MacroAdapterProtocol)
        secondary.source_name = "secondary"
        secondary.supports.return_value = True
        secondary.fetch.return_value = [
            MacroDataPoint(code="TEST", value=100.0, observed_at=date(2024, 1, 1), source="secondary")
        ]

        adapter = FailoverAdapter(adapters=[primary, secondary])
        result = adapter.fetch("TEST", date(2024, 1, 1), date(2024, 1, 31))

        # 主源不支持，应直接使用备用源
        assert len(result) == 1
        primary.fetch.assert_not_called()
        secondary.fetch.assert_called_once()

    def test_empty_data_from_primary(self):
        """测试主源返回空数据"""
        primary = Mock(spec=MacroAdapterProtocol)
        primary.source_name = "primary"
        primary.supports.return_value = True
        primary.fetch.return_value = []  # 空数据

        secondary = Mock(spec=MacroAdapterProtocol)
        secondary.source_name = "secondary"
        secondary.supports.return_value = True
        secondary.fetch.return_value = [
            MacroDataPoint(code="TEST", value=100.0, observed_at=date(2024, 1, 1), source="secondary")
        ]

        adapter = FailoverAdapter(adapters=[primary, secondary])
        result = adapter.fetch("TEST", date(2024, 1, 1), date(2024, 1, 31))

        # 主源返回空数据，应使用备用源
        assert len(result) == 1
        assert result[0].source == "secondary"


# ============================================================================
# Test MultiSourceAdapter
# ============================================================================

class TestMultiSourceAdapter:
    """测试 MultiSourceAdapter 多源聚合"""

    def test_init_no_adapters(self):
        """测试无适配器初始化失败"""
        with pytest.raises(ValueError, match="至少需要一个适配器"):
            MultiSourceAdapter(adapters=[])

    def test_merge_multiple_sources(self):
        """测试合并多个数据源"""
        source1 = Mock(spec=MacroAdapterProtocol)
        source1.source_name = "source1"
        source1.supports.return_value = True
        source1.fetch.return_value = [
            MacroDataPoint(code="TEST", value=100.0, observed_at=date(2024, 1, 1), published_at=date(2024, 1, 2), source="source1"),
            MacroDataPoint(code="TEST", value=101.0, observed_at=date(2024, 1, 2), published_at=date(2024, 1, 3), source="source1"),
        ]

        source2 = Mock(spec=MacroAdapterProtocol)
        source2.source_name = "source2"
        source2.supports.return_value = True
        source2.fetch.return_value = [
            MacroDataPoint(code="TEST", value=102.0, observed_at=date(2024, 1, 2), published_at=date(2024, 1, 4), source="source2"),
            MacroDataPoint(code="TEST", value=103.0, observed_at=date(2024, 1, 3), published_at=date(2024, 1, 5), source="source2"),
        ]

        adapter = MultiSourceAdapter(adapters=[source1, source2])
        result = adapter.fetch("TEST", date(2024, 1, 1), date(2024, 1, 31))

        # 应该返回 3 条数据（1/1 来自 source1，1/2 来自 source2，1/3 来自 source2）
        assert len(result) == 3
        # 验证按日期排序
        assert result[0].observed_at == date(2024, 1, 1)
        assert result[1].observed_at == date(2024, 1, 2)
        assert result[2].observed_at == date(2024, 1, 3)

    def test_deduplicate_keep_newest(self):
        """测试去重并保留最新的"""
        source1 = Mock(spec=MacroAdapterProtocol)
        source1.source_name = "source1"
        source1.supports.return_value = True
        source1.fetch.return_value = [
            MacroDataPoint(
                code="TEST",
                value=100.0,
                observed_at=date(2024, 1, 1),
                published_at=date(2024, 1, 2),  # 较早发布
                source="source1"
            ),
        ]

        source2 = Mock(spec=MacroAdapterProtocol)
        source2.source_name = "source2"
        source2.supports.return_value = True
        source2.fetch.return_value = [
            MacroDataPoint(
                code="TEST",
                value=102.0,
                observed_at=date(2024, 1, 1),
                published_at=date(2024, 1, 5),  # 较晚发布
                source="source2"
            ),
        ]

        adapter = MultiSourceAdapter(adapters=[source1, source2])
        result = adapter.fetch("TEST", date(2024, 1, 1), date(2024, 1, 31))

        # 应该只返回一条，且是发布时间较新的
        assert len(result) == 1
        assert result[0].value == 102.0
        assert result[0].published_at == date(2024, 1, 5)

    def test_one_source_fails(self):
        """测试一个数据源失败"""
        source1 = Mock(spec=MacroAdapterProtocol)
        source1.source_name = "source1"
        source1.supports.return_value = True
        source1.fetch.side_effect = Exception("Source1 failed")

        source2 = Mock(spec=MacroAdapterProtocol)
        source2.source_name = "source2"
        source2.supports.return_value = True
        source2.fetch.return_value = [
            MacroDataPoint(code="TEST", value=100.0, observed_at=date(2024, 1, 1), source="source2"),
        ]

        adapter = MultiSourceAdapter(adapters=[source1, source2])
        result = adapter.fetch("TEST", date(2024, 1, 1), date(2024, 1, 31))

        # 应该返回成功的数据
        assert len(result) == 1
        assert result[0].source == "source2"

    def test_all_sources_fail(self):
        """测试所有数据源失败"""
        source1 = Mock(spec=MacroAdapterProtocol)
        source1.source_name = "source1"
        source1.supports.return_value = True
        source1.fetch.side_effect = Exception("Source1 failed")

        source2 = Mock(spec=MacroAdapterProtocol)
        source2.source_name = "source2"
        source2.supports.return_value = True
        source2.fetch.side_effect = Exception("Source2 failed")

        adapter = MultiSourceAdapter(adapters=[source1, source2])

        with pytest.raises(DataSourceUnavailableError, match="所有数据源均无法获取"):
            adapter.fetch("TEST", date(2024, 1, 1), date(2024, 1, 31))

    def test_supports_any_adapter(self):
        """测试 supports 方法（任一适配器支持即可）"""
        source1 = Mock(spec=MacroAdapterProtocol)
        source1.supports.return_value = False

        source2 = Mock(spec=MacroAdapterProtocol)
        source2.supports.return_value = True

        adapter = MultiSourceAdapter(adapters=[source1, source2])

        assert adapter.supports("TEST") is True

    def test_skip_unsupported_adapters(self):
        """测试跳过不支持的适配器"""
        source1 = Mock(spec=MacroAdapterProtocol)
        source1.source_name = "source1"
        source1.supports.return_value = False

        source2 = Mock(spec=MacroAdapterProtocol)
        source2.source_name = "source2"
        source2.supports.return_value = True
        source2.fetch.return_value = [
            MacroDataPoint(code="TEST", value=100.0, observed_at=date(2024, 1, 1), source="source2"),
        ]

        adapter = MultiSourceAdapter(adapters=[source1, source2])
        result = adapter.fetch("TEST", date(2024, 1, 1), date(2024, 1, 31))

        # 只应调用支持的适配器
        source1.fetch.assert_not_called()
        source2.fetch.assert_called_once()
        assert len(result) == 1


# ============================================================================
# Test Error Handling
# ============================================================================

class TestAdapterErrorHandling:
    """测试适配器错误处理"""

    def test_primary_exception_handling(self):
        """测试主源异常处理"""
        primary = Mock(spec=MacroAdapterProtocol)
        primary.source_name = "primary"
        primary.supports.return_value = True
        primary.fetch.side_effect = RuntimeError("Unexpected error")

        secondary = Mock(spec=MacroAdapterProtocol)
        secondary.source_name = "secondary"
        secondary.supports.return_value = True
        secondary.fetch.return_value = [
            MacroDataPoint(code="TEST", value=100.0, observed_at=date(2024, 1, 1), source="secondary")
        ]

        adapter = FailoverAdapter(adapters=[primary, secondary])
        result = adapter.fetch("TEST", date(2024, 1, 1), date(2024, 1, 31))

        # 应该切换到备用源
        assert len(result) == 1
        assert result[0].source == "secondary"

    def test_zero_value_in_consistency_check(self):
        """测试一致性校验中的零值处理"""
        primary = Mock(spec=MacroAdapterProtocol)
        primary.source_name = "primary"
        primary.supports.return_value = True
        primary.fetch.return_value = [
            MacroDataPoint(code="TEST", value=0.0, observed_at=date(2024, 1, 1), source="primary")
        ]

        secondary = Mock(spec=MacroAdapterProtocol)
        secondary.source_name = "secondary"
        secondary.supports.return_value = True
        secondary.fetch.return_value = [
            MacroDataPoint(code="TEST", value=1.0, observed_at=date(2024, 1, 1), source="secondary")
        ]

        adapter = FailoverAdapter(
            adapters=[primary, secondary],
            validate_consistency=True,
            tolerance=0.01
        )
        result = adapter.fetch("TEST", date(2024, 1, 1), date(2024, 1, 31))

        # 主值为零时，应跳过该点的校验
        assert len(result) == 1
        assert result[0].source == "primary"

    def test_no_common_data_points(self):
        """测试无共同数据点时的一致性校验"""
        primary = Mock(spec=MacroAdapterProtocol)
        primary.source_name = "primary"
        primary.supports.return_value = True
        primary.fetch.return_value = [
            MacroDataPoint(code="TEST", value=100.0, observed_at=date(2024, 1, 1), source="primary")
        ]

        secondary = Mock(spec=MacroAdapterProtocol)
        secondary.source_name = "secondary"
        secondary.supports.return_value = True
        secondary.fetch.return_value = [
            MacroDataPoint(code="TEST", value=101.0, observed_at=date(2024, 1, 2), source="secondary")
        ]

        adapter = FailoverAdapter(
            adapters=[primary, secondary],
            validate_consistency=True,
            tolerance=0.01
        )
        result = adapter.fetch("TEST", date(2024, 1, 1), date(2024, 1, 31))

        # 无共同数据点，应通过校验
        assert len(result) == 1
        assert result[0].source == "primary"
