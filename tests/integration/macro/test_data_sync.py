"""
Integration Tests for Macro Data Sync Workflow

测试宏观数据同步的端到端流程，包括：
1. 完整同步流程
2. Failover 机制
3. Point-in-Time (PIT) 数据处理
"""

import pytest
from datetime import date, timedelta
from unittest.mock import Mock, patch, MagicMock
from django.test import TestCase

from apps.macro.domain.entities import MacroIndicator, PeriodType
from apps.macro.infrastructure.repositories import DjangoMacroRepository
from apps.macro.infrastructure.adapters.base import MacroDataPoint, DataSourceUnavailableError
from apps.macro.infrastructure.adapters.failover_adapter import FailoverAdapter
from apps.macro.application.use_cases import (
    SyncMacroDataUseCase,
    SyncMacroDataRequest,
    MacroDataPoint,
)


@pytest.mark.django_db
class TestMacroDataSyncWorkflow:
    """测试宏观数据同步完整工作流"""

    def test_complete_sync_workflow(self):
        """测试完整数据同步流程

        流程：
        1. 触发同步任务
        2. 验证数据已写入数据库
        3. 验证单位转换正确
        4. 验证 PIT 数据处理
        """
        # 1. 准备 Mock 适配器
        mock_adapter = Mock()
        mock_adapter.source_name = "test_adapter"
        mock_adapter.supports = Mock(return_value=True)

        # 模拟返回的宏观数据点
        test_data_points = [
            MacroDataPoint(
                code="CN_PMI",
                value=50.5,
                observed_at=date(2024, 1, 1),
                published_at=date(2024, 1, 2),
                source="test",
                unit="指数",
                original_unit="指数"
            ),
            MacroDataPoint(
                code="CN_CPI",
                value=2.1,
                observed_at=date(2024, 1, 1),
                published_at=date(2024, 1, 10),
                source="test",
                unit="%",
                original_unit="%"
            ),
        ]
        mock_adapter.fetch = Mock(return_value=test_data_points)

        # 2. 创建 Use Case
        repository = DjangoMacroRepository()
        use_case = SyncMacroDataUseCase(
            repository=repository,
            adapters={"test": mock_adapter}
        )

        # 3. 执行同步
        request = SyncMacroDataRequest(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            indicators=["CN_PMI", "CN_CPI"]
        )
        response = use_case.execute(request)

        # 4. 验证结果
        assert response.success, f"同步失败: {response.errors}"
        assert response.synced_count == 2, f"应同步 2 条数据，实际: {response.synced_count}"

        # 5. 验证数据已写入数据库
        pmi_indicator = repository.get_by_code_and_date(
            code="CN_PMI",
            observed_at=date(2024, 1, 1)
        )
        assert pmi_indicator is not None, "PMI 数据未保存"
        assert pmi_indicator.value == 50.5, "PMI 值不正确"
        assert pmi_indicator.unit == "指数", "PMI 单位不正确"
        assert pmi_indicator.source == "test", "数据源不正确"

        cpi_indicator = repository.get_by_code_and_date(
            code="CN_CPI",
            observed_at=date(2024, 1, 1)
        )
        assert cpi_indicator is not None, "CPI 数据未保存"
        assert cpi_indicator.value == 2.1, "CPI 值不正确"
        assert cpi_indicator.unit == "%", "CPI 单位不正确"

    def test_sync_with_unit_conversion(self):
        """测试单位转换功能

        验证货币类数据（如新增信贷）会自动转换为"元"单位存储
        """
        # Mock 适配器返回新增信贷数据（原始单位为万亿元）
        mock_adapter = Mock()
        mock_adapter.source_name = "test_adapter"
        mock_adapter.supports = Mock(return_value=True)

        test_data_points = [
            MacroDataPoint(
                code="CN_NEW_CREDIT",
                value=3.5,  # 3.5万亿元
                observed_at=date(2024, 1, 1),
                published_at=date(2024, 1, 15),
                source="test",
                unit="万亿元",
                original_unit="万亿元"
            ),
        ]
        mock_adapter.fetch = Mock(return_value=test_data_points)

        repository = DjangoMacroRepository()
        use_case = SyncMacroDataUseCase(
            repository=repository,
            adapters={"test": mock_adapter}
        )

        request = SyncMacroDataRequest(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            indicators=["CN_NEW_CREDIT"]
        )
        response = use_case.execute(request)

        assert response.success

        # 验证数据已转换为"元"单位
        credit_indicator = repository.get_by_code_and_date(
            code="CN_NEW_CREDIT",
            observed_at=date(2024, 1, 1)
        )
        assert credit_indicator is not None
        # 万亿元转换为元需要乘以 1万亿
        expected_value = 3.5 * 1000000000000
        assert credit_indicator.value == expected_value, \
            f"新增信贷值应转换为元: 期望 {expected_value}, 实际 {credit_indicator.value}"
        assert credit_indicator.unit == "元", \
            f"新增信贷单位应为'元': 实际 '{credit_indicator.unit}'"
        assert credit_indicator.original_unit == "万亿元", \
            f"原始单位应保留: 实际 '{credit_indicator.original_unit}'"

    def test_sync_deduplication(self):
        """测试去重处理

        验证重复数据不会被重复保存
        """
        mock_adapter = Mock()
        mock_adapter.source_name = "test_adapter"
        mock_adapter.supports = Mock(return_value=True)

        test_data_points = [
            MacroDataPoint(
                code="CN_PMI",
                value=50.5,
                observed_at=date(2024, 1, 1),
                published_at=date(2024, 1, 2),
                source="test",
                unit="指数",
                original_unit="指数"
            ),
        ]
        mock_adapter.fetch = Mock(return_value=test_data_points)

        repository = DjangoMacroRepository()
        use_case = SyncMacroDataUseCase(
            repository=repository,
            adapters={"test": mock_adapter}
        )

        request = SyncMacroDataRequest(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            indicators=["CN_PMI"]
        )

        # 第一次同步
        response1 = use_case.execute(request)
        assert response1.success
        assert response1.synced_count == 1
        assert response1.skipped_count == 0

        # 第二次同步（相同数据）
        response2 = use_case.execute(request)
        assert response2.success
        assert response2.synced_count == 0, "重复数据不应被保存"
        assert response2.skipped_count == 1, "应有 1 条数据被跳过"

        # 验证目标日期不会产生重复记录
        same_day_count = repository._model.objects.filter(
            code="CN_PMI",
            reporting_period=date(2024, 1, 1)
        ).count()
        assert same_day_count == 1, f"目标日期应仅有 1 条记录，实际: {same_day_count}"


