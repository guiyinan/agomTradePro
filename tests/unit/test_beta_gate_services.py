"""
Unit Tests for Beta Gate Domain Services

测试 BetaGateEvaluator 和 VisibilityUniverseBuilder 的行为。
"""

import pytest
from datetime import datetime
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
    VisibilityUniverse,
)
from apps.beta_gate.domain.services import (
    BetaGateEvaluator,
    VisibilityUniverseBuilder,
    GateConfigSelector,
    get_default_configs,
)


class TestGateConfigSelector:
    """GateConfigSelector 测试"""

    @pytest.fixture
    def selector(self):
        """选择器 fixture"""
        configs = get_default_configs()
        return GateConfigSelector(configs)

    def test_get_balanced_config(self, selector):
        """测试获取平衡型配置"""
        config = selector.get_config(RiskProfile.BALANCED)

        assert config is not None
        assert config.risk_profile == RiskProfile.BALANCED
        assert isinstance(config, GateConfig)

    def test_get_conservative_config(self, selector):
        """测试获取保守型配置"""
        config = selector.get_config(RiskProfile.CONSERVATIVE)

        assert config is not None
        assert config.risk_profile == RiskProfile.CONSERVATIVE

    def test_get_aggressive_config(self, selector):
        """测试获取激进型配置"""
        config = selector.get_config(RiskProfile.AGGRESSIVE)

        assert config is not None
        assert config.risk_profile == RiskProfile.AGGRESSIVE


class TestBetaGateEvaluator:
    """BetaGateEvaluator 测试"""

    @pytest.fixture
    def config(self):
        """配置 fixture"""
        return GateConfig(
            config_id="test_config",
            risk_profile=RiskProfile.BALANCED,
            version=1,
            regime_constraints={
                "Recovery": GateMatchResult(
                    allowed_assets=[],
                    forbidden_assets=[],
                    allowed_categories=[
                        AssetCategory.A_SHARE_LARGE_CAP,
                        AssetCategory.BOND,
                    ],
                    forbidden_categories=[
                        AssetCategory.COMMODITY,
                    ],
                    allowed_strategies=[
                        Strategy.TACTICAL_ASSET_ALLOCATION,
                    ],
                    forbidden_strategies=[],
                ),
                "Slowdown": GateMatchResult(
                    allowed_assets=[],
                    forbidden_assets=[],
                    allowed_categories=[AssetCategory.BOND],
                    forbidden_categories=[
                        AssetCategory.A_SHARE_LARGE_CAP,
                        AssetCategory.COMMODITY,
                    ],
                    allowed_strategies=[],
                    forbidden_strategies=[
                        Strategy.TACTICAL_ASSET_ALLOCATION,
                    ],
                ),
            },
            policy_constraints={
                PolicyLevel.P0: GateMatchResult(allowed_assets=[], forbidden_assets=[]),
                PolicyLevel.P2: GateMatchResult(
                    forbidden_categories=[AssetCategory.COMMODITY]
                ),
            },
            asset_category_visibility={},
            strategy_visibility={},
            confidence_threshold=0.3,
            portfolio_exposure_limit=0.8,
        )

    @pytest.fixture
    def evaluator(self, config):
        """评估器 fixture"""
        return BetaGateEvaluator(config)

    def test_evaluate_passing_asset(self, evaluator):
        """测试通过评估的资产"""
        decision = evaluator.evaluate(
            asset_code="000001.SH",
            asset_class="a_share金融",
            current_regime="Recovery",
            regime_confidence=0.7,
            policy_level=PolicyLevel.P0,
            current_portfolio_value=100000.0,
            new_position_value=10000.0,
        )

        assert decision.is_passed is True
        assert decision.status == GateStatus.PASSED
        assert decision.blocking_reason == ""

    def test_evaluate_blocked_by_regime_category(self, evaluator):
        """测试被 Regime 资产类别拦截"""
        decision = evaluator.evaluate(
            asset_code="AU2312",  # 黄金期货
            asset_class="commodity",
            current_regime="Recovery",
            regime_confidence=0.7,
            policy_level=PolicyLevel.P0,
        )

        assert decision.is_blocked is True
        assert "forbidden" in decision.blocking_reason.lower()

    def test_evaluate_blocked_by_low_confidence(self, evaluator):
        """测试低置信度拦截"""
        decision = evaluator.evaluate(
            asset_code="000001.SH",
            asset_class="a_share金融",
            current_regime="Recovery",
            regime_confidence=0.2,  # 低于阈值 0.3
            policy_level=PolicyLevel.P0,
        )

        assert decision.is_blocked is True
        assert "confidence" in decision.blocking_reason.lower()

    def test_evaluate_blocked_by_policy_level(self, evaluator):
        """测试 Policy 档位拦截"""
        decision = evaluator.evaluate(
            asset_code="AU2312",  # 黄金期货
            asset_class="commodity",
            current_regime="Recovery",
            regime_confidence=0.7,
            policy_level=PolicyLevel.P2,
        )

        assert decision.is_blocked is True

    def test_evaluate_batch(self, evaluator):
        """测试批量评估"""
        assets = [
            ("000001.SH", "a_share金融"),
            ("000002.SZ", "a_share金融"),
            ("AU2312", "commodity"),
        ]

        decisions = evaluator.evaluate_batch(
            assets=assets,
            current_regime="Recovery",
            regime_confidence=0.7,
            policy_level=PolicyLevel.P0,
            current_portfolio_value=100000.0,
        )

        assert len(decisions) == 3
        # 股票应该通过，商品应该被拦截
        assert decisions[0].is_passed is True  # 000001.SH
        assert decisions[2].is_blocked is True  # AU2312


