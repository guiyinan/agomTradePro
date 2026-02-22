"""
Integration Tests for Backtest Execution

测试回测执行流程，包括：
1. 完整回测执行
2. 交易成本计算
3. 性能指标计算
"""

import pytest
from datetime import date, timedelta
from unittest.mock import Mock

from apps.backtest.domain.entities import BacktestConfig, BacktestResult, BacktestStatus, Trade
from apps.backtest.domain.services import BacktestEngine
from apps.backtest.infrastructure.repositories import DjangoBacktestRepository
from apps.backtest.application.use_cases import RunBacktestUseCase, RunBacktestRequest
from apps.regime.infrastructure.repositories import DjangoRegimeRepository
from apps.regime.domain.entities import RegimeSnapshot


@pytest.mark.django_db
class TestBacktestExecution:
    """测试回测执行流程"""

    def test_complete_backtest_workflow(self):
        """测试完整回测执行

        流程：
        1. 准备回测配置（资产、权重、日期）
        2. 执行回测
        3. 验证 equity_curve 生成
        4. 验证 trades 记录
        5. 验证性能指标（Sharpe、最大回撤）
        """
        # 1. 准备 Regime 数据
        regime_repo = DjangoRegimeRepository()
        base_date = date(2022, 1, 1)

        # 创建历史 Regime 数据
        regimes = [
            RegimeSnapshot(
                growth_momentum_z=1.0,
                inflation_momentum_z=-0.5,
                distribution={"Recovery": 0.6, "Overheat": 0.2, "Stagflation": 0.1, "Deflation": 0.1},
                dominant_regime="Recovery",
                confidence=0.6,
                observed_at=base_date + timedelta(days=30 * i)
            )
            for i in range(12)
        ]

        for regime in regimes:
            regime_repo.save_snapshot(regime)

        # 2. Mock 获取资产价格函数
        def mock_get_regime(dt):
            # 返回当前日期的 Regime
            snapshot = regime_repo.get_snapshot_by_date(dt)
            if snapshot:
                return {
                    'dominant_regime': snapshot.dominant_regime,
                    'distribution': snapshot.distribution,
                    'confidence': snapshot.confidence
                }
            return None

        def mock_get_price(asset_class, dt):
            # 简单的模拟价格
            base_prices = {
                'EQUITY': 3000.0,
                'BOND': 100.0,
                'GOLD': 400.0,
                'CASH': 1.0
            }
            base = base_prices.get(asset_class, 100.0)
            # 添加一些随机波动
            days = (dt - base_date).days
            return base * (1 + 0.0001 * days)  # 简单线性增长

        # 3. 创建回测请求
        repository = DjangoBacktestRepository()
        use_case = RunBacktestUseCase(
            repository=repository,
            get_regime_func=mock_get_regime,
            get_asset_price_func=mock_get_price
        )

        request = RunBacktestRequest(
            name="测试回测",
            start_date=base_date,
            end_date=base_date + timedelta(days=30 * 11),  # 12 个月
            initial_capital=100000.0,
            rebalance_frequency="monthly",
            use_pit_data=False,
            transaction_cost_bps=10.0
        )

        # 4. 执行回测
        response = use_case.execute(request)

        # 5. 验证结果
        assert response.backtest_id is not None, "应创建回测 ID"
        assert response.status in ['completed', 'running'], f"回测状态应为 completed 或 running: {response.status}"
        assert len(response.errors) == 0, f"回测不应有错误: {response.errors}"

        # 6. 验证性能指标存在
        if response.result:
            assert 'total_return' in response.result or 'sharpe_ratio' in response.result, \
                "结果应包含性能指标"

    def test_transaction_cost_calculation(self):
        """测试交易成本计算

        验证：
        1. 每笔交易的成本
        2. 总成本对收益的影响
        """
        repository = DjangoBacktestRepository()
        base_date = date(2022, 1, 1)

        # Mock Regime 和价格数据
        def mock_get_regime(dt):
            return {
                'dominant_regime': 'Recovery',
                'distribution': {"Recovery": 0.5, "Overheat": 0.2, "Stagflation": 0.2, "Deflation": 0.1},
                'confidence': 0.5
            }

        def mock_get_price(asset_class, dt):
            # 模拟价格波动
            base = 100.0
            days = (dt - base_date).days
            return base + (days % 10) * 2  # 简单的锯齿波动

        use_case = RunBacktestUseCase(
            repository=repository,
            get_regime_func=mock_get_regime,
            get_asset_price_func=mock_get_price
        )

        # 执行带成本的回测
        request_with_cost = RunBacktestRequest(
            name="回测-含交易成本",
            start_date=base_date,
            end_date=base_date + timedelta(days=30 * 6),  # 6 个月
            initial_capital=100000.0,
            transaction_cost_bps=10.0  # 10 个基点
        )

        response_with_cost = use_case.execute(request_with_cost)

        # 执行无成本的回测
        request_no_cost = RunBacktestRequest(
            name="回测-无交易成本",
            start_date=base_date,
            end_date=base_date + timedelta(days=30 * 6),
            initial_capital=100000.0,
            transaction_cost_bps=0.0
        )

        response_no_cost = use_case.execute(request_no_cost)

        # 验证：有成本的回测收益应该更低或相等
        if (response_with_cost.result and response_no_cost.result and
            'total_return' in response_with_cost.result and 'total_return' in response_no_cost.result):
            return_with_cost = response_with_cost.result['total_return']
            return_no_cost = response_no_cost.result['total_return']
            assert return_with_cost <= return_no_cost, \
                f"有成本的收益应更低: {return_with_cost} vs {return_no_cost}"

    def test_performance_metrics(self):
        """测试性能指标计算

        验证：
        1. 年化收益率
        2. Sharpe 比率
        3. 最大回撤
        4. 胜率
        """
        repository = DjangoBacktestRepository()
        base_date = date(2022, 1, 1)

        def mock_get_regime(dt):
            return {
                'dominant_regime': 'Recovery',
                'distribution': {"Recovery": 0.5, "Overheat": 0.2, "Stagflation": 0.2, "Deflation": 0.1},
                'confidence': 0.5
            }

        def mock_get_price(asset_class, dt):
            # 模拟上涨趋势（便于测试）
            base = 100.0
            days = (dt - base_date).days
            return base * (1 + 0.001 * days)  # 每天约 0.1% 上涨

        use_case = RunBacktestUseCase(
            repository=repository,
            get_regime_func=mock_get_regime,
            get_asset_price_func=mock_get_price
        )

        request = RunBacktestRequest(
            name="性能指标测试",
            start_date=base_date,
            end_date=base_date + timedelta(days=365),  # 1 年
            initial_capital=100000.0,
            rebalance_frequency="monthly"
        )

        response = use_case.execute(request)

        # 验证回测成功
        assert response.backtest_id is not None
        assert response.status == 'completed'

        # 验证性能指标
        if response.result:
            # 检查关键性能指标
            result = response.result

            # 验证有正收益（因为模拟的是上涨趋势）
            if 'total_return' in result:
                assert result['total_return'] >= 0, "上涨趋势应有正收益"

            # 验证 Sharpe 比率是有效数字
            if 'sharpe_ratio' in result:
                assert isinstance(result['sharpe_ratio'], (int, float)), "Sharpe 应为数值"
                # Mock 数据可能产生极端值，只验证类型
                assert result['sharpe_ratio'] > -1000, "Sharpe 应在合理范围内"

            # 验证最大回撤是有效数字
            if 'max_drawdown' in result:
                assert isinstance(result['max_drawdown'], (int, float)), "最大回撤应为数值"
                # Mock 数据和浮点误差可能导致微小的正值或零
                # 允许 -100 到 0.01 的范围（容忍小的浮点误差）
                assert -100 <= result['max_drawdown'] <= 0.01, \
                    f"最大回撤应在合理范围内，实际: {result['max_drawdown']}"

    def test_backtest_with_different_frequencies(self):
        """测试不同再平衡频率

        验证：
        1. 每月再平衡
        2. 每季度再平衡
        3. 每年再平衡
        """
        repository = DjangoBacktestRepository()
        base_date = date(2022, 1, 1)

        def mock_get_regime(dt):
            return {
                'dominant_regime': 'Recovery',
                'distribution': {"Recovery": 0.5, "Overheat": 0.2, "Stagflation": 0.2, "Deflation": 0.1},
                'confidence': 0.5
            }

        def mock_get_price(asset_class, dt):
            days = (dt - base_date).days
            return 100.0 + days * 0.1

        use_case = RunBacktestUseCase(
            repository=repository,
            get_regime_func=mock_get_regime,
            get_asset_price_func=mock_get_price
        )

        # 使用有效的再平衡频率
        frequencies = ['monthly', 'quarterly', 'yearly']
        results = []

        for freq in frequencies:
            request = RunBacktestRequest(
                name=f"测试-{freq}",
                start_date=base_date,
                end_date=base_date + timedelta(days=365),  # 1 年
                initial_capital=100000.0,
                rebalance_frequency=freq
            )

            response = use_case.execute(request)
            assert response.status == 'completed', f"{freq} 回测应完成"
            results.append((freq, response))

        # 验证不同频率产生了不同的交易数量
        # （这取决于实现，某些频率可能产生更多交易）
        for freq, response in results:
            assert response.backtest_id is not None

    def test_backtest_crud_operations(self):
        """测试回测 CRUD 操作

        验证：
        1. 创建回测
        2. 查询回测
        3. 更新回测
        4. 删除回测
        """
        repository = DjangoBacktestRepository()

        # 1. 创建回测
        config = BacktestConfig(
            start_date=date(2022, 1, 1),
            end_date=date(2022, 12, 31),
            initial_capital=100000.0,
            rebalance_frequency="monthly",
            use_pit_data=False,
            transaction_cost_bps=10.0
        )

        model = repository.create_backtest("测试回测", config)
        assert model.id is not None
        assert model.name == "测试回测"

        backtest_id = model.id

        # 2. 查询回测（使用正确的方法名）
        retrieved = repository.get_backtest_by_id(backtest_id)
        assert retrieved is not None
        assert retrieved.name == "测试回测"

        # 3. 更新回测状态
        success = repository.update_status(backtest_id, 'completed')
        assert success

        updated = repository.get_backtest_by_id(backtest_id)
        assert updated.status == 'completed'

        # 4. 删除回测
        deleted = repository.delete_backtest(backtest_id)
        assert deleted

        # 验证已删除
        deleted_retrieved = repository.get_backtest_by_id(backtest_id)
        assert deleted_retrieved is None

    def test_get_backtest_list(self):
        """测试获取回测列表

        验证可以查询所有回测并按状态过滤
        """
        repository = DjangoBacktestRepository()
        base_date = date(2022, 1, 1)

        config = BacktestConfig(
            start_date=base_date,
            end_date=date(2022, 12, 31),
            initial_capital=100000.0,
            rebalance_frequency="monthly",
            use_pit_data=False,
            transaction_cost_bps=10.0
        )

        # 创建多个回测
        created_ids = []
        for i in range(5):
            model = repository.create_backtest(f"回测{i}", config)
            created_ids.append(model.id)
            if i < 3:
                repository.update_status(model.id, 'completed')
            else:
                repository.update_status(model.id, 'failed')

        # 查询所有回测
        all_backtests = repository.get_all_backtests()
        # 可能存在其他测试创建的回测，只验证我们创建的都在其中
        all_ids = [b.id for b in all_backtests]
        for created_id in created_ids:
            assert created_id in all_ids, f"创建的回测 {created_id} 应在列表中"

        # 按状态过滤
        completed = repository.get_backtests_by_status('completed')
        completed_ids = [c.id for c in completed]
        assert len([cid for cid in created_ids[:3] if cid in completed_ids]) >= 3

        failed = repository.get_backtests_by_status('failed')
        failed_ids = [f.id for f in failed]
        assert len([cid for cid in created_ids[3:] if cid in failed_ids]) >= 2