@pytest.mark.django_db
class TestFailoverMechanism:
    """测试 Failover 机制"""

    def test_failover_to_secondary_source(self):
        """测试主数据源失败时自动切换到备用源"""
        # 主适配器（会失败）
        primary_adapter = Mock()
        primary_adapter.source_name = "primary"
        primary_adapter.supports = Mock(return_value=True)
        primary_adapter.fetch = Mock(side_effect=DataSourceUnavailableError("主源不可用"))

        # 备用适配器
        secondary_adapter = Mock()
        secondary_adapter.source_name = "secondary"
        secondary_adapter.supports = Mock(return_value=True)

        test_data_points = [
            MacroDataPoint(
                code="CN_PMI",
                value=50.5,
                observed_at=date(2024, 1, 1),
                published_at=date(2024, 1, 2),
                source="secondary",
                unit="指数",
                original_unit="指数"
            ),
        ]
        secondary_adapter.fetch = Mock(return_value=test_data_points)

        # 创建 Failover 适配器
        failover_adapter = FailoverAdapter(
            adapters=[primary_adapter, secondary_adapter],
            validate_consistency=False
        )

        repository = DjangoMacroRepository()
        use_case = SyncMacroDataUseCase(
            repository=repository,
            adapters={"failover": failover_adapter}
        )

        request = SyncMacroDataRequest(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            indicators=["CN_PMI"]
        )
        response = use_case.execute(request)

        # 验证成功从备用源获取数据
        assert response.success
        assert response.synced_count == 1

        # 验证调用了主适配器（失败）
        primary_adapter.fetch.assert_called_once()

        # 验证调用了备用适配器（成功）
        secondary_adapter.fetch.assert_called_once()

    def test_data_consistency_validation(self):
        """测试数据一致性校验

        当主备数据源差异超过容差时，应记录警告
        """
        # 主适配器
        primary_adapter = Mock()
        primary_adapter.source_name = "primary"
        primary_adapter.supports = Mock(return_value=True)

        primary_data = [
            MacroDataPoint(
                code="CN_PMI",
                value=50.0,
                observed_at=date(2024, 1, 1),
                published_at=date(2024, 1, 2),
                source="primary",
                unit="指数",
                original_unit="指数"
            ),
        ]
        primary_adapter.fetch = Mock(return_value=primary_data)

        # 备用适配器（返回差异较大的数据，超过 1% 容差）
        secondary_adapter = Mock()
        secondary_adapter.source_name = "secondary"
        secondary_adapter.supports = Mock(return_value=True)

        secondary_data = [
            MacroDataPoint(
                code="CN_PMI",
                value=52.0,  # 差异 4%，超过 1% 容差
                observed_at=date(2024, 1, 1),
                published_at=date(2024, 1, 2),
                source="secondary",
                unit="指数",
                original_unit="指数"
            ),
        ]
        secondary_adapter.fetch = Mock(return_value=secondary_data)

        # 创建 Failover 适配器（启用一致性校验）
        failover_adapter = FailoverAdapter(
            adapters=[primary_adapter, secondary_adapter],
            validate_consistency=True,
            tolerance=0.01  # 1% 容差
        )

        repository = DjangoMacroRepository()
        use_case = SyncMacroDataUseCase(
            repository=repository,
            adapters={"failover": failover_adapter}
        )

        request = SyncMacroDataRequest(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            indicators=["CN_PMI"]
        )
        response = use_case.execute(request)

        # 验证使用主数据源的数据
        assert response.success

        pmi_indicator = repository.get_by_code_and_date(
            code="CN_PMI",
            observed_at=date(2024, 1, 1)
        )
        assert pmi_indicator is not None
        assert pmi_indicator.value == 50.0, "应使用主数据源的值"

    def test_all_sources_unavailable(self):
        """测试所有数据源都不可用的场景"""
        # 主适配器
        primary_adapter = Mock()
        primary_adapter.source_name = "primary"
        primary_adapter.supports = Mock(return_value=True)
        primary_adapter.fetch = Mock(side_effect=DataSourceUnavailableError("主源失败"))

        # 备用适配器
        secondary_adapter = Mock()
        secondary_adapter.source_name = "secondary"
        secondary_adapter.supports = Mock(return_value=True)
        secondary_adapter.fetch = Mock(side_effect=DataSourceUnavailableError("备用源失败"))

        failover_adapter = FailoverAdapter(
            adapters=[primary_adapter, secondary_adapter]
        )

        repository = DjangoMacroRepository()
        use_case = SyncMacroDataUseCase(
            repository=repository,
            adapters={"failover": failover_adapter}
        )

        request = SyncMacroDataRequest(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            indicators=["CN_PMI"]
        )
        response = use_case.execute(request)

        # 验证同步失败
        assert not response.success
        assert len(response.errors) > 0
        assert "CN_PMI" in response.errors[0]


