"""
策略执行引擎集成测试

测试覆盖：
- StrategyExecutor 完整执行流程
- 规则驱动策略端到端测试
- 上下文准备和错误处理
"""

import pytest

from apps.strategy.application.strategy_executor import StrategyExecutor
from apps.strategy.domain.entities import (
    ActionType,
    AIConfig,
    RiskControlParams,
    RuleCondition,
    RuleType,
    Strategy,
    StrategyConfig,
    StrategyType,
)

# ========================================================================
# Mock 提供者
# ========================================================================


class MockMacroProvider:
    """模拟宏观数据提供者"""

    def get_indicator(self, indicator_code: str):
        if indicator_code == "CN_PMI_MANUFACTURING":
            return 50.5
        return None

    def get_all_indicators(self):
        """获取所有宏观指标（用于上下文准备）"""
        return {"CN_PMI_MANUFACTURING": 50.5, "US_10Y_TREASURY_YIELD": 4.2, "CN_CPI_YOY": 2.1}


class MockRegimeProvider:
    """模拟 Regime 提供者"""

    def get_current_regime(self) -> dict:
        return {
            "dominant_regime": "HG",
            "confidence": 0.85,
            "growth_momentum_z": 1.5,
            "inflation_momentum_z": 1.2,
        }


class MockAssetPoolProvider:
    """模拟资产池提供者"""

    def get_investable_assets(self, min_score: float = 60.0, limit: int = 50):
        return [
            {
                "asset_code": "000001.SH",
                "asset_name": "上证指数",
                "total_score": 75,
                "regime_score": 80,
                "policy_score": 70,
            },
            {
                "asset_code": "510300.SH",
                "asset_name": "沪深300ETF",
                "total_score": 68,
                "regime_score": 72,
                "policy_score": 65,
            },
        ]


class MockSignalProvider:
    """模拟信号提供者"""

    def get_valid_signals(self):
        return [
            {
                "signal_id": 1,
                "asset_code": "000001.SH",
                "direction": "LONG",
                "logic_desc": "PMI 扩张，经济复苏",
                "target_regime": "HG",
            }
        ]


class MockPortfolioProvider:
    """模拟投资组合数据提供者"""

    def get_positions(self, portfolio_id: int):
        return []

    def get_cash(self, portfolio_id: int):
        return 100000.0


class MockStrategyRepository:
    """模拟策略仓储"""

    def __init__(self, strategy: Strategy = None):
        self._strategy = strategy

    def get_by_id(self, strategy_id: int):
        return self._strategy

    def save(self, strategy):
        return 1

    def get_by_user(self, user_id: int, is_active: bool = True):
        return []

    def get_active_strategies_for_portfolio(self, portfolio_id: int):
        return []

    def delete(self, strategy_id: int):
        return True


class MockExecutionLogRepository:
    """模拟执行日志仓储"""

    def __init__(self):
        self.saved_logs = []

    def save(self, result):
        self.saved_logs.append(result)
        return 1

    def get_by_strategy(self, strategy_id: int, limit: int = 100):
        return []

    def get_by_portfolio(self, portfolio_id: int, limit: int = 100):
        return []


# ========================================================================
# 策略执行引擎集成测试
# ========================================================================


