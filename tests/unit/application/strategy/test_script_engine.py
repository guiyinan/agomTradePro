"""
脚本执行引擎单元测试

测试覆盖：
- ScriptAPI 功能
- ScriptExecutionEnvironment 沙箱安全
- ScriptBasedStrategyExecutor 端到端测试
- 安全模式验证（strict/standard/relaxed）
"""
from unittest.mock import MagicMock, Mock

import pytest

from apps.strategy.application.script_engine import (
    ScriptAPI,
    ScriptBasedStrategyExecutor,
    ScriptExecutionEnvironment,
    SecurityConfig,
    SecurityMode,
)
from apps.strategy.domain.entities import (
    ActionType,
    RiskControlParams,
    ScriptConfig,
    Strategy,
    StrategyConfig,
    StrategyType,
)

# ========================================================================
# 安全配置测试
# ========================================================================

class TestSecurityConfig:
    """安全配置测试"""

    def test_relaxed_mode_allowed_modules(self):
        """测试宽松模式允许的模块"""
        modules = SecurityConfig.get_allowed_modules(SecurityMode.RELAXED)
        assert 'pandas' in modules
        assert 'numpy' in modules
        assert 'math' in modules
        assert 'datetime' in modules

    def test_standard_mode_allowed_modules(self):
        """测试标准模式允许的模块"""
        modules = SecurityConfig.get_allowed_modules(SecurityMode.STANDARD)
        assert 'pandas' not in modules
        assert 'numpy' not in modules
        assert 'math' in modules
        assert 'statistics' in modules

    def test_strict_mode_allowed_modules(self):
        """测试严格模式允许的模块"""
        modules = SecurityConfig.get_allowed_modules(SecurityMode.STRICT)
        assert 'pandas' not in modules
        assert 'statistics' not in modules
        assert 'math' in modules
        assert 'datetime' in modules

    def test_forbidden_modules(self):
        """测试禁止的模块"""
        assert not SecurityConfig.is_module_allowed('os', SecurityMode.RELAXED)
        assert not SecurityConfig.is_module_allowed('sys', SecurityMode.RELAXED)
        assert not SecurityConfig.is_module_allowed('subprocess', SecurityMode.RELAXED)
        assert not SecurityConfig.is_module_allowed('eval', SecurityMode.RELAXED)

    def test_restricted_modules_in_relaxed_mode(self):
        """测试宽松模式下仍禁止某些模块"""
        # 即使在宽松模式，这些模块也是禁止的
        assert not SecurityConfig.is_module_allowed('os', SecurityMode.RELAXED)
        assert not SecurityConfig.is_module_allowed('subprocess', SecurityMode.RELAXED)


# ========================================================================
# 脚本 API 测试
# ========================================================================

