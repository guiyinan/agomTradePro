"""
Domain 层实体单元测试

测试覆盖：
- 值对象验证（RiskControlParams, StrategyConfig, ScriptConfig, AIConfig）
- 实体验证（Strategy, RuleCondition, SignalRecommendation）
- 枚举类型
- 边界条件测试
"""
import pytest
from datetime import datetime

from apps.strategy.domain.entities import (
    StrategyType,
    ActionType,
    RuleType,
    ApprovalMode,
    RiskControlParams,
    StrategyConfig,
    ScriptConfig,
    AIConfig,
    Strategy,
    RuleCondition,
    SignalRecommendation,
    StrategyExecutionResult
)


# ========================================================================
# 值对象测试
# ========================================================================

class TestRiskControlParams:
    """风控参数值对象测试"""

    def test_default_values(self):
        """测试默认值"""
        params = RiskControlParams()
        assert params.max_position_pct == 20.0
        assert params.max_total_position_pct == 95.0
        assert params.stop_loss_pct is None

    def test_valid_values(self):
        """测试有效值"""
        params = RiskControlParams(
            max_position_pct=30.0,
            max_total_position_pct=90.0,
            stop_loss_pct=10.0
        )
        assert params.max_position_pct == 30.0
        assert params.max_total_position_pct == 90.0
        assert params.stop_loss_pct == 10.0

    def test_invalid_max_position_pct(self):
        """测试无效的单资产最大持仓比例"""
        with pytest.raises(ValueError, match="max_position_pct 必须在 0-100 之间"):
            RiskControlParams(max_position_pct=-1.0)

        with pytest.raises(ValueError, match="max_position_pct 必须在 0-100 之间"):
            RiskControlParams(max_position_pct=101.0)

    def test_invalid_max_total_position_pct(self):
        """测试无效的总持仓比例上限"""
        with pytest.raises(ValueError, match="max_total_position_pct 必须在 0-100 之间"):
            RiskControlParams(max_total_position_pct=-1.0)

        with pytest.raises(ValueError, match="max_total_position_pct 必须在 0-100 之间"):
            RiskControlParams(max_total_position_pct=101.0)

    def test_invalid_stop_loss_pct(self):
        """测试无效的止损比例"""
        with pytest.raises(ValueError, match="stop_loss_pct 必须在 0-100 之间"):
            RiskControlParams(stop_loss_pct=-1.0)

        with pytest.raises(ValueError, match="stop_loss_pct 必须在 0-100 之间"):
            RiskControlParams(stop_loss_pct=101.0)

    def test_immutability(self):
        """测试不可变性"""
        params = RiskControlParams()
        with pytest.raises(Exception):  # FrozenInstanceError
            params.max_position_pct = 30.0


class TestStrategyConfig:
    """策略配置值对象测试"""

    def test_valid_config(self):
        """测试有效配置"""
        risk_params = RiskControlParams()
        config = StrategyConfig(
            strategy_type=StrategyType.RULE_BASED,
            risk_params=risk_params,
            description="测试策略"
        )
        assert config.strategy_type == StrategyType.RULE_BASED
        assert config.risk_params == risk_params
        assert config.description == "测试策略"

    def test_immutability(self):
        """测试不可变性"""
        risk_params = RiskControlParams()
        config = StrategyConfig(
            strategy_type=StrategyType.RULE_BASED,
            risk_params=risk_params
        )
        with pytest.raises(Exception):  # FrozenInstanceError
            config.description = "修改后的描述"


class TestScriptConfig:
    """脚本配置值对象测试"""

    def test_valid_python_script(self):
        """测试有效的 Python 脚本配置"""
        config = ScriptConfig(
            script_code="print('hello')",
            script_language="python",
            allowed_modules=['math', 'datetime']
        )
        assert config.script_code == "print('hello')"
        assert config.script_language == "python"
        assert config.allowed_modules == ['math', 'datetime']

    def test_invalid_script_language(self):
        """测试无效的脚本语言"""
        with pytest.raises(ValueError, match="不支持的脚本语言"):
            ScriptConfig(
                script_code="code",
                script_language="javascript"
            )


