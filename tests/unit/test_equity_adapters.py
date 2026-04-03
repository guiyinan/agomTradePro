"""
Unit tests for equity module adapters and TODO cleanup

测试 TODO 清理后的功能：
1. 规则变化检测
2. Regime 历史数据填充
3. 行业过滤缓存
"""

from datetime import date, timedelta
from unittest.mock import MagicMock, Mock, patch

import pytest


class TestIncrementalScreeningEngineRuleDetection:
    """测试增量筛选引擎的规则变化检测"""

    def test_rule_hash_computation(self):
        """测试规则哈希计算"""
        from apps.equity.domain.optimized_screener import IncrementalScreeningEngine
        from apps.equity.domain.rules import StockScreeningRule

        engine = IncrementalScreeningEngine()
        rule1 = StockScreeningRule(
            regime='Recovery',
            name='测试规则',
            min_roe=15.0,
            max_pe=30.0
        )

        hash1 = engine._compute_rule_hash(rule1)
        assert hash1 is not None
        assert isinstance(hash1, str)
        assert len(hash1) == 64  # SHA-256 哈希长度

    def test_has_rule_changed_first_run(self):
        """测试首次运行时规则未变化"""
        from apps.equity.domain.optimized_screener import IncrementalScreeningEngine
        from apps.equity.domain.rules import StockScreeningRule

        engine = IncrementalScreeningEngine()
        rule = StockScreeningRule(
            regime='Recovery',
            name='测试规则',
            min_roe=15.0,
            max_pe=30.0
        )

        result = engine._has_rule_changed(rule)

        assert result is False  # 首次运行不算变化
        assert engine._last_rule_hash is not None

    def test_has_rule_changed_no_change(self):
        """测试规则未变化"""
        from apps.equity.domain.optimized_screener import IncrementalScreeningEngine
        from apps.equity.domain.rules import StockScreeningRule

        engine = IncrementalScreeningEngine()
        rule = StockScreeningRule(
            regime='Recovery',
            name='测试规则',
            min_roe=15.0,
            max_pe=30.0
        )

        # 第一次调用
        engine._has_rule_changed(rule)
        # 第二次调用相同规则
        result = engine._has_rule_changed(rule)

        assert result is False

    def test_has_rule_changed_with_change(self):
        """测试规则已变化"""
        from apps.equity.domain.optimized_screener import IncrementalScreeningEngine
        from apps.equity.domain.rules import StockScreeningRule

        engine = IncrementalScreeningEngine()
        rule1 = StockScreeningRule(
            regime='Recovery',
            name='测试规则',
            min_roe=15.0,
            max_pe=30.0
        )
        rule2 = StockScreeningRule(
            regime='Recovery',
            name='测试规则',
            min_roe=20.0,  # 修改了 min_roe
            max_pe=30.0
        )

        # 第一次调用
        engine._has_rule_changed(rule1)
        # 第二次调用不同规则
        result = engine._has_rule_changed(rule2)

        assert result is True


class TestRegimeHistoryFill:
    """测试 Regime 历史数据填充功能"""

    def test_fill_missing_dates(self):
        """测试填充缺失日期"""
        from apps.equity.application.use_cases import AnalyzeRegimeCorrelationUseCase

        use_case = AnalyzeRegimeCorrelationUseCase(
            stock_repository=Mock(),
            regime_repository=Mock()
        )

        # 创建有缺失的数据
        regime_history = {
            date(2024, 1, 1): 'Recovery',
            date(2024, 1, 3): 'Recovery',
            date(2024, 1, 5): 'Overheat',
        }

        result = use_case._fill_missing_dates(
            regime_history,
            date(2024, 1, 1),
            date(2024, 1, 5)
        )

        # 验证所有日期都被填充
        assert date(2024, 1, 1) in result
        assert date(2024, 1, 2) in result
        assert date(2024, 1, 3) in result
        assert date(2024, 1, 4) in result
        assert date(2024, 1, 5) in result

        # 1月2日应该使用1月1日的 Regime
        assert result[date(2024, 1, 2)] == 'Recovery'
        # 1月4日应该使用1月3日的 Regime
        assert result[date(2024, 1, 4)] == 'Recovery'

    def test_fill_missing_dates_empty_history(self):
        """测试空历史数据的填充"""
        from apps.equity.application.use_cases import AnalyzeRegimeCorrelationUseCase

        use_case = AnalyzeRegimeCorrelationUseCase(
            stock_repository=Mock(),
            regime_repository=Mock()
        )

        result = use_case._fill_missing_dates(
            {},  # 空历史
            date(2024, 1, 1),
            date(2024, 1, 3)
        )

        # 应该使用默认 Regime 填充所有日期
        assert len(result) == 3
        assert all(v == 'Recovery' for v in result.values())


