"""
AI 策略执行器单元测试

测试覆盖：
- AIResponseParser 响应解析
- AIStrategyExecutor 执行流程
- 审核模式过滤
- 待审核信号队列管理
"""
import pytest
from unittest.mock import Mock, MagicMock, patch

from apps.strategy.application.ai_strategy_executor import (
    AIStrategyExecutor,
    AIResponseParser,
    AIClientFactory,
    PendingApprovalQueue
)
from apps.strategy.domain.entities import (
    Strategy,
    StrategyType,
    ActionType,
    RiskControlParams,
    StrategyConfig,
    AIConfig
)


# ========================================================================
# AI 响应解析器测试
# ========================================================================

class TestAIResponseParser:
    """AI 响应解析器测试"""

    def test_parse_json_array_format(self):
        """测试解析 JSON 数组格式"""
        content = '''[
            {"asset_code": "000001.SH", "action": "buy", "weight": 0.3, "reason": "PMI 扩张", "confidence": 0.8},
            {"asset_code": "510300.SH", "action": "sell", "weight": 0.5, "reason": "风险控制", "confidence": 0.9}
        ]'''

        signals = AIResponseParser.parse_signals(content)

        assert len(signals) == 2
        assert signals[0].asset_code == "000001.SH"
        assert signals[0].action == ActionType.BUY
        assert signals[0].weight == 0.3
        assert signals[0].confidence == 0.8

        assert signals[1].action == ActionType.SELL

    def test_parse_json_object_with_signals_field(self):
        """测试解析包含 signals 字段的 JSON 对象"""
        content = '''{
            "reason": "市场分析",
            "signals": [
                {"asset_code": "000001.SH", "action": "buy", "weight": 0.3}
            ]
        }'''

        signals = AIResponseParser.parse_signals(content)

        assert len(signals) == 1
        assert signals[0].asset_code == "000001.SH"

    def test_parse_single_signal_object(self):
        """测试解析单个信号对象"""
        content = '''{"asset_code": "000001.SH", "action": "buy", "weight": 0.3}'''

        signals = AIResponseParser.parse_signals(content)

        assert len(signals) == 1
        assert signals[0].asset_code == "000001.SH"

    def test_parse_text_csv_format(self):
        """测试解析纯文本 CSV 格式"""
        content = '''
000001.SH,buy,0.3,PMI 扩张
510300.SH,sell,0.5,风险控制
'''

        signals = AIResponseParser.parse_signals(content, default_confidence=0.7)

        assert len(signals) == 2
        assert signals[0].asset_code == "000001.SH"
        assert signals[0].action == ActionType.BUY
        assert signals[0].confidence == 0.7

    def test_parse_with_invalid_action(self):
        """测试无效的 action 类型"""
        content = '''[{"asset_code": "000001.SH", "action": "invalid", "weight": 0.3}]'''

        signals = AIResponseParser.parse_signals(content)

        # 无效 action 应该默认为 HOLD
        assert len(signals) == 1
        assert signals[0].action == ActionType.HOLD

    def test_parse_with_missing_asset_code(self):
        """测试缺少 asset_code"""
        content = '''[{"action": "buy", "weight": 0.3}]'''

        signals = AIResponseParser.parse_signals(content)

        # 缺少 asset_code 的信号应该被跳过
        assert len(signals) == 0

    def test_parse_with_invalid_weight(self):
        """测试无效的 weight"""
        content = '''[{"asset_code": "000001.SH", "action": "buy", "weight": 2.5}]'''

        signals = AIResponseParser.parse_signals(content)

        # 超出范围 [0,1] 的 weight 应该被设为 None
        assert len(signals) == 1
        assert signals[0].weight is None

    def test_parse_with_invalid_confidence(self):
        """测试无效的 confidence"""
        content = '''[{"asset_code": "000001.SH", "action": "buy", "confidence": "invalid"}]'''

        signals = AIResponseParser.parse_signals(content, default_confidence=0.6)

        # 无效 confidence 应该使用默认值
        assert len(signals) == 1
        assert signals[0].confidence == 0.6