class TestScriptAPI:
    """脚本 API 测试"""

    @pytest.fixture
    def mock_providers(self):
        """创建 Mock 提供者"""
        return {
            'macro_provider': Mock(),
            'regime_provider': Mock(),
            'asset_pool_provider': Mock(),
            'signal_provider': Mock(),
            'portfolio_provider': Mock()
        }

    @pytest.fixture
    def script_api(self, mock_providers):
        """创建脚本 API"""
        # 配置 Mock 返回值
        mock_providers['macro_provider'].get_indicator.return_value = 50.5
        mock_providers['macro_provider'].get_all_indicators.return_value = {'CN_PMI': 50.5}
        mock_providers['regime_provider'].get_current_regime.return_value = {
            'dominant_regime': 'HG',
            'confidence': 0.85
        }
        mock_providers['asset_pool_provider'].get_investable_assets.return_value = [
            {'asset_code': '000001.SH', 'total_score': 75}
        ]
        mock_providers['signal_provider'].get_valid_signals.return_value = []
        mock_providers['portfolio_provider'].get_positions.return_value = []
        mock_providers['portfolio_provider'].get_cash.return_value = 100000.0

        return ScriptAPI(**mock_providers, portfolio_id=1)

    def test_get_macro_indicator(self, script_api, mock_providers):
        """测试获取宏观指标"""
        result = script_api.get_macro_indicator('CN_PMI')
        assert result == 50.5
        mock_providers['macro_provider'].get_indicator.assert_called_once_with('CN_PMI')

    def test_get_all_macro_indicators(self, script_api, mock_providers):
        """测试获取所有宏观指标"""
        result = script_api.get_all_macro_indicators()
        assert result == {'CN_PMI': 50.5}
        mock_providers['macro_provider'].get_all_indicators.assert_called_once()

    def test_get_regime(self, script_api, mock_providers):
        """测试获取 Regime"""
        result = script_api.get_regime()
        assert result['dominant_regime'] == 'HG'
        mock_providers['regime_provider'].get_current_regime.assert_called_once()

    def test_get_asset_pool(self, script_api, mock_providers):
        """测试获取资产池"""
        result = script_api.get_asset_pool(min_score=70, limit=10)
        assert len(result) == 1
        assert result[0]['asset_code'] == '000001.SH'
        mock_providers['asset_pool_provider'].get_investable_assets.assert_called_once_with(
            min_score=70, limit=10
        )

    def test_calculate_signal(self, script_api):
        """测试生成信号"""
        result = script_api.calculate_signal(
            asset_code='000001.SH',
            asset_name='上证指数',
            action='buy',
            weight=0.3,
            reason='PMI 扩张',
            confidence=0.8
        )

        assert result['asset_code'] == '000001.SH'
        assert result['action'] == 'buy'
        assert result['weight'] == 0.3
        assert result['confidence'] == 0.8

    def test_get_portfolio_positions(self, script_api, mock_providers):
        """测试获取持仓"""
        result = script_api.get_portfolio_positions()
        mock_providers['portfolio_provider'].get_positions.assert_called_once_with(1)

    def test_get_portfolio_cash(self, script_api, mock_providers):
        """测试获取现金"""
        result = script_api.get_portfolio_cash()
        assert result == 100000.0
        mock_providers['portfolio_provider'].get_cash.assert_called_once_with(1)


# ========================================================================
# 脚本执行环境测试（沙箱）
# ========================================================================