class TestAIConfig:
    """AI 配置值对象测试"""

    def test_default_values(self):
        """测试默认值"""
        config = AIConfig()
        assert config.approval_mode == ApprovalMode.CONDITIONAL
        assert config.confidence_threshold == 0.8
        assert config.temperature == 0.7
        assert config.max_tokens == 2000

    def test_valid_config(self):
        """测试有效配置"""
        config = AIConfig(
            approval_mode=ApprovalMode.AUTO,
            confidence_threshold=0.9,
            temperature=0.5,
            max_tokens=4000
        )
        assert config.approval_mode == ApprovalMode.AUTO
        assert config.confidence_threshold == 0.9
        assert config.temperature == 0.5
        assert config.max_tokens == 4000

    def test_invalid_confidence_threshold(self):
        """测试无效的置信度阈值"""
        with pytest.raises(ValueError, match="confidence_threshold 必须在 0-1 之间"):
            AIConfig(confidence_threshold=-0.1)

        with pytest.raises(ValueError, match="confidence_threshold 必须在 0-1 之间"):
            AIConfig(confidence_threshold=1.1)

    def test_invalid_temperature(self):
        """测试无效的温度参数"""
        with pytest.raises(ValueError, match="temperature 必须在 0-2 之间"):
            AIConfig(temperature=-0.1)

        with pytest.raises(ValueError, match="temperature 必须在 0-2 之间"):
            AIConfig(temperature=2.1)

    def test_invalid_max_tokens(self):
        """测试无效的最大 token 数"""
        with pytest.raises(ValueError, match="max_tokens 必须大于 0"):
            AIConfig(max_tokens=0)


# ========================================================================
# 实体测试
# ========================================================================

class TestRuleCondition:
    """规则条件实体测试"""

    def test_valid_condition(self):
        """测试有效的规则条件"""
        condition = RuleCondition(
            rule_id=1,
            strategy_id=1,
            rule_name="PMI复苏买入规则",
            rule_type=RuleType.MACRO,
            condition_json={
                "operator": ">",
                "indicator": "CN_PMI_MANUFACTURING",
                "threshold": 50
            },
            action=ActionType.BUY,
            weight=0.3,
            target_assets=["000001.SH"],
            priority=100
        )
        assert condition.rule_id == 1
        assert condition.rule_name == "PMI复苏买入规则"
        assert condition.rule_type == RuleType.MACRO
        assert condition.action == ActionType.BUY
        assert condition.weight == 0.3

    def test_invalid_weight(self):
        """测试无效的权重"""
        with pytest.raises(ValueError, match="weight 必须在 0-1 之间"):
            RuleCondition(
                rule_id=1,
                strategy_id=1,
                rule_name="测试规则",
                rule_type=RuleType.MACRO,
                condition_json={"operator": ">", "threshold": 50},
                action=ActionType.BUY,
                weight=-0.1
            )

        with pytest.raises(ValueError, match="weight 必须在 0-1 之间"):
            RuleCondition(
                rule_id=1,
                strategy_id=1,
                rule_name="测试规则",
                rule_type=RuleType.MACRO,
                condition_json={"operator": ">", "threshold": 50},
                action=ActionType.BUY,
                weight=1.1
            )

    def test_missing_operator_in_condition_json(self):
        """测试缺少 operator 的 condition_json"""
        with pytest.raises(ValueError, match="condition_json 必须包含 'operator' 字段"):
            RuleCondition(
                rule_id=1,
                strategy_id=1,
                rule_name="测试规则",
                rule_type=RuleType.MACRO,
                condition_json={"threshold": 50},  # 缺少 operator
                action=ActionType.BUY
            )

    def test_invalid_condition_json_type(self):
        """测试无效的 condition_json 类型"""
        with pytest.raises(ValueError, match="condition_json 必须是字典类型"):
            RuleCondition(
                rule_id=1,
                strategy_id=1,
                rule_name="测试规则",
                rule_type=RuleType.MACRO,
                condition_json=["invalid", "type"],  # 列表而非字典
                action=ActionType.BUY
            )


