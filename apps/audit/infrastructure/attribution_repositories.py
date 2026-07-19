"""Attribution report persistence for Audit.

Owns ORM persistence for attribution reports, loss analyses, and experience
summaries, plus the lightweight database health probe.
"""

from datetime import date

from .models import (
    AttributionReport,
    ExperienceSummary,
    LossAnalysis,
)

__all__ = ["AttributionRepositoryMixin"]


class AttributionRepositoryMixin:
    """Attribution report, loss analysis, and experience summary persistence."""

    def get_database_health(self) -> dict[str, str]:
        """Run a lightweight database probe and return connection metadata."""

        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")

        return {
            "database": str(connection.settings_dict["NAME"]),
            "engine": str(connection.settings_dict["ENGINE"]),
        }

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
        regime_actual: str | None = None,
        attribution_method: str = 'heuristic',
    ) -> int:
        """
        保存归因分析报告

        Args:
            attribution_method: 归因方法 ('heuristic' 或 'brinson')

        Returns:
            int: 报告 ID
        """
        report = AttributionReport._default_manager.create(
            backtest_id=backtest_id,
            period_start=period_start,
            period_end=period_end,
            attribution_method=attribution_method,
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
        analysis = LossAnalysis._default_manager.create(
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
        summary = ExperienceSummary._default_manager.create(
            report_id=report_id,
            lesson=lesson,
            recommendation=recommendation,
            priority=priority,
        )
        return summary.id

    def get_attribution_report(self, report_id: int) -> dict | None:
        """获取归因报告"""
        try:
            report = AttributionReport._default_manager.get(id=report_id)
            return self._serialize_report(report)
        except AttributionReport.DoesNotExist:
            return None

    def list_attribution_report_records(
        self,
        attribution_method: str | None = None,
        limit: int | None = None,
    ) -> list[AttributionReport]:
        """返回归因报告 ORM 记录，供界面层查询服务组装页面上下文。"""
        queryset = AttributionReport._default_manager.select_related("backtest").order_by(
            "-created_at"
        )
        if attribution_method:
            queryset = queryset.filter(attribution_method=attribution_method)
        if limit is not None:
            queryset = queryset[:limit]
        return list(queryset)

    def count_attribution_reports(self) -> int:
        """统计归因报告总数。"""
        return AttributionReport._default_manager.count()

    def get_reported_backtest_ids(self) -> set[int]:
        """返回已生成归因报告的回测 ID 集合。"""
        return set(AttributionReport._default_manager.values_list("backtest_id", flat=True))

    def get_attribution_report_record(self, report_id: int) -> AttributionReport | None:
        """按 ID 返回归因报告 ORM 记录。"""
        try:
            return AttributionReport._default_manager.select_related("backtest").get(id=report_id)
        except AttributionReport.DoesNotExist:
            return None

    def get_reports_by_backtest(self, backtest_id: int) -> list[dict]:
        """获取指定回测的所有归因报告"""
        reports = AttributionReport._default_manager.filter(
            backtest_id=backtest_id
        ).order_by('-period_end')

        return [self._serialize_report(r) for r in reports]

    def get_reports_by_date_range(
        self,
        start_date: date,
        end_date: date
    ) -> list[dict]:
        """获取日期范围内的归因报告"""
        reports = AttributionReport._default_manager.filter(
            period_start__gte=start_date,
            period_end__lte=end_date
        ).order_by('-period_end')

        return [self._serialize_report(r) for r in reports]

    def get_loss_analyses(self, report_id: int) -> list[dict]:
        """获取报告的损失分析"""
        analyses = LossAnalysis._default_manager.filter(
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

    def get_loss_analysis_records(self, report_id: int) -> list[LossAnalysis]:
        """返回损失分析 ORM 记录。"""
        return list(
            LossAnalysis._default_manager.filter(report_id=report_id).order_by("-impact")
        )

    def get_experience_summaries(self, report_id: int) -> list[dict]:
        """获取报告的经验总结"""
        summaries = ExperienceSummary._default_manager.filter(
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

    def get_experience_summary_records(self, report_id: int) -> list[ExperienceSummary]:
        """返回经验总结 ORM 记录。"""
        return list(
            ExperienceSummary._default_manager.filter(report_id=report_id).order_by(
                "-priority", "-created_at"
            )
        )

    def _serialize_report(self, report: AttributionReport) -> dict:
        """序列化归因报告"""
        return {
            'id': report.id,
            'backtest_id': report.backtest_id,
            'period_start': report.period_start.isoformat(),
            'period_end': report.period_end.isoformat(),
            'attribution_method': report.attribution_method,
            'attribution_method_display': report.get_attribution_method_display(),
            'regime_timing_pnl': float(report.regime_timing_pnl),
            'asset_selection_pnl': float(report.asset_selection_pnl),
            'interaction_pnl': float(report.interaction_pnl),
            'total_pnl': float(report.total_pnl),
            'regime_accuracy': float(report.regime_accuracy),
            'regime_predicted': report.regime_predicted,
            'regime_actual': report.regime_actual,
            'created_at': report.created_at.isoformat(),
        }