class TestEquityViewSetInitialization:
    """测试 EquityViewSet 初始化"""

    def test_viewset_has_regime_repo(self):
        """测试 ViewSet 正确注入了 regime_repo"""
        # 导入前需要确保 Django 已设置
        import django
        from django.conf import settings

        if not settings.configured:
            settings.configure(
                DEBUG=True,
                DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3'}},
                INSTALLED_APPS=[
                    'django.contrib.contenttypes',
                    'django.contrib.auth',
                    'rest_framework',
                    'apps.equity',
                ],
                SECRET_KEY='test-secret-key',
            )
            django.setup()

        from apps.equity.interface.views import EquityViewSet

        viewset = EquityViewSet()

        # 验证 regime_repo 已被注入
        assert hasattr(viewset, 'regime_repo')
        assert viewset.regime_repo is not None


class TestStockPoolImplementation:
    """测试股票池功能实现"""

    def test_stock_pool_adapter_exists(self):
        """测试股票池适配器存在"""
        from apps.equity.infrastructure.adapters import StockPoolRepositoryAdapter

        assert StockPoolRepositoryAdapter is not None

        # 验证适配器有所需的方法
        adapter = StockPoolRepositoryAdapter()
        assert hasattr(adapter, 'get_current_pool')
        assert hasattr(adapter, 'save_pool')
        assert hasattr(adapter, 'get_latest_pool_info')


# TODO 计数测试
class TestTOODOCount:
    """验证 TODO 数量是否符合要求"""

    def test_count_todos_in_equity_module(self):
        """
        测试 equity 模块中剩余的 TODO 数量

        要求：
        - 消除 >= 70% 的 TODO（即消除 >= 8 个，保留 <= 3 个非关键 TODO）
        - 保留的 TODO 应标记为 [低优先级] 或 [未来优化]
        """
        import os
        import re

        files_to_check = [
            'apps/equity/application/use_cases.py',
            'apps/equity/domain/optimized_screener.py',
            'apps/equity/interface/views.py',
        ]

        total_todos = 0
        low_priority_todos = 0

        base_path = 'D:/githv/agomTradePro'

        for file_path in files_to_check:
            full_path = os.path.join(base_path, file_path)
            if not os.path.exists(full_path):
                continue

            with open(full_path, encoding='utf-8') as f:
                content = f.read()

                # 查找 TODO
                todos = re.findall(r'# TODO([^\n]*)', content)
                total_todos += len(todos)

                # 统计低优先级 TODO
                for todo in todos:
                    if '[低优先级]' in todo or '[未来优化]' in todo or '[可保留' in todo:
                        low_priority_todos += 1

        # 原始 TODO 数量约为 11 个
        # 至少需要消除 8 个（>= 70%）
        remaining_todos = total_todos

        # 验证：剩余的 TODO 应该 <= 3
        assert remaining_todos <= 3, f"剩余 {remaining_todos} 个 TODO，超过了 3 个的限制"

        # 验证：剩余的 TODO 应该是低优先级的
        assert remaining_todos == low_priority_todos, "剩余的 TODO 都应该是低优先级或未来优化"