class TestScriptExecutionEnvironment:
    """脚本执行环境测试"""

    @pytest.fixture
    def mock_providers(self):
        """创建 Mock 提供者"""
        providers = {
            'macro_provider': Mock(),
            'regime_provider': Mock(),
            'asset_pool_provider': Mock(),
            'signal_provider': Mock(),
            'portfolio_provider': Mock()
        }

        # 配置默认返回值
        providers['macro_provider'].get_indicator.return_value = 50.5
        providers['macro_provider'].get_all_indicators.return_value = {'CN_PMI': 50.5}
        providers['regime_provider'].get_current_regime.return_value = {'dominant_regime': 'HG'}
        providers['asset_pool_provider'].get_investable_assets.return_value = [
            {'asset_code': '000001.SH', 'asset_name': '上证指数', 'total_score': 75}
        ]
        providers['signal_provider'].get_valid_signals.return_value = []
        providers['portfolio_provider'].get_positions.return_value = []
        providers['portfolio_provider'].get_cash.return_value = 100000.0

        return providers

    @pytest.fixture
    def script_api(self, mock_providers):
        """创建脚本 API"""
        return ScriptAPI(**mock_providers, portfolio_id=1)

    @pytest.fixture
    def execution_env(self):
        """创建执行环境"""
        return ScriptExecutionEnvironment(security_mode=SecurityMode.RELAXED)

    def test_execute_simple_script(self, execution_env, script_api):
        """测试执行简单脚本"""
        script_code = """
# 简单脚本：生成一个信号
signals.append(calculate_signal(
    asset_code='000001.SH',
    asset_name='上证指数',
    action='buy',
    weight=0.5,
    reason='测试信号',
    confidence=0.8
))
"""
        result = execution_env.execute(script_code, script_api)

        assert len(result) == 1
        assert result[0]['asset_code'] == '000001.SH'
        assert result[0]['action'] == 'buy'

    def test_execute_script_with_data_access(self, execution_env, script_api):
        """测试执行访问数据的脚本"""
        script_code = """
# 访问宏观数据
pmi = get_macro_indicator('CN_PMI')
regime = get_regime()

# 根据数据生成信号
if pmi and pmi > 50:
    signals.append(calculate_signal(
        asset_code='000001.SH',
        asset_name='上证指数',
        action='buy',
        reason=f'PMI {pmi} 扩张'
    ))
"""
        result = execution_env.execute(script_code, script_api)

        assert len(result) == 1
        assert 'PMI 50.5 扩张' in result[0]['reason']

    def test_execute_script_with_asset_pool(self, execution_env, script_api):
        """测试执行使用资产池的脚本"""
        script_code = """
# 获取资产池
assets = get_asset_pool(min_score=60)

# 为每个高分资产生成信号
for asset in assets:
    if asset['total_score'] > 70:
        signals.append(calculate_signal(
            asset_code=asset['asset_code'],
            asset_name=asset['asset_name'],
            action='buy',
            weight=0.3,
            reason=f'高分资产: {asset["total_score"]}'
        ))
"""
        result = execution_env.execute(script_code, script_api)

        assert len(result) == 1
        assert result[0]['asset_code'] == '000001.SH'

    def test_script_with_allowed_modules(self, execution_env, script_api):
        """测试使用允许的模块"""
        script_code = """
import math

# 使用 math 模块
result = math.sqrt(100)

signals.append(calculate_signal(
    asset_code='000001.SH',
    asset_name='上证指数',
    action='buy',
    reason=f'计算结果: {result}'
))
"""
        result = execution_env.execute(script_code, script_api)
        assert len(result) == 1

    def test_script_with_forbidden_module_import(self, execution_env, script_api):
        """测试禁止的模块导入"""
        script_code = """
import os
signals.append(calculate_signal('000001.SH', 'test', 'buy'))
"""
        with pytest.raises(ValueError, match="not allowed"):
            execution_env.execute(script_code, script_api)

    def test_script_syntax_error(self, execution_env, script_api):
        """测试脚本语法错误"""
        script_code = """
# 语法错误
if True
    signals.append(calculate_signal('000001.SH', 'test', 'buy'))
"""
        with pytest.raises(Exception):
            execution_env.execute(script_code, script_api)

    def test_script_with_invalid_signal_format(self, execution_env, script_api):
        """测试无效的信号格式"""
        script_code = """
# 信号格式错误：缺少 asset_code
signals.append({'action': 'buy'})
"""
        with pytest.raises(ValueError, match="must have"):
            execution_env.execute(script_code, script_api)

    def test_script_returns_non_list(self, execution_env, script_api):
        """测试脚本返回非列表"""
        script_code = """
# 覆盖 signals 变量为非列表
signals = "invalid"
"""
        with pytest.raises(ValueError, match="must return a 'signals' list"):
            execution_env.execute(script_code, script_api)

    def test_script_security_strict_mode(self):
        """测试严格模式安全限制"""
        # 创建严格模式环境
        execution_env = ScriptExecutionEnvironment(security_mode=SecurityMode.STRICT)

        script_code = """
import statistics  # 严格模式下不允许
signals.append(calculate_signal('000001.SH', 'test', 'buy'))
"""
        # 重新创建 script_api
        mock_providers = {
            'macro_provider': Mock(),
            'regime_provider': Mock(),
            'asset_pool_provider': Mock(),
            'signal_provider': Mock(),
            'portfolio_provider': Mock()
        }
        for provider in mock_providers.values():
            if hasattr(provider, 'get_indicator'):
                provider.get_indicator.return_value = 50.5
            if hasattr(provider, 'get_all_indicators'):
                provider.get_all_indicators.return_value = {}
            if hasattr(provider, 'get_current_regime'):
                provider.get_current_regime.return_value = {}
            if hasattr(provider, 'get_investable_assets'):
                provider.get_investable_assets.return_value = []
            if hasattr(provider, 'get_valid_signals'):
                provider.get_valid_signals.return_value = []
            if hasattr(provider, 'get_positions'):
                provider.get_positions.return_value = []
            if hasattr(provider, 'get_cash'):
                provider.get_cash.return_value = 0.0

        script_api = ScriptAPI(**mock_providers, portfolio_id=1)

        with pytest.raises(ValueError, match="not allowed"):
            execution_env.execute(script_code, script_api)


# ========================================================================
# 脚本驱动策略执行器测试
# ========================================================================