class TestVisibilityUniverseBuilder:
    """VisibilityUniverseBuilder 测试"""

    @pytest.fixture
    def builder(self):
        """构建器 fixture"""
        return VisibilityUniverseBuilder()

    @pytest.fixture
    def config(self):
        """配置 fixture"""
        return GateConfig(
            config_id="test_config",
            risk_profile=RiskProfile.BALANCED,
            version=1,
            regime_constraints={
                "Recovery": GateMatchResult(
                    allowed_assets=[],
                    forbidden_assets=[],
                    allowed_categories=[
                        AssetCategory.A_SHARE_LARGE_CAP,
                        AssetCategory.BOND,
                    ],
                    forbidden_categories=[
                        AssetCategory.COMMODITY,
                    ],
                    allowed_strategies=[
                        Strategy.TACTICAL_ASSET_ALLOCATION,
                    ],
                    forbidden_strategies=[],
                ),
            },
            policy_constraints={
                PolicyLevel.P0: GateMatchResult(allowed_assets=[], forbidden_assets=[]),
                PolicyLevel.P2: GateMatchResult(
                    forbidden_categories=[AssetCategory.COMMODITY]
                ),
            },
            asset_category_visibility={
                AssetCategory.A_SHARE_LARGE_CAP: True,
                AssetCategory.BOND: True,
                AssetCategory.COMMODITY: False,
            },
            strategy_visibility={
                Strategy.TACTICAL_ASSET_ALLOCATION: True,
                Strategy.SECTOR_ROTATION: False,
            },
            confidence_threshold=0.3,
            portfolio_exposure_limit=0.8,
        )

    def test_build_universe(self, builder, config):
        """测试构建可见性宇宙"""
        universe = builder.build(
            current_regime="Recovery",
            regime_confidence=0.7,
            policy_level=PolicyLevel.P0,
            risk_profile=RiskProfile.BALANCED,
            config_selector=GateConfigSelector([config]),
        )

        assert universe.current_regime == "Recovery"
        assert universe.policy_level == PolicyLevel.P0
        assert universe.regime_confidence == 0.7
        assert AssetCategory.A_SHARE_LARGE_CAP in universe.visible_asset_categories
        assert AssetCategory.COMMODITY in universe.hard_exclusions

    def test_universe_low_confidence_adjustment(self, builder, config):
        """测试低置信度时的调整"""
        universe = builder.build(
            current_regime="Recovery",
            regime_confidence=0.25,  # 低于阈值 0.3
            policy_level=PolicyLevel.P0,
            risk_profile=RiskProfile.BALANCED,
            config_selector=GateConfigSelector([config]),
        )

        # 低置信度应该将更多资产加入观察列表
        assert len(universe.watch_list) > 0

    def test_universe_policy_p2_restriction(self, builder, config):
        """测试 P2 档位的限制"""
        universe = builder.build(
            current_regime="Recovery",
            regime_confidence=0.7,
            policy_level=PolicyLevel.P2,
            risk_profile=RiskProfile.BALANCED,
            config_selector=GateConfigSelector([config]),
        )

        # P2 档位应该有更多硬排除
        assert AssetCategory.COMMODITY in universe.hard_exclusions
