"""
特征提供者单元测试

测试 Top-down 和 Bottom-up 特征提供者。
"""

from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone

from apps.alpha_trigger.domain.entities import SignalStrength
from apps.decision_rhythm.infrastructure.feature_providers import (
    AlphaCandidateProvider,
    AlphaModelFeatureProvider,
    AlphaSignalProvider,
    AssetValuationProvider,
    BetaGateFeatureProvider,
    CompositeFeatureProvider,
    FlowFeatureProvider,
    FundamentalFeatureProvider,
    PolicyFeatureProvider,
    RegimeFeatureProvider,
    SentimentFeatureProvider,
    TechnicalFeatureProvider,
)


class TestRegimeFeatureProvider:
    """测试 Regime 特征提供者"""

    def test_get_regime_success(self):
        """测试成功获取 Regime"""
        with patch(
            "apps.regime.application.current_regime.resolve_current_regime"
        ) as mock_resolve:
            mock_result = MagicMock()
            mock_result.dominant_regime = "GROWTH_INFLATION"
            mock_result.confidence = 0.85
            mock_result.observed_at = date.today()
            mock_result.data_source = "tushare"
            mock_result.is_fallback = False
            mock_result.warnings = []
            mock_resolve.return_value = mock_result

            provider = RegimeFeatureProvider()
            result = provider.get_regime()

            assert result is not None
            assert result["regime"] == "GROWTH_INFLATION"
            assert result["confidence"] == 0.85
            assert result["is_fallback"] is False

    def test_get_regime_failure(self):
        """测试获取 Regime 失败"""
        with patch(
            "apps.regime.application.current_regime.resolve_current_regime"
        ) as mock_resolve:
            mock_resolve.side_effect = Exception("Connection error")

            provider = RegimeFeatureProvider()
            result = provider.get_regime()

            assert result is None


class TestPolicyFeatureProvider:
    """测试 Policy 特征提供者"""

    def test_get_policy_level_success(self):
        """测试成功获取政策档位"""
        with patch(
            "apps.policy.infrastructure.repositories.DjangoPolicyRepository"
        ) as mock_repo_class:
            mock_repo = MagicMock()
            mock_level = MagicMock()
            mock_level.value = "LEVEL_2"
            mock_repo.get_current_policy_level.return_value = mock_level
            mock_repo_class.return_value = mock_repo

            provider = PolicyFeatureProvider()
            result = provider.get_policy_level()

            assert result == "LEVEL_2"

    def test_get_policy_level_none(self):
        """测试政策档位为空"""
        with patch(
            "apps.policy.infrastructure.repositories.DjangoPolicyRepository"
        ) as mock_repo_class:
            mock_repo = MagicMock()
            mock_repo.get_current_policy_level.return_value = None
            mock_repo_class.return_value = mock_repo

            provider = PolicyFeatureProvider()
            result = provider.get_policy_level()

            assert result == "LEVEL_0"

    def test_get_policy_level_error(self):
        """测试获取政策档位失败"""
        with patch(
            "apps.policy.infrastructure.repositories.DjangoPolicyRepository"
        ) as mock_repo_class:
            mock_repo_class.side_effect = Exception("DB error")

            provider = PolicyFeatureProvider()
            result = provider.get_policy_level()

            assert result == "LEVEL_0"


