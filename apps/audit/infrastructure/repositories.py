"""
Repository for Audit Domain.
"""

from typing import List, Optional
from datetime import date
from django.db.models import QuerySet

from .models import AttributionReport, LossAnalysis, ExperienceSummary
from apps.backtest.infrastructure.models import BacktestResultModel


class DjangoAuditRepository:
    """Audit 数据仓储"""

    def save_attribution_report(
        self,
        backtest_id: int,
        period_start: date,
        period_end: date,
        regime_timing_pnl: float,
        asset_selection_pnl: float,
        interaction_pnl: float,
        total_pnl: float,
        regime_accuracy: float,
        regime_predicted: str,
        regime_actual: Optional[str] = None,
    ) -> int:
        """
        保存归因分析报告

        Returns:
            int: 报告 ID
        """
        report = AttributionReport.objects.create(
            backtest_id=backtest_id,
            period_start=period_start,
            period_end=period_end,
            regime_timing_pnl=regime_timing_pnl,
            asset_selection_pnl=asset_selection_pnl,
            interaction_pnl=interaction_pnl,
            total_pnl=total_pnl,
            regime_accuracy=regime_accuracy,
            regime_predicted=regime_predicted,
            regime_actual=regime_actual,
        )
        return report.id

    def save_loss_analysis(
        self,
        report_id: int,
        loss_source: str,
        impact: float,
        impact_percentage: float,
        description: str,
        improvement_suggestion: str = '',
    ) -> int:
        """保存损失归因分析"""
        analysis = LossAnalysis.objects.create(
            report_id=report_id,
            loss_source=loss_source,
            impact=impact,
            impact_percentage=impact_percentage,
            description=description,
            improvement_suggestion=improvement_suggestion,
        )
        return analysis.id

    def save_experience_summary(
        self,
        report_id: int,
        lesson: str,
        recommendation: str,
        priority: str = 'MEDIUM',
    ) -> int:
        """保存经验总结"""
        summary = ExperienceSummary.objects.create(
            report_id=report_id,
            lesson=lesson,
            recommendation=recommendation,
            priority=priority,
        )
        return summary.id

    def get_attribution_report(self, report_id: int) -> Optional[dict]:
        """获取归因报告"""
        try:
            report = AttributionReport.objects.get(id=report_id)
            return self._serialize_report(report)
        except AttributionReport.DoesNotExist:
            return None

    def get_reports_by_backtest(self, backtest_id: int) -> List[dict]:
        """获取指定回测的所有归因报告"""
        reports = AttributionReport.objects.filter(
            backtest_id=backtest_id
        ).order_by('-period_end')

        return [self._serialize_report(r) for r in reports]

    def get_reports_by_date_range(
        self,
        start_date: date,
        end_date: date
    ) -> List[dict]:
        """获取日期范围内的归因报告"""
        reports = AttributionReport.objects.filter(
            period_start__gte=start_date,
            period_end__lte=end_date
        ).order_by('-period_end')

        return [self._serialize_report(r) for r in reports]

    def get_loss_analyses(self, report_id: int) -> List[dict]:
        """获取报告的损失分析"""
        analyses = LossAnalysis.objects.filter(
            report_id=report_id
        ).order_by('-impact')

        return [
            {
                'id': a.id,
                'loss_source': a.loss_source,
                'loss_source_display': a.get_loss_source_display(),
                'impact': float(a.impact),
                'impact_percentage': float(a.impact_percentage),
                'description': a.description,
                'improvement_suggestion': a.improvement_suggestion,
            }
            for a in analyses
        ]

    def get_experience_summaries(self, report_id: int) -> List[dict]:
        """获取报告的经验总结"""
        summaries = ExperienceSummary.objects.filter(
            report_id=report_id
        ).order_by('-priority', '-created_at')

        return [
            {
                'id': s.id,
                'lesson': s.lesson,
                'recommendation': s.recommendation,
                'priority': s.priority,
                'is_applied': s.is_applied,
                'applied_at': s.applied_at.isoformat() if s.applied_at else None,
            }
            for s in summaries
        ]

    def _serialize_report(self, report: AttributionReport) -> dict:
        """序列化归因报告"""
        return {
            'id': report.id,
            'backtest_id': report.backtest_id,
            'period_start': report.period_start.isoformat(),
            'period_end': report.period_end.isoformat(),
            'regime_timing_pnl': float(report.regime_timing_pnl),
            'asset_selection_pnl': float(report.asset_selection_pnl),
            'interaction_pnl': float(report.interaction_pnl),
            'total_pnl': float(report.total_pnl),
            'regime_accuracy': float(report.regime_accuracy),
            'regime_predicted': report.regime_predicted,
            'regime_actual': report.regime_actual,
            'created_at': report.created_at.isoformat(),
        }
