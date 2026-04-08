"""
Unit Tests for Repository Layer

测试 Infrastructure 层的 Repository 实现，包括：
1. CRUD 操作
2. Entity ↔ Model 映射
3. 查询和过滤功能
4. 错误处理
"""

from datetime import date, timedelta

import pytest
from django.contrib.auth.models import User
from django.utils import timezone

from apps.backtest.domain.entities import BacktestConfig, BacktestStatus
from apps.backtest.infrastructure.repositories import DjangoBacktestRepository
from apps.macro.domain.entities import MacroIndicator, PeriodType
from apps.macro.infrastructure.models import MacroIndicator as MacroIndicatorORM
from apps.macro.infrastructure.repositories import DjangoMacroRepository
from apps.regime.domain.entities import RegimeSnapshot
from apps.regime.infrastructure.repositories import DjangoRegimeRepository
from apps.signal.domain.entities import InvestmentSignal, SignalStatus
from apps.signal.infrastructure.models import InvestmentSignalModel
from apps.signal.infrastructure.repositories import DjangoSignalRepository


@pytest.mark.django_db
class TestDjangoMacroRepository:
    """测试 DjangoMacroRepository"""

    def test_save_and_retrieve_indicator(self):
        """测试保存和检索宏观指标"""
        repository = DjangoMacroRepository()
        indicator = MacroIndicator(
            code="CN_PMI",
            value=50.5,
            reporting_period=date(2024, 1, 1),
            period_type=PeriodType.MONTH,
            unit="指数",
            original_unit="指数",
            published_at=date(2024, 1, 2),
            source="test"
        )

        # 保存指标
        saved = repository.save_indicator(indicator)
        assert saved.code == "CN_PMI"
        assert saved.value == 50.5

        # 检查 ORM 对象有 ID
        orm_obj = MacroIndicatorORM.objects.filter(code="CN_PMI", reporting_period=date(2024, 1, 1)).first()
        assert orm_obj is not None
        assert orm_obj.id is not None

        # 通过代码和日期检索
        retrieved = repository.get_by_code_and_date("CN_PMI", date(2024, 1, 1))
        assert retrieved is not None
        assert retrieved.code == "CN_PMI"
        assert retrieved.value == 50.5

    def test_save_indicators_batch(self):
        """测试批量保存指标"""
        repository = DjangoMacroRepository()
        indicators = [
            MacroIndicator(
                code=f"TEST_IND_{i}",
                value=100.0 + i,
                reporting_period=date(2024, 1, i + 1),
                period_type=PeriodType.DAY,
                unit="指数",
                original_unit="指数",
                published_at=date(2024, 1, i + 1),
                source="test"
            )
            for i in range(5)
        ]

        saved_list = repository.save_indicators_batch(indicators)
        assert len(saved_list) == 5
        assert all(s.code.startswith("TEST_IND_") for s in saved_list)

    def test_get_series_with_filters(self):
        """测试带过滤条件的时序查询"""
        repository = DjangoMacroRepository()

        # 创建测试数据
        for i in range(10):
            indicator = MacroIndicator(
                code="TEST_SERIES",
                value=100.0 + i,
                reporting_period=date(2024, 1, i + 1),
                period_type=PeriodType.DAY,
                unit="指数",
                original_unit="指数",
                published_at=date(2024, 1, i + 1),
                source="test"
            )
            repository.save_indicator(indicator)

        # 查询全部
        all_series = repository.get_series("TEST_SERIES")
        assert len(all_series) == 10

        # 查询日期范围
        filtered = repository.get_series(
            "TEST_SERIES",
            start_date=date(2024, 1, 3),
            end_date=date(2024, 1, 7)
        )
        assert len(filtered) == 5  # 1/3 - 1/7

        # 按数据源过滤
        by_source = repository.get_series("TEST_SERIES", source="test")
        assert len(by_source) == 10

    def test_get_latest_observation(self):
        """测试获取最新观测值"""
        repository = DjangoMacroRepository()
        test_code = "TEST_LATEST_OBS"

        # 创建多个时期的指标
        for i in range(5):
            indicator = MacroIndicator(
                code=test_code,
                value=50.0 + i,
                reporting_period=date(2024, 1, i * 7 + 1),  # 每周
                period_type=PeriodType.MONTH,
                unit="指数",
                original_unit="指数",
                published_at=date(2024, 1, i * 7 + 2),
                source="test"
            )
            repository.save_indicator(indicator)

        # 获取最新值
        latest = repository.get_latest_observation(test_code)
        assert latest is not None
        assert latest.value == 54.0  # 最后一个值

        # 获取某个日期之前的最新值
        before_date = repository.get_latest_observation(test_code, before_date=date(2024, 1, 15))
        assert before_date is not None
        assert before_date.reporting_period < date(2024, 1, 15)

    def test_entity_to_model_mapping(self):
        """测试 Entity 到 Model 的映射"""
        repository = DjangoMacroRepository()
        indicator = MacroIndicator(
            code="TEST_INDICATOR",
            value=123.45,
            reporting_period=date(2024, 6, 15),
            period_type=PeriodType.MONTH,
            unit="亿元",
            original_unit="万亿元",
            published_at=date(2024, 6, 16),
            source="test_source"
        )

        saved = repository.save_indicator(indicator)

        # 验证字段映射
        assert saved.code == "TEST_INDICATOR"
        assert saved.value == 123.45
        assert saved.unit == "亿元"
        assert saved.original_unit == "万亿元"
        assert saved.source == "test_source"
        # period_type 在返回时应该是枚举类型
        assert isinstance(saved.period_type, PeriodType)

    def test_get_growth_and_inflation_series(self):
        """测试获取增长和通胀指标序列"""
        repository = DjangoMacroRepository()

        # 创建 PMI 数据
        for i in range(12):
            indicator = MacroIndicator(
                code="CN_PMI",
                value=50.0 + i * 0.1,
                reporting_period=date(2024, i + 1, 1),
                period_type=PeriodType.MONTH,
                unit="指数",
                original_unit="指数",
                published_at=date(2024, i + 1, 2),
                source="test"
            )
            repository.save_indicator(indicator)

        # 获取增长序列（数值）
        growth_values = repository.get_growth_series("PMI", source="test")
        assert len(growth_values) == 12

        # 获取增长序列（完整指标）
        growth_full = repository.get_growth_series_full("PMI", source="test")
        assert len(growth_full) == 12
        assert all(isinstance(g, MacroIndicator) for g in growth_full)

    def test_delete_operations(self):
        """测试删除操作"""
        repository = DjangoMacroRepository()

        indicator = MacroIndicator(
            code="TO_DELETE",
            value=100.0,
            reporting_period=date(2024, 1, 1),
            period_type=PeriodType.DAY,
            unit="指数",
            original_unit="指数",
            published_at=date(2024, 1, 1),
            source="test"
        )
        repository.save_indicator(indicator)

        # 删除
        deleted = repository.delete_indicator("TO_DELETE", date(2024, 1, 1))
        assert deleted

        # 验证已删除
        retrieved = repository.get_by_code_and_date("TO_DELETE", date(2024, 1, 1))
        assert retrieved is None

    def test_statistics(self):
        """测试统计信息"""
        repository = DjangoMacroRepository()
        before = repository.get_statistics()

        # 创建不同指标的数据
        for code in ["TEST_STAT_A", "TEST_STAT_B", "TEST_STAT_C"]:
            for i in range(5):
                indicator = MacroIndicator(
                    code=code,
                    value=100.0 + i,
                    reporting_period=date(2024, 1, i + 1),
                    period_type=PeriodType.DAY,
                    unit="指数",
                    original_unit="指数",
                    published_at=date(2024, 1, i + 1),
                    source="test_source"
                )
                repository.save_indicator(indicator)

        stats = repository.get_statistics()
        assert stats['total_indicators'] - before['total_indicators'] == 3
        assert stats['total_records'] - before['total_records'] == 15
        assert len(stats['sources']) > 0