# ========================================================================
# AI 策略执行器测试
# ========================================================================

class TestAIStrategyExecutor:
    """AI 策略执行器测试"""

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
    def executor(self, mock_providers):
        """创建 AI 策略执行器"""
        return AIStrategyExecutor(**mock_providers)

    @pytest.fixture
    def ai_strategy(self):
        """创建 AI 策略"""
        risk_params = RiskControlParams()
        config = StrategyConfig(
            strategy_type=StrategyType.AI_DRIVEN,
            risk_params=risk_params
        )

        ai_config = AIConfig(
            prompt_template_id=1,
            chain_config_id=None,
            ai_provider_id=1,
            temperature=0.7,
            max_tokens=2000,
            approval_mode='conditional',
            confidence_threshold=0.8
        )

        return Strategy(
            strategy_id=1,
            name="AI 测试策略",
            strategy_type=StrategyType.AI_DRIVEN,
            version=1,
            is_active=True,
            created_by_id=1,
            config=config,
            risk_params=risk_params,
            ai_config=ai_config
        )

    def test_execute_without_ai_config(self, executor):
        """测试没有 AI 配置的策略"""
        # 创建一个 Mock 策略对象（绕过 __post_init__ 验证）
        class MockStrategy:
            def __init__(self):
                self.strategy_id = 1
                self.name = "无效策略"
                self.ai_config = None

        strategy = MockStrategy()

        with pytest.raises(ValueError, match="must have ai_config"):
            executor.execute(strategy, portfolio_id=1)

    def test_apply_approval_mode_auto(self, executor):
        """测试自动审核模式"""
        risk_params = RiskControlParams()
        config = StrategyConfig(
            strategy_type=StrategyType.AI_DRIVEN,
            risk_params=risk_params
        )

        ai_config = AIConfig(
            prompt_template_id=1,
            approval_mode='auto',
            confidence_threshold=0.8
        )

        strategy = Strategy(
            strategy_id=1,
            name="AI 策略",
            strategy_type=StrategyType.AI_DRIVEN,
            version=1,
            is_active=True,
            created_by_id=1,
            config=config,
            risk_params=risk_params,
            ai_config=ai_config
        )

        # 创建测试信号
        from apps.strategy.domain.entities import SignalRecommendation
        signals = [
            SignalRecommendation(
                asset_code="000001.SH",
                asset_name="上证指数",
                action=ActionType.BUY,
                confidence=0.5,
                metadata={}
            ),
            SignalRecommendation(
                asset_code="510300.SH",
                asset_name="沪深300ETF",
                action=ActionType.SELL,
                confidence=0.9,
                metadata={}
            )
        ]

        # 应用审核模式
        filtered = executor._apply_approval_mode(
            signals,
            'auto',
            0.8
        )

        # auto 模式应该返回所有信号
        assert len(filtered) == 2

    def test_apply_approval_mode_conditional(self, executor):
        """测试条件审核模式"""
        from apps.strategy.domain.entities import SignalRecommendation

        signals = [
            SignalRecommendation(
                asset_code="000001.SH",
                asset_name="上证指数",
                action=ActionType.BUY,
                confidence=0.9,  # 高于阈值
                metadata={}
            ),
            SignalRecommendation(
                asset_code="510300.SH",
                asset_name="沪深300ETF",
                action=ActionType.SELL,
                confidence=0.6,  # 低于阈值
                metadata={}
            )
        ]

        # 应用条件审核模式
        filtered = executor._apply_approval_mode(
            signals,
            'conditional',
            0.8
        )

        # 应该返回所有信号，但状态不同
        assert len(filtered) == 2
        assert filtered[0].metadata['approval_status'] == 'auto_approved'
        assert filtered[0].metadata['requires_approval'] is False
        assert filtered[1].metadata['approval_status'] == 'pending'
        assert filtered[1].metadata['requires_approval'] is True

    def test_apply_approval_mode_always(self, executor):
        """测试必须人工审核模式"""
        from apps.strategy.domain.entities import SignalRecommendation

        signals = [
            SignalRecommendation(
                asset_code="000001.SH",
                asset_name="上证指数",
                action=ActionType.BUY,
                confidence=0.9,
                metadata={}
            )
        ]

        # 应用必须审核模式
        filtered = executor._apply_approval_mode(
            signals,
            'always',
            0.8
        )

        # 所有信号都应该需要审核
        assert len(filtered) == 1
        assert filtered[0].metadata['approval_status'] == 'pending'
        assert filtered[0].metadata['requires_approval'] is True

    def test_apply_approval_mode_unknown(self, executor):
        """测试未知审核模式"""
        from apps.strategy.domain.entities import SignalRecommendation

        signals = [
            SignalRecommendation(
                asset_code="000001.SH",
                asset_name="上证指数",
                action=ActionType.BUY,
                confidence=0.5,
                metadata={}
            )
        ]

        # 未知模式应该返回所有信号
        filtered = executor._apply_approval_mode(
            signals,
            'unknown',
            0.8
        )

        assert len(filtered) == 1


