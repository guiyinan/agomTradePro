"""
Integration Tests for Audit Module - Full Attribution Workflow

Tests end-to-end attribution analysis workflow:
1. Backtest completion
2. Attribution report generation
3. Loss analysis and experience summary
4. Database persistence
5. Report retrieval
"""

import pytest
import json
from datetime import date, timedelta
from unittest.mock import Mock, patch

from apps.audit.domain.services import (
    analyze_attribution,
    AttributionConfig,
    AttributionAnalyzer,
)
from apps.audit.domain.entities import (
    RegimePeriod,
    RegimeSnapshot,
    LossSource,
)
from apps.audit.application.use_cases import (
    GenerateAttributionReportUseCase,
    GenerateAttributionReportRequest,
    GetAuditSummaryUseCase,
    GetAuditSummaryRequest,
)
from apps.audit.infrastructure.repositories import DjangoAuditRepository
from apps.audit.infrastructure.models import (
    AttributionReport,
    LossAnalysis,
    ExperienceSummary,
)
from apps.backtest.infrastructure.repositories import DjangoBacktestRepository
from apps.backtest.infrastructure.models import BacktestResultModel


@pytest.mark.django_db
class TestFullAttributionWorkflow:
    """Test complete attribution workflow from backtest to report."""

    def test_end_to_end_attribution_workflow(self):
        """Test end-to-end attribution workflow.

        Workflow:
        1. Create and save a backtest result
        2. Generate attribution report
        3. Verify loss analysis
        4. Verify experience summary
        5. Retrieve and validate report
        """
        # 1. Create backtest result
        backtest_model = self._create_sample_backtest()
        backtest_model.save()

        # 2. Generate attribution report
        audit_repo = DjangoAuditRepository()
        backtest_repo = DjangoBacktestRepository()
        use_case = GenerateAttributionReportUseCase(audit_repo, backtest_repo)

        request = GenerateAttributionReportRequest(backtest_id=backtest_model.id)
        response = use_case.execute(request)

        # 3. Verify successful generation
        assert response.success, f"Attribution generation failed: {response.error}"
        assert response.report_id is not None

        # 4. Verify database records
        report = AttributionReport.objects.get(id=response.report_id)
        assert report.backtest_id == backtest_model.id
        assert report.total_pnl is not None

        # 5. Verify loss analysis if applicable
        loss_analyses = LossAnalysis.objects.filter(report_id=response.report_id)
        if report.total_pnl < 0:
            assert loss_analyses.exists(), "Loss analysis should exist for negative returns"

        # 6. Verify experience summary
        summaries = ExperienceSummary.objects.filter(report_id=response.report_id)
        assert summaries.exists(), "Experience summary should exist"

        # 7. Retrieve via summary use case
        summary_use_case = GetAuditSummaryUseCase(audit_repo)
        summary_request = GetAuditSummaryRequest(backtest_id=backtest_model.id)
        summary_response = summary_use_case.execute(summary_request)

        assert summary_response.success
        assert len(summary_response.reports) > 0
        assert 'loss_analyses' in summary_response.reports[0]
        assert 'experience_summaries' in summary_response.reports[0]

    def test_attribution_with_multiple_regime_changes(self):
        """Test attribution with multiple regime changes."""
        # Create backtest with multiple regime changes
        backtest_model = self._create_multi_regime_backtest()
        backtest_model.save()

        # Generate attribution
        audit_repo = DjangoAuditRepository()
        backtest_repo = DjangoBacktestRepository()
        use_case = GenerateAttributionReportUseCase(audit_repo, backtest_repo)

        request = GenerateAttributionReportRequest(backtest_id=backtest_model.id)
        response = use_case.execute(request)

        assert response.success
        assert response.report_id is not None

        # Verify regime accuracy was calculated
        report = AttributionReport.objects.get(id=response.report_id)
        assert report.regime_accuracy is not None

    def test_attribution_with_losses(self):
        """Test attribution correctly identifies and categorizes losses."""
        # Create backtest with losses
        backtest_model = self._create_loss_backtest()
        backtest_model.save()

        # Generate attribution
        audit_repo = DjangoAuditRepository()
        backtest_repo = DjangoBacktestRepository()
        use_case = GenerateAttributionReportUseCase(audit_repo, backtest_repo)

        request = GenerateAttributionReportRequest(backtest_id=backtest_model.id)
        response = use_case.execute(request)

        assert response.success

        # Verify loss analysis
        loss_analyses = LossAnalysis.objects.filter(report_id=response.report_id)
        assert loss_analyses.exists(), "Loss analysis should exist"

        loss_analysis = loss_analyses.first()
        assert loss_analysis.loss_source in [
            'REGIME_ERROR', 'TIMING_ERROR', 'ASSET_SELECTION_ERROR',
            'EXECUTION_ERROR', 'TRANSACTION_COST', 'POLICY_MISJUDGMENT',
            'EXTERNAL_SHOCK'
        ]
        assert loss_analysis.impact < 0  # Should be negative

    def test_attribution_summary_by_date_range(self):
        """Test retrieving attribution summary by date range."""
        # Create multiple backtests
        backtest1 = self._create_sample_backtest(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 3, 31)
        )
        backtest1.save()

        backtest2 = self._create_sample_backtest(
            start_date=date(2024, 4, 1),
            end_date=date(2024, 6, 30)
        )
        backtest2.save()

        # Generate reports for both
        audit_repo = DjangoAuditRepository()
        backtest_repo = DjangoBacktestRepository()
        use_case = GenerateAttributionReportUseCase(audit_repo, backtest_repo)

        use_case.execute(GenerateAttributionReportRequest(backtest_id=backtest1.id))
        use_case.execute(GenerateAttributionReportRequest(backtest_id=backtest2.id))

        # Retrieve by date range
        summary_use_case = GetAuditSummaryUseCase(audit_repo)
        summary_request = GetAuditSummaryRequest(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 6, 30)
        )
        summary_response = summary_use_case.execute(summary_request)

        assert summary_response.success
        assert len(summary_response.reports) == 2

    def _create_sample_backtest(
        self,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 6, 30)
    ) -> BacktestResultModel:
        """Create a sample backtest result model."""
        equity_curve = []
        current_value = 100000.0
        current_date = start_date

        while current_date <= end_date:
            equity_curve.append([current_date.isoformat(), current_value])
            current_value += 500.0  # Simple growth
            current_date += timedelta(days=1)

        regime_history = [
            {
                "date": start_date.isoformat(),
                "regime": "RECOVERY",
                "confidence": 0.85
            },
            {
                "date": (start_date + timedelta(days=90)).isoformat(),
                "regime": "OVERHEAT",
                "confidence": 0.75
            }
        ]

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
            regime_history=json.dumps(regime_history),
            trades=[],
            status='completed'
        )

    def _create_multi_regime_backtest(self) -> BacktestResultModel:
        """Create backtest with multiple regime changes."""
        start_date = date(2024, 1, 1)
        end_date = date(2024, 6, 30)

        equity_curve = []
        current_value = 100000.0
        current_date = start_date

        while current_date <= end_date:
            equity_curve.append([current_date.isoformat(), current_value])
            # Add some volatility
            if (current_date - start_date).days % 30 < 15:
                current_value *= 1.01
            else:
                current_value *= 0.99
            current_date += timedelta(days=1)

        regime_history = [
            {"date": (start_date + timedelta(days=0)).isoformat(), "regime": "RECOVERY", "confidence": 0.85},
            {"date": (start_date + timedelta(days=45)).isoformat(), "regime": "OVERHEAT", "confidence": 0.80},
            {"date": (start_date + timedelta(days=90)).isoformat(), "regime": "SLOWDOWN", "confidence": 0.70},
            {"date": (start_date + timedelta(days=135)).isoformat(), "regime": "STAGFLATION", "confidence": 0.65},
        ]

        return BacktestResultModel(
            name="Multi-Regime Backtest",
            start_date=start_date,
            end_date=end_date,
            initial_capital=100000.0,
            final_capital=105000.0,
            total_return=0.05,
            sharpe_ratio=0.5,
            max_drawdown=-0.10,
            annualized_return=0.10,
            equity_curve=json.dumps(equity_curve),
            regime_history=json.dumps(regime_history),
            trades=[],
            status='completed'
        )

    def _create_loss_backtest(self) -> BacktestResultModel:
        """Create backtest with losses."""
        start_date = date(2024, 1, 1)
        end_date = date(2024, 3, 31)

        equity_curve = []
        current_value = 100000.0
        current_date = start_date

        while current_date <= end_date:
            equity_curve.append([current_date.isoformat(), current_value])
            current_value *= 0.995  # Loss
            current_date += timedelta(days=1)

        regime_history = [
            {"date": start_date.isoformat(), "regime": "RECOVERY", "confidence": 0.3},
            {"date": (start_date + timedelta(days=45)).isoformat(), "regime": "SLOWDOWN", "confidence": 0.4},
        ]

        return BacktestResultModel(
            name="Loss Backtest",
            start_date=start_date,
            end_date=end_date,
            initial_capital=100000.0,
            final_capital=85000.0,
            total_return=-0.15,
            sharpe_ratio=-0.5,
            max_drawdown=-0.20,
            annualized_return=-0.60,
            equity_curve=json.dumps(equity_curve),
            regime_history=json.dumps(regime_history),
            trades=[],
            status='completed'
        )


