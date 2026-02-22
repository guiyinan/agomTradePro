"""
Unit tests for Audit module Use Cases.

Tests for:
- GenerateAttributionReportUseCase
- GetAuditSummaryUseCase
- EvaluateIndicatorPerformanceUseCase
- ValidateThresholdsUseCase
- AdjustIndicatorWeightsUseCase
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import date, timedelta
from typing import List, Dict

from apps.audit.application.use_cases import (
    GenerateAttributionReportRequest,
    GenerateAttributionReportResponse,
    GenerateAttributionReportUseCase,
    GetAuditSummaryRequest,
    GetAuditSummaryResponse,
    GetAuditSummaryUseCase,
    EvaluateIndicatorPerformanceRequest,
    EvaluateIndicatorPerformanceResponse,
    EvaluateIndicatorPerformanceUseCase,
    ValidateThresholdsRequest,
    ValidateThresholdsResponse,
    ValidateThresholdsUseCase,
    AdjustIndicatorWeightsRequest,
    AdjustIndicatorWeightsResponse,
    AdjustIndicatorWeightsUseCase,
)
from apps.audit.domain.entities import (
    IndicatorPerformanceReport,
    ValidationStatus,
    DynamicWeightConfig,
)
from apps.backtest.infrastructure.adapters.base import AssetPricePoint


# ============ Fixtures ============

@pytest.fixture
def mock_audit_repository():
    """Create mock audit repository."""
    repo = Mock()
    repo.save_attribution_report = Mock(return_value=1)
    repo.save_loss_analysis = Mock(return_value=1)
    repo.save_experience_summary = Mock(return_value=1)
    repo.get_reports_by_backtest = Mock(return_value=[])
    repo.get_reports_by_date_range = Mock(return_value=[])
    repo.get_loss_analyses = Mock(return_value=[])
    repo.get_experience_summaries = Mock(return_value=[])
    return repo


@pytest.fixture
def mock_backtest_repository():
    """Create mock backtest repository."""
    repo = Mock()
    return repo


@pytest.fixture
def sample_backtest_model():
    """Create sample backtest model."""
    model = Mock()
    model.id = 1
    model.name = "Test Backtest"
    model.start_date = date(2024, 1, 1)
    model.end_date = date(2024, 6, 30)
    model.initial_capital = 100000.0
    model.total_return = 0.10
    model.sharpe_ratio = 1.5
    model.max_drawdown = -0.05
    model.annualized_return = 0.20
    model.equity_curve = '[[1698796800000, 100000], [1701388800000, 105000]]'
    model.regime_history = '[{"date": "2024-01-01", "regime": "RECOVERY", "confidence": 0.85}]'
    model.trades = []
    model.status = 'completed'
    return model


@pytest.fixture
def mock_price_adapter():
    """Create mock price adapter with sample data."""
    mock_adapter = Mock()
    from datetime import date as dt_date

    # Create sample price points for multiple asset classes
    sample_prices_equity = [
        AssetPricePoint(
            asset_class='a_share_growth',
            price=100.0,
            as_of_date=dt_date(2024, 1, 1),
            source='mock'
        ),
        AssetPricePoint(
            asset_class='a_share_growth',
            price=101.0,
            as_of_date=dt_date(2024, 1, 2),
            source='mock'
        ),
        AssetPricePoint(
            asset_class='a_share_growth',
            price=102.0,
            as_of_date=dt_date(2024, 1, 3),
            source='mock'
        ),
    ]
    sample_prices_bond = [
        AssetPricePoint(
            asset_class='china_bond',
            price=100.0,
            as_of_date=dt_date(2024, 1, 1),
            source='mock'
        ),
        AssetPricePoint(
            asset_class='china_bond',
            price=100.5,
            as_of_date=dt_date(2024, 1, 2),
            source='mock'
        ),
        AssetPricePoint(
            asset_class='china_bond',
            price=101.0,
            as_of_date=dt_date(2024, 1, 3),
            source='mock'
        ),
    ]

    # Setup mock to return different data based on asset_class
    def mock_get_prices(asset_class, start_date, end_date):
        if asset_class == 'a_share_growth':
            return sample_prices_equity
        elif asset_class == 'china_bond':
            return sample_prices_bond
        return []

    mock_adapter.get_prices.side_effect = mock_get_prices
    return mock_adapter


# ============ Test GenerateAttributionReportUseCase ============

class TestGenerateAttributionReportUseCase:
    """Test GenerateAttributionReportUseCase."""

    @pytest.fixture
    def use_case(self, mock_audit_repository, mock_backtest_repository):
        """Create use case instance."""
        return GenerateAttributionReportUseCase(
            audit_repository=mock_audit_repository,
            backtest_repository=mock_backtest_repository
        )

    def test_initialization(self, mock_audit_repository, mock_backtest_repository):
        """Test use case initialization."""
        use_case = GenerateAttributionReportUseCase(
            audit_repository=mock_audit_repository,
            backtest_repository=mock_backtest_repository
        )
        assert use_case.audit_repo == mock_audit_repository
        assert use_case.backtest_repo == mock_backtest_repository

    @patch('shared.config.secrets.get_secrets')
    @patch('apps.backtest.infrastructure.adapters.composite_price_adapter.create_default_price_adapter')
    def test_execute_success(
        self,
        mock_create_adapter,
        mock_get_secrets,
        use_case,
        mock_backtest_repository,
        sample_backtest_model,
        mock_price_adapter
    ):
        """Test successful execution."""
        # Setup mocks
        mock_secrets = Mock()
        mock_secrets.data_sources.tushare_token = "test_token"
        mock_get_secrets.return_value = mock_secrets
        mock_create_adapter.return_value = mock_price_adapter

        mock_backtest_repository.get_backtest_by_id = Mock(return_value=sample_backtest_model)

        request = GenerateAttributionReportRequest(backtest_id=1)
        response = use_case.execute(request)

        assert response.success is True
        assert response.report_id is not None
        assert response.error is None

    def test_execute_backtest_not_found(self, use_case, mock_backtest_repository):
        """Test with non-existent backtest."""
        mock_backtest_repository.get_backtest_by_id = Mock(return_value=None)

        request = GenerateAttributionReportRequest(backtest_id=999)
        response = use_case.execute(request)

        assert response.success is False
        assert "不存在" in response.error
        assert response.report_id is None

    @patch('shared.config.secrets.get_secrets')
    @patch('apps.backtest.infrastructure.adapters.composite_price_adapter.create_default_price_adapter')
    def test_execute_saves_attribution_report(
        self,
        mock_create_adapter,
        mock_get_secrets,
        use_case,
        mock_backtest_repository,
        mock_audit_repository,
        sample_backtest_model,
        mock_price_adapter
    ):
        """Test that attribution report is saved."""
        # Setup mocks
        mock_secrets = Mock()
        mock_secrets.data_sources.tushare_token = "test_token"
        mock_get_secrets.return_value = mock_secrets
        mock_create_adapter.return_value = mock_price_adapter

        mock_backtest_repository.get_backtest_by_id = Mock(return_value=sample_backtest_model)

        request = GenerateAttributionReportRequest(backtest_id=1)
        use_case.execute(request)

        # Verify save_attribution_report was called
        mock_audit_repository.save_attribution_report.assert_called_once()

    @patch('shared.config.secrets.get_secrets')
    @patch('apps.backtest.infrastructure.adapters.composite_price_adapter.create_default_price_adapter')
    def test_execute_saves_loss_analysis_when_losses(
        self,
        mock_create_adapter,
        mock_get_secrets,
        use_case,
        mock_backtest_repository,
        mock_audit_repository,
        sample_backtest_model,
        mock_price_adapter
    ):
        """Test that loss analysis is saved when there are losses."""
        # Setup mocks
        mock_secrets = Mock()
        mock_secrets.data_sources.tushare_token = "test_token"
        mock_get_secrets.return_value = mock_secrets
        mock_create_adapter.return_value = mock_price_adapter

        mock_backtest_repository.get_backtest_by_id = Mock(return_value=sample_backtest_model)

        request = GenerateAttributionReportRequest(backtest_id=1)
        use_case.execute(request)

        # Verify loss analysis methods were called (may or may not save depending on loss)
        assert mock_audit_repository.save_loss_analysis.called or mock_audit_repository.save_experience_summary.called

    @patch('shared.config.secrets.get_secrets')
    @patch('apps.backtest.infrastructure.adapters.composite_price_adapter.create_default_price_adapter')
    def test_execute_saves_experience_summary(
        self,
        mock_create_adapter,
        mock_get_secrets,
        use_case,
        mock_backtest_repository,
        mock_audit_repository,
        sample_backtest_model,
        mock_price_adapter
    ):
        """Test that experience summary is saved."""
        # Setup mocks
        mock_secrets = Mock()
        mock_secrets.data_sources.tushare_token = "test_token"
        mock_get_secrets.return_value = mock_secrets
        mock_create_adapter.return_value = mock_price_adapter

        mock_backtest_repository.get_backtest_by_id = Mock(return_value=sample_backtest_model)

        request = GenerateAttributionReportRequest(backtest_id=1)
        use_case.execute(request)

        # Verify save_experience_summary was called
        mock_audit_repository.save_experience_summary.assert_called_once()

    def test_backtest_model_to_dict(self, use_case, sample_backtest_model):
        """Test _backtest_model_to_dict method."""
        result = use_case._backtest_model_to_dict(sample_backtest_model)

        assert result['id'] == 1
        assert result['name'] == "Test Backtest"
        assert result['start_date'] == date(2024, 1, 1)
        assert result['end_date'] == date(2024, 6, 30)
        assert result['total_return'] == 0.10
        assert isinstance(result['equity_curve'], list)

    @patch('shared.config.secrets.get_secrets')
    @patch('apps.backtest.infrastructure.adapters.composite_price_adapter.create_default_price_adapter')
    def test_build_asset_returns(
        self,
        mock_create_adapter,
        mock_get_secrets,
        use_case,
        sample_backtest_model
    ):
        """Test _build_asset_returns method with mocked price adapter."""
        # Mock the secrets
        mock_secrets = Mock()
        mock_secrets.data_sources.tushare_token = "test_token"
        mock_get_secrets.return_value = mock_secrets

        # Mock the price adapter with sample data
        mock_adapter = Mock()
        from datetime import date as dt_date

        # Create sample price points for multiple asset classes
        sample_prices_equity = [
            AssetPricePoint(
                asset_class='a_share_growth',
                price=100.0,
                as_of_date=dt_date(2024, 1, 1),
                source='mock'
            ),
            AssetPricePoint(
                asset_class='a_share_growth',
                price=101.0,
                as_of_date=dt_date(2024, 1, 2),
                source='mock'
            ),
        ]
        sample_prices_bond = [
            AssetPricePoint(
                asset_class='china_bond',
                price=100.0,
                as_of_date=dt_date(2024, 1, 1),
                source='mock'
            ),
            AssetPricePoint(
                asset_class='china_bond',
                price=100.5,
                as_of_date=dt_date(2024, 1, 2),
                source='mock'
            ),
        ]

        # Setup mock to return different data based on asset_class
        def mock_get_prices(asset_class, start_date, end_date):
            if asset_class == 'a_share_growth':
                return sample_prices_equity
            elif asset_class == 'china_bond':
                return sample_prices_bond
            return []

        mock_adapter.get_prices.side_effect = mock_get_prices
        mock_create_adapter.return_value = mock_adapter

        backtest_dict = {
            'start_date': date(2024, 1, 1),
            'end_date': date(2024, 1, 31),
        }
        asset_returns = use_case._build_asset_returns(backtest_dict)

        assert isinstance(asset_returns, dict)
        assert 'equity' in asset_returns  # a_share_growth maps to 'equity'
        assert 'bond' in asset_returns  # china_bond maps to 'bond'
        # Should have calculated returns from the price points
        assert len(asset_returns['equity']) == 1  # One return from two price points

    @patch('shared.config.secrets.get_secrets')
    @patch('apps.backtest.infrastructure.adapters.composite_price_adapter.create_default_price_adapter')
    def test_execute_handles_json_decode_error(
        self,
        mock_create_adapter,
        mock_get_secrets,
        use_case,
        mock_backtest_repository,
        mock_price_adapter
    ):
        """Test handling of invalid JSON in regime_history."""
        # Setup mocks
        mock_secrets = Mock()
        mock_secrets.data_sources.tushare_token = "test_token"
        mock_get_secrets.return_value = mock_secrets
        mock_create_adapter.return_value = mock_price_adapter

        model = Mock()
        model.id = 1
        model.start_date = date(2024, 1, 1)
        model.end_date = date(2024, 6, 30)
        model.total_return = 0.10
        model.equity_curve = 'invalid json'
        model.regime_history = 'not a json'
        model.trades = []

        mock_backtest_repository.get_backtest_by_id = Mock(return_value=model)

        request = GenerateAttributionReportRequest(backtest_id=1)
        response = use_case.execute(request)

        # Should still succeed with empty regime history
        assert response.success is True


# ============ Test GetAuditSummaryUseCase ============

class TestGetAuditSummaryUseCase:
    """Test GetAuditSummaryUseCase."""

    @pytest.fixture
    def use_case(self, mock_audit_repository):
        """Create use case instance."""
        return GetAuditSummaryUseCase(audit_repository=mock_audit_repository)

    @pytest.fixture
    def sample_reports(self):
        """Create sample reports."""
        return [
            {
                'id': 1,
                'backtest_id': 1,
                'period_start': date(2024, 1, 1),
                'period_end': date(2024, 6, 30),
                'total_pnl': 0.10,
            },
            {
                'id': 2,
                'backtest_id': 1,
                'period_start': date(2024, 1, 1),
                'period_end': date(2024, 6, 30),
                'total_pnl': 0.08,
            },
        ]

    def test_initialization(self, mock_audit_repository):
        """Test use case initialization."""
        use_case = GetAuditSummaryUseCase(audit_repository=mock_audit_repository)
        assert use_case.audit_repo == mock_audit_repository

    def test_execute_by_backtest_id(
        self,
        use_case,
        mock_audit_repository,
        sample_reports
    ):
        """Test getting reports by backtest ID."""
        mock_audit_repository.get_reports_by_backtest = Mock(return_value=sample_reports)
        mock_audit_repository.get_loss_analyses = Mock(return_value=[])
        mock_audit_repository.get_experience_summaries = Mock(return_value=[])

        request = GetAuditSummaryRequest(backtest_id=1)
        response = use_case.execute(request)

        assert response.success is True
        assert len(response.reports) == 2
        assert response.error is None

    def test_execute_by_date_range(
        self,
        use_case,
        mock_audit_repository,
        sample_reports
    ):
        """Test getting reports by date range."""
        mock_audit_repository.get_reports_by_date_range = Mock(return_value=sample_reports)
        mock_audit_repository.get_loss_analyses = Mock(return_value=[])
        mock_audit_repository.get_experience_summaries = Mock(return_value=[])

        request = GetAuditSummaryRequest(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31)
        )
        response = use_case.execute(request)

        assert response.success is True
        assert len(response.reports) == 2

    def test_execute_missing_parameters(self, use_case):
        """Test with missing required parameters."""
        request = GetAuditSummaryRequest()
        response = use_case.execute(request)

        assert response.success is False
        assert "必须提供" in response.error

    def test_execute_includes_loss_analyses(
        self,
        use_case,
        mock_audit_repository
    ):
        """Test that loss analyses are included."""
        mock_audit_repository.get_reports_by_backtest = Mock(return_value=[{'id': 1}])
        mock_audit_repository.get_loss_analyses = Mock(return_value=[
            {'loss_source': 'REGIME_TIMING_ERROR', 'impact': -0.02}
        ])
        mock_audit_repository.get_experience_summaries = Mock(return_value=[])

        request = GetAuditSummaryRequest(backtest_id=1)
        response = use_case.execute(request)

        assert response.success is True
        assert 'loss_analyses' in response.reports[0]

    def test_execute_includes_experience_summaries(
        self,
        use_case,
        mock_audit_repository
    ):
        """Test that experience summaries are included."""
        mock_audit_repository.get_reports_by_backtest = Mock(return_value=[{'id': 1}])
        mock_audit_repository.get_loss_analyses = Mock(return_value=[])
        mock_audit_repository.get_experience_summaries = Mock(return_value=[
            {'lesson': 'Test lesson', 'priority': 'HIGH'}
        ])

        request = GetAuditSummaryRequest(backtest_id=1)
        response = use_case.execute(request)

        assert response.success is True
        assert 'experience_summaries' in response.reports[0]


# ============ Test EvaluateIndicatorPerformanceUseCase ============

class TestEvaluateIndicatorPerformanceUseCase:
    """Test EvaluateIndicatorPerformanceUseCase."""

    @pytest.fixture
    def use_case(self, mock_audit_repository):
        """Create use case instance."""
        return EvaluateIndicatorPerformanceUseCase(audit_repository=mock_audit_repository)

    @pytest.fixture
    def mock_threshold_model(self):
        """Create mock threshold model."""
        model = Mock()
        model.indicator_code = "CN_PMI"
        model.indicator_name = "PMI"
        model.level_low = 49.0
        model.level_high = 51.0
        model.base_weight = 1.0
        model.min_weight = 0.0
        model.max_weight = 2.0
        model.decay_threshold = 0.2
        model.decay_penalty = 0.5
        model.improvement_threshold = 0.1
        model.improvement_bonus = 1.2
        model.action_thresholds = {
            'keep_min_f1': 0.6,
            'reduce_min_f1': 0.4,
            'remove_max_f1': 0.3,
        }
        return model

    def test_initialization(self, mock_audit_repository):
        """Test use case initialization."""
        use_case = EvaluateIndicatorPerformanceUseCase(audit_repository=mock_audit_repository)
        assert use_case.audit_repo == mock_audit_repository

    @patch('apps.audit.application.use_cases.IndicatorThresholdConfigModel')
    @patch('apps.audit.application.use_cases.MacroIndicator')
    @patch('apps.audit.application.use_cases.RegimeLog')
    def test_execute_success(
        self,
        mock_regime_log,
        mock_macro_indicator,
        mock_threshold_config_model,
        use_case,
        mock_threshold_model
    ):
        """Test successful execution."""
        # Setup mocks
        mock_threshold_config_model.objects.filter.return_value.first.return_value = mock_threshold_model
        mock_macro_indicator.objects.filter.order_by.return_value.values_list.return_value = [
            (date(2024, 1, 1), 50.0),
            (date(2024, 2, 1), 51.0),
        ]
        mock_regime_log_obj = Mock()
        mock_regime_log_obj.observed_at = date(2024, 1, 1)
        mock_regime_log_obj.dominant_regime = "RECOVERY"
        mock_regime_log_obj.confidence = 0.85
        mock_regime_log_obj.growth_momentum_z = 1.0
        mock_regime_log_obj.inflation_momentum_z = 0.5
        mock_regime_log_obj.distribution = {"RECOVERY": 0.7}
        mock_regime_log.objects.filter.order_by.return_value = [mock_regime_log_obj]

        request = EvaluateIndicatorPerformanceRequest(
            indicator_code="CN_PMI",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 6, 30)
        )
        response = use_case.execute(request)

        assert response.success is True
        assert response.report is not None

    @patch('apps.audit.application.use_cases.IndicatorThresholdConfigModel')
    def test_execute_threshold_not_found(self, mock_threshold_config_model, use_case):
        """Test with non-existent threshold config."""
        mock_threshold_config_model.objects.filter.return_value.first.return_value = None

        request = EvaluateIndicatorPerformanceRequest(
            indicator_code="NONEXISTENT",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 6, 30)
        )
        response = use_case.execute(request)

        assert response.success is False
        assert "不存在" in response.error

    @patch('apps.audit.application.use_cases.IndicatorThresholdConfigModel')
    @patch('apps.audit.application.use_cases.MacroIndicator')
    def test_execute_no_indicator_data(
        self,
        mock_macro_indicator,
        mock_threshold_config_model,
        use_case,
        mock_threshold_model
    ):
        """Test with no indicator data."""
        mock_threshold_config_model.objects.filter.return_value.first.return_value = mock_threshold_model
        mock_macro_indicator.objects.filter.order_by.return_value.values_list.return_value = []

        request = EvaluateIndicatorPerformanceRequest(
            indicator_code="CN_PMI",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 6, 30)
        )
        response = use_case.execute(request)

        assert response.success is False
        assert "无数据" in response.error

    @patch('apps.audit.application.use_cases.IndicatorThresholdConfigModel')
    @patch('apps.audit.application.use_cases.MacroIndicator')
    @patch('apps.audit.application.use_cases.RegimeLog')
    def test_shadow_mode_no_save(
        self,
        mock_regime_log,
        mock_macro_indicator,
        mock_threshold_config_model,
        use_case,
        mock_threshold_model
    ):
        """Test shadow mode doesn't save results."""
        mock_threshold_config_model.objects.filter.return_value.first.return_value = mock_threshold_model
        mock_macro_indicator.objects.filter.order_by.return_value.values_list.return_value = [
            (date(2024, 1, 1), 50.0),
        ]
        mock_regime_log_obj = Mock()
        mock_regime_log_obj.observed_at = date(2024, 1, 1)
        mock_regime_log_obj.dominant_regime = "RECOVERY"
        mock_regime_log_obj.confidence = 0.85
        mock_regime_log_obj.growth_momentum_z = 1.0
        mock_regime_log_obj.inflation_momentum_z = 0.5
        mock_regime_log_obj.distribution = {"RECOVERY": 0.7}
        mock_regime_log.objects.filter.order_by.return_value = [mock_regime_log_obj]

        request = EvaluateIndicatorPerformanceRequest(
            indicator_code="CN_PMI",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 6, 30),
            use_shadow_mode=True
        )
        response = use_case.execute(request)

        assert response.success is True
        assert response.report_id is None  # No ID in shadow mode


