"""
Integration Tests for Regime Actual Calculation in Attribution Reports.

Tests the regime_actual field calculation logic:
1. When regime data is available from RegimeLog
2. When regime data is missing (error codes)
3. When data is insufficient (error codes)
4. When multiple regimes are present (dominant calculation)
5. Edge cases and error handling
"""

import pytest
import json
from datetime import date, timedelta
from unittest.mock import Mock, patch

from apps.audit.application.use_cases import (
    GenerateAttributionReportUseCase,
    GenerateAttributionReportRequest,
)
from apps.audit.infrastructure.repositories import DjangoAuditRepository
from apps.backtest.infrastructure.repositories import DjangoBacktestRepository
from apps.backtest.infrastructure.models import BacktestResultModel
from apps.backtest.infrastructure.adapters.base import AssetPricePoint
from apps.regime.infrastructure.repositories import DjangoRegimeRepository
from apps.regime.domain.entities import RegimeSnapshot
from apps.audit.infrastructure.models import AttributionReport


@pytest.fixture
def mock_price_adapter():
    """Create mock price adapter with sample data."""
    mock_adapter = Mock()

    sample_prices = [
        AssetPricePoint(
            asset_class='a_share_growth',
            price=100.0,
            as_of_date=date(2024, 1, 1),
            source='mock'
        ),
        AssetPricePoint(
            asset_class='a_share_growth',
            price=101.0,
            as_of_date=date(2024, 1, 2),
            source='mock'
        ),
    ]

    mock_adapter.get_prices.return_value = sample_prices
    return mock_adapter