@pytest.mark.django_db
class TestDjangoRegimeRepository:
    """测试 DjangoRegimeRepository"""

    def test_save_regime_snapshot(self):
        """测试保存 Regime 快照"""
        repository = DjangoRegimeRepository()
        snapshot = RegimeSnapshot(
            growth_momentum_z=1.0,
            inflation_momentum_z=-0.5,
            distribution={"Recovery": 0.6, "Overheat": 0.2, "Stagflation": 0.1, "Deflation": 0.1},
            dominant_regime="Recovery",
            confidence=0.6,
            observed_at=date(2024, 1, 1)
        )

        # 保存快照
        saved = repository.save_snapshot(snapshot)
        assert saved.dominant_regime == "Recovery"
        assert saved.growth_momentum_z == 1.0

    def test_get_latest_snapshot(self):
        """测试获取最新快照"""
        repository = DjangoRegimeRepository()

        # 创建多个快照
        for i in range(5):
            snapshot = RegimeSnapshot(
                growth_momentum_z=float(i) / 10,
                inflation_momentum_z=0.0,
                distribution={"Recovery": 1.0},
                dominant_regime="Recovery",
                confidence=0.5,
                observed_at=date(2024, 1, i * 7 + 1)
            )
            repository.save_snapshot(snapshot)

        # 获取最新快照
        latest = repository.get_latest_snapshot()
        assert latest is not None
        assert latest.observed_at == date(2024, 1, 29)

    def test_get_snapshot_by_date(self):
        """测试按日期获取快照"""
        repository = DjangoRegimeRepository()

        snapshot = RegimeSnapshot(
            growth_momentum_z=1.0,
            inflation_momentum_z=-0.5,
            distribution={"Recovery": 0.6},
            dominant_regime="Recovery",
            confidence=0.6,
            observed_at=date(2024, 6, 15)
        )
        repository.save_snapshot(snapshot)

        # 按日期检索
        retrieved = repository.get_snapshot_by_date(date(2024, 6, 15))
        assert retrieved is not None
        assert retrieved.dominant_regime == "Recovery"

        # 不存在的日期
        not_found = repository.get_snapshot_by_date(date(2024, 6, 16))
        assert not_found is None

    def test_get_regime_history(self):
        """测试获取 Regime 历史记录"""
        repository = DjangoRegimeRepository()

        # 创建不同 Regime 的快照
        regimes = ["Recovery", "Overheat", "Stagflation", "Recovery"]
        for i, regime in enumerate(regimes):
            snapshot = RegimeSnapshot(
                growth_momentum_z=0.0,
                inflation_momentum_z=0.0,
                distribution={regime: 1.0},
                dominant_regime=regime,
                confidence=0.5,
                observed_at=date(2024, 1, i + 1)
            )
            repository.save_snapshot(snapshot)

        # 获取 Recovery 的历史
        recovery_history = repository.get_regime_history("Recovery")
        assert len(recovery_history) == 2
        assert all(s.dominant_regime == "Recovery" for s in recovery_history)

    def test_get_snapshots_in_range(self):
        """测试获取日期范围内的快照"""
        repository = DjangoRegimeRepository()

        # 创建一系列快照
        for i in range(10):
            snapshot = RegimeSnapshot(
                growth_momentum_z=0.0,
                inflation_momentum_z=0.0,
                distribution={"Recovery": 1.0},
                dominant_regime="Recovery",
                confidence=0.5,
                observed_at=date(2024, 1, i + 1)
            )
            repository.save_snapshot(snapshot)

        # 获取范围内的快照
        snapshots = repository.get_snapshots_in_range(
            start_date=date(2024, 1, 3),
            end_date=date(2024, 1, 7)
        )
        assert len(snapshots) == 5  # 1/3 - 1/7

    def test_regime_distribution_stats(self):
        """测试 Regime 分布统计"""
        repository = DjangoRegimeRepository()

        # 创建不同 Regime 的快照（使用不同日期避免覆盖）
        regime_counts = {"Recovery": 5, "Overheat": 3, "Stagflation": 2}
        day_offset = 0
        for regime, count in regime_counts.items():
            for i in range(count):
                snapshot = RegimeSnapshot(
                    growth_momentum_z=0.0,
                    inflation_momentum_z=0.0,
                    distribution={regime: 1.0},
                    dominant_regime=regime,
                    confidence=0.5,
                    observed_at=date(2024, 1, day_offset + 1)
                )
                repository.save_snapshot(snapshot)
                day_offset += 1

        # 获取统计
        stats = repository.get_regime_distribution_stats()
        assert stats['total'] == 10
        assert 'by_regime' in stats
        # 验证各 Regime 的计数
        assert stats['by_regime']['Recovery']['count'] == 5
        assert stats['by_regime']['Overheat']['count'] == 3


