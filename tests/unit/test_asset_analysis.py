"""
资产分析模块单元测试
"""

import pytest
from datetime import date

from apps.asset_analysis.domain.entities import AssetScore, AssetType, AssetStyle
from apps.asset_analysis.domain.value_objects import WeightConfig, ScoreContext
from apps.asset_analysis.domain.services import (
    RegimeMatcher,
    PolicyMatcher,
    SentimentMatcher,
    SignalMatcher,
)
from apps.asset_analysis.application.services import AssetMultiDimScorer
from apps.asset_analysis.infrastructure.repositories import DjangoWeightConfigRepository


class TestAssetScore:
    """测试 AssetScore 实体"""

    def test_create_asset_score(self):
        """测试创建资产评分"""
        score = AssetScore(
            asset_type=AssetType.EQUITY,
            asset_code="000001",
            asset_name="测试股票",
            style=AssetStyle.GROWTH,
            total_score=75.5,
        )
        assert score.asset_type == AssetType.EQUITY
        assert score.asset_code == "000001"
        assert score.total_score == 75.5

    def test_to_dict(self):
        """测试转换为字典"""
        score = AssetScore(
            asset_type=AssetType.FUND,
            asset_code="000001",
            asset_name="测试基金",
            total_score=80.0,
            allocation_percent=15.0,
        )
        d = score.to_dict()
        assert d["asset_type"] == "fund"
        assert d["total_score"] == 80.0
        assert d["allocation"] == "15.0%"

    def test_score_validation(self):
        """测试分数验证"""
        with pytest.raises(ValueError, match="必须在 0-100 之间"):
            AssetScore(
                asset_type=AssetType.EQUITY,
                asset_code="000001",
                asset_name="测试",
                regime_score=150,  # 无效值
            )


class TestWeightConfig:
    """测试 WeightConfig 值对象"""

    def test_default_weights(self):
        """测试默认权重"""
        config = WeightConfig()
        assert config.regime_weight == 0.40
        assert config.policy_weight == 0.25
        assert config.sentiment_weight == 0.20
        assert config.signal_weight == 0.15

    def test_weight_sum_validation(self):
        """测试权重总和验证"""
        with pytest.raises(ValueError, match="权重总和必须为1.0"):
            WeightConfig(
                regime_weight=0.6,
                policy_weight=0.6,
                sentiment_weight=0.0,
                signal_weight=0.0,  # 总和为 1.2（不等于 1.0）
            )

    def test_negative_weight_validation(self):
        """测试负权重验证"""
        with pytest.raises(ValueError, match="必须为非负数"):
            WeightConfig(regime_weight=-0.1)


class TestScoreContext:
    """测试 ScoreContext 值对象"""

    def test_create_context(self):
        """测试创建评分上下文"""
        context = ScoreContext(
            current_regime="Recovery",
            policy_level="P0",
            sentiment_index=0.5,
            active_signals=[],
        )
        assert context.current_regime == "Recovery"
        assert context.sentiment_index == 0.5

    def test_sentiment_index_validation(self):
        """测试情绪指数验证"""
        with pytest.raises(ValueError, match="sentiment_index 必须在 -3.0 到"):
            ScoreContext(
                current_regime="Recovery",
                policy_level="P0",
                sentiment_index=5.0,  # 超出范围
                active_signals=[],
            )


class TestRegimeMatcher:
    """测试 Regime 匹配器"""

    def test_recovery_equity(self):
        """测试 Recovery + Equity 组合"""
        asset = AssetScore(
            asset_type=AssetType.EQUITY,
            asset_code="000001",
            asset_name="测试股票",
        )
        score = RegimeMatcher.match(asset, "Recovery")
        # Recovery + Equity 应该得高分（基础 90 * 0.6 = 54，无风格加 70 * 0.4 = 28，共 82）
        assert 80 <= score <= 95

    def test_stagflation_bond(self):
        """测试 Stagflation + Bond 组合"""
        asset = AssetScore(
            asset_type=AssetType.BOND,
            asset_code="000001",
            asset_name="测试债券",
        )
        score = RegimeMatcher.match(asset, "Stagflation")
        # Stagflation + Bond 应该得高分
        assert 80 <= score <= 95