class TestSignalRecommendation:
    """信号推荐实体测试"""

    def test_valid_signal(self):
        """测试有效的信号推荐"""
        signal = SignalRecommendation(
            asset_code="000001.SH",
            asset_name="平安银行",
            action=ActionType.BUY,
            weight=0.3,
            reason="PMI 超预期，经济复苏",
            confidence=0.8
        )
        assert signal.asset_code == "000001.SH"
        assert signal.asset_name == "平安银行"
        assert signal.action == ActionType.BUY
        assert signal.weight == 0.3
        assert signal.confidence == 0.8

    def test_invalid_weight(self):
        """测试无效的权重"""
        with pytest.raises(ValueError, match="weight 必须在 0-1 之间"):
            SignalRecommendation(
                asset_code="000001.SH",
                asset_name="平安银行",
                action=ActionType.BUY,
                weight=-0.1
            )

    def test_invalid_confidence(self):
        """测试无效的置信度"""
        with pytest.raises(ValueError, match="confidence 必须在 0-1 之间"):
            SignalRecommendation(
                asset_code="000001.SH",
                asset_name="平安银行",
                action=ActionType.BUY,
                confidence=-0.1
            )

        with pytest.raises(ValueError, match="confidence 必须在 0-1 之间"):
            SignalRecommendation(
                asset_code="000001.SH",
                asset_name="平安银行",
                action=ActionType.BUY,
                confidence=1.1
            )


class TestStrategy:
    """策略实体测试"""

    def test_rule_based_strategy(self):
        """测试规则驱动策略"""
        risk_params = RiskControlParams()
        config = StrategyConfig(
            strategy_type=StrategyType.RULE_BASED,
            risk_params=risk_params
        )
        rule = RuleCondition(
            rule_id=1,
            strategy_id=1,
            rule_name="测试规则",
            rule_type=RuleType.MACRO,
            condition_json={"operator": ">", "threshold": 50},
            action=ActionType.BUY
        )

        strategy = Strategy(
            strategy_id=1,
            name="PMI复苏策略",
            strategy_type=StrategyType.RULE_BASED,
            version=1,
            is_active=True,
            created_by_id=1,
            config=config,
            risk_params=risk_params,
            rule_conditions=[rule]
        )
        assert strategy.strategy_type == StrategyType.RULE_BASED
        assert len(strategy.rule_conditions) == 1

    def test_rule_based_strategy_without_rules(self):
        """测试没有规则的规则驱动策略（应该失败）"""
        risk_params = RiskControlParams()
        config = StrategyConfig(
            strategy_type=StrategyType.RULE_BASED,
            risk_params=risk_params
        )

        with pytest.raises(ValueError, match="规则驱动策略必须包含至少一个规则条件"):
            Strategy(
                strategy_id=1,
                name="PMI复苏策略",
                strategy_type=StrategyType.RULE_BASED,
                version=1,
                is_active=True,
                created_by_id=1,
                config=config,
                risk_params=risk_params,
                rule_conditions=[]  # 空列表
            )

    def test_script_based_strategy(self):
        """测试脚本驱动策略"""
        risk_params = RiskControlParams()
        config = StrategyConfig(
            strategy_type=StrategyType.SCRIPT_BASED,
            risk_params=risk_params
        )
        script_config = ScriptConfig(
            script_code="print('hello')"
        )

        strategy = Strategy(
            strategy_id=1,
            name="自定义脚本策略",
            strategy_type=StrategyType.SCRIPT_BASED,
            version=1,
            is_active=True,
            created_by_id=1,
            config=config,
            risk_params=risk_params,
            script_config=script_config
        )
        assert strategy.strategy_type == StrategyType.SCRIPT_BASED
        assert strategy.script_config is not None

    def test_script_based_strategy_without_script_config(self):
        """测试没有脚本配置的脚本驱动策略（应该失败）"""
        risk_params = RiskControlParams()
        config = StrategyConfig(
            strategy_type=StrategyType.SCRIPT_BASED,
            risk_params=risk_params
        )

        with pytest.raises(ValueError, match="脚本驱动策略必须包含脚本配置"):
            Strategy(
                strategy_id=1,
                name="自定义脚本策略",
                strategy_type=StrategyType.SCRIPT_BASED,
                version=1,
                is_active=True,
                created_by_id=1,
                config=config,
                risk_params=risk_params,
                script_config=None
            )

    def test_ai_driven_strategy(self):
        """测试 AI 驱动策略"""
        risk_params = RiskControlParams()
        config = StrategyConfig(
            strategy_type=StrategyType.AI_DRIVEN,
            risk_params=risk_params
        )
        ai_config = AIConfig()

        strategy = Strategy(
            strategy_id=1,
            name="AI投资策略",
            strategy_type=StrategyType.AI_DRIVEN,
            version=1,
            is_active=True,
            created_by_id=1,
            config=config,
            risk_params=risk_params,
            ai_config=ai_config
        )
        assert strategy.strategy_type == StrategyType.AI_DRIVEN
        assert strategy.ai_config is not None

    def test_ai_driven_strategy_without_ai_config(self):
        """测试没有 AI 配置的 AI 驱动策略（应该失败）"""
        risk_params = RiskControlParams()
        config = StrategyConfig(
            strategy_type=StrategyType.AI_DRIVEN,
            risk_params=risk_params
        )

        with pytest.raises(ValueError, match="AI驱动策略必须包含AI配置"):
            Strategy(
                strategy_id=1,
                name="AI投资策略",
                strategy_type=StrategyType.AI_DRIVEN,
                version=1,
                is_active=True,
                created_by_id=1,
                config=config,
                risk_params=risk_params,
                ai_config=None
            )