@pytest.mark.django_db
class TestPitDataHandling:
    """测试 Point-in-Time 数据处理"""

    def test_pit_data_availability(self):
        """测试 PIT 数据可用性检查

        验证在指定日期只能看到该日期前已发布的数据
        """
        repository = DjangoMacroRepository()
        test_code = "CN_PMI_PIT_TEST"

        # 保存数据（带发布延迟）
        # 1 月份数据在 2 月发布
        repository.save_indicator(
            MacroIndicator(
                code=test_code,
                value=50.0,
                reporting_period=date(2024, 1, 1),
                published_at=date(2024, 2, 15),  # 2 月 15 日发布
                source="test",
                unit="指数",
                original_unit="指数",
                period_type=PeriodType.MONTH
            )
        )

        # 2 月份数据在 3 月发布
        repository.save_indicator(
            MacroIndicator(
                code=test_code,
                value=51.0,
                reporting_period=date(2024, 2, 1),
                published_at=date(2024, 3, 15),  # 3 月 15 日发布
                source="test",
                unit="指数",
                original_unit="指数",
                period_type=PeriodType.MONTH
            )
        )

        # 验证：在 2024-02-01 时，1 月份数据不可见（尚未发布）
        latest_date = repository.get_latest_observation_date(
            code=test_code,
            as_of_date=date(2024, 2, 1)
        )
        assert latest_date is None, "2024-02-01 时不应有可见数据"

        # 验证：在 2024-02-20 时，1 月份数据可见
        latest_date = repository.get_latest_observation_date(
            code=test_code,
            as_of_date=date(2024, 2, 20)
        )
        assert latest_date == date(2024, 1, 1), "2024-02-20 时应可见 1 月数据"

        # 验证：在 2024-03-20 时，2 月份数据可见
        latest_date = repository.get_latest_observation_date(
            code=test_code,
            as_of_date=date(2024, 3, 20)
        )
        assert latest_date == date(2024, 2, 1), "2024-03-20 时应可见 2 月数据"

    def test_pit_data_with_revisions(self):
        """测试 PIT 数据的修订版本处理

        验证同一数据点的多次修订能正确保存和查询
        """
        repository = DjangoMacroRepository()

        # 第一次发布（修订版 1）
        repository.save_indicator(
            MacroIndicator(
                code="CN_GDP",
                value=5.2,
                reporting_period=date(2024, 1, 1),
                published_at=date(2024, 1, 20),
                source="test",
                unit="%",
                original_unit="%",
                period_type=PeriodType.QUARTER
            ),
            revision_number=1
        )

        # 第二次发布（修订版 2 - 初步核实）
        repository.save_indicator(
            MacroIndicator(
                code="CN_GDP",
                value=5.3,  # 上修 0.1
                reporting_period=date(2024, 1, 1),
                published_at=date(2024, 2, 20),
                source="test",
                unit="%",
                original_unit="%",
                period_type=PeriodType.QUARTER
            ),
            revision_number=2
        )

        # 第三次发布（修订版 3 - 最终核实）
        repository.save_indicator(
            MacroIndicator(
                code="CN_GDP",
                value=5.25,  # 微调
                reporting_period=date(2024, 1, 1),
                published_at=date(2024, 3, 20),
                source="test",
                unit="%",
                original_unit="%",
                period_type=PeriodType.QUARTER
            ),
            revision_number=3
        )

        # 验证：获取最新修订版本
        latest = repository.get_by_code_and_date(
            code="CN_GDP",
            observed_at=date(2024, 1, 1),
            revision_number=None  # None 表示获取最新版本
        )
        assert latest is not None
        assert latest.value == 5.25, "应获取最新修订版 3 的值"

        # 验证：获取特定修订版本
        rev1 = repository.get_by_code_and_date(
            code="CN_GDP",
            observed_at=date(2024, 1, 1),
            revision_number=1
        )
        assert rev1 is not None
        assert rev1.value == 5.2, "修订版 1 的值应为 5.2"

        rev2 = repository.get_by_code_and_date(
            code="CN_GDP",
            observed_at=date(2024, 1, 1),
            revision_number=2
        )
        assert rev2 is not None
        assert rev2.value == 5.3, "修订版 2 的值应为 5.3"

    def test_pit_mode_in_series_query(self):
        """测试 PIT 模式下的时序查询"""
        repository = DjangoMacroRepository()

        # 准备测试数据：三个观测期，每期有修订
        # 1 月数据
        repository.save_indicator(
            MacroIndicator(
                code="CN_CPI",
                value=2.0,
                reporting_period=date(2024, 1, 1),
                published_at=date(2024, 2, 15),
                source="test",
                unit="%",
                original_unit="%",
                period_type=PeriodType.MONTH
            ),
            revision_number=1
        )
        repository.save_indicator(
            MacroIndicator(
                code="CN_CPI",
                value=2.1,  # 修订
                reporting_period=date(2024, 1, 1),
                published_at=date(2024, 3, 15),
                source="test",
                unit="%",
                original_unit="%",
                period_type=PeriodType.MONTH
            ),
            revision_number=2
        )

        # 2 月数据
        repository.save_indicator(
            MacroIndicator(
                code="CN_CPI",
                value=2.3,
                reporting_period=date(2024, 2, 1),
                published_at=date(2024, 3, 15),
                source="test",
                unit="%",
                original_unit="%",
                period_type=PeriodType.MONTH
            ),
            revision_number=1
        )

        # 验证：PIT 模式查询
        series = repository.get_series(
            code="CN_CPI",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 2, 28),
            use_pit=True  # 启用 PIT 模式
        )

        # 应返回每个观测期的最新修订版本
        assert len(series) == 2, f"应返回 2 个观测期，实际: {len(series)}"

        # 验证 1 月数据使用修订版 2
        january = next((s for s in series if s.reporting_period == date(2024, 1, 1)), None)
        assert january is not None
        assert january.value == 2.1, "1 月应使用修订版 2 的值"

        # 验证 2 月数据
        february = next((s for s in series if s.reporting_period == date(2024, 2, 1)), None)
        assert february is not None
        assert february.value == 2.3