class TestBetaGateFeatureProvider:
    """测试 Beta Gate 特征提供者"""

    def test_check_beta_gate_pass(self):
        """测试 Beta Gate 通过"""
        with patch(
            "apps.beta_gate.application.use_cases.EvaluateBetaGateUseCase"
        ) as mock_use_case_class:
            mock_use_case = MagicMock()
            mock_decision = MagicMock()
            mock_decision.is_passed = True
            mock_use_case.execute.return_value = MagicMock(
                success=True,
                decision=mock_decision,
            )
            mock_use_case_class.return_value = mock_use_case

            provider = BetaGateFeatureProvider()
            result = provider.check_beta_gate("000001.SZ")

            assert result is True

    def test_check_beta_gate_fail(self):
        """测试 Beta Gate 不通过"""
        with patch(
            "apps.beta_gate.application.use_cases.EvaluateBetaGateUseCase"
        ) as mock_use_case_class:
            mock_use_case = MagicMock()
            mock_decision = MagicMock()
            mock_decision.is_passed = False
            mock_use_case.execute.return_value = MagicMock(
                success=True,
                decision=mock_decision,
            )
            mock_use_case_class.return_value = mock_use_case

            provider = BetaGateFeatureProvider()
            result = provider.check_beta_gate("000001.SZ")

            assert result is False

    def test_check_beta_gate_error(self):
        """测试 Beta Gate 检查失败（默认通过）"""
        with patch(
            "apps.beta_gate.application.use_cases.EvaluateBetaGateUseCase"
        ) as mock_use_case_class:
            mock_use_case_class.side_effect = Exception("Gate error")

            provider = BetaGateFeatureProvider()
            result = provider.check_beta_gate("000001.SZ")

            # 默认通过，避免因检查失败而阻塞所有推荐
            assert result is True


class TestSentimentFeatureProvider:
    """测试舆情特征提供者"""

    def test_get_sentiment_score_success(self):
        """测试成功获取舆情分数"""
        with patch(
            "apps.sentiment.infrastructure.repositories.SentimentIndexRepository"
        ) as mock_repo_class:
            mock_repo = MagicMock()
            mock_sentiment = MagicMock()
            mock_sentiment.composite_index = 1.5  # -3~3 范围，1.5 归一化后为 (1.5+3)/6 = 0.75
            mock_repo.get_by_date.return_value = mock_sentiment
            mock_repo_class.return_value = mock_repo

            provider = SentimentFeatureProvider()
            result = provider.get_sentiment_score("000001.SZ")

            # composite_index 1.5 归一化到 (1.5 + 3) / 6 = 0.75
            assert abs(result - 0.75) < 0.01

    def test_get_sentiment_score_default(self):
        """测试获取舆情分数失败时返回默认值"""
        with patch(
            "apps.sentiment.infrastructure.repositories.SentimentIndexRepository"
        ) as mock_repo_class:
            mock_repo = MagicMock()
            mock_repo.get_by_date.return_value = None
            mock_repo_class.return_value = mock_repo

            provider = SentimentFeatureProvider()
            result = provider.get_sentiment_score("000001.SZ")

            assert result == 0.5


class TestFlowFeatureProvider:
    """测试资金流向特征提供者"""

    def test_get_flow_score_success(self):
        """测试成功获取资金流向分数"""
        with patch(
            "apps.realtime.infrastructure.repositories.RedisRealtimePriceRepository"
        ) as mock_repo_class:
            mock_repo = MagicMock()
            mock_price = MagicMock()
            mock_price.volume = 150_000_000  # 1.5亿
            mock_repo.get_latest_price.return_value = mock_price
            mock_repo_class.return_value = mock_repo

            provider = FlowFeatureProvider()
            result = provider.get_flow_score("000001.SZ")

            # 使用 sigmoid 函数，成交量 1.5亿应该接近 0.5+
            assert 0.4 <= result <= 0.7

    def test_get_flow_score_default(self):
        """测试获取资金流向分数失败时返回默认值"""
        with patch(
            "apps.realtime.infrastructure.repositories.RedisRealtimePriceRepository"
        ) as mock_repo_class:
            mock_repo = MagicMock()
            mock_repo.get_latest_price.return_value = None
            mock_repo_class.return_value = mock_repo

            provider = FlowFeatureProvider()
            result = provider.get_flow_score("000001.SZ")

            assert result == 0.5