@pytest.mark.django_db
class TestAttributionAnalysisAccuracy:
    """Test accuracy of attribution analysis."""

    def test_regime_timing_attribution(self):
        """Test regime timing attribution accuracy."""
        # Create scenario where regime timing is clearly the issue
        backtest = self._create_regime_timing_scenario()
        backtest.save()

        audit_repo = DjangoAuditRepository()
        backtest_repo = DjangoBacktestRepository()
        use_case = GenerateAttributionReportUseCase(audit_repo, backtest_repo)

        response = use_case.execute(GenerateAttributionReportRequest(backtest_id=backtest.id))

        assert response.success

        # Check that regime timing is identified as a factor
        report = AttributionReport.objects.get(id=response.report_id)
        # The regime_timing_pnl should be calculated
        assert report.regime_timing_pnl is not None

    def test_asset_selection_attribution(self):
        """Test asset selection attribution accuracy."""
        # Create scenario where asset selection is the issue
        backtest = self._create_asset_selection_scenario()
        backtest.save()

        audit_repo = DjangoAuditRepository()
        backtest_repo = DjangoBacktestRepository()
        use_case = GenerateAttributionReportUseCase(audit_repo, backtest_repo)

        response = use_case.execute(GenerateAttributionReportRequest(backtest_id=backtest.id))

        assert response.success

        report = AttributionReport.objects.get(id=response.report_id)
        assert report.asset_selection_pnl is not None

    def test_interaction_effect_attribution(self):
        """Test interaction effect attribution."""
        backtest = self._create_interaction_scenario()
        backtest.save()

        audit_repo = DjangoAuditRepository()
        backtest_repo = DjangoBacktestRepository()
        use_case = GenerateAttributionReportUseCase(audit_repo, backtest_repo)

        response = use_case.execute(GenerateAttributionReportRequest(backtest_id=backtest.id))

        assert response.success

        report = AttributionReport.objects.get(id=response.report_id)
        # Check PnL decomposition sums correctly
        total = report.regime_timing_pnl + report.asset_selection_pnl + report.interaction_pnl
        # Should be close to total_pnl (allowing for some tolerance due to heuristic method)
        assert abs(total - report.total_pnl) < 0.05

    def _create_regime_timing_scenario(self) -> BacktestResultModel:
        """Create backtest where regime timing is the issue."""
        start_date = date(2024, 1, 1)
        end_date = date(2024, 3, 31)

        equity_curve = [
            [start_date.isoformat(), 100000.0],
            [(start_date + timedelta(days=30)).isoformat(), 102000.0],
            [(start_date + timedelta(days=60)).isoformat(), 101000.0],
            [end_date.isoformat(), 100500.0],
        ]

        # Low confidence regime predictions
        regime_history = [
            {"date": start_date.isoformat(), "regime": "RECOVERY", "confidence": 0.3},
            {"date": (start_date + timedelta(days=45)).isoformat(), "regime": "OVERHEAT", "confidence": 0.35},
        ]

        return BacktestResultModel(
            name="Regime Timing Test",
            start_date=start_date,
            end_date=end_date,
            initial_capital=100000.0,
            final_capital=100500.0,
            total_return=0.005,
            sharpe_ratio=0.1,
            max_drawdown=-0.02,
            annualized_return=0.02,
            equity_curve=json.dumps(equity_curve),
            regime_history=json.dumps(regime_history),
            trades=[],
            status='completed'
        )

    def _create_asset_selection_scenario(self) -> BacktestResultModel:
        """Create backtest where asset selection is the issue."""
        start_date = date(2024, 1, 1)
        end_date = date(2024, 3, 31)

        equity_curve = [
            [start_date.isoformat(), 100000.0],
            [(start_date + timedelta(days=30)).isoformat(), 101000.0],
            [(start_date + timedelta(days=60)).isoformat(), 101500.0],
            [end_date.isoformat(), 102000.0],
        ]

        # Good regime prediction but poor returns
        regime_history = [
            {"date": start_date.isoformat(), "regime": "RECOVERY", "confidence": 0.9},
            {"date": (start_date + timedelta(days=45)).isoformat(), "regime": "OVERHEAT", "confidence": 0.85},
        ]

        return BacktestResultModel(
            name="Asset Selection Test",
            start_date=start_date,
            end_date=end_date,
            initial_capital=100000.0,
            final_capital=102000.0,
            total_return=0.02,
            sharpe_ratio=0.3,
            max_drawdown=-0.01,
            annualized_return=0.08,
            equity_curve=json.dumps(equity_curve),
            regime_history=json.dumps(regime_history),
            trades=[],
            status='completed'
        )

    def _create_interaction_scenario(self) -> BacktestResultModel:
        """Create backtest testing interaction effects."""
        start_date = date(2024, 1, 1)
        end_date = date(2024, 3, 31)

        equity_curve = [
            [start_date.isoformat(), 100000.0],
            [(start_date + timedelta(days=30)).isoformat(), 103000.0],
            [(start_date + timedelta(days=60)).isoformat(), 106000.0],
            [end_date.isoformat(), 108000.0],
        ]

        regime_history = [
            {"date": start_date.isoformat(), "regime": "RECOVERY", "confidence": 0.8},
        ]

        return BacktestResultModel(
            name="Interaction Test",
            start_date=start_date,
            end_date=end_date,
            initial_capital=100000.0,
            final_capital=108000.0,
            total_return=0.08,
            sharpe_ratio=1.2,
            max_drawdown=-0.01,
            annualized_return=0.32,
            equity_curve=json.dumps(equity_curve),
            regime_history=json.dumps(regime_history),
            trades=[],
            status='completed'
        )


