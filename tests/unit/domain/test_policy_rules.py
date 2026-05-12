"""
Tests for Policy Domain Rules.

Tests the pure domain logic in apps/policy/domain/rules.py
Only uses Python standard library - no Django imports.
"""

from dataclasses import FrozenInstanceError

import pytest

from apps.policy.domain.entities import PolicyLevel
from apps.policy.domain.rules import (
    DEFAULT_KEYWORD_RULES,
    POLICY_RESPONSE_RULES,
    MarketAction,
    PolicyLevelKeywordRule,
    analyze_policy_transition,
    get_cash_allocation_adjustment,
    get_policy_response,
    get_recommendations_for_level,
    get_signal_pause_duration_hours,
    is_high_risk_level,
    requires_manual_intervention,
    should_pause_trading_signals,
    should_trigger_alert,
    validate_policy_event,
)


class TestPolicyResponseRules:
    """测试政策档位响应规则配置"""

    def test_all_policy_levels_have_rules(self):
        """测试所有档位都有响应规则配置"""
        expected_levels = {PolicyLevel.P0, PolicyLevel.P1, PolicyLevel.P2, PolicyLevel.P3}
        actual_levels = set(POLICY_RESPONSE_RULES.keys())
        assert actual_levels == expected_levels

    def test_p0_response_configuration(self):
        """测试 P0 常态配置"""
        response = POLICY_RESPONSE_RULES[PolicyLevel.P0]
        assert response.level == PolicyLevel.P0
        assert response.name == "常态"
        assert response.market_action == MarketAction.NORMAL_OPERATION
        assert response.cash_adjustment == 0.0
        assert response.signal_pause_hours is None
        assert response.requires_manual_approval is False
        assert response.alert_triggered is False

    def test_p1_response_configuration(self):
        """测试 P1 预警配置"""
        response = POLICY_RESPONSE_RULES[PolicyLevel.P1]
        assert response.level == PolicyLevel.P1
        assert response.name == "预警"
        assert response.market_action == MarketAction.INCREASE_CASH
        assert response.cash_adjustment == 10.0
        assert response.signal_pause_hours is None
        assert response.requires_manual_approval is False
        assert response.alert_triggered is False

    def test_p2_response_configuration(self):
        """测试 P2 干预配置"""
        response = POLICY_RESPONSE_RULES[PolicyLevel.P2]
        assert response.level == PolicyLevel.P2
        assert response.name == "干预"
        assert response.market_action == MarketAction.PAUSE_SIGNALS
        assert response.cash_adjustment == 20.0
        assert response.signal_pause_hours == 48
        assert response.requires_manual_approval is True
        assert response.alert_triggered is True

    def test_p3_response_configuration(self):
        """测试 P3 危机配置"""
        response = POLICY_RESPONSE_RULES[PolicyLevel.P3]
        assert response.level == PolicyLevel.P3
        assert response.name == "危机"
        assert response.market_action == MarketAction.MANUAL_TAKEOVER
        assert response.cash_adjustment == 100.0
        assert response.signal_pause_hours is None
        assert response.requires_manual_approval is True
        assert response.alert_triggered is True

    def test_response_is_immutable(self):
        """测试响应配置是不可变的"""
        response = POLICY_RESPONSE_RULES[PolicyLevel.P0]
        with pytest.raises(FrozenInstanceError):  # frozen=True makes it immutable
            response.cash_adjustment = 5.0


class TestGetPolicyResponse:
    """测试获取政策响应"""

    def test_get_existing_level(self):
        """测试获取存在的档位"""
        response = get_policy_response(PolicyLevel.P1)
        assert response.level == PolicyLevel.P1
        assert response.name == "预警"

    def test_get_unknown_level_raises_error(self):
        """测试获取未知档位抛出异常"""
        # 创建一个不存在的档位（通过 hack）
        with pytest.raises(ValueError, match="Unknown policy level"):
            get_policy_response("INVALID_LEVEL")