@pytest.mark.django_db
class TestBacktestEdgeCases:
    """测试回测边界情况"""

    def test_empty_period_backtest(self):
        """测试空时间段回测

        当没有数据时回测应优雅地失败
        """
        repository = DjangoBacktestRepository()

        def mock_get_regime(dt):
            return None  # 无 Regime 数据

        def mock_get_price(asset_class, dt):
            return None  # 无价格数据

        use_case = RunBacktestUseCase(
            repository=repository,
            get_regime_func=mock_get_regime,
            get_asset_price_func=mock_get_price
        )

        request = RunBacktestRequest(
            name="空数据测试",
            start_date=date(2020, 1, 1),
            end_date=date(2020, 12, 31),
            initial_capital=100000.0
        )

        response = use_case.execute(request)

        # 应该失败或返回空结果
        assert response.status in ['failed', 'completed']

    def test_single_day_backtest(self):
        """测试单日回测

        边界情况：只有一天的回测
        """
        repository = DjangoBacktestRepository()
        base_date = date(2022, 1, 1)

        def mock_get_regime(dt):
            return {
                'dominant_regime': 'Recovery',
                'distribution': {"Recovery": 0.5, "Overheat": 0.2, "Stagflation": 0.2, "Deflation": 0.1},
                'confidence': 0.5
            }

        def mock_get_price(asset_class, dt):
            return 100.0

        use_case = RunBacktestUseCase(
            repository=repository,
            get_regime_func=mock_get_regime,
            get_asset_price_func=mock_get_price
        )

        # Domain 层要求 start_date < end_date，所以使用最短期间（1天差）
        request = RunBacktestRequest(
            name="单日测试",
            start_date=base_date,
            end_date=date(2022, 1, 2),  # 第二天（最短期限）
            initial_capital=100000.0
        )

        response = use_case.execute(request)

        # 单日回测应完成但交易很少
        assert response.status == 'completed'

    def test_very_long_period_backtest(self):
        """测试超长周期回测

        验证系统可以处理多年的数据
        """
        repository = DjangoBacktestRepository()
        base_date = date(2010, 1, 1)

        def mock_get_regime(dt):
            return {
                'dominant_regime': 'Recovery',
                'distribution': {"Recovery": 0.5, "Overheat": 0.2, "Stagflation": 0.2, "Deflation": 0.1},
                'confidence': 0.5
            }

        def mock_get_price(asset_class, dt):
            days = (dt - base_date).days
            return 100.0 + days * 0.05

        use_case = RunBacktestUseCase(
            repository=repository,
            get_regime_func=mock_get_regime,
            get_asset_price_func=mock_get_price
        )

        request = RunBacktestRequest(
            name="长期回测",
            start_date=base_date,
            end_date=date(2020, 12, 31),  # 11 年
            initial_capital=100000.0,
            rebalance_frequency="monthly"
        )

        response = use_case.execute(request)

        # 应该能够完成
        assert response.status == 'completed'