@pytest.mark.django_db
class TestRegimeActualCalculation:
    """Test regime_actual field calculation in attribution reports."""

    @patch('apps.backtest.infrastructure.adapters.composite_price_adapter.create_default_price_adapter')
    @patch('shared.config.secrets.get_secrets')
    def test_regime_actual_with_complete_data(
        self,
        mock_get_secrets,
        mock_create_adapter,
        mock_price_adapter
    ):
        """Test regime_actual when complete regime data is available."""
        # Setup mocks
        mock_secrets = Mock()
        mock_secrets.data_sources.tushare_token = "test_token"
        mock_get_secrets.return_value = mock_secrets
        mock_create_adapter.return_value = mock_price_adapter

        # Create backtest
        start_date = date(2024, 1, 1)
        end_date = date(2024, 3, 31)
        backtest = self._create_backtest(start_date, end_date)
        backtest.save()

        # Create regime data - predominantly Recovery
        regime_repo = DjangoRegimeRepository()
        current_date = start_date
        while current_date <= end_date:
            # Create a pattern: 70% Recovery, 30% Overheat
            if (current_date - start_date).days % 10 < 7:
                regime = "Recovery"
            else:
                regime = "Overheat"

            snapshot = RegimeSnapshot(
                observed_at=current_date,
                growth_momentum_z=1.0 if regime == "Recovery" else 2.0,
                inflation_momentum_z=0.5,
                dominant_regime=regime,
                confidence=0.8,
                distribution={"Recovery": 0.7, "Overheat": 0.3}
            )
            regime_repo.save_snapshot(snapshot)
            current_date += timedelta(days=1)

        # Generate attribution report
        audit_repo = DjangoAuditRepository()
        backtest_repo = DjangoBacktestRepository()
        use_case = GenerateAttributionReportUseCase(audit_repo, backtest_repo)

        request = GenerateAttributionReportRequest(backtest_id=backtest.id)
        response = use_case.execute(request)

        assert response.success, f"Failed: {response.error}"
        assert response.report_id is not None

        # Verify regime_actual is set
        report = AttributionReport.objects.get(id=response.report_id)
        assert report.regime_actual is not None
        assert report.regime_actual == "Recovery", (
            f"Expected 'Recovery' as dominant regime, got '{report.regime_actual}'"
        )
        # Verify it's not an error code
        assert not report.regime_actual.startswith("ERROR:")
        assert not report.regime_actual.startswith("EXTRAPOLATED:")

    @patch('apps.backtest.infrastructure.adapters.composite_price_adapter.create_default_price_adapter')
    @patch('shared.config.secrets.get_secrets')
    def test_regime_actual_with_no_data_returns_error_code(
        self,
        mock_get_secrets,
        mock_create_adapter,
        mock_price_adapter
    ):
        """Test regime_actual when no regime data is available."""
        # Setup mocks
        mock_secrets = Mock()
        mock_secrets.data_sources.tushare_token = "test_token"
        mock_get_secrets.return_value = mock_secrets
        mock_create_adapter.return_value = mock_price_adapter

        # Create backtest
        start_date = date(2024, 1, 1)
        end_date = date(2024, 3, 31)
        backtest = self._create_backtest(start_date, end_date)
        backtest.save()

        # Don't create any regime data

        # Generate attribution report
        audit_repo = DjangoAuditRepository()
        backtest_repo = DjangoBacktestRepository()
        use_case = GenerateAttributionReportUseCase(audit_repo, backtest_repo)

        request = GenerateAttributionReportRequest(backtest_id=backtest.id)
        response = use_case.execute(request)

        assert response.success, f"Failed: {response.error}"

        # Verify regime_actual returns error code (not null)
        report = AttributionReport.objects.get(id=response.report_id)
        assert report.regime_actual is not None
        assert report.regime_actual == GenerateAttributionReportUseCase.ERROR_NO_REGIME_DATA

    @patch('apps.backtest.infrastructure.adapters.composite_price_adapter.create_default_price_adapter')
    @patch('shared.config.secrets.get_secrets')
    def test_regime_actual_with_insufficient_data_returns_error_code(
        self,
        mock_get_secrets,
        mock_create_adapter,
        mock_price_adapter
    ):
        """Test regime_actual when regime data is insufficient (< 10 points)."""
        # Setup mocks
        mock_secrets = Mock()
        mock_secrets.data_sources.tushare_token = "test_token"
        mock_get_secrets.return_value = mock_secrets
        mock_create_adapter.return_value = mock_price_adapter

        # Create backtest with long period
        start_date = date(2024, 1, 1)
        end_date = date(2024, 3, 31)  # 90 days
        backtest = self._create_backtest(start_date, end_date)
        backtest.save()

        # Create only 5 regime data points (insufficient)
        regime_repo = DjangoRegimeRepository()
        for i in range(5):
            snapshot = RegimeSnapshot(
                observed_at=start_date + timedelta(days=i * 18),
                growth_momentum_z=1.0,
                inflation_momentum_z=0.5,
                dominant_regime="Recovery",
                confidence=0.8,
                distribution={"Recovery": 0.8}
            )
            regime_repo.save_snapshot(snapshot)

        # Generate attribution report
        audit_repo = DjangoAuditRepository()
        backtest_repo = DjangoBacktestRepository()
        use_case = GenerateAttributionReportUseCase(audit_repo, backtest_repo)

        request = GenerateAttributionReportRequest(backtest_id=backtest.id)
        response = use_case.execute(request)

        assert response.success

        # Verify regime_actual returns insufficient data error code
        report = AttributionReport.objects.get(id=response.report_id)
        assert report.regime_actual is not None
        assert report.regime_actual == GenerateAttributionReportUseCase.ERROR_INSUFFICIENT_DATA

    @patch('apps.backtest.infrastructure.adapters.composite_price_adapter.create_default_price_adapter')
    @patch('shared.config.secrets.get_secrets')
    def test_regime_actual_with_tied_regimes_returns_error_code(
        self,
        mock_get_secrets,
        mock_create_adapter,
        mock_price_adapter
    ):
        """Test regime_actual when no single regime dominates."""
        # Setup mocks
        mock_secrets = Mock()
        mock_secrets.data_sources.tushare_token = "test_token"
        mock_get_secrets.return_value = mock_secrets
        mock_create_adapter.return_value = mock_price_adapter

        # Create backtest
        start_date = date(2024, 1, 1)
        end_date = date(2024, 1, 30)
        backtest = self._create_backtest(start_date, end_date)
        backtest.save()

        # Create regime data with equal distribution (50% each)
        regime_repo = DjangoRegimeRepository()
        current_date = start_date
        while current_date <= end_date:
            day_of_month = current_date.day
            if day_of_month <= 15:
                regime = "Recovery"
            else:
                regime = "Overheat"

            snapshot = RegimeSnapshot(
                observed_at=current_date,
                growth_momentum_z=1.0,
                inflation_momentum_z=0.5,
                dominant_regime=regime,
                confidence=0.8,
                distribution={"Recovery": 0.5, "Overheat": 0.5}
            )
            regime_repo.save_snapshot(snapshot)
            current_date += timedelta(days=1)

        # Generate attribution report
        audit_repo = DjangoAuditRepository()
        backtest_repo = DjangoBacktestRepository()
        use_case = GenerateAttributionReportUseCase(audit_repo, backtest_repo)

        request = GenerateAttributionReportRequest(backtest_id=backtest.id)
        response = use_case.execute(request)

        assert response.success

        # Verify regime_actual returns cannot determine error code
        report = AttributionReport.objects.get(id=response.report_id)
        assert report.regime_actual is not None
        assert report.regime_actual == GenerateAttributionReportUseCase.ERROR_CANNOT_DETERMINE

    @patch('apps.backtest.infrastructure.adapters.composite_price_adapter.create_default_price_adapter')
    @patch('shared.config.secrets.get_secrets')
    def test_regime_actual_with_extrapolated_data(
        self,
        mock_get_secrets,
        mock_create_adapter,
        mock_price_adapter
    ):
        """Test regime_actual when using extrapolated latest data."""
        # Setup mocks
        mock_secrets = Mock()
        mock_secrets.data_sources.tushare_token = "test_token"
        mock_get_secrets.return_value = mock_secrets
        mock_create_adapter.return_value = mock_price_adapter

        # Create backtest for future period (no data in period)
        start_date = date(2025, 1, 1)
        end_date = date(2025, 3, 31)
        backtest = self._create_backtest(start_date, end_date)
        backtest.save()

        # Create regime data before backtest period
        regime_repo = DjangoRegimeRepository()
        snapshot = RegimeSnapshot(
            observed_at=date(2024, 12, 31),
            growth_momentum_z=1.0,
            inflation_momentum_z=0.5,
            dominant_regime="Recovery",
            confidence=0.8,
            distribution={"Recovery": 0.8}
        )
        regime_repo.save_snapshot(snapshot)

        # Generate attribution report
        audit_repo = DjangoAuditRepository()
        backtest_repo = DjangoBacktestRepository()
        use_case = GenerateAttributionReportUseCase(audit_repo, backtest_repo)

        request = GenerateAttributionReportRequest(backtest_id=backtest.id)
        response = use_case.execute(request)

        assert response.success

        # Verify regime_actual uses extrapolated data
        report = AttributionReport.objects.get(id=response.report_id)
        assert report.regime_actual is not None
        assert report.regime_actual.startswith("EXTRAPOLATED:")
        parts = report.regime_actual.split(":")
        assert len(parts) >= 3
        assert parts[1] == "Recovery"
        # parts[2] should be a date
        extrapolated_date = date.fromisoformat(parts[2])

    @patch('apps.backtest.infrastructure.adapters.composite_price_adapter.create_default_price_adapter')
    @patch('shared.config.secrets.get_secrets')
    def test_regime_actual_with_low_dominance_threshold(
        self,
        mock_get_secrets,
        mock_create_adapter,
        mock_price_adapter
    ):
        """Test regime_actual when dominant regime is below 40% threshold."""
        # Setup mocks
        mock_secrets = Mock()
        mock_secrets.data_sources.tushare_token = "test_token"
        mock_get_secrets.return_value = mock_secrets
        mock_create_adapter.return_value = mock_price_adapter

        # Create backtest
        start_date = date(2024, 1, 1)
        end_date = date(2024, 1, 20)
        backtest = self._create_backtest(start_date, end_date)
        backtest.save()

        # Create regime data with 35% Recovery, 33% Overheat, 32% Stagflation
        regime_repo = DjangoRegimeRepository()
        current_date = start_date
        while current_date <= end_date:
            day_of_month = current_date.day
            if day_of_month <= 7:
                regime = "Recovery"
            elif day_of_month <= 14:
                regime = "Overheat"
            else:
                regime = "Stagflation"

            snapshot = RegimeSnapshot(
                observed_at=current_date,
                growth_momentum_z=1.0,
                inflation_momentum_z=0.5,
                dominant_regime=regime,
                confidence=0.8,
                distribution={"Recovery": 0.35, "Overheat": 0.33, "Stagflation": 0.32}
            )
            regime_repo.save_snapshot(snapshot)
            current_date += timedelta(days=1)

        # Generate attribution report
        audit_repo = DjangoAuditRepository()
        backtest_repo = DjangoBacktestRepository()
        use_case = GenerateAttributionReportUseCase(audit_repo, backtest_repo)

        request = GenerateAttributionReportRequest(backtest_id=backtest.id)
        response = use_case.execute(request)

        assert response.success

        # Verify regime_actual returns cannot determine (below 40% threshold)
        report = AttributionReport.objects.get(id=response.report_id)
        assert report.regime_actual is not None
        assert report.regime_actual == GenerateAttributionReportUseCase.ERROR_CANNOT_DETERMINE

    @patch('apps.backtest.infrastructure.adapters.composite_price_adapter.create_default_price_adapter')
    @patch('shared.config.secrets.get_secrets')
    def test_regime_actual_and_predicted_both_set(
        self,
        mock_get_secrets,
        mock_create_adapter,
        mock_price_adapter
    ):
        """Test that both regime_predicted and regime_actual are set in report."""
        # Setup mocks
        mock_secrets = Mock()
        mock_secrets.data_sources.tushare_token = "test_token"
        mock_get_secrets.return_value = mock_secrets
        mock_create_adapter.return_value = mock_price_adapter

        # Create backtest with regime_history
        start_date = date(2024, 1, 1)
        end_date = date(2024, 3, 31)
        backtest = self._create_backtest_with_regime_history(start_date, end_date, "Recovery")
        backtest.save()

        # Create regime data
        regime_repo = DjangoRegimeRepository()
        current_date = start_date
        while current_date <= end_date:
            snapshot = RegimeSnapshot(
                observed_at=current_date,
                growth_momentum_z=1.0,
                inflation_momentum_z=0.5,
                dominant_regime="Recovery",
                confidence=0.8,
                distribution={"Recovery": 0.8}
            )
            regime_repo.save_snapshot(snapshot)
            current_date += timedelta(days=1)

        # Generate attribution report
        audit_repo = DjangoAuditRepository()
        backtest_repo = DjangoBacktestRepository()
        use_case = GenerateAttributionReportUseCase(audit_repo, backtest_repo)

        request = GenerateAttributionReportRequest(backtest_id=backtest.id)
        response = use_case.execute(request)

        assert response.success

        # Verify both fields are set
        report = AttributionReport.objects.get(id=response.report_id)
        assert report.regime_predicted is not None
        assert report.regime_actual is not None
        assert not report.regime_predicted.startswith("ERROR:")
        assert not report.regime_actual.startswith("ERROR:")

    def _create_backtest(self, start_date: date, end_date: date) -> BacktestResultModel:
        """Create a sample backtest result model."""
        equity_curve = []
        current_value = 100000.0
        current_date = start_date

        while current_date <= end_date:
            equity_curve.append([current_date.isoformat(), current_value])
            current_value += 500.0
            current_date += timedelta(days=1)

        return BacktestResultModel(
            name="Test Backtest",
            start_date=start_date,
            end_date=end_date,
            initial_capital=100000.0,
            final_capital=115000.0,
            total_return=0.15,
            sharpe_ratio=1.5,
            max_drawdown=-0.05,
            annualized_return=0.30,
            equity_curve=json.dumps(equity_curve),
            regime_history=json.dumps([]),
            trades=[],
            status='completed'
        )

    def _create_backtest_with_regime_history(
        self,
        start_date: date,
        end_date: date,
        regime: str
    ) -> BacktestResultModel:
        """Create a backtest with regime_history."""
        equity_curve = []
        current_value = 100000.0
        current_date = start_date

        while current_date <= end_date:
            equity_curve.append([current_date.isoformat(), current_value])
            current_value += 500.0
            current_date += timedelta(days=1)

        regime_history = [
            {
                "date": start_date.isoformat(),
                "regime": regime.upper(),
                "dominant_regime": regime,
                "confidence": 0.85
            }
        ]

        return BacktestResultModel(
            name="Test Backtest with Regime",
            start_date=start_date,
            end_date=end_date,
            initial_capital=100000.0,
            final_capital=115000.0,
            total_return=0.15,
            sharpe_ratio=1.5,
            max_drawdown=-0.05,
            annualized_return=0.30,
            equity_curve=json.dumps(equity_curve),
            regime_history=json.dumps(regime_history),
            trades=[],
            status='completed'
        )