class TestShouldPauseTradingSignals:
    """测试是否暂停交易信号"""

    def test_p0_does_not_pause(self):
        """测试 P0 不暂停信号"""
        assert should_pause_trading_signals(PolicyLevel.P0) is False

    def test_p1_does_not_pause(self):
        """测试 P1 不暂停信号"""
        assert should_pause_trading_signals(PolicyLevel.P1) is False

    def test_p2_pauses_signals(self):
        """测试 P2 暂停信号"""
        assert should_pause_trading_signals(PolicyLevel.P2) is True

    def test_p3_pauses_signals(self):
        """测试 P3 暂停信号（人工接管）"""
        assert should_pause_trading_signals(PolicyLevel.P3) is True


class TestGetSignalPauseDurationHours:
    """测试获取信号暂停时长"""

    def test_p0_no_pause(self):
        """测试 P0 不暂停"""
        assert get_signal_pause_duration_hours(PolicyLevel.P0) is None

    def test_p1_no_pause(self):
        """测试 P1 不暂停"""
        assert get_signal_pause_duration_hours(PolicyLevel.P1) is None

    def test_p2_pause_48_hours(self):
        """测试 P2 暂停 48 小时"""
        assert get_signal_pause_duration_hours(PolicyLevel.P2) == 48

    def test_p3_no_auto_pause(self):
        """测试 P3 无自动恢复时长（人工接管）"""
        assert get_signal_pause_duration_hours(PolicyLevel.P3) is None


class TestShouldTriggerAlert:
    """测试是否触发告警"""

    def test_p0_no_alert(self):
        """测试 P0 不触发告警"""
        assert should_trigger_alert(PolicyLevel.P0) is False

    def test_p1_no_alert(self):
        """测试 P1 不触发告警"""
        assert should_trigger_alert(PolicyLevel.P1) is False

    def test_p2_triggers_alert(self):
        """测试 P2 触发告警"""
        assert should_trigger_alert(PolicyLevel.P2) is True

    def test_p3_triggers_alert(self):
        """测试 P3 触发告警"""
        assert should_trigger_alert(PolicyLevel.P3) is True


class TestRequiresManualIntervention:
    """测试是否需要人工干预"""

    def test_p0_no_manual(self):
        """测试 P0 不需要人工"""
        assert requires_manual_intervention(PolicyLevel.P0) is False

    def test_p1_no_manual(self):
        """测试 P1 不需要人工"""
        assert requires_manual_intervention(PolicyLevel.P1) is False

    def test_p2_requires_manual(self):
        """测试 P2 需要人工审批"""
        assert requires_manual_intervention(PolicyLevel.P2) is True

    def test_p3_requires_manual(self):
        """测试 P3 需要人工接管"""
        assert requires_manual_intervention(PolicyLevel.P3) is True


class TestGetCashAllocationAdjustment:
    """测试获取现金配置调整"""

    def test_p0_no_adjustment(self):
        """测试 P0 无现金调整"""
        assert get_cash_allocation_adjustment(PolicyLevel.P0) == 0.0

    def test_p1_increase_cash(self):
        """测试 P1 提升现金 10%"""
        assert get_cash_allocation_adjustment(PolicyLevel.P1) == 10.0

    def test_p2_increase_cash(self):
        """测试 P2 提升现金 20%"""
        assert get_cash_allocation_adjustment(PolicyLevel.P2) == 20.0

    def test_p3_full_cash(self):
        """测试 P3 全仓转现金 100%"""
        assert get_cash_allocation_adjustment(PolicyLevel.P3) == 100.0


class TestIsHighRiskLevel:
    """测试高风险档位判断"""

    def test_p0_not_high_risk(self):
        """测试 P0 不是高风险"""
        assert is_high_risk_level(PolicyLevel.P0) is False

    def test_p1_not_high_risk(self):
        """测试 P1 不是高风险"""
        assert is_high_risk_level(PolicyLevel.P1) is False

    def test_p2_is_high_risk(self):
        """测试 P2 是高风险"""
        assert is_high_risk_level(PolicyLevel.P2) is True

    def test_p3_is_high_risk(self):
        """测试 P3 是高风险"""
        assert is_high_risk_level(PolicyLevel.P3) is True