@pytest.mark.django_db
class TestDjangoSignalRepository:
    """测试 DjangoSignalRepository"""

    def test_save_signal_with_rules(self):
        """测试保存信号和准入规则"""
        repository = DjangoSignalRepository()
        signal = InvestmentSignal(
            id=None,
            asset_code="000001.SH",
            asset_class="a_share_growth",
            direction="LONG",
            logic_desc="PMI 连续回升，经济复苏",
            invalidation_logic="PMI 跌破 50 且连续 2 月低于前值时证伪",
            invalidation_threshold=49.5,
            target_regime="Recovery",
            created_at=date(2024, 1, 1),
            status=SignalStatus.PENDING,
            rejection_reason=""
        )

        saved = repository.save_signal(signal)
        assert saved.asset_code == "000001.SH"
        assert saved.status == SignalStatus.PENDING

    def test_filter_by_status(self):
        """测试按状态过滤信号"""
        repository = DjangoSignalRepository()

        # 创建不同状态的信号
        for status in [SignalStatus.PENDING, SignalStatus.APPROVED, SignalStatus.REJECTED]:
            signal = InvestmentSignal(
                id=None,
                asset_code=f"00000{status.value}.SH",
                asset_class="a_share_growth",
                direction="LONG",
                logic_desc=f"测试信号 - {status.value}",
                invalidation_logic="测试证伪逻辑描述，长度至少需要十个字符",
                invalidation_threshold=50.0,
                target_regime="Recovery",
                created_at=date(2024, 1, 1),
                status=status,
                rejection_reason=""
            )
            repository.save_signal(signal)

        # 按状态过滤
        pending = repository.get_signals_by_status(SignalStatus.PENDING)
        assert len(pending) == 1
        assert pending[0].status == SignalStatus.PENDING

        approved = repository.get_signals_by_status(SignalStatus.APPROVED)
        assert len(approved) == 1

    def test_update_signal_status(self):
        """测试更新信号状态"""
        repository = DjangoSignalRepository()

        signal = InvestmentSignal(
            id=None,
            asset_code="000001.SH",
            asset_class="a_share_growth",
            direction="LONG",
            logic_desc="测试信号",
            invalidation_logic="测试证伪逻辑描述，长度至少需要十个字符",
            invalidation_threshold=50.0,
            target_regime="Recovery",
            created_at=date(2024, 1, 1),
            status=SignalStatus.PENDING,
            rejection_reason=""
        )
        saved = repository.save_signal(signal)

        # 更新状态
        success = repository.update_signal_status(
            saved.id,
            SignalStatus.APPROVED
        )
        assert success

        # 验证更新
        updated = repository.get_signal_by_id(saved.id)
        assert updated.status == SignalStatus.APPROVED

        # 拒绝信号
        success = repository.update_signal_status(
            saved.id,
            SignalStatus.REJECTED,
            rejection_reason="测试拒绝原因"
        )
        assert success

        rejected = repository.get_signal_by_id(saved.id)
        assert rejected.status == SignalStatus.REJECTED
        assert rejected.rejection_reason == "测试拒绝原因"

    def test_get_active_signals(self):
        """测试获取活跃信号"""
        repository = DjangoSignalRepository()

        # 创建多个活跃信号
        for i in range(3):
            signal = InvestmentSignal(
                id=None,
                asset_code=f"00000{i}.SH",
                asset_class="a_share_growth",
                direction="LONG",
                logic_desc=f"测试信号 {i}",
                invalidation_logic=f"测试证伪逻辑描述 {i}，长度足够",
                invalidation_threshold=50.0,
                target_regime="Recovery",
                created_at=date(2024, 1, 1),
                status=SignalStatus.APPROVED,
                rejection_reason=""
            )
            repository.save_signal(signal)

        # 获取活跃信号
        active = repository.get_active_signals()
        assert len(active) == 3
        assert all(s.status == SignalStatus.APPROVED for s in active)

    def test_get_signals_by_regime(self):
        """测试按目标 Regime 获取信号"""
        repository = DjangoSignalRepository()

        # 创建不同目标 Regime 的信号
        for regime in ["Recovery", "Overheat", "Stagflation"]:
            signal = InvestmentSignal(
                id=None,
                asset_code="000001.SH",
                asset_class="a_share_growth",
                direction="LONG",
                logic_desc=f"测试信号 - {regime}",
                invalidation_logic="测试证伪逻辑描述，长度至少需要十个字符",
                invalidation_threshold=50.0,
                target_regime=regime,
                created_at=date(2024, 1, 1),
                status=SignalStatus.APPROVED,
                rejection_reason=""
            )
            repository.save_signal(signal)

        # 获取 Recovery 信号
        recovery_signals = repository.get_signals_by_regime("Recovery")
        assert len(recovery_signals) == 1
        assert recovery_signals[0].target_regime == "Recovery"

    def test_get_statistics(self):
        """测试统计信息"""
        repository = DjangoSignalRepository()

        # 创建不同状态的信号
        status_counts = {
            SignalStatus.PENDING: 3,
            SignalStatus.APPROVED: 5,
            SignalStatus.REJECTED: 2
        }
        for status, count in status_counts.items():
            for i in range(count):
                signal = InvestmentSignal(
                    id=None,
                    asset_code=f"00000{i}.SH",
                    asset_class="a_share_growth",
                    direction="LONG",
                    logic_desc=f"测试信号 {i}",
                    invalidation_logic="测试证伪逻辑描述，长度至少需要十个字符",
                    invalidation_threshold=50.0,
                    target_regime="Recovery",
                    created_at=date(2024, 1, 1),
                    status=status,
                    rejection_reason=""
                )
                repository.save_signal(signal)

        stats = repository.get_statistics()
        assert stats['total'] == 10
        assert stats['by_status']['pending']['count'] == 3
        assert stats['by_status']['approved']['count'] == 5
        assert stats['by_status']['rejected']['count'] == 2

    def test_get_signals_created_between_uses_user_id_field(self):
        """摘要查询应返回真实存在的 user_id 字段，避免 daily summary 失败。"""
        repository = DjangoSignalRepository()
        user = User.objects.create_user(username="signal-owner", password="test-pass-123")
        created_at = timezone.now() - timedelta(hours=1)

        signal = InvestmentSignalModel.objects.create(
            user=user,
            asset_code="000001.SH",
            asset_class="a_share_growth",
            direction="LONG",
            logic_desc="测试信号摘要",
            invalidation_logic="测试证伪逻辑描述，长度至少需要十个字符",
            invalidation_threshold=50.0,
            target_regime="Recovery",
            status="pending",
        )
        InvestmentSignalModel.objects.filter(id=signal.id).update(created_at=created_at)

        details = repository.get_signals_created_between(
            created_at - timedelta(minutes=1),
            created_at + timedelta(minutes=1),
        )

        assert details == [
            {
                "asset_code": "000001.SH",
                "logic_desc": "测试信号摘要",
                "user_id": user.id,
            }
        ]