class TestTechnicalFeatureProvider:
    """测试技术面特征提供者"""

    def test_get_technical_score_success(self):
        """测试成功获取技术面分数"""
        with patch(
            "apps.equity.infrastructure.repositories.DjangoStockRepository"
        ) as mock_repo_class:
            mock_repo = MagicMock()
            # 模拟返回股票列表
            mock_stock_info = MagicMock()
            mock_stock_info.stock_code = "000001.SZ"
            mock_repo.get_all_stocks_with_fundamentals.return_value = [
                (mock_stock_info, MagicMock(), MagicMock())
            ]
            mock_repo_class.return_value = mock_repo

            provider = TechnicalFeatureProvider()
            result = provider.get_technical_score("000001.SZ")

            # 目前返回默认值 0.5
            assert result == 0.5

    def test_get_technical_score_default(self):
        """测试获取技术面分数失败时返回默认值"""
        with patch(
            "apps.equity.infrastructure.repositories.DjangoStockRepository"
        ) as mock_repo_class:
            mock_repo = MagicMock()
            mock_repo.get_all_stocks_with_fundamentals.return_value = []
            mock_repo_class.return_value = mock_repo

            provider = TechnicalFeatureProvider()
            result = provider.get_technical_score("000001.SZ")

            assert result == 0.5


class TestFundamentalFeatureProvider:
    """测试基本面特征提供者"""

    def test_get_fundamental_score_success(self):
        """测试成功获取基本面分数"""
        with patch(
            "apps.equity.infrastructure.repositories.DjangoStockRepository"
        ) as mock_repo_class:
            mock_repo = MagicMock()
            # 模拟返回股票列表
            mock_stock_info = MagicMock()
            mock_stock_info.stock_code = "000001.SZ"
            mock_financial = MagicMock()
            mock_financial.roe = 10.0  # ROE 10% 对应 0.5 分
            mock_repo.get_all_stocks_with_fundamentals.return_value = [
                (mock_stock_info, mock_financial, MagicMock())
            ]
            mock_repo_class.return_value = mock_repo

            provider = FundamentalFeatureProvider()
            result = provider.get_fundamental_score("000001.SZ")

            # ROE 10% / 20% = 0.5
            assert result == 0.5

    def test_get_fundamental_score_default(self):
        """测试获取基本面分数失败时返回默认值"""
        with patch(
            "apps.equity.infrastructure.repositories.DjangoStockRepository"
        ) as mock_repo_class:
            mock_repo = MagicMock()
            mock_repo.get_all_stocks_with_fundamentals.return_value = []
            mock_repo_class.return_value = mock_repo

            provider = FundamentalFeatureProvider()
            result = provider.get_fundamental_score("000001.SZ")

            assert result == 0.5


class TestAlphaModelFeatureProvider:
    """测试 Alpha 模型特征提供者"""

    def test_get_alpha_model_score_success(self):
        """测试成功获取 Alpha 模型分数"""
        with patch(
            "apps.alpha.application.services.AlphaService"
        ) as mock_service_class:
            mock_service = MagicMock()
            mock_result = MagicMock()
            mock_result.success = True
            mock_stock_score = MagicMock()
            mock_stock_score.code = "000001.SZ"
            mock_stock_score.score = 0.7  # -1~1 范围，归一化后 (0.7+1)/2 = 0.85
            mock_result.scores = [mock_stock_score]
            mock_service.get_stock_scores.return_value = mock_result
            mock_service_class.return_value = mock_service

            provider = AlphaModelFeatureProvider()
            result = provider.get_alpha_model_score("000001.SZ")

            # score 0.7 归一化到 (0.7 + 1) / 2 = 0.85
            assert abs(result - 0.85) < 0.01

    def test_get_alpha_model_score_default(self):
        """测试获取 Alpha 模型分数失败时返回默认值"""
        with patch(
            "apps.alpha.application.services.AlphaService"
        ) as mock_service_class:
            mock_service_class.side_effect = ImportError()

            with patch(
                "apps.alpha_trigger.infrastructure.repositories.AlphaCandidateRepository"
            ) as mock_repo_class:
                mock_repo = MagicMock()
                mock_repo.get_by_asset.return_value = []
                mock_repo_class.return_value = mock_repo

                provider = AlphaModelFeatureProvider()
                result = provider.get_alpha_model_score("000001.SZ")

                assert result == 0.5

    def test_get_alpha_model_score_from_candidate_confidence(self):
        """测试 Alpha 候选可回退为真实分数，而不是固定中性值"""
        with patch(
            "apps.alpha.application.services.AlphaService"
        ) as mock_service_class:
            mock_service_class.side_effect = ImportError()

            with patch(
                "apps.alpha_trigger.infrastructure.repositories.AlphaCandidateRepository"
            ) as mock_repo_class:
                mock_repo = MagicMock()
                mock_candidate = SimpleNamespace(
                    confidence=0.82,
                    strength=SignalStrength.STRONG,
                )
                mock_repo.get_by_asset.return_value = [mock_candidate]
                mock_repo_class.return_value = mock_repo

                provider = AlphaModelFeatureProvider()
                result = provider.get_alpha_model_score("000001.SZ")

                assert result == 0.82