class TestValidatePolicyEvent:
    """测试政策事件验证"""

    def test_valid_p0_event(self):
        """测试有效的 P0 事件"""
        is_valid, errors = validate_policy_event(
            PolicyLevel.P0,
            "正常市场状态",
            "无重大政策干预",
            "https://example.com/news"
        )
        assert is_valid is True
        assert len(errors) == 0

    def test_valid_p2_event(self):
        """测试有效的 P2 事件"""
        is_valid, errors = validate_policy_event(
            PolicyLevel.P2,
            "央行宣布降准",
            "中国人民银行宣布下调存款准备金率0.5个百分点，释放长期资金",
            "https://pbc.gov.cn/news/12345"
        )
        assert is_valid is True
        assert len(errors) == 0

    def test_empty_title(self):
        """测试空标题"""
        is_valid, errors = validate_policy_event(
            PolicyLevel.P1,
            "",
            "描述内容",
            "https://example.com"
        )
        assert is_valid is False
        assert "标题不能为空" in errors

    def test_empty_description(self):
        """测试空描述"""
        is_valid, errors = validate_policy_event(
            PolicyLevel.P1,
            "标题",
            "",
            "https://example.com"
        )
        assert is_valid is False
        assert "描述不能为空" in errors

    def test_p2_short_description(self):
        """测试 P2 描述过短"""
        is_valid, errors = validate_policy_event(
            PolicyLevel.P2,
            "降息",
            "降了",  # 少于 20 字符
            "https://example.com"
        )
        assert is_valid is False
        assert any("至少 20 个字符" in e for e in errors)

    def test_p3_short_description(self):
        """测试 P3 描述过短"""
        is_valid, errors = validate_policy_event(
            PolicyLevel.P3,
            "熔断",
            "市场熔断了",  # 少于 20 字符
            "https://example.com"
        )
        assert is_valid is False
        assert any("至少 20 个字符" in e for e in errors)

    def test_empty_evidence_url(self):
        """测试缺少证据 URL"""
        is_valid, errors = validate_policy_event(
            PolicyLevel.P1,
            "标题",
            "描述内容",
            ""
        )
        assert is_valid is False
        assert "证据 URL" in errors[0]

    def test_invalid_evidence_url_format(self):
        """测试无效的 URL 格式"""
        is_valid, errors = validate_policy_event(
            PolicyLevel.P1,
            "标题",
            "描述内容",
            "ftp://example.com"
        )
        assert is_valid is False
        assert "http:// 或 https://" in errors[0]

    def test_multiple_errors(self):
        """测试多个错误同时存在"""
        is_valid, errors = validate_policy_event(
            PolicyLevel.P2,
            "",
            "短",
            ""
        )
        assert is_valid is False
        assert len(errors) >= 3


class TestAnalyzePolicyTransition:
    """测试政策档位变更分析"""

    def test_initial_transition(self):
        """测试初始状态（from_level=None）"""
        transition = analyze_policy_transition(None, PolicyLevel.P1)
        assert transition.from_level is None
        assert transition.to_level == PolicyLevel.P1
        assert transition.is_upgrade is False
        # 日期格式检查
        assert len(transition.transition_date) == 10  # YYYY-MM-DD

    def test_upgrade_p0_to_p1(self):
        """测试升级 P0 -> P1"""
        transition = analyze_policy_transition(PolicyLevel.P0, PolicyLevel.P1)
        assert transition.from_level == PolicyLevel.P0
        assert transition.to_level == PolicyLevel.P1
        assert transition.is_upgrade is True

    def test_upgrade_p1_to_p2(self):
        """测试升级 P1 -> P2"""
        transition = analyze_policy_transition(PolicyLevel.P1, PolicyLevel.P2)
        assert transition.from_level == PolicyLevel.P1
        assert transition.to_level == PolicyLevel.P2
        assert transition.is_upgrade is True

    def test_upgrade_p2_to_p3(self):
        """测试升级 P2 -> P3"""
        transition = analyze_policy_transition(PolicyLevel.P2, PolicyLevel.P3)
        assert transition.from_level == PolicyLevel.P2
        assert transition.to_level == PolicyLevel.P3
        assert transition.is_upgrade is True

    def test_downgrade_p2_to_p1(self):
        """测试降级 P2 -> P1"""
        transition = analyze_policy_transition(PolicyLevel.P2, PolicyLevel.P1)
        assert transition.from_level == PolicyLevel.P2
        assert transition.to_level == PolicyLevel.P1
        assert transition.is_upgrade is False

    def test_downgrade_p3_to_p0(self):
        """测试降级 P3 -> P0"""
        transition = analyze_policy_transition(PolicyLevel.P3, PolicyLevel.P0)
        assert transition.from_level == PolicyLevel.P3
        assert transition.to_level == PolicyLevel.P0
        assert transition.is_upgrade is False

    def test_same_level(self):
        """测试同档位"""
        transition = analyze_policy_transition(PolicyLevel.P1, PolicyLevel.P1)
        assert transition.from_level == PolicyLevel.P1
        assert transition.to_level == PolicyLevel.P1
        assert transition.is_upgrade is False

    def test_transition_is_immutable(self):
        """测试变更记录是不可变的"""
        transition = analyze_policy_transition(PolicyLevel.P0, PolicyLevel.P1)
        with pytest.raises(FrozenInstanceError):
            transition.is_upgrade = False