@pytest.mark.django_db
class TestDjangoBacktestRepository:
    """测试 DjangoBacktestRepository"""

    def test_create_backtest(self):
        """测试创建回测"""
        repository = DjangoBacktestRepository()
        config = BacktestConfig(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            initial_capital=100000.0,
            rebalance_frequency="monthly",
            use_pit_data=False,
            transaction_cost_bps=10.0
        )

        model = repository.create_backtest("测试回测", config)
        assert model.id is not None
        assert model.name == "测试回测"
        assert model.status == "pending"  # ORM 存储字符串

    def test_get_backtest_by_id(self):
        """测试按 ID 获取回测"""
        repository = DjangoBacktestRepository()
        config = BacktestConfig(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            initial_capital=100000.0,
            rebalance_frequency="monthly",
            use_pit_data=False,
            transaction_cost_bps=10.0
        )

        model = repository.create_backtest("测试回测", config)
        backtest_id = model.id

        # 检索回测
        retrieved = repository.get_backtest_by_id(backtest_id)
        assert retrieved is not None
        assert retrieved.name == "测试回测"

    def test_update_status(self):
        """测试更新回测状态"""
        repository = DjangoBacktestRepository()
        config = BacktestConfig(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            initial_capital=100000.0,
            rebalance_frequency="monthly",
            use_pit_data=False,
            transaction_cost_bps=10.0
        )

        model = repository.create_backtest("测试回测", config)
        backtest_id = model.id

        # 更新状态为 running
        success = repository.update_status(backtest_id, "running")
        assert success

        updated = repository.get_backtest_by_id(backtest_id)
        assert updated.status == "running"

        # 更新状态为 completed
        success = repository.update_status(backtest_id, "completed")
        assert success

        updated = repository.get_backtest_by_id(backtest_id)
        assert updated.status == "completed"

    def test_delete_backtest(self):
        """测试删除回测"""
        repository = DjangoBacktestRepository()
        config = BacktestConfig(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            initial_capital=100000.0,
            rebalance_frequency="monthly",
            use_pit_data=False,
            transaction_cost_bps=10.0
        )

        model = repository.create_backtest("测试回测", config)
        backtest_id = model.id

        # 删除
        deleted = repository.delete_backtest(backtest_id)
        assert deleted

        # 验证已删除
        retrieved = repository.get_backtest_by_id(backtest_id)
        assert retrieved is None

    def test_get_all_backtests(self):
        """测试获取所有回测"""
        repository = DjangoBacktestRepository()
        config = BacktestConfig(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            initial_capital=100000.0,
            rebalance_frequency="monthly",
            use_pit_data=False,
            transaction_cost_bps=10.0
        )

        # 创建多个回测
        created_ids = []
        for i in range(3):
            model = repository.create_backtest(f"回测{i}", config)
            created_ids.append(model.id)

        # 获取所有回测
        all_backtests = repository.get_all_backtests()
        all_ids = [b.id for b in all_backtests]
        for created_id in created_ids:
            assert created_id in all_ids

    def test_get_backtests_by_status(self):
        """测试按状态获取回测"""
        repository = DjangoBacktestRepository()
        config = BacktestConfig(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            initial_capital=100000.0,
            rebalance_frequency="monthly",
            use_pit_data=False,
            transaction_cost_bps=10.0
        )

        # 创建不同状态的回测
        for status in ["pending", "running", "completed"]:
            model = repository.create_backtest(f"回测-{status}", config)
            repository.update_status(model.id, status)

        # 按状态过滤
        pending = repository.get_backtests_by_status("pending")
        assert len(pending) >= 1
        assert all(b.status == "pending" for b in pending)

        completed = repository.get_backtests_by_status("completed")
        assert len(completed) >= 1

    def test_get_statistics(self):
        """测试统计信息"""
        repository = DjangoBacktestRepository()
        config = BacktestConfig(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            initial_capital=100000.0,
            rebalance_frequency="monthly",
            use_pit_data=False,
            transaction_cost_bps=10.0
        )

        # 创建多个回测
        for i in range(5):
            model = repository.create_backtest(f"回测{i}", config)
            if i < 3:
                repository.update_status(model.id, "completed")

        stats = repository.get_statistics()
        assert stats['total'] >= 5
        # by_status 是字典，包含 count 和 percentage
        assert isinstance(stats['by_status']['completed'], dict)