class TestCompositeFeatureProvider:
    """测试组合特征提供者"""

    def test_composite_provider_has_all_methods(self):
        """测试组合提供者具有所有方法"""
        provider = CompositeFeatureProvider()

        assert hasattr(provider, "get_regime")
        assert hasattr(provider, "get_policy_level")
        assert hasattr(provider, "check_beta_gate")
        assert hasattr(provider, "get_sentiment_score")
        assert hasattr(provider, "get_flow_score")
        assert hasattr(provider, "get_technical_score")
        assert hasattr(provider, "get_fundamental_score")
        assert hasattr(provider, "get_alpha_model_score")

    def test_composite_provider_uses_independent_repository_slots(self):
        """测试组合提供者不会复用错误的 _repository 属性。"""
        with patch(
            "apps.policy.infrastructure.repositories.DjangoPolicyRepository"
        ) as mock_policy_repo_class, patch(
            "apps.sentiment.infrastructure.repositories.SentimentIndexRepository"
        ) as mock_sentiment_repo_class:
            mock_policy_repo = MagicMock()
            mock_policy_level = MagicMock()
            mock_policy_level.value = "LEVEL_2"
            mock_policy_repo.get_current_policy_level.return_value = mock_policy_level
            mock_policy_repo_class.return_value = mock_policy_repo

            mock_sentiment_repo = MagicMock()
            mock_latest = MagicMock()
            mock_latest.composite_index = 1.2
            mock_sentiment_repo.get_by_date.return_value = mock_latest
            mock_sentiment_repo_class.return_value = mock_sentiment_repo

            provider = CompositeFeatureProvider()

            assert provider.get_policy_level() == "LEVEL_2"
            assert provider.get_sentiment_score("000001.SZ") > 0.5
            mock_sentiment_repo.get_by_date.assert_called_once()

    def test_composite_provider_initializes_use_case_and_service_slots(self):
        """测试组合提供者会初始化独立的 use case / service 槽位。"""
        with patch(
            "apps.beta_gate.domain.services.GateConfigSelector"
        ) as mock_selector_class, patch(
            "apps.beta_gate.application.use_cases.EvaluateBetaGateUseCase"
        ) as mock_use_case_class, patch(
            "apps.alpha.application.services.AlphaService"
        ) as mock_service_class:
            mock_selector = MagicMock()
            mock_selector_class.return_value = mock_selector

            mock_use_case = MagicMock()
            mock_response = MagicMock()
            mock_response.success = False
            mock_response.decision = None
            mock_use_case.execute.return_value = mock_response
            mock_use_case_class.return_value = mock_use_case

            mock_service = MagicMock()
            mock_result = MagicMock()
            mock_result.success = True
            mock_stock_score = MagicMock()
            mock_stock_score.code = "000001.SZ"
            mock_stock_score.score = 0.2
            mock_result.scores = [mock_stock_score]
            mock_service.get_stock_scores.return_value = mock_result
            mock_service_class.return_value = mock_service

            provider = CompositeFeatureProvider()

            assert provider.check_beta_gate("000001.SZ") is False
            assert abs(provider.get_alpha_model_score("000001.SZ") - 0.6) < 0.01
            mock_use_case.execute.assert_called_once()
            mock_service.get_stock_scores.assert_called_once()