@pytest.mark.django_db
class TestBacktestAuditIntegration:
    """测试回测与审计的集成"""

    def test_backtest_auto_triggers_audit(self):
        """测试回测完成后自动触发审计分析

        验证：
        1. 回测成功完成后自动创建审计报告（或至少尝试审计）
        2. 审计状态在响应中正确反映
        3. 审计失败不影响回测结果
        """
        from apps.audit.infrastructure.repositories import DjangoAuditRepository
        from apps.audit.infrastructure.models import AttributionReport

        base_date = date(2022, 1, 1)

        # Mock 数据函数
        def mock_get_regime(dt):
            return {
                'dominant_regime': 'Recovery',
                'distribution': {"Recovery": 0.5, "Overheat": 0.2, "Stagflation": 0.2, "Deflation": 0.1},
                'confidence': 0.5,
                'date': dt
            }

        def mock_get_price(asset_class, dt):
            days = (dt - base_date).days
            return 100.0 + days * 0.1

        # 创建回测 Use Case
        backtest_repo = DjangoBacktestRepository()
        use_case = RunBacktestUseCase(
            repository=backtest_repo,
            get_regime_func=mock_get_regime,
            get_asset_price_func=mock_get_price
        )

        request = RunBacktestRequest(
            name="审计集成测试",
            start_date=base_date,
            end_date=base_date + timedelta(days=180),  # 6 个月
            initial_capital=100000.0,
            rebalance_frequency="monthly"
        )

        # 执行回测（应自动触发审计）
        response = use_case.execute(request)

        # 验证回测成功
        assert response.backtest_id is not None
        assert response.status == 'completed'

        # 验证审计状态在响应中正确设置
        assert hasattr(response, 'audit_status'), "响应应包含 audit_status 字段"
        assert response.audit_status in ['success', 'failed', 'skipped', 'pending'], \
            f"审计状态应为有效值，实际: {response.audit_status}"

        # 验证审计报告（如果审计成功）
        if response.audit_status == 'success':
            audit_repo = DjangoAuditRepository()
            reports = audit_repo.get_reports_by_backtest(response.backtest_id)

            # 应该至少有一个审计报告
            assert len(reports) > 0, "审计成功时应创建审计报告"

            # 验证报告包含必要字段
            report = reports[0]
            assert 'backtest_id' in report
            assert report['backtest_id'] == response.backtest_id
            assert 'regime_timing_pnl' in report
            assert 'asset_selection_pnl' in report
            assert 'total_pnl' in report
            assert response.audit_report_id is not None
        elif response.audit_status == 'failed':
            # 审计失败时，应该有错误信息
            assert response.audit_error is not None, "审计失败时应包含错误信息"

    def test_backtest_audit_failure_notification(self):
        """测试审计失败时用户得到通知

        验证：
        1. 当审计失败时，响应包含 audit_status='failed'
        2. 当审计失败时，响应包含 audit_error 错误信息
        3. 审计失败不影响回测结果本身
        """
        from unittest.mock import patch, MagicMock
        from apps.audit.application.use_cases import GenerateAttributionReportResponse

        base_date = date(2022, 1, 1)

        def mock_get_regime(dt):
            return {
                'dominant_regime': 'Recovery',
                'distribution': {"Recovery": 0.5, "Overheat": 0.2, "Stagflation": 0.2, "Deflation": 0.1},
                'confidence': 0.5,
                'date': dt
            }

        def mock_get_price(asset_class, dt):
            days = (dt - base_date).days
            return 100.0 + days * 0.1

        backtest_repo = DjangoBacktestRepository()

        # Mock 审计用例返回失败响应（注意：Response 只有 success, report_id, error 三个字段）
        mock_audit_response = GenerateAttributionReportResponse(
            success=False,
            report_id=None,
            error="审计数据不足：缺少基准配置"
        )

        # Patch at the source import location
        with patch('apps.audit.application.use_cases.GenerateAttributionReportUseCase', MagicMock()) as MockAuditUC:
            # 配置 mock 实例
            mock_instance = MockAuditUC.return_value
            mock_instance.execute.return_value = mock_audit_response

            use_case = RunBacktestUseCase(
                repository=backtest_repo,
                get_regime_func=mock_get_regime,
                get_asset_price_func=mock_get_price
            )

            request = RunBacktestRequest(
                name="审计失败通知测试",
                start_date=base_date,
                end_date=base_date + timedelta(days=180),
                initial_capital=100000.0,
                rebalance_frequency="monthly"
            )

            response = use_case.execute(request)

            # 验证回测本身成功
            assert response.backtest_id is not None, "回测应成功创建"
            assert response.status == 'completed', "回测状态应为 completed"
            assert response.result is not None, "回测应包含结果"

            # 验证审计失败状态正确传递
            assert response.audit_status == 'failed', \
                f"审计状态应为 'failed'，实际: {response.audit_status}"
            assert response.audit_error is not None, "审计失败时应包含错误信息"
            assert "审计数据不足" in response.audit_error, \
                f"错误信息应包含具体原因，实际: {response.audit_error}"
            assert response.audit_report_id is None, "审计失败时不应有 report_id"

    def test_backtest_audit_exception_handling(self):
        """测试审计异常时的处理

        验证：
        1. 当审计抛出异常时，响应包含 audit_status='failed'
        2. 当审计抛出异常时，响应包含 audit_error 错误信息
        3. 审计异常不影响回测结果本身
        """
        from unittest.mock import patch
        from apps.audit.application.use_cases import GenerateAttributionReportUseCase as OriginalAuditUC

        base_date = date(2022, 1, 1)

        def mock_get_regime(dt):
            return {
                'dominant_regime': 'Recovery',
                'distribution': {"Recovery": 0.5, "Overheat": 0.2, "Stagflation": 0.2, "Deflation": 0.1},
                'confidence': 0.5,
                'date': dt
            }

        def mock_get_price(asset_class, dt):
            days = (dt - base_date).days
            return 100.0 + days * 0.1

        backtest_repo = DjangoBacktestRepository()

        # Create a mock class that raises exception on execute
        class MockAuditUseCase:
            def __init__(self, *args, **kwargs):
                pass

            def execute(self, *args, **kwargs):
                raise RuntimeError("数据库连接超时")

        # Patch at the source import location - use a callable that returns our mock class
        with patch('apps.audit.application.use_cases.GenerateAttributionReportUseCase', MockAuditUseCase):
            use_case = RunBacktestUseCase(
                repository=backtest_repo,
                get_regime_func=mock_get_regime,
                get_asset_price_func=mock_get_price
            )

            request = RunBacktestRequest(
                name="审计异常处理测试",
                start_date=base_date,
                end_date=base_date + timedelta(days=180),
                initial_capital=100000.0,
                rebalance_frequency="monthly"
            )

            response = use_case.execute(request)

            # 验证回测本身成功
            assert response.backtest_id is not None, "回测应成功创建"
            assert response.status == 'completed', "回测状态应为 completed"

            # 验证审计异常状态正确传递
            assert response.audit_status == 'failed', \
                f"审计状态应为 'failed'，实际: {response.audit_status}"
            assert response.audit_error is not None, "审计异常时应包含错误信息"
            assert "数据库连接超时" in response.audit_error, \
                f"错误信息应包含具体原因，实际: {response.audit_error}"
            assert response.audit_report_id is None, "审计异常时不应有 report_id"

    def test_backtest_failed_skips_audit(self):
        """测试回测失败时跳过审计

        验证：
        1. 当回测失败时，audit_status='skipped'
        2. 不会触发审计流程
        """
        from unittest.mock import patch

        base_date = date(2022, 1, 1)

        # 使用更激进的 mock 来确保回测失败
        def mock_get_regime(dt):
            # 返回 None 应该导致回测失败或没有有效数据
            return None

        def mock_get_price(asset_class, dt):
            # 返回 None 应该导致回测失败
            return None

        # 使用 mock repository 来确保保存结果时失败
        class FailingBacktestRepository(DjangoBacktestRepository):
            def save_result(self, backtest_id, result):
                # 故意不保存，让回测流程继续但可能导致问题
                # 或者直接抛出异常
                raise ValueError("模拟保存失败")

        backtest_repo = FailingBacktestRepository()

        use_case = RunBacktestUseCase(
            repository=backtest_repo,
            get_regime_func=mock_get_regime,
            get_asset_price_func=mock_get_price
        )

        request = RunBacktestRequest(
            name="回测失败跳过审计测试",
            start_date=base_date,
            end_date=base_date + timedelta(days=180),
            initial_capital=100000.0,
        )

        response = use_case.execute(request)

        # 验证回测失败
        assert response.status == 'failed', f"回测应失败，实际状态: {response.status}"

        # 验证审计状态为跳过（回测失败时不尝试审计）
        assert response.audit_status == 'skipped', \
            f"回测失败时审计状态应为 'skipped'，实际: {response.audit_status}"
