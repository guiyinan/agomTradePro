"""
Unit Tests for Beta Gate Domain Entities

测试 GateConfig 和 GateDecision 实体的行为。
"""

import pytest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apps.beta_gate.domain.entities import (
    GateConfig,
    GateDecision,
    GateStatus,
    GateMatchResult,
    RiskProfile,
    AssetCategory,
    Strategy,
    PolicyLevel,
)


class TestGateConfig:
    """GateConfig 实体测试"""

    @pytest.fixture
    def base_config(self):
        """基础配置 fixture"""
        return GateConfig(
            config_id="test_config_v1",
            risk_profile=RiskProfile.BALANCED,
            version=1,
            regime_constraints={},
            policy_constraints={},
            asset_category_visibility={},
            strategy_visibility={},
            confidence_threshold=0.3,
            portfolio_exposure_limit=0.8,
            custom_rules={},
            created_at=datetime.now(ZoneInfo("Asia/Shanghai")),
            valid_from=datetime.now(ZoneInfo("Asia/Shanghai")),
        )

    def test_gate_config_creation(self, base_config):
        """测试配置创建"""
        assert base_config.config_id == "test_config_v1"
        assert base_config.risk_profile == RiskProfile.BALANCED
        assert base_config.version == 1
        assert base_config.confidence_threshold == 0.3
        assert base_config.portfolio_exposure_limit == 0.8

    def test_is_valid_active_period(self, base_config):
        """测试有效期内验证"""
        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        base_config.valid_from = now - timedelta(days=1)
        base_config.valid_until = now + timedelta(days=30)

        assert base_config.is_valid is True

    def test_is_valid_expired(self, base_config):
        """测试过期验证"""
        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        base_config.valid_from = now - timedelta(days=60)
        base_config.valid_until = now - timedelta(days=1)

        assert base_config.is_valid is False

    def test_is_valid_not_started(self, base_config):
        """测试未开始验证"""
        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        base_config.valid_from = now + timedelta(days=1)
        base_config.valid_until = now + timedelta(days=30)

        assert base_config.is_valid is False

    def test_regime_constraint_matching(self):
        """测试 Regime 约束匹配"""
        config = GateConfig(
            config_id="test_config",
            risk_profile=RiskProfile.BALANCED,
            version=1,
            regime_constraints={
                "Recovery": GateMatchResult(
                    allowed_assets=["000001.SH"],
                    forbidden_assets=["000002.SZ"],
                    allowed_categories=[AssetCategory.A_SHARE_LARGE_CAP],
                    forbidden_categories=[AssetCategory.COMMODITY],
                    allowed_strategies=[Strategy.TACTICAL_ASSET_ALLOCATION],
                    forbidden_strategies=[Strategy.SECTOR_ROTATION],
                )
            },
            policy_constraints={},
            asset_category_visibility={},
            strategy_visibility={},
            confidence_threshold=0.3,
            portfolio_exposure_limit=0.8,
        )

        result = config.regime_constraints["Recovery"]
        assert "000001.SH" in result.allowed_assets
        assert "000002.SZ" in result.forbidden_assets
        assert AssetCategory.A_SHARE_LARGE_CAP in result.allowed_categories
        assert AssetCategory.COMMODITY in result.forbidden_categories


class TestGateMatchResult:
    """GateMatchResult 实体测试"""

    def test_empty_match_result(self):
        """测试空的匹配结果"""
        result = GateMatchResult()

        assert result.allowed_assets == []
        assert result.forbidden_assets == []
        assert result.allowed_categories == []
        assert result.forbidden_categories == []
        assert result.allowed_strategies == []
        assert result.forbidden_strategies == []

    def test_match_result_with_values(self):
        """测试有值的匹配结果"""
        result = GateMatchResult(
            allowed_assets=["000001.SH", "000002.SZ"],
            forbidden_assets=["510300.SH"],
            allowed_categories=[AssetCategory.A_SHARE_LARGE_CAP, AssetCategory.BOND],
            forbidden_categories=[AssetCategory.COMMODITY],
            allowed_strategies=[Strategy.TACTICAL_ASSET_ALLOCATION],
            forbidden_strategies=[Strategy.SECTOR_ROTATION],
        )

        assert len(result.allowed_assets) == 2
        assert "510300.SH" in result.forbidden_assets
        assert AssetCategory.BOND in result.allowed_categories
        assert AssetCategory.COMMODITY in result.forbidden_categories
        assert Strategy.TACTICAL_ASSET_ALLOCATION in result.allowed_strategies


class TestGateDecision:
    """GateDecision 实体测试"""

    @pytest.fixture
    def passed_decision(self):
        """通过的决策 fixture"""
        return GateDecision(
            asset_code="000001.SH",
            asset_class="a_share金融",
            status=GateStatus.PASSED,
            current_regime="Recovery",
            policy_level=PolicyLevel.P0,
            regime_confidence=0.7,
            is_passed=True,
            blocking_reason=None,
            risk_profile=RiskProfile.BALANCED,
            evaluation_details={},
            created_at=datetime.now(ZoneInfo("Asia/Shanghai")),
        )

    @pytest.fixture
    def blocked_decision(self):
        """被拦截的决策 fixture"""
        return GateDecision(
            asset_code="510300.SH",
            asset_class="etf",
            status=GateStatus.BLOCKED,
            current_regime="Slowdown",
            policy_level=PolicyLevel.P2,
            regime_confidence=0.4,
            is_passed=False,
            blocking_reason="Policy level P2 restricts ETF exposure",
            risk_profile=RiskProfile.CONSERVATIVE,
            evaluation_details={"policy_check": "failed"},
            created_at=datetime.now(ZoneInfo("Asia/Shanghai")),
        )

    def test_passed_decision_properties(self, passed_decision):
        """测试通过决策的属性"""
        assert passed_decision.asset_code == "000001.SH"
        assert passed_decision.status == GateStatus.PASSED
        assert passed_decision.is_passed is True
        assert passed_decision.blocking_reason is None

    def test_blocked_decision_properties(self, blocked_decision):
        """测试拦截决策的属性"""
        assert blocked_decision.asset_code == "510300.SH"
        assert blocked_decision.status == GateStatus.BLOCKED
        assert blocked_decision.is_blocked is True
        assert blocked_decision.blocking_reason == "Policy level P2 restricts ETF exposure"

    def test_decision_evaluation_details(self, blocked_decision):
        """测试评估详情"""
        assert blocked_decision.evaluation_details == {"policy_check": "failed"}