class TestAssetValuationProvider:
    """测试资产估值提供者"""

    @pytest.mark.django_db
    def test_get_valuation_from_snapshot(self):
        """测试从估值快照获取估值数据"""
        from decimal import Decimal

        from apps.decision_rhythm.infrastructure.models import ValuationSnapshotModel

        # 创建测试数据
        ValuationSnapshotModel.objects.create(
            snapshot_id="vs_test",
            security_code="000001.SZ",
            valuation_method="PE_BAND",
            fair_value=Decimal("15.50"),
            entry_price_low=Decimal("14.80"),
            entry_price_high=Decimal("15.20"),
            target_price_low=Decimal("18.00"),
            target_price_high=Decimal("20.00"),
            stop_loss_price=Decimal("13.50"),
        )

        provider = AssetValuationProvider()
        result = provider.get_valuation("000001.SZ")

        assert result is not None
        assert result["fair_value"] == 15.50
        assert result["entry_price_low"] == 14.80

    @pytest.mark.django_db
    def test_get_valuation_prefers_data_center_fact_extra_before_fallback(self):
        """测试优先使用 data_center 估值事实中的正式估值字段"""
        with (
            patch(
                "apps.data_center.infrastructure.repositories.ValuationFactRepository"
            ) as mock_fact_repo_class,
            patch(
                "apps.realtime.infrastructure.repositories.RedisRealtimePriceRepository"
            ) as mock_price_repo_class,
        ):
            mock_fact_repo = MagicMock()
            mock_fact_repo.get_latest.return_value = SimpleNamespace(
                val_date=timezone.localdate(),
                extra={"intrinsic_value_per_share": "12.00"},
            )
            mock_fact_repo_class.return_value = mock_fact_repo

            provider = AssetValuationProvider()
            result = provider.get_valuation("000003.SZ")

        assert result is not None
        assert result["valuation_source"] == "data_center_valuation_fact"
        assert result["fair_value"] == 12.0
        assert result["entry_price_low"] == 11.4
        assert result["entry_price_high"] == 12.6
        assert result["target_price_low"] == 13.8
        assert result["target_price_high"] == 15.0
        mock_price_repo_class.assert_not_called()

    @pytest.mark.django_db
    def test_get_valuation_rejects_stale_data_center_fact(self):
        """测试过期 data_center 估值不会只因非零而被使用"""
        from decimal import Decimal

        with (
            patch(
                "apps.data_center.infrastructure.repositories.ValuationFactRepository"
            ) as mock_fact_repo_class,
            patch(
                "apps.realtime.infrastructure.repositories.RedisRealtimePriceRepository"
            ) as mock_price_repo_class,
        ):
            mock_fact_repo = MagicMock()
            mock_fact_repo.get_latest.return_value = SimpleNamespace(
                val_date=timezone.localdate()
                - timedelta(days=AssetValuationProvider.MAX_FORMAL_VALUATION_AGE_DAYS + 1),
                extra={"intrinsic_value_per_share": "12.00", "quality_flag": "ok"},
            )
            mock_fact_repo_class.return_value = mock_fact_repo
            mock_price_repo = MagicMock()
            mock_price_repo.get_latest_price.return_value = SimpleNamespace(
                price=Decimal("10.00")
            )
            mock_price_repo_class.return_value = mock_price_repo

            provider = AssetValuationProvider()
            result = provider.get_valuation("000004.SZ")

        assert result is not None
        assert result["valuation_source"] == "current_price_fallback"
        assert result["fair_value"] == 10.0

    @pytest.mark.django_db
    def test_get_valuation_rejects_invalid_data_center_fact(self):
        """测试低质量 data_center 估值不会只因非零而被使用"""
        from decimal import Decimal

        with (
            patch(
                "apps.data_center.infrastructure.repositories.ValuationFactRepository"
            ) as mock_fact_repo_class,
            patch(
                "apps.realtime.infrastructure.repositories.RedisRealtimePriceRepository"
            ) as mock_price_repo_class,
        ):
            mock_fact_repo = MagicMock()
            mock_fact_repo.get_latest.return_value = SimpleNamespace(
                val_date=timezone.localdate(),
                extra={
                    "intrinsic_value_per_share": "12.00",
                    "is_valid": False,
                    "quality_flag": "invalid_pb",
                },
            )
            mock_fact_repo_class.return_value = mock_fact_repo
            mock_price_repo = MagicMock()
            mock_price_repo.get_latest_price.return_value = SimpleNamespace(
                price=Decimal("10.00")
            )
            mock_price_repo_class.return_value = mock_price_repo

            provider = AssetValuationProvider()
            result = provider.get_valuation("000005.SZ")

        assert result is not None
        assert result["valuation_source"] == "current_price_fallback"
        assert result["fair_value"] == 10.0

    @pytest.mark.django_db
    def test_get_valuation_uses_older_valid_fact_before_fallback(self):
        """测试最新估值质量差时继续查找窗口内可用正式估值"""
        with (
            patch(
                "apps.data_center.infrastructure.repositories.ValuationFactRepository"
            ) as mock_fact_repo_class,
            patch(
                "apps.realtime.infrastructure.repositories.RedisRealtimePriceRepository"
            ) as mock_price_repo_class,
        ):
            mock_fact_repo = MagicMock()
            mock_fact_repo.get_series.return_value = [
                SimpleNamespace(
                    val_date=timezone.localdate(),
                    extra={
                        "intrinsic_value_per_share": "12.00",
                        "is_valid": False,
                        "quality_flag": "invalid_pb",
                    },
                ),
                SimpleNamespace(
                    val_date=timezone.localdate() - timedelta(days=1),
                    extra={"intrinsic_value_per_share": "11.80", "quality_flag": "ok"},
                ),
            ]
            mock_fact_repo_class.return_value = mock_fact_repo

            provider = AssetValuationProvider()
            result = provider.get_valuation("000007.SZ")

        assert result is not None
        assert result["valuation_source"] == "data_center_valuation_fact"
        assert result["fair_value"] == 11.8
        mock_fact_repo.get_latest.assert_not_called()
        mock_price_repo_class.assert_not_called()

    @pytest.mark.django_db
    def test_get_valuation_rejects_legacy_snapshot(self):
        """测试 legacy 快照不会只因价格非零而被推荐使用"""
        from decimal import Decimal

        from apps.decision_rhythm.infrastructure.models import ValuationSnapshotModel

        ValuationSnapshotModel.objects.create(
            snapshot_id="vs_legacy",
            security_code="000006.SZ",
            valuation_method="LEGACY",
            fair_value=Decimal("15.50"),
            entry_price_low=Decimal("14.80"),
            entry_price_high=Decimal("15.20"),
            target_price_low=Decimal("18.00"),
            target_price_high=Decimal("20.00"),
            stop_loss_price=Decimal("13.50"),
            is_legacy=True,
        )

        with patch(
            "apps.realtime.infrastructure.repositories.RedisRealtimePriceRepository"
        ) as mock_price_repo_class:
            mock_price_repo = MagicMock()
            mock_price_repo.get_latest_price.return_value = SimpleNamespace(
                price=Decimal("10.00")
            )
            mock_price_repo_class.return_value = mock_price_repo

            provider = AssetValuationProvider()
            result = provider.get_valuation("000006.SZ")

        assert result is not None
        assert result["valuation_source"] == "current_price_fallback"
        assert result["valuation_method"] == "FALLBACK"

    @pytest.mark.django_db
    def test_get_valuation_creates_current_price_fallback(self):
        """测试估值缺失时基于当前价创建兜底估值快照"""
        from decimal import Decimal

        from apps.decision_rhythm.infrastructure.models import ValuationSnapshotModel

        with patch(
            "apps.realtime.infrastructure.repositories.RedisRealtimePriceRepository"
        ) as mock_repo_class:
            mock_repo = MagicMock()
            mock_repo.get_latest_price.return_value = SimpleNamespace(price=Decimal("10.00"))
            mock_repo_class.return_value = mock_repo

            provider = AssetValuationProvider()
            result = provider.get_valuation("000002.SZ")

        assert result is not None
        assert result["valuation_method"] == "FALLBACK"
        assert result["valuation_source"] == "current_price_fallback"
        assert result["fair_value"] == 10.0
        assert result["entry_price_low"] == 9.5
        assert result["entry_price_high"] == 10.2
        assert result["target_price_low"] == 11.5
        assert result["target_price_high"] == 12.5
        assert result["stop_loss_price"] == 9.0
        assert (
            ValuationSnapshotModel.objects.filter(
                security_code="000002.SZ",
                valuation_method="FALLBACK",
            ).count()
            == 1
        )


