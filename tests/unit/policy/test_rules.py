"""
Unit Tests for Policy Domain Rules

测试政策档位响应规则和业务逻辑。
"""

import pytest
from datetime import date

from apps.policy.domain.entities import PolicyEvent, PolicyLevel
from apps.policy.domain.rules import (
    get_policy_response,
    should_pause_trading_signals,
    should_trigger_alert,
    requires_manual_intervention,
    get_cash_allocation_adjustment,
    is_high_risk_level,
    validate_policy_event,
    analyze_policy_transition,
    get_recommendations_for_level,
    PolicyResponse,
)


class TestPolicyResponseRules:
    """测试政策响应规则"""

    def test_get_policy_response_p0(self):
        """测试 P0 响应配置"""
        response = get_policy_response(PolicyLevel.P0)

        assert response.level == PolicyLevel.P0
        assert response.name == "常态"
        assert response.cash_adjustment == 0.0
        assert response.signal_pause_hours is None
        assert not response.requires_manual_approval
        assert not response.alert_triggered

    def test_get_policy_response_p1(self):
        """测试 P1 响应配置"""
        response = get_policy_response(PolicyLevel.P1)

        assert response.level == PolicyLevel.P1
        assert response.name == "预警"
        assert response.cash_adjustment == 10.0
        assert response.signal_pause_hours is None
        assert not response.requires_manual_approval

    def test_get_policy_response_p2(self):
        """测试 P2 响应配置"""
        response = get_policy_response(PolicyLevel.P2)

        assert response.level == PolicyLevel.P2
        assert response.name == "干预"
        assert response.cash_adjustment == 20.0
        assert response.signal_pause_hours == 48
        assert response.requires_manual_approval
        assert response.alert_triggered

    def test_get_policy_response_p3(self):
        """测试 P3 响应配置"""
        response = get_policy_response(PolicyLevel.P3)

        assert response.level == PolicyLevel.P3
        assert response.name == "危机"
        assert response.cash_adjustment == 100.0
        assert response.requires_manual_approval
        assert response.alert_triggered

    def test_get_policy_response_invalid_level(self):
        """测试无效档位"""
        with pytest.raises(ValueError, match="Unknown policy level"):
            get_policy_response("INVALID")


class TestPolicyDecisionRules:
    """测试政策决策规则"""

    def test_should_pause_trading_signals_p0(self):
        """测试 P0 不暂停交易"""
        assert not should_pause_trading_signals(PolicyLevel.P0)

    def test_should_pause_trading_signals_p1(self):
        """测试 P1 不暂停交易"""
        assert not should_pause_trading_signals(PolicyLevel.P1)

    def test_should_pause_trading_signals_p2(self):
        """测试 P2 暂停交易"""
        assert should_pause_trading_signals(PolicyLevel.P2)

    def test_should_pause_trading_signals_p3(self):
        """测试 P3 暂停交易（人工接管）"""
        assert should_pause_trading_signals(PolicyLevel.P3)

    def test_should_trigger_alert_p0_p1(self):
        """测试 P0/P1 不触发告警"""
        assert not should_trigger_alert(PolicyLevel.P0)
        assert not should_trigger_alert(PolicyLevel.P1)

    def test_should_trigger_alert_p2_p3(self):
        """测试 P2/P3 触发告警"""
        assert should_trigger_alert(PolicyLevel.P2)
        assert should_trigger_alert(PolicyLevel.P3)

    def test_requires_manual_intervention_p2_p3(self):
        """测试 P2/P3 需要人工干预"""
        assert not requires_manual_intervention(PolicyLevel.P0)
        assert not requires_manual_intervention(PolicyLevel.P1)
        assert requires_manual_intervention(PolicyLevel.P2)
        assert requires_manual_intervention(PolicyLevel.P3)

    def test_get_cash_allocation_adjustment(self):
        """测试现金配置调整"""
        assert get_cash_allocation_adjustment(PolicyLevel.P0) == 0.0
        assert get_cash_allocation_adjustment(PolicyLevel.P1) == 10.0
        assert get_cash_allocation_adjustment(PolicyLevel.P2) == 20.0
        assert get_cash_allocation_adjustment(PolicyLevel.P3) == 100.0

    def test_is_high_risk_level(self):
        """测试高风险判断"""
        assert not is_high_risk_level(PolicyLevel.P0)
        assert not is_high_risk_level(PolicyLevel.P1)
        assert is_high_risk_level(PolicyLevel.P2)
        assert is_high_risk_level(PolicyLevel.P3)