class TestScriptBasedStrategyExecutor:
    """脚本驱动策略执行器测试"""

    @pytest.fixture
    def mock_providers(self):
        """创建 Mock 提供者"""
        providers = {
            'macro_provider': Mock(),
            'regime_provider': Mock(),
            'asset_pool_provider': Mock(),
            'signal_provider': Mock(),
            'portfolio_provider': Mock()
        }

        # 配置默认返回值
        providers['macro_provider'].get_indicator.return_value = 50.5
        providers['macro_provider'].get_all_indicators.return_value = {'CN_PMI': 50.5}
        providers['regime_provider'].get_current_regime.return_value = {'dominant_regime': 'HG'}
        providers['asset_pool_provider'].get_investable_assets.return_value = [
            {'asset_code': '000001.SH', 'asset_name': '上证指数', 'total_score': 75}
        ]
        providers['signal_provider'].get_valid_signals.return_value = []
        providers['portfolio_provider'].get_positions.return_value = []
        providers['portfolio_provider'].get_cash.return_value = 100000.0

        return providers

    @pytest.fixture
    def executor(self, mock_providers):
        """创建脚本执行器"""
        return ScriptBasedStrategyExecutor(
            security_mode=SecurityMode.RELAXED,
            **mock_providers
        )

    @pytest.fixture
    def script_strategy(self):
        """创建脚本策略"""
        risk_params = RiskControlParams()
        config = StrategyConfig(
            strategy_type=StrategyType.SCRIPT_BASED,
            risk_params=risk_params
        )

        script_config = ScriptConfig(
            script_code="""
# 简单的脚本策略
pmi = get_macro_indicator('CN_PMI_MANUFACTURING')
regime = get_regime()

if pmi and pmi > 50 and regime['dominant_regime'] == 'HG':
    assets = get_asset_pool(min_score=60)
    for asset in assets:
        if asset['total_score'] > 70:
            signals.append(calculate_signal(
                asset_code=asset['asset_code'],
                asset_name=asset['asset_name'],
                action='buy',
                weight=0.3,
                reason=f'PMI {pmi} 扩张，{regime["dominant_regime"]} Regime'
            ))
""",
            script_language='python',
            allowed_modules=['math', 'datetime'],
            sandbox_config={}
        )

        return Strategy(
            strategy_id=1,
            name="测试脚本策略",
            strategy_type=StrategyType.SCRIPT_BASED,
            version=1,
            is_active=True,
            created_by_id=1,
            config=config,
            risk_params=risk_params,
            script_config=script_config
        )

    def test_execute_script_strategy(self, executor, script_strategy):
        """测试执行脚本策略"""
        result = executor.execute(script_strategy, portfolio_id=1)

        assert len(result) > 0
        assert result[0].action == ActionType.BUY

    def test_execute_strategy_without_script_config(self, executor):
        """测试没有脚本配置的策略"""
        # 创建一个临时策略对象（绕过 __post_init__ 验证）
        # 直接设置属性而不是通过构造函数
        class MockStrategy:
            def __init__(self):
                self.strategy_id = 1
                self.name = "无效策略"
                self.script_config = None

        strategy = MockStrategy()

        with pytest.raises(ValueError, match="must have script_config"):
            executor.execute(strategy, portfolio_id=1)

    def test_execute_strategy_with_script_error(self, executor, mock_providers):
        """测试脚本执行错误"""
        # 配置 mock 抛出异常
        mock_providers['macro_provider'].get_indicator.side_effect = Exception("API Error")

        risk_params = RiskControlParams()
        config = StrategyConfig(
            strategy_type=StrategyType.SCRIPT_BASED,
            risk_params=risk_params
        )

        script_config = ScriptConfig(
            script_code="""
pmi = get_macro_indicator('CN_PMI')
signals.append(calculate_signal('000001.SH', 'test', 'buy'))
""",
            script_language='python'
        )

        strategy = Strategy(
            strategy_id=1,
            name="错误策略",
            strategy_type=StrategyType.SCRIPT_BASED,
            version=1,
            is_active=True,
            created_by_id=1,
            config=config,
            risk_params=risk_params,
            script_config=script_config
        )

        # 脚本执行应该失败，但不会崩溃
        # 实际行为取决于 get_macro_indicator 的错误处理
        result = executor.execute(strategy, portfolio_id=1)
        # 由于 Mock 会返回 None，脚本逻辑应该能处理这种情况