class TestAlphaSignalProvider:
    """测试 Alpha 信号提供者"""

    def test_get_active_signals(self):
        """测试获取活跃信号"""
        with patch(
            "apps.alpha_trigger.infrastructure.repositories.AlphaTriggerRepository"
        ) as mock_trigger_repo_class, patch(
            "apps.alpha_trigger.infrastructure.repositories.AlphaCandidateRepository"
        ) as mock_candidate_repo_class:
            # Mock trigger repository
            mock_trigger_repo = MagicMock()
            mock_trigger = MagicMock()
            mock_trigger.trigger_id = "trig_001"
            mock_trigger.asset_code = "000001.SZ"
            mock_trigger.status.value = "ACTIVE"
            mock_trigger_repo.get_active.return_value = [mock_trigger]
            mock_trigger_repo_class.return_value = mock_trigger_repo

            # Mock candidate repository
            mock_candidate_repo = MagicMock()
            mock_candidate = MagicMock()
            mock_candidate.candidate_id = "cand_001"
            mock_candidate.asset_code = "000001.SZ"
            mock_candidate.alpha_score = 0.85
            mock_candidate.status.value = "ACTIONABLE"
            mock_candidate_repo.get_by_asset.return_value = [mock_candidate]
            mock_candidate_repo.get_actionable.return_value = []
            mock_candidate_repo_class.return_value = mock_candidate_repo

            provider = AlphaSignalProvider()
            result = provider.get_active_signals("000001.SZ")

            # 应该包含触发器和候选两个来源的信号
            assert len(result) >= 1


class TestAlphaCandidateProvider:
    """测试 Alpha 候选提供者"""

    def test_get_active_candidates(self):
        """测试获取活跃候选"""
        with patch(
            "apps.alpha_trigger.infrastructure.repositories.AlphaCandidateRepository"
        ) as mock_repo_class:
            mock_repo = MagicMock()
            mock_candidate = MagicMock()
            mock_candidate.candidate_id = "cand_001"
            mock_candidate.asset_code = "000001.SZ"
            mock_candidate.alpha_score = 0.85
            mock_candidate.direction = "BUY"
            mock_repo.get_actionable.return_value = [mock_candidate]
            mock_repo_class.return_value = mock_repo

            provider = AlphaCandidateProvider()
            result = provider.get_active_candidates("account_001")

            assert len(result) == 1
            assert result[0]["candidate_id"] == "cand_001"