class TestPolicyValidation:
    """测试政策事件验证"""

    def test_validate_valid_event(self):
        """测试有效事件"""
        is_valid, errors = validate_policy_event(
            level=PolicyLevel.P2,
            title="央行宣布降准",
            description="中国人民银行决定下调存款准备金率 0.5 个百分点，释放长期资金约 1 万亿元。",
            evidence_url="https://example.com/news/1"
        )

        assert is_valid
        assert len(errors) == 0

    def test_validate_empty_title(self):
        """测试空标题"""
        is_valid, errors = validate_policy_event(
            level=PolicyLevel.P2,
            title="",
            description="有效的描述内容",
            evidence_url="https://example.com/news/1"
        )

        assert not is_valid
        assert any("标题" in e for e in errors)

    def test_validate_short_description_for_p2(self):
        """测试 P2 描述过短"""
        is_valid, errors = validate_policy_event(
            level=PolicyLevel.P2,
            title="测试标题",
            description="太短了",
            evidence_url="https://example.com/news/1"
        )

        assert not is_valid
        assert any("至少" in e for e in errors)

    def test_validate_missing_evidence_url(self):
        """测试缺少证据 URL"""
        is_valid, errors = validate_policy_event(
            level=PolicyLevel.P2,
            title="测试标题",
            description="这是一个足够长的描述内容，满足验证要求",
            evidence_url=""
        )

        assert not is_valid
        assert any("证据" in e or "URL" in e for e in errors)

    def test_validate_invalid_url(self):
        """测试无效 URL"""
        is_valid, errors = validate_policy_event(
            level=PolicyLevel.P2,
            title="测试标题",
            description="这是一个足够长的描述内容，满足验证要求",
            evidence_url="not-a-url"
        )

        assert not is_valid
        assert any("http" in e for e in errors)


class TestPolicyTransition:
    """测试政策档位变更分析"""

    def test_upgrade_transition_p0_to_p2(self):
        """测试 P0 -> P2 升级"""
        transition = analyze_policy_transition(
            from_level=PolicyLevel.P0,
            to_level=PolicyLevel.P2
        )

        assert transition.from_level == PolicyLevel.P0
        assert transition.to_level == PolicyLevel.P2
        assert transition.is_upgrade is True

    def test_downgrade_transition_p2_to_p1(self):
        """测试 P2 -> P1 降级"""
        transition = analyze_policy_transition(
            from_level=PolicyLevel.P2,
            to_level=PolicyLevel.P1
        )

        assert transition.from_level == PolicyLevel.P2
        assert transition.to_level == PolicyLevel.P1
        assert transition.is_upgrade is False

    def test_initial_transition_none_to_p2(self):
        """测试初始状态 None -> P2"""
        transition = analyze_policy_transition(
            from_level=None,
            to_level=PolicyLevel.P2
        )

        assert transition.from_level is None
        assert transition.to_level == PolicyLevel.P2
        assert transition.is_upgrade is False  # None 被视为初始状态


class TestPolicyRecommendations:
    """测试政策建议"""

    def test_recommendations_for_p0(self):
        """测试 P0 建议"""
        recommendations = get_recommendations_for_level(PolicyLevel.P0)

        assert len(recommendations) > 0
        assert "常态" in recommendations[0]
        assert any("正常运行" in r for r in recommendations)

    def test_recommendations_for_p2(self):
        """测试 P2 建议"""
        recommendations = get_recommendations_for_level(PolicyLevel.P2)

        assert len(recommendations) > 0
        assert any("暂停" in r for r in recommendations)
        assert any("48" in r for r in recommendations)

    def test_recommendations_for_p3(self):
        """测试 P3 建议"""
        recommendations = get_recommendations_for_level(PolicyLevel.P3)

        assert len(recommendations) > 0
        assert any("危机" in r for r in recommendations)
        assert any("人工接管" in r for r in recommendations)


class TestPolicyEventCreation:
    """测试政策事件创建"""

    def test_create_valid_event(self):
        """测试创建有效事件"""
        event = PolicyEvent(
            event_date=date.today(),
            level=PolicyLevel.P2,
            title="央行降准",
            description="中国人民银行决定降准",
            evidence_url="https://example.com/news/1"
        )

        assert event.event_date == date.today()
        assert event.level == PolicyLevel.P2
        assert event.title == "央行降准"

    def test_event_immutability(self):
        """测试事件不可变性"""
        event = PolicyEvent(
            event_date=date.today(),
            level=PolicyLevel.P2,
            title="测试",
            description="测试",
            evidence_url="https://example.com"
        )

        # frozen=True 的 dataclass 是不可变的
        with pytest.raises(Exception):  # FrozenInstanceError
            event.title = "修改后"