class TestGetRecommendationsForLevel:
    """测试获取操作建议"""

    def test_p0_recommendations(self):
        """测试 P0 建议"""
        recommendations = get_recommendations_for_level(PolicyLevel.P0)
        assert len(recommendations) >= 2
        assert "常态" in recommendations[0]
        assert any("正常运行" in r for r in recommendations)

    def test_p1_recommendations(self):
        """测试 P1 建议"""
        recommendations = get_recommendations_for_level(PolicyLevel.P1)
        assert "预警" in recommendations[0]
        assert any("10" in r or "10%" in r for r in recommendations)
        assert any("现金" in r for r in recommendations)

    def test_p2_recommendations(self):
        """测试 P2 建议"""
        recommendations = get_recommendations_for_level(PolicyLevel.P2)
        assert "干预" in recommendations[0]
        assert any("48" in r for r in recommendations)
        assert any("暂停" in r for r in recommendations)
        assert any("20" in r or "20%" in r for r in recommendations)

    def test_p3_recommendations(self):
        """测试 P3 建议"""
        recommendations = get_recommendations_for_level(PolicyLevel.P3)
        assert "危机" in recommendations[0]
        assert any("危机" in r for r in recommendations)
        assert any("人工接管" in r for r in recommendations)
        assert any("100%" in r or "现金" in r for r in recommendations)


class TestPolicyLevelKeywordRule:
    """测试政策档位关键词规则"""

    def test_default_keyword_rules_exist(self):
        """测试默认关键词规则存在"""
        assert len(DEFAULT_KEYWORD_RULES) >= 3

    def test_p3_keywords(self):
        """测试 P3 关键词"""
        p3_rules = [r for r in DEFAULT_KEYWORD_RULES if r.level == PolicyLevel.P3]
        assert len(p3_rules) > 0
        assert "熔断" in p3_rules[0].keywords
        assert "紧急" in p3_rules[0].keywords

    def test_p2_keywords(self):
        """测试 P2 关键词"""
        p2_rules = [r for r in DEFAULT_KEYWORD_RULES if r.level == PolicyLevel.P2]
        assert len(p2_rules) > 0
        assert "降息" in p2_rules[0].keywords
        assert "降准" in p2_rules[0].keywords

    def test_p1_keywords(self):
        """测试 P1 关键词"""
        p1_rules = [r for r in DEFAULT_KEYWORD_RULES if r.level == PolicyLevel.P1]
        assert len(p1_rules) > 0
        assert "酝酿" in p1_rules[0].keywords
        assert "研究" in p1_rules[0].keywords

    def test_keyword_rule_is_immutable(self):
        """测试关键词规则是不可变的"""
        rule = PolicyLevelKeywordRule(
            level=PolicyLevel.P2,
            keywords=["降息"],
            weight=1
        )
        with pytest.raises(FrozenInstanceError):
            rule.keywords = ["加息"]


class TestMarketAction:
    """测试市场行动枚举"""

    def test_market_action_values(self):
        """测试市场行动枚举值"""
        assert MarketAction.NORMAL_OPERATION.value == "normal_operation"
        assert MarketAction.INCREASE_CASH.value == "increase_cash"
        assert MarketAction.PAUSE_SIGNALS.value == "pause_signals"
        assert MarketAction.FULL_HEDGING.value == "full_hedging"
        assert MarketAction.MANUAL_TAKEOVER.value == "manual_takeover"