# ========================================================================
# 待审核信号队列测试
# ========================================================================

class TestPendingApprovalQueue:
    """待审核信号队列测试"""

    @pytest.fixture
    def queue(self):
        return PendingApprovalQueue()

    @pytest.fixture
    def sample_signals(self):
        """创建示例信号"""
        from apps.strategy.domain.entities import SignalRecommendation
        return [
            SignalRecommendation(
                asset_code="000001.SH",
                asset_name="上证指数",
                action=ActionType.BUY,
                confidence=0.5,
                metadata={'requires_approval': True, 'approval_status': 'pending'}
            ),
            SignalRecommendation(
                asset_code="510300.SH",
                asset_name="沪深300ETF",
                action=ActionType.SELL,
                confidence=0.6,
                metadata={'requires_approval': True, 'approval_status': 'pending'}
            )
        ]

    def test_add_and_get_pending_signals(self, queue, sample_signals):
        """测试添加和获取待审核信号"""
        queue.add_pending_signals(1, 1, sample_signals)

        pending = queue.get_pending_signals(1, 1)

        assert len(pending) == 2
        assert pending[0].asset_code == "000001.SH"
        assert pending[1].asset_code == "510300.SH"

    def test_approve_signal(self, queue, sample_signals):
        """测试审核通过信号"""
        queue.add_pending_signals(1, 1, sample_signals)

        success = queue.approve_signal(1, 1, "000001.SH")

        assert success is True

        # 验证状态已更新
        pending = queue.get_pending_signals(1, 1)
        assert pending[0].metadata['approval_status'] == 'approved'
        assert pending[0].metadata['requires_approval'] is False

    def test_reject_signal(self, queue, sample_signals):
        """测试审核拒绝信号"""
        queue.add_pending_signals(1, 1, sample_signals)

        success = queue.reject_signal(1, 1, "000001.SH")

        assert success is True

        # 验证状态已更新
        pending = queue.get_pending_signals(1, 1)
        assert pending[0].metadata['approval_status'] == 'rejected'

    def test_approve_nonexistent_signal(self, queue, sample_signals):
        """测试审核不存在的信号"""
        queue.add_pending_signals(1, 1, sample_signals)

        success = queue.approve_signal(1, 1, "999999.SH")

        assert success is False

    def test_get_empty_queue(self, queue):
        """测试获取空队列"""
        pending = queue.get_pending_signals(1, 1)

        assert len(pending) == 0

    def test_multiple_portfolios(self, queue, sample_signals):
        """测试多个投资组合的队列"""
        queue.add_pending_signals(1, 1, sample_signals)
        queue.add_pending_signals(1, 2, sample_signals)

        pending_1 = queue.get_pending_signals(1, 1)
        pending_2 = queue.get_pending_signals(1, 2)

        assert len(pending_1) == 2
        assert len(pending_2) == 2