@pytest.mark.django_db
class TestRegimeActualEdgeCases:
    """Test edge cases for regime_actual calculation."""

    @patch('apps.backtest.infrastructure.adapters.composite_price_adapter.create_default_price_adapter')
    @patch('shared.config.secrets.get_secrets')
    def test_single_day_backtest(
        self,
        mock_get_secrets,
        mock_create_adapter,
        mock_price_adapter
    ):
        """Test regime_actual with single day backtest.

        Expected behavior: With only 1 data point (< 10 threshold),
        the system should return INSUFFICIENT_DATA error code.
        """
        # Setup mocks
        mock_secrets = Mock()
        mock_secrets.data_sources.tushare_token = "test_token"
        mock_get_secrets.return_value = mock_secrets
        mock_create_adapter.return_value = mock_price_adapter

        # Create single day backtest
        start_date = end_date = date(2024, 1, 1)
        backtest = self._create_backtest(start_date, end_date)
        backtest.save()

        # Create regime data for that day
        regime_repo = DjangoRegimeRepository()
        snapshot = RegimeSnapshot(
            observed_at=start_date,
            growth_momentum_z=1.0,
            inflation_momentum_z=0.5,
            dominant_regime="Recovery",
            confidence=0.8,
            distribution={"Recovery": 0.8}
        )
        regime_repo.save_snapshot(snapshot)

        # Generate attribution report
        audit_repo = DjangoAuditRepository()
        backtest_repo = DjangoBacktestRepository()
        use_case = GenerateAttributionReportUseCase(audit_repo, backtest_repo)

        request = GenerateAttributionReportRequest(backtest_id=backtest.id)
        response = use_case.execute(request)

        # Should succeed but with insufficient data error code
        assert response.success
        report = AttributionReport.objects.get(id=response.report_id)
        # With only 1 data point (< 10), should return INSUFFICIENT_DATA
        assert report.regime_actual == GenerateAttributionReportUseCase.ERROR_INSUFFICIENT_DATA

    @patch('apps.backtest.infrastructure.adapters.composite_price_adapter.create_default_price_adapter')
    @patch('shared.config.secrets.get_secrets')
    def test_backward_compatibility_with_old_reports(
        self,
        mock_get_secrets,
        mock_create_adapter,
        mock_price_adapter
    ):
        """Test that reports with null regime_actual don't break retrieval."""
        # Setup mocks
        mock_secrets = Mock()
        mock_secrets.data_sources.tushare_token = "test_token"
        mock_get_secrets.return_value = mock_secrets
        mock_create_adapter.return_value = mock_price_adapter

        # Create backtest
        start_date = date(2024, 1, 1)
        end_date = date(2024, 3, 31)
        backtest = self._create_backtest(start_date, end_date)
        backtest.save()

        # Manually create a report with null regime_actual (simulating old data)
        from apps.audit.infrastructure.models import AttributionReport
        old_report = AttributionReport.objects.create(
            backtest=backtest,
            period_start=start_date,
            period_end=end_date,
            attribution_method='heuristic',
            regime_timing_pnl=0.05,
            asset_selection_pnl=0.03,
            interaction_pnl=0.02,
            total_pnl=0.10,
            regime_accuracy=0.75,
            regime_predicted="Recovery",
            regime_actual=None,  # Old behavior
        )

        # Verify retrieval doesn't crash
        audit_repo = DjangoAuditRepository()
        retrieved_report = audit_repo.get_attribution_report(old_report.id)

        assert retrieved_report is not None
        assert retrieved_report['regime_actual'] is None

    def _create_backtest(self, start_date: date, end_date: date) -> BacktestResultModel:
        """Create a sample backtest result model."""
        equity_curve = []
        current_value = 100000.0
        current_date = start_date

        while current_date <= end_date:
            equity_curve.append([current_date.isoformat(), current_value])
            current_value += 500.0
            current_date += timedelta(days=1)

        return BacktestResultModel(
            name="Test Backtest",
            start_date=start_date,
            end_date=end_date,
            initial_capital=100000.0,
            final_capital=115000.0,
            total_return=0.15,
            sharpe_ratio=1.5,
            max_drawdown=-0.05,
            annualized_return=0.30,
            equity_curve=json.dumps(equity_curve),
            regime_history=json.dumps([]),
            trades=[],
            status='completed'
        )