@pytest.mark.django_db
class TestAttributionPersistence:
    """Test persistence and retrieval of attribution data."""

    def test_loss_analysis_persistence(self):
        """Test that loss analysis is correctly persisted."""
        backtest = self._create_loss_backtest()
        backtest.save()

        audit_repo = DjangoAuditRepository()
        backtest_repo = DjangoBacktestRepository()
        use_case = GenerateAttributionReportUseCase(audit_repo, backtest_repo)

        response = use_case.execute(GenerateAttributionReportRequest(backtest_id=backtest.id))

        # Verify loss analysis
        loss_analyses = LossAnalysis.objects.filter(report_id=response.report_id)
        assert loss_analyses.exists()

        loss = loss_analyses.first()
        assert loss.loss_source is not None
        assert loss.impact is not None
        assert loss.impact_percentage is not None
        assert loss.description is not None
        assert loss.improvement_suggestion is not None

    def test_experience_summary_persistence(self):
        """Test that experience summaries are correctly persisted."""
        backtest = self._create_sample_backtest()
        backtest.save()

        audit_repo = DjangoAuditRepository()
        backtest_repo = DjangoBacktestRepository()
        use_case = GenerateAttributionReportUseCase(audit_repo, backtest_repo)

        response = use_case.execute(GenerateAttributionReportRequest(backtest_id=backtest.id))

        # Verify experience summary
        summaries = ExperienceSummary.objects.filter(report_id=response.report_id)
        assert summaries.exists()

        summary = summaries.first()
        assert summary.lesson is not None
        assert summary.recommendation is not None
        assert summary.priority in ['HIGH', 'MEDIUM', 'LOW']

    def test_multiple_reports_same_backtest(self):
        """Test handling multiple reports for the same backtest."""
        backtest = self._create_sample_backtest()
        backtest.save()

        audit_repo = DjangoAuditRepository()
        backtest_repo = DjangoBacktestRepository()
        use_case = GenerateAttributionReportUseCase(audit_repo, backtest_repo)

        # Generate two reports
        response1 = use_case.execute(GenerateAttributionReportRequest(backtest_id=backtest.id))
        response2 = use_case.execute(GenerateAttributionReportRequest(backtest_id=backtest.id))

        assert response1.success
        assert response2.success
        assert response1.report_id != response2.report_id

        # Verify both exist
        reports = AttributionReport.objects.filter(backtest_id=backtest.id)
        assert reports.count() == 2

    def _create_sample_backtest(self) -> BacktestResultModel:
        """Create sample backtest."""
        start_date = date(2024, 1, 1)
        end_date = date(2024, 3, 31)

        return BacktestResultModel(
            name="Persistence Test",
            start_date=start_date,
            end_date=end_date,
            initial_capital=100000.0,
            final_capital=110000.0,
            total_return=0.10,
            sharpe_ratio=1.5,
            max_drawdown=-0.03,
            annualized_return=0.40,
            equity_curve=json.dumps([
                [start_date.isoformat(), 100000.0],
                [end_date.isoformat(), 110000.0]
            ]),
            regime_history=json.dumps([
                {"date": start_date.isoformat(), "regime": "RECOVERY", "confidence": 0.85}
            ]),
            trades=[],
            status='completed'
        )

    def _create_loss_backtest(self) -> BacktestResultModel:
        """Create loss backtest."""
        start_date = date(2024, 1, 1)
        end_date = date(2024, 3, 31)

        return BacktestResultModel(
            name="Loss Test",
            start_date=start_date,
            end_date=end_date,
            initial_capital=100000.0,
            final_capital=90000.0,
            total_return=-0.10,
            sharpe_ratio=-0.5,
            max_drawdown=-0.15,
            annualized_return=-0.40,
            equity_curve=json.dumps([
                [start_date.isoformat(), 100000.0],
                [end_date.isoformat(), 90000.0]
            ]),
            regime_history=json.dumps([
                {"date": start_date.isoformat(), "regime": "RECOVERY", "confidence": 0.3}
            ]),
            trades=[],
            status='completed'
        )