class TestPolicyMatcher:
    """测试 Policy 匹配器"""

    def test_p0_equity(self):
        """测试 P0 + Equity 组合"""
        asset = AssetScore(
            asset_type=AssetType.EQUITY,
            asset_code="000001",
            asset_name="测试股票",
        )
        score = PolicyMatcher.match(asset, "P0")
        assert score >= 85  # P0 股票应该得高分

    def test_p3_equity(self):
        """测试 P3 + Equity 组合"""
        asset = AssetScore(
            asset_type=AssetType.EQUITY,
            asset_code="000001",
            asset_name="测试股票",
        )
        score = PolicyMatcher.match(asset, "P3")
        assert score <= 15  # P3 股票应该得低分


class TestSentimentMatcher:
    """测试 Sentiment 匹配器"""

    def test_positive_sentiment_equity(self):
        """测试正面情绪 + 股票"""
        asset = AssetScore(
            asset_type=AssetType.EQUITY,
            asset_code="000001",
            asset_name="测试股票",
        )
        score = SentimentMatcher.match(asset, 2.0)
        assert score >= 70  # 正面情绪股票应该得高分

    def test_negative_sentiment_bond(self):
        """测试负面情绪 + 债券"""
        asset = AssetScore(
            asset_type=AssetType.BOND,
            asset_code="000001",
            asset_name="测试债券",
        )
        score = SentimentMatcher.match(asset, -2.0)
        assert score >= 70  # 负面情绪债券应该得高分


class TestSignalMatcher:
    """测试 Signal 匹配器"""

    def test_no_signals(self):
        """测试无信号"""
        asset = AssetScore(
            asset_type=AssetType.EQUITY,
            asset_code="000001",
            asset_name="测试股票",
        )
        score = SignalMatcher.match(asset, [])
        assert score == 50.0  # 无信号中性

    def test_matching_signal(self):
        """测试匹配信号"""
        from dataclasses import dataclass

        @dataclass
        class MockSignal:
            asset_code: str

        asset = AssetScore(
            asset_type=AssetType.EQUITY,
            asset_code="000001",
            asset_name="测试股票",
        )
        signals = [MockSignal(asset_code="000001")]
        score = SignalMatcher.match(asset, signals)
        assert score >= 60  # 有匹配信号应该加分


class TestAssetMultiDimScorer:
    """测试资产多维度评分器"""

    def test_score_single_asset(self):
        """测试单个资产评分"""
        # 使用 mock 仓储
        class MockWeightRepo:
            def get_active_weights(self, asset_type=None):
                return WeightConfig()

        scorer = AssetMultiDimScorer(MockWeightRepo())

        asset = AssetScore(
            asset_type=AssetType.EQUITY,
            asset_code="000001",
            asset_name="测试股票",
            style=AssetStyle.GROWTH,
        )

        context = ScoreContext(
            current_regime="Recovery",
            policy_level="P0",
            sentiment_index=0.5,
            active_signals=[],
        )

        scored_asset = scorer.score(asset, context)

        # 验证各维度得分已设置
        assert scored_asset.regime_score > 0
        assert scored_asset.policy_score > 0
        assert scored_asset.sentiment_score > 0
        assert scored_asset.signal_score == 50  # 无信号
        assert scored_asset.total_score > 0

    def test_score_batch_assets(self):
        """测试批量资产评分"""
        class MockWeightRepo:
            def get_active_weights(self, asset_type=None):
                return WeightConfig()

        scorer = AssetMultiDimScorer(MockWeightRepo())

        assets = [
            AssetScore(
                asset_type=AssetType.EQUITY,
                asset_code=f"00000{i}",
                asset_name=f"测试股票{i}",
                style=AssetStyle.GROWTH,
            )
            for i in range(1, 6)
        ]

        context = ScoreContext(
            current_regime="Recovery",
            policy_level="P0",
            sentiment_index=0.5,
            active_signals=[],
        )

        scored_assets = scorer.score_batch(assets, context)

        # 验证排序
        assert scored_assets[0].rank == 1
        assert scored_assets[1].rank == 2

        # 验证排名按得分降序
        for i in range(len(scored_assets) - 1):
            assert scored_assets[i].total_score >= scored_assets[i + 1].total_score