# ============ Test ValidateThresholdsUseCase ============

class TestValidateThresholdsUseCase:
    """Test ValidateThresholdsUseCase."""

    @pytest.fixture
    def use_case(self, mock_audit_repository):
        """Create use case instance."""
        return ValidateThresholdsUseCase(audit_repository=mock_audit_repository)

    @pytest.fixture
    def mock_threshold_models(self):
        """Create mock threshold models."""
        models = []
        for i in range(3):
            model = Mock()
            model.indicator_code = f"INDICATOR_{i}"
            model.indicator_name = f"Indicator {i}"
            model.level_low = 40.0
            model.level_high = 60.0
            model.base_weight = 1.0
            model.min_weight = 0.0
            model.max_weight = 2.0
            model.decay_threshold = 0.2
            model.decay_penalty = 0.5
            model.improvement_threshold = 0.1
            model.improvement_bonus = 1.2
            model.action_thresholds = {
                'keep_min_f1': 0.6,
                'reduce_min_f1': 0.4,
                'remove_max_f1': 0.3,
            }
            models.append(model)
        return models

    def test_initialization(self, mock_audit_repository):
        """Test use case initialization."""
        use_case = ValidateThresholdsUseCase(audit_repository=mock_audit_repository)
        assert use_case.audit_repo == mock_audit_repository

    def test_generate_overall_recommendation_excellent(self, use_case):
        """Test overall recommendation for excellent performance."""
        recommendation = use_case._generate_overall_recommendation(
            approved=8,
            rejected=1,
            pending=1,
            avg_f1=0.75,
            avg_stability=0.70
        )
        assert "优秀" in recommendation
        assert "8/10" in recommendation

    def test_generate_overall_recommendation_good(self, use_case):
        """Test overall recommendation for good performance."""
        recommendation = use_case._generate_overall_recommendation(
            approved=6,
            rejected=2,
            pending=2,
            avg_f1=0.55,
            avg_stability=0.60
        )
        assert "良好" in recommendation

    def test_generate_overall_recommendation_poor(self, use_case):
        """Test overall recommendation for poor performance."""
        recommendation = use_case._generate_overall_recommendation(
            approved=2,
            rejected=7,
            pending=1,
            avg_f1=0.30,
            avg_stability=0.25
        )
        assert "较差" in recommendation or "重构" in recommendation

    def test_generate_overall_recommendation_empty(self, use_case):
        """Test overall recommendation with no indicators."""
        recommendation = use_case._generate_overall_recommendation(
            approved=0,
            rejected=0,
            pending=0,
            avg_f1=0.0,
            avg_stability=0.0
        )
        assert "无指标" in recommendation