class TestStrategyExecutionResult:
    """策略执行结果实体测试"""

    def test_successful_execution(self):
        """测试成功的执行"""
        signal = SignalRecommendation(
            asset_code="000001.SH",
            asset_name="平安银行",
            action=ActionType.BUY,
            weight=0.3,
            confidence=0.8
        )

        result = StrategyExecutionResult(
            strategy_id=1,
            portfolio_id=1,
            execution_time=datetime.now(),
            execution_duration_ms=100,
            signals=[signal],
            is_success=True
        )
        assert result.is_success is True
        assert len(result.signals) == 1
        assert result.execution_duration_ms == 100

    def test_failed_execution(self):
        """测试失败的执行"""
        result = StrategyExecutionResult(
            strategy_id=1,
            portfolio_id=1,
            execution_time=datetime.now(),
            execution_duration_ms=50,
            signals=[],
            is_success=False,
            error_message="执行失败：找不到宏观数据"
        )
        assert result.is_success is False
        assert len(result.signals) == 0
        assert result.error_message == "执行失败：找不到宏观数据"

    def test_to_dict(self):
        """测试转换为字典"""
        signal = SignalRecommendation(
            asset_code="000001.SH",
            asset_name="平安银行",
            action=ActionType.BUY,
            weight=0.3,
            confidence=0.8
        )

        result = StrategyExecutionResult(
            strategy_id=1,
            portfolio_id=1,
            execution_time=datetime.now(),
            execution_duration_ms=100,
            signals=[signal],
            is_success=True
        )

        result_dict = result.to_dict()
        assert result_dict['strategy_id'] == 1
        assert result_dict['portfolio_id'] == 1
        assert len(result_dict['signals']) == 1
        assert result_dict['is_success'] is True
        assert result_dict['execution_duration_ms'] == 100