class TestStrategyExecutor:
    """策略执行引擎集成测试"""

    @pytest.fixture
    def mock_providers(self):
        """创建 Mock 提供者"""
        return {
            "strategy_repository": MockStrategyRepository(),
            "execution_log_repository": MockExecutionLogRepository(),
            "macro_provider": MockMacroProvider(),
            "regime_provider": MockRegimeProvider(),
            "asset_pool_provider": MockAssetPoolProvider(),
            "signal_provider": MockSignalProvider(),
            "portfolio_provider": MockPortfolioProvider(),
        }

    @pytest.fixture
    def executor(self, mock_providers):
        """创建策略执行引擎"""
        return StrategyExecutor(**mock_providers)

    @pytest.fixture
    def rule_based_strategy(self):
        """创建规则驱动策略"""
        risk_params = RiskControlParams(max_position_pct=20.0, max_total_position_pct=95.0)
        config = StrategyConfig(
            strategy_type=StrategyType.RULE_BASED,
            risk_params=risk_params,
            description="测试规则策略",
        )

        rules = [
            RuleCondition(
                rule_id=1,
                strategy_id=1,
                rule_name="PMI 扩张",
                rule_type=RuleType.MACRO,
                condition_json={
                    "operator": ">",
                    "indicator": "CN_PMI_MANUFACTURING",
                    "threshold": 50,
                },
                action=ActionType.BUY,
                weight=0.5,
                target_assets=[],  # 空列表表示所有可投资产
                priority=10,
                is_enabled=True,
            ),
            RuleCondition(
                rule_id=2,
                strategy_id=1,
                rule_name="HG Regime",
                rule_type=RuleType.REGIME,
                condition_json={"operator": "==", "value": "HG"},
                action=ActionType.BUY,
                weight=0.3,
                target_assets=["000001.SH"],
                priority=5,
                is_enabled=True,
            ),
        ]

        return Strategy(
            strategy_id=1,
            name="测试规则策略",
            strategy_type=StrategyType.RULE_BASED,
            version=1,
            is_active=True,
            created_by_id=1,
            config=config,
            risk_params=risk_params,
            rule_conditions=rules,
        )

    def test_execute_rule_based_strategy_success(
        self, executor, mock_providers, rule_based_strategy
    ):
        """测试成功执行规则驱动策略"""
        # 设置策略仓储返回测试策略
        mock_providers["strategy_repository"]._strategy = rule_based_strategy

        # 执行策略
        result = executor.execute_strategy(strategy_id=1, portfolio_id=1)

        # 验证结果
        assert result.is_success is True
        assert result.strategy_id == 1
        assert result.portfolio_id == 1
        assert len(result.signals) > 0
        assert result.error_message == ""

        # 验证信号内容
        buy_signals = [s for s in result.signals if s.action == ActionType.BUY]
        assert len(buy_signals) > 0

        # 验证日志已保存
        assert len(mock_providers["execution_log_repository"].saved_logs) == 1

    def test_ai_strategy_blocks_before_portfolio_context_reads(self, executor, mock_providers):
        """Unwired Agent authority must fail before portfolio provider access."""

        risk_params = RiskControlParams()
        strategy_config = StrategyConfig(
            strategy_type=StrategyType.AI_DRIVEN,
            risk_params=risk_params,
        )
        ai_strategy = Strategy(
            strategy_id=1,
            name="AI authority guard",
            strategy_type=StrategyType.AI_DRIVEN,
            version=1,
            is_active=True,
            created_by_id=1,
            config=strategy_config,
            risk_params=risk_params,
            ai_config=AIConfig(prompt_template_id=1),
        )
        mock_providers["strategy_repository"]._strategy = ai_strategy
        mock_providers["portfolio_provider"].get_positions = lambda _portfolio_id: (
            _ for _ in ()
        ).throw(AssertionError("portfolio must not be read before authority"))

        result = executor.execute_strategy(strategy_id=1, portfolio_id=1)

        assert result.is_success is False
        assert "agent_authority_not_wired" in result.error_message

    def test_execute_with_disabled_rule(self, executor, mock_providers, rule_based_strategy):
        """测试禁用规则的策略执行"""
        # 禁用第一条规则
        rule_based_strategy.rule_conditions[0].is_enabled = False
        mock_providers["strategy_repository"]._strategy = rule_based_strategy

        result = executor.execute_strategy(strategy_id=1, portfolio_id=1)

        assert result.is_success is True
        # 只有第二条规则生效
        assert len(result.signals) > 0

    def test_execute_blocks_degraded_asset_pool_items(
        self, executor, mock_providers, rule_based_strategy
    ):
        """降级资产池数据不得驱动交易信号。"""

        class DegradedAssetPoolProvider:
            def get_investable_assets(self, min_score: float = 60.0, limit: int = 50):
                return [
                    {
                        "asset_code": "000001.SH",
                        "asset_name": "上证指数",
                        "total_score": 90,
                        "regime_score": 90,
                        "policy_score": 90,
                        "is_fallback": True,
                        "actionable": False,
                        "data_quality": {"status": "degraded"},
                    }
                ]

        mock_providers["strategy_repository"]._strategy = rule_based_strategy
        executor.asset_pool_provider = DegradedAssetPoolProvider()

        result = executor.execute_strategy(strategy_id=1, portfolio_id=1)

        assert result.is_success is True
        assert result.context["asset_pool"] == []
        assert result.signals == []

    def test_execute_with_no_matching_rules(self, executor, mock_providers):
        """测试没有规则匹配的策略执行"""
        # 创建不匹配的策略
        risk_params = RiskControlParams()
        config = StrategyConfig(strategy_type=StrategyType.RULE_BASED, risk_params=risk_params)

        rules = [
            RuleCondition(
                rule_id=1,
                strategy_id=1,
                rule_name="PMI 高位",
                rule_type=RuleType.MACRO,
                condition_json={
                    "operator": ">",
                    "indicator": "CN_PMI_MANUFACTURING",
                    "threshold": 60,  # 不满足
                },
                action=ActionType.BUY,
                is_enabled=True,
            )
        ]

        strategy = Strategy(
            strategy_id=1,
            name="不匹配策略",
            strategy_type=StrategyType.RULE_BASED,
            version=1,
            is_active=True,
            created_by_id=1,
            config=config,
            risk_params=risk_params,
            rule_conditions=rules,
        )

        mock_providers["strategy_repository"]._strategy = strategy

        result = executor.execute_strategy(strategy_id=1, portfolio_id=1)

        assert result.is_success is True
        assert len(result.signals) == 0  # 没有信号生成

    def test_execute_strategy_not_found(self, executor, mock_providers):
        """测试策略不存在的情况"""
        mock_providers["strategy_repository"]._strategy = None

        result = executor.execute_strategy(strategy_id=999, portfolio_id=1)

        assert result.is_success is False
        assert "not found" in result.error_message.lower()
        assert len(result.signals) == 0

    @pytest.mark.parametrize(
        ("strategy_id", "portfolio_id", "expected_field"),
        [
            (0, 1, "strategy_id"),
            (True, 1, "strategy_id"),
            (1, -1, "portfolio_id"),
            (1, False, "portfolio_id"),
        ],
    )
    def test_execute_rejects_invalid_identifiers(
        self,
        executor,
        strategy_id,
        portfolio_id,
        expected_field,
    ):
        """无效或 bool 主键不得进入策略仓储和数据提供者。"""
        result = executor.execute_strategy(
            strategy_id=strategy_id,
            portfolio_id=portfolio_id,
        )

        assert result.is_success is False
        assert result.signals == []
        assert expected_field in result.error_message

    def test_execute_fails_closed_when_required_context_is_unavailable(
        self,
        executor,
        mock_providers,
        rule_based_strategy,
    ):
        """必需上下文读取异常时，不得以空数据伪装成功。"""

        class UnavailableMacroProvider:
            def get_all_indicators(self):
                raise RuntimeError("upstream unavailable")

        mock_providers["strategy_repository"]._strategy = rule_based_strategy
        executor.macro_provider = UnavailableMacroProvider()

        result = executor.execute_strategy(strategy_id=1, portfolio_id=1)

        assert result.is_success is False
        assert result.signals == []
        assert "context unavailable: macro" in result.error_message
        assert mock_providers["execution_log_repository"].saved_logs == [result]

    def test_execute_fails_closed_on_invalid_portfolio_cash(
        self,
        executor,
        mock_providers,
        rule_based_strategy,
    ):
        """非有限现金余额不得进入策略执行上下文。"""

        class InvalidCashPortfolioProvider(MockPortfolioProvider):
            def get_cash(self, portfolio_id: int):
                return float("nan")

        mock_providers["strategy_repository"]._strategy = rule_based_strategy
        executor.portfolio_provider = InvalidCashPortfolioProvider()

        result = executor.execute_strategy(strategy_id=1, portfolio_id=1)

        assert result.is_success is False
        assert result.signals == []
        assert "context unavailable: portfolio" in result.error_message

    def test_execute_fails_closed_when_audit_log_cannot_be_saved(
        self,
        executor,
        mock_providers,
        rule_based_strategy,
    ):
        """未能持久化审计日志的执行结果不得被上层消费。"""

        class FailingExecutionLogRepository(MockExecutionLogRepository):
            def save(self, result):
                raise RuntimeError("database unavailable")

        mock_providers["strategy_repository"]._strategy = rule_based_strategy
        executor.execution_log_repository = FailingExecutionLogRepository()

        result = executor.execute_strategy(strategy_id=1, portfolio_id=1)

        assert result.is_success is False
        assert result.signals == []
        assert result.error_message == "Strategy execution log persistence failed"

    def test_execute_keeps_only_highest_priority_signal_per_asset(
        self,
        executor,
        mock_providers,
        rule_based_strategy,
    ):
        """同一资产命中多条规则时保留先执行的高优先级建议。"""
        mock_providers["strategy_repository"]._strategy = rule_based_strategy

        result = executor.execute_strategy(strategy_id=1, portfolio_id=1)

        assert result.is_success is True
        assert [signal.asset_code for signal in result.signals] == [
            "000001.SH",
            "510300.SH",
        ]
        assert result.signals[0].weight == 0.5

    def test_context_preparation(self, executor, mock_providers, rule_based_strategy):
        """测试上下文准备"""
        mock_providers["strategy_repository"]._strategy = rule_based_strategy

        result = executor.execute_strategy(strategy_id=1, portfolio_id=1)

        # 验证上下文包含必要数据
        context = result.context
        assert "macro" in context
        assert "regime" in context
        assert "asset_pool" in context
        assert "portfolio" in context
        assert "signals" in context

        # 验证 Regime 数据
        assert context["regime"]["dominant_regime"] == "HG"

        # 验证资产池
        assert len(context["asset_pool"]) > 0

        # 验证投资组合数据
        assert "positions" in context["portfolio"]
        assert "cash" in context["portfolio"]

    def test_composite_rule_execution(self, executor, mock_providers):
        """测试组合规则执行"""
        risk_params = RiskControlParams()
        config = StrategyConfig(strategy_type=StrategyType.RULE_BASED, risk_params=risk_params)

        # 创建组合规则（AND 条件）
        rules = [
            RuleCondition(
                rule_id=1,
                strategy_id=1,
                rule_name="组合条件",
                rule_type=RuleType.COMPOSITE,
                condition_json={
                    "operator": "AND",
                    "conditions": [
                        {
                            "type": "macro",
                            "operator": ">",
                            "indicator": "CN_PMI_MANUFACTURING",
                            "threshold": 50,
                        },
                        {"type": "regime", "operator": "==", "value": "HG"},
                    ],
                },
                action=ActionType.BUY,
                weight=0.4,
                is_enabled=True,
            )
        ]

        strategy = Strategy(
            strategy_id=1,
            name="组合规则策略",
            strategy_type=StrategyType.RULE_BASED,
            version=1,
            is_active=True,
            created_by_id=1,
            config=config,
            risk_params=risk_params,
            rule_conditions=rules,
        )

        mock_providers["strategy_repository"]._strategy = strategy

        result = executor.execute_strategy(strategy_id=1, portfolio_id=1)

        assert result.is_success is True
        assert len(result.signals) > 0

    def test_execution_duration_recorded(self, executor, mock_providers, rule_based_strategy):
        """测试执行时长记录"""
        mock_providers["strategy_repository"]._strategy = rule_based_strategy

        result = executor.execute_strategy(strategy_id=1, portfolio_id=1)

        assert result.execution_duration_ms >= 0
        assert isinstance(result.execution_duration_ms, int)

    def test_priority_ordering(self, executor, mock_providers):
        """测试规则按优先级排序执行"""
        risk_params = RiskControlParams()
        config = StrategyConfig(strategy_type=StrategyType.RULE_BASED, risk_params=risk_params)

        # 创建不同优先级的规则
        rules = [
            RuleCondition(
                rule_id=1,
                strategy_id=1,
                rule_name="低优先级",
                rule_type=RuleType.REGIME,
                condition_json={"operator": "==", "value": "HG"},
                action=ActionType.BUY,
                weight=0.1,
                priority=1,
                is_enabled=True,
            ),
            RuleCondition(
                rule_id=2,
                strategy_id=1,
                rule_name="高优先级",
                rule_type=RuleType.MACRO,
                condition_json={
                    "operator": ">",
                    "indicator": "CN_PMI_MANUFACTURING",
                    "threshold": 50,
                },
                action=ActionType.BUY,
                weight=0.5,
                priority=10,
                is_enabled=True,
            ),
        ]

        strategy = Strategy(
            strategy_id=1,
            name="优先级测试策略",
            strategy_type=StrategyType.RULE_BASED,
            version=1,
            is_active=True,
            created_by_id=1,
            config=config,
            risk_params=risk_params,
            rule_conditions=rules,
        )

        mock_providers["strategy_repository"]._strategy = strategy

        result = executor.execute_strategy(strategy_id=1, portfolio_id=1)

        # 两个规则都匹配，应该生成信号
        assert result.is_success is True
        assert len(result.signals) > 0

    def test_target_assets_filtering(self, executor, mock_providers):
        """测试目标资产过滤"""
        risk_params = RiskControlParams()
        config = StrategyConfig(strategy_type=StrategyType.RULE_BASED, risk_params=risk_params)

        # 规则指定目标资产
        rules = [
            RuleCondition(
                rule_id=1,
                strategy_id=1,
                rule_name="指定资产",
                rule_type=RuleType.MACRO,
                condition_json={
                    "operator": ">",
                    "indicator": "CN_PMI_MANUFACTURING",
                    "threshold": 50,
                },
                action=ActionType.BUY,
                target_assets=["000001.SH"],  # 只买上证指数
                is_enabled=True,
            )
        ]

        strategy = Strategy(
            strategy_id=1,
            name="目标资产过滤策略",
            strategy_type=StrategyType.RULE_BASED,
            version=1,
            is_active=True,
            created_by_id=1,
            config=config,
            risk_params=risk_params,
            rule_conditions=rules,
        )

        mock_providers["strategy_repository"]._strategy = strategy

        result = executor.execute_strategy(strategy_id=1, portfolio_id=1)

        assert result.is_success is True
        # 验证所有信号都是针对目标资产的
        for signal in result.signals:
            assert signal.asset_code == "000001.SH"
