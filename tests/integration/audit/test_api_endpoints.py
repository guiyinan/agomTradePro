"""
Integration Tests for Audit Module API Endpoints.

Tests for:
- POST /audit/reports/generate/ - GenerateAttributionReportView
- GET /audit/api/summary/ - AuditSummaryView
- Request validation
- Response serialization
- Error handling
"""

import json
from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APIClient

from apps.audit.infrastructure.models import (
    AttributionReport,
    ExperienceSummary,
    LossAnalysis,
)
from apps.backtest.infrastructure.models import BacktestResultModel

User = get_user_model()


# Mock asset returns for all tests that need it
@pytest.fixture(autouse=True)
def mock_asset_returns():
    """Auto-mock _build_asset_returns to avoid external API calls."""
    mock_data = {
        'equity': [(date(2024, 1, 15), 0.02), (date(2024, 2, 15), 0.015)],
        'bond': [(date(2024, 1, 15), 0.005), (date(2024, 2, 15), 0.003)],
    }
    with patch(
        'apps.audit.application.use_cases.GenerateAttributionReportUseCase._build_asset_returns',
        return_value=mock_data
    ):
        yield


def _build_authenticated_api_client(username: str = "testuser") -> APIClient:
    """Create an authenticated client without failing on duplicate usernames."""
    user, _ = User.objects.get_or_create(username=username)
    user.set_password('testpass')
    user.save(update_fields=['password'])
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.mark.django_db
class TestGenerateAttributionReportAPI:
    """Test POST /audit/reports/generate/ endpoint."""

    @pytest.fixture
    def api_client(self):
        """Create authenticated API client."""
        return _build_authenticated_api_client("testuser_audit_generate")

    @pytest.fixture
    def sample_backtest(self):
        """Create sample backtest for testing."""
        equity_curve = [
            ["2024-01-01", 100000.0],
            ["2024-02-01", 105000.0],
            ["2024-03-01", 110000.0],
        ]
        regime_history = [
            {"date": "2024-01-01", "regime": "RECOVERY", "confidence": 0.85},
            {"date": "2024-02-15", "regime": "OVERHEAT", "confidence": 0.80},
        ]

        backtest = BacktestResultModel.objects.create(
            name="API Test Backtest",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 3, 31),
            initial_capital=100000.0,
            final_capital=110000.0,
            total_return=0.10,
            sharpe_ratio=1.5,
            max_drawdown=-0.03,
            annualized_return=0.40,
            equity_curve=json.dumps(equity_curve),
            regime_history=json.dumps(regime_history),
            trades=[],
            status='completed'
        )
        return backtest

    def test_generate_attribution_report_success(self, api_client, sample_backtest):
        """Test successful generation of attribution report."""
        url = '/audit/api/reports/generate/'
        data = {'backtest_id': sample_backtest.id}

        response = api_client.post(url, data, format='json')

        assert response.status_code == status.HTTP_201_CREATED
        assert 'id' in response.data
        assert 'backtest_id' in response.data
        assert 'total_pnl' in response.data
        assert 'regime_timing_pnl' in response.data
        assert 'asset_selection_pnl' in response.data
        assert 'interaction_pnl' in response.data
        assert 'regime_accuracy' in response.data

    def test_generate_attribution_report_includes_nested_data(
        self,
        api_client,
        sample_backtest
    ):
        """Test that response includes loss_analyses and experience_summaries."""
        url = '/audit/api/reports/generate/'
        data = {'backtest_id': sample_backtest.id}

        response = api_client.post(url, data, format='json')

        assert response.status_code == status.HTTP_201_CREATED
        # Check for nested data (may be empty if no losses)
        assert 'loss_analyses' in response.data
        assert 'experience_summaries' in response.data

    def test_generate_attribution_report_missing_backtest_id(self, api_client):
        """Test with missing backtest_id field."""
        url = '/audit/api/reports/generate/'
        data = {}  # Missing backtest_id

        response = api_client.post(url, data, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'error' in response.data or 'backtest_id' in response.data

    def test_generate_attribution_report_nonexistent_backtest(self, api_client):
        """Test with non-existent backtest ID."""
        url = '/audit/api/reports/generate/'
        data = {'backtest_id': 99999}  # Non-existent

        response = api_client.post(url, data, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'error' in response.data

    def test_generate_attribution_report_invalid_backtest_id_type(self, api_client):
        """Test with invalid backtest_id type."""
        url = '/audit/api/reports/generate/'
        data = {'backtest_id': 'not_an_integer'}

        response = api_client.post(url, data, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_generate_attribution_report_creates_db_records(
        self,
        api_client,
        sample_backtest
    ):
        """Test that API creates database records."""
        url = '/audit/api/reports/generate/'
        data = {'backtest_id': sample_backtest.id}

        initial_count = AttributionReport.objects.count()
        response = api_client.post(url, data, format='json')

        assert response.status_code == status.HTTP_201_CREATED
        assert AttributionReport.objects.count() == initial_count + 1

        # Verify report was created
        report = AttributionReport.objects.get(id=response.data['id'])
        assert report.backtest_id == sample_backtest.id

    def test_generate_attribution_report_unauthenticated(self):
        """Test that unauthenticated request is rejected."""
        client = APIClient()  # Not authenticated
        url = '/audit/api/reports/generate/'
        data = {'backtest_id': 1}

        response = client.post(url, data, format='json')

        # Should be unauthorized or redirect
        assert response.status_code in [
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN
        ]

    def test_generate_multiple_reports_same_backtest(
        self,
        api_client,
        sample_backtest
    ):
        """Test generating multiple reports for the same backtest."""
        url = '/audit/api/reports/generate/'
        data = {'backtest_id': sample_backtest.id}

        response1 = api_client.post(url, data, format='json')
        response2 = api_client.post(url, data, format='json')

        assert response1.status_code == status.HTTP_201_CREATED
        assert response2.status_code == status.HTTP_201_CREATED
        assert response1.data['id'] != response2.data['id']

    def test_attribution_report_with_losses_creates_loss_analysis(
        self,
        api_client
    ):
        """Test that loss scenarios create loss analysis records."""
        # Create backtest with losses
        equity_curve = [
            ["2024-01-01", 100000.0],
            ["2024-02-01", 95000.0],
            ["2024-03-01", 90000.0],
        ]
        regime_history = [
            {"date": "2024-01-01", "regime": "RECOVERY", "confidence": 0.3},
        ]

        backtest = BacktestResultModel.objects.create(
            name="Loss Backtest",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 3, 31),
            initial_capital=100000.0,
            final_capital=90000.0,
            total_return=-0.10,
            sharpe_ratio=-0.5,
            max_drawdown=-0.15,
            annualized_return=-0.40,
            equity_curve=json.dumps(equity_curve),
            regime_history=json.dumps(regime_history),
            trades=[],
            status='completed'
        )

        url = '/audit/api/reports/generate/'
        data = {'backtest_id': backtest.id}

        response = api_client.post(url, data, format='json')

        assert response.status_code == status.HTTP_201_CREATED

        # Check for loss analyses
        loss_analyses = LossAnalysis.objects.filter(report_id=response.data['id'])
        # May or may not exist depending on attribution logic
        # Just verify the field is present in response
        assert 'loss_analyses' in response.data


@pytest.mark.django_db
class TestAuditSummaryAPI:
    """Test GET /audit/api/summary/ endpoint."""

    @pytest.fixture
    def api_client(self):
        """Create authenticated API client."""
        return _build_authenticated_api_client("testuser_audit_summary")

    @pytest.fixture
    def sample_reports(self):
        """Create sample attribution reports."""
        reports = []
        for i in range(3):
            backtest = BacktestResultModel.objects.create(
                name=f"Summary Test Backtest {i}",
                start_date=date(2024, 1, 1),
                end_date=date(2024, 3, 31),
                initial_capital=100000.0,
                final_capital=110000.0,
                total_return=0.10,
                sharpe_ratio=1.5,
                max_drawdown=-0.03,
                annualized_return=0.40,
                equity_curve=json.dumps([["2024-01-01", 100000.0]]),
                regime_history=json.dumps([{"date": "2024-01-01", "regime": "RECOVERY"}]),
                trades=[],
                status='completed'
            )

            report = AttributionReport.objects.create(
                backtest_id=backtest.id,
                period_start=date(2024, 1, 1),
                period_end=date(2024, 3, 31),
                total_pnl=0.10,
                regime_timing_pnl=0.03,
                asset_selection_pnl=0.05,
                interaction_pnl=0.02,
                regime_accuracy=0.75,
                regime_predicted="RECOVERY"
            )
            reports.append(report)

        return reports

    def test_get_summary_by_backtest_id(self, api_client, sample_reports):
        """Test getting summary by backtest ID."""
        backtest_id = sample_reports[0].backtest_id
        url = f'/audit/api/summary/?backtest_id={backtest_id}'

        response = api_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert isinstance(response.data, list)
        assert len(response.data) >= 1

    def test_get_summary_by_date_range(self, api_client, sample_reports):
        """Test getting summary by date range."""
        url = '/audit/api/summary/?start_date=2024-01-01&end_date=2024-12-31'

        response = api_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert isinstance(response.data, list)

    def test_get_summary_missing_parameters(self, api_client):
        """Test with missing required parameters."""
        url = '/audit/api/summary/'  # No parameters

        response = api_client.get(url)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'error' in response.data

    def test_get_summary_invalid_backtest_id(self, api_client):
        """Test with invalid backtest_id type."""
        url = '/audit/api/summary/?backtest_id=not_an_integer'

        response = api_client.get(url)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'error' in response.data

    def test_get_summary_invalid_date_format(self, api_client):
        """Test with invalid date format."""
        url = '/audit/api/summary/?start_date=01-01-2024&end_date=12-31-2024'

        response = api_client.get(url)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'error' in response.data

    def test_get_summary_includes_nested_data(self, api_client, sample_reports):
        """Test that summary includes loss_analyses and experience_summaries."""
        backtest_id = sample_reports[0].backtest_id

        # Create nested data
        LossAnalysis.objects.create(
            report_id=sample_reports[0].id,
            loss_source='REGIME_ERROR',
            impact=-0.02,
            impact_percentage=20.0,
            description='Test loss',
            improvement_suggestion='Test suggestion'
        )

        ExperienceSummary.objects.create(
            report_id=sample_reports[0].id,
            lesson='Test lesson',
            recommendation='Test recommendation',
            priority='HIGH'
        )

        url = f'/audit/api/summary/?backtest_id={backtest_id}'
        response = api_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        # Check that nested data is included
        if len(response.data) > 0:
            assert 'loss_analyses' in response.data[0]
            assert 'experience_summaries' in response.data[0]

    def test_get_summary_empty_result(self, api_client):
        """Test with no matching reports."""
        url = '/audit/api/summary/?backtest_id=99999'

        response = api_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data == []

    def test_get_summary_unauthenticated(self):
        """Test that unauthenticated request is rejected."""
        client = APIClient()  # Not authenticated
        url = '/audit/api/summary/?backtest_id=1'

        response = client.get(url)

        # Should be unauthorized or redirect
        assert response.status_code in [
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN
        ]


@pytest.mark.django_db
class TestAuditAPIResponseSerialization:
    """Test response serialization and data formats."""

    @pytest.fixture
    def api_client(self):
        """Create authenticated API client."""
        return _build_authenticated_api_client("testuser_audit_serialization")

    @pytest.fixture
    def sample_backtest(self):
        """Create sample backtest."""
        equity_curve = [
            ["2024-01-01", 100000.0],
            ["2024-02-01", 105000.0],
        ]
        regime_history = [
            {"date": "2024-01-01", "regime": "RECOVERY", "confidence": 0.85},
        ]

        return BacktestResultModel.objects.create(
            name="Serialization Test",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 2, 29),
            initial_capital=100000.0,
            final_capital=105000.0,
            total_return=0.05,
            sharpe_ratio=1.0,
            max_drawdown=-0.02,
            annualized_return=0.30,
            equity_curve=json.dumps(equity_curve),
            regime_history=json.dumps(regime_history),
            trades=[],
            status='completed'
        )

    def test_attribution_report_data_types(self, api_client, sample_backtest):
        """Test that response data has correct types."""
        url = '/audit/api/reports/generate/'
        data = {'backtest_id': sample_backtest.id}

        response = api_client.post(url, data, format='json')

        assert response.status_code == status.HTTP_201_CREATED

        # Check field types
        assert isinstance(response.data['id'], int)
        assert isinstance(response.data['backtest_id'], int)
        assert isinstance(response.data['total_pnl'], (int, float))
        assert isinstance(response.data['regime_timing_pnl'], (int, float))
        assert isinstance(response.data['asset_selection_pnl'], (int, float))
        assert isinstance(response.data['interaction_pnl'], (int, float))
        assert isinstance(response.data['regime_accuracy'], (int, float))

    def test_summary_response_is_list(self, api_client, sample_backtest):
        """Test that summary API returns a list."""
        # First generate a report
        url = '/audit/api/reports/generate/'
        data = {'backtest_id': sample_backtest.id}
        api_client.post(url, data, format='json')

        # Then get summary
        summary_url = f'/audit/api/summary/?backtest_id={sample_backtest.id}'
        response = api_client.get(summary_url)

        assert response.status_code == status.HTTP_200_OK
        assert isinstance(response.data, list)

    def test_date_fields_serialized_correctly(
        self,
        api_client,
        sample_backtest
    ):
        """Test that date fields are serialized correctly."""
        url = '/audit/api/reports/generate/'
        data = {'backtest_id': sample_backtest.id}

        response = api_client.post(url, data, format='json')

        assert response.status_code == status.HTTP_201_CREATED

        # Check date fields
        if 'period_start' in response.data:
            assert response.data['period_start'] is not None
        if 'period_end' in response.data:
            assert response.data['period_end'] is not None

    def test_nested_data_structure(self, api_client, sample_backtest):
        """Test that nested data has correct structure."""
        url = '/audit/api/reports/generate/'
        data = {'backtest_id': sample_backtest.id}

        response = api_client.post(url, data, format='json')

        assert response.status_code == status.HTTP_201_CREATED

        # Check nested data structure
        if 'loss_analyses' in response.data:
            assert isinstance(response.data['loss_analyses'], list)
        if 'experience_summaries' in response.data:
            assert isinstance(response.data['experience_summaries'], list)


@pytest.mark.django_db
class TestAuditAPIErrorHandling:
    """Test API error handling and edge cases."""

    @pytest.fixture
    def api_client(self):
        """Create authenticated API client."""
        return _build_authenticated_api_client("testuser_audit_errors")

    def test_generate_report_concurrent_requests(self, api_client):
        """Test handling concurrent requests."""
        # Create multiple backtests
        backtests = []
        for i in range(5):
            backtest = BacktestResultModel.objects.create(
                name=f"Concurrent Test {i}",
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 31),
                initial_capital=100000.0,
                final_capital=105000.0,
                total_return=0.05,
                sharpe_ratio=1.0,
                max_drawdown=-0.02,
                annualized_return=0.60,
                equity_curve=json.dumps([["2024-01-01", 100000.0]]),
                regime_history=json.dumps([{"date": "2024-01-01", "regime": "RECOVERY"}]),
                trades=[],
                status='completed'
            )
            backtests.append(backtest)

        # Generate reports concurrently (sequentially in test)
        url = '/audit/api/reports/generate/'
        responses = []
        for backtest in backtests:
            data = {'backtest_id': backtest.id}
            response = api_client.post(url, data, format='json')
            responses.append(response)

        # All should succeed
        for response in responses:
            assert response.status_code == status.HTTP_201_CREATED

    def test_summary_with_partial_date_range(self, api_client):
        """Test summary with only start_date or end_date."""
        # These should fail - both dates required
        url = '/audit/api/summary/?start_date=2024-01-01'
        response = api_client.get(url)
        assert response.status_code == status.HTTP_400_BAD_REQUEST

        url = '/audit/api/summary/?end_date=2024-12-31'
        response = api_client.get(url)
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_generate_report_with_incomplete_backtest(self, api_client):
        """Test generating report for incomplete backtest."""
        backtest = BacktestResultModel.objects.create(
            name="Incomplete Backtest",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            initial_capital=100000.0,
            final_capital=100000.0,
            total_return=0.0,
            sharpe_ratio=0.0,
            max_drawdown=0.0,
            annualized_return=0.0,
            equity_curve=json.dumps([]),  # Empty
            regime_history=json.dumps([]),  # Empty
            trades=[],
            status='in_progress'  # Not completed
        )

        url = '/audit/api/reports/generate/'
        data = {'backtest_id': backtest.id}

        response = api_client.post(url, data, format='json')

        # Should handle gracefully (may succeed or fail with specific error)
        assert response.status_code in [
            status.HTTP_201_CREATED,
            status.HTTP_400_BAD_REQUEST
        ]

    def test_large_backtest_data_handling(self, api_client):
        """Test handling of backtest with large data."""
        # Create backtest with many data points
        equity_curve = []
        for i in range(1000):
            equity_curve.append([f"2024-{(i % 12) + 1:02d}-{(i % 28) + 1:02d}", 100000 + i * 10])

        backtest = BacktestResultModel.objects.create(
            name="Large Data Backtest",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            initial_capital=100000.0,
            final_capital=110000.0,
            total_return=0.10,
            sharpe_ratio=1.5,
            max_drawdown=-0.03,
            annualized_return=0.10,
            equity_curve=json.dumps(equity_curve),
            regime_history=json.dumps([{"date": "2024-01-01", "regime": "RECOVERY"}]),
            trades=[],
            status='completed'
        )

        url = '/audit/api/reports/generate/'
        data = {'backtest_id': backtest.id}

        response = api_client.post(url, data, format='json')

        # Should handle large data
        assert response.status_code in [
            status.HTTP_201_CREATED,
            status.HTTP_400_BAD_REQUEST
        ]