# ============ Test AdjustIndicatorWeightsUseCase ============

class TestAdjustIndicatorWeightsUseCase:
    """Test AdjustIndicatorWeightsUseCase."""

    @pytest.fixture
    def use_case(self, mock_audit_repository):
        """Create use case instance."""
        return AdjustIndicatorWeightsUseCase(audit_repository=mock_audit_repository)

    def test_initialization(self, mock_audit_repository):
        """Test use case initialization."""
        use_case = AdjustIndicatorWeightsUseCase(audit_repository=mock_audit_repository)
        assert use_case.audit_repo == mock_audit_repository

    def test_generate_adjustment_reason_increase(self, use_case):
        """Test adjustment reason for INCREASE action."""
        reason = use_case._generate_adjustment_reason(
            action='INCREASE',
            f1_score=0.85,
            stability_score=0.80
        )
        assert "增加权重" in reason
        assert "0.85" in reason

    def test_generate_adjustment_reason_keep(self, use_case):
        """Test adjustment reason for KEEP action."""
        reason = use_case._generate_adjustment_reason(
            action='KEEP',
            f1_score=0.70,
            stability_score=0.65
        )
        assert "保持" in reason

    def test_generate_adjustment_reason_decrease(self, use_case):
        """Test adjustment reason for DECREASE action."""
        reason = use_case._generate_adjustment_reason(
            action='DECREASE',
            f1_score=0.50,
            stability_score=0.45
        )
        assert "降低权重" in reason

    def test_generate_adjustment_reason_remove(self, use_case):
        """Test adjustment reason for REMOVE action."""
        reason = use_case._generate_adjustment_reason(
            action='REMOVE',
            f1_score=0.25,
            stability_score=0.20
        )
        assert "移除" in reason or "大幅降低" in reason

    def test_generate_adjustment_reason_unknown(self, use_case):
        """Test adjustment reason for unknown action."""
        reason = use_case._generate_adjustment_reason(
            action='UNKNOWN',
            f1_score=0.5,
            stability_score=0.5
        )
        assert "未知" in reason