@pytest.mark.django_db
class TestRepositoryErrorHandling:
    """测试仓储错误处理"""

    def test_get_nonexistent_indicator(self):
        """测试获取不存在的指标"""
        repository = DjangoMacroRepository()
        result = repository.get_by_code_and_date("NONEXISTENT", date(2024, 1, 1))
        assert result is None

    def test_get_nonexistent_signal(self):
        """测试获取不存在的信号"""
        repository = DjangoSignalRepository()
        result = repository.get_signal_by_id(999999)
        assert result is None

    def test_update_nonexistent_backtest_status(self):
        """测试更新不存在的回测状态"""
        repository = DjangoBacktestRepository()
        success = repository.update_status(99999, "running")
        assert success is False

    def test_delete_nonexistent_backtest(self):
        """测试删除不存在的回测"""
        repository = DjangoBacktestRepository()
        deleted = repository.delete_backtest(99999)
        assert deleted is False

    def test_save_existing_indicator(self):
        """测试保存已存在的指标（更新）"""
        repository = DjangoMacroRepository()
        indicator = MacroIndicator(
            code="CN_PMI",
            value=50.0,
            reporting_period=date(2024, 1, 1),
            period_type=PeriodType.MONTH,
            unit="指数",
            original_unit="指数",
            published_at=date(2024, 1, 2),
            source="test"
        )
        repository.save_indicator(indicator)

        # 更新同一个指标
        updated = MacroIndicator(
            code="CN_PMI",
            value=51.0,  # 更新的值
            reporting_period=date(2024, 1, 1),
            period_type=PeriodType.MONTH,
            unit="指数",
            original_unit="指数",
            published_at=date(2024, 1, 3),
            source="test"
        )
        saved = repository.save_indicator(updated)
        assert saved.value == 51.0  # 应该是更新后的值