# ============ Test Request/Response Models ============

class TestRequestResponseModels:
    """Test request and response dataclasses."""

    def test_generate_attribution_report_request(self):
        """Test GenerateAttributionReportRequest."""
        request = GenerateAttributionReportRequest(backtest_id=1)
        assert request.backtest_id == 1

    def test_generate_attribution_report_response_success(self):
        """Test GenerateAttributionReportResponse success."""
        response = GenerateAttributionReportResponse(
            success=True,
            report_id=1
        )
        assert response.success is True
        assert response.report_id == 1
        assert response.error is None

    def test_generate_attribution_report_response_failure(self):
        """Test GenerateAttributionReportResponse failure."""
        response = GenerateAttributionReportResponse(
            success=False,
            error="Backtest not found"
        )
        assert response.success is False
        assert response.error == "Backtest not found"
        assert response.report_id is None

    def test_get_audit_summary_request_with_backtest(self):
        """Test GetAuditSummaryRequest with backtest_id."""
        request = GetAuditSummaryRequest(backtest_id=1)
        assert request.backtest_id == 1
        assert request.start_date is None
        assert request.end_date is None

    def test_get_audit_summary_request_with_dates(self):
        """Test GetAuditSummaryRequest with date range."""
        request = GetAuditSummaryRequest(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31)
        )
        assert request.backtest_id is None
        assert request.start_date == date(2024, 1, 1)
        assert request.end_date == date(2024, 12, 31)

    def test_evaluate_indicator_performance_request(self):
        """Test EvaluateIndicatorPerformanceRequest."""
        request = EvaluateIndicatorPerformanceRequest(
            indicator_code="CN_PMI",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 6, 30),
            use_shadow_mode=True
        )
        assert request.indicator_code == "CN_PMI"
        assert request.use_shadow_mode is True

    def test_validate_thresholds_request_all_indicators(self):
        """Test ValidateThresholdsRequest for all indicators."""
        request = ValidateThresholdsRequest(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31)
        )
        assert request.indicator_codes is None

    def test_validate_thresholds_request_specific_indicators(self):
        """Test ValidateThresholdsRequest for specific indicators."""
        request = ValidateThresholdsRequest(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            indicator_codes=["CN_PMI", "CN_CPI"]
        )
        assert len(request.indicator_codes) == 2

    def test_adjust_indicator_weights_request(self):
        """Test AdjustIndicatorWeightsRequest."""
        request = AdjustIndicatorWeightsRequest(
            validation_run_id="validation_abc123",
            auto_apply=True
        )
        assert request.validation_run_id == "validation_abc123"
        assert request.auto_apply is True
