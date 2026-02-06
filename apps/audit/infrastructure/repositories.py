"""
Repository for Audit Domain.
"""

from typing import List, Optional
from datetime import date
from django.db.models import QuerySet

from .models import (
    AttributionReport,
    LossAnalysis,
    ExperienceSummary,
    IndicatorPerformanceModel,
    IndicatorThresholdConfigModel,
    ValidationSummaryModel,
)
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
        report = AttributionReport._default_manager.create(
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

    def get_attribution_report(self, report_id: int) -> Optional[dict]:
        """获取归因报告"""
        try:
            report = AttributionReport._default_manager.get(id=report_id)
            return self._serialize_report(report)
        except AttributionReport.DoesNotExist:
            return None

    def get_reports_by_backtest(self, backtest_id: int) -> List[dict]:
        """获取指定回测的所有归因报告"""
        reports = AttributionReport._default_manager.filter(
            backtest_id=backtest_id
        ).order_by('-period_end')

        return [self._serialize_report(r) for r in reports]

    def get_reports_by_date_range(
        self,
        start_date: date,
        end_date: date
    ) -> List[dict]:
        """获取日期范围内的归因报告"""
        reports = AttributionReport._default_manager.filter(
            period_start__gte=start_date,
            period_end__lte=end_date
        ).order_by('-period_end')

        return [self._serialize_report(r) for r in reports]

    def get_loss_analyses(self, report_id: int) -> List[dict]:
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

    def get_experience_summaries(self, report_id: int) -> List[dict]:
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

    # ============ 指标表现评估相关方法 ============

    def get_indicator_performance(
        self,
        indicator_code: str,
        start_date: date,
        end_date: date,
    ) -> List[dict]:
        """获取指标在指定时间段内的表现记录"""
        performances = IndicatorPerformanceModel._default_manager.filter(
            indicator_code=indicator_code,
            evaluation_period_start__gte=start_date,
            evaluation_period_end__lte=end_date,
        ).order_by('-evaluation_period_end')

        return [
            {
                'id': p.id,
                'indicator_code': p.indicator_code,
                'evaluation_period_start': p.evaluation_period_start.isoformat(),
                'evaluation_period_end': p.evaluation_period_end.isoformat(),
                'f1_score': float(p.f1_score) if p.f1_score else None,
                'stability_score': float(p.stability_score),
                'recommended_action': p.recommended_action,
                'recommended_weight': float(p.recommended_weight),
                'confidence_level': float(p.confidence_level),
                'created_at': p.created_at.isoformat(),
            }
            for p in performances
        ]

    def get_latest_indicator_performance(self, indicator_code: str) -> Optional[dict]:
        """获取指标最新的表现记录"""
        try:
            performance = IndicatorPerformanceModel._default_manager.filter(
                indicator_code=indicator_code
            ).latest('evaluation_period_end')

            return {
                'id': performance.id,
                'indicator_code': performance.indicator_code,
                'evaluation_period_start': performance.evaluation_period_start.isoformat(),
                'evaluation_period_end': performance.evaluation_period_end.isoformat(),
                'f1_score': float(performance.f1_score) if performance.f1_score else None,
                'stability_score': float(performance.stability_score),
                'recommended_action': performance.recommended_action,
                'recommended_weight': float(performance.recommended_weight),
                'confidence_level': float(performance.confidence_level),
                'created_at': performance.created_at.isoformat(),
            }
        except IndicatorPerformanceModel.DoesNotExist:
            return None

    def get_active_threshold_configs(self) -> List[dict]:
        """获取所有激活的阈值配置"""
        configs = IndicatorThresholdConfigModel._default_manager.filter(
            is_active=True
        ).order_by('category', 'indicator_code')

        return [
            {
                'indicator_code': c.indicator_code,
                'indicator_name': c.indicator_name,
                'category': c.category,
                'level_low': float(c.level_low) if c.level_low is not None else None,
                'level_high': float(c.level_high) if c.level_high is not None else None,
                'base_weight': float(c.base_weight),
                'min_weight': float(c.min_weight),
                'max_weight': float(c.max_weight),
                'decay_threshold': float(c.decay_threshold),
                'decay_penalty': float(c.decay_penalty),
                'improvement_threshold': float(c.improvement_threshold),
                'improvement_bonus': float(c.improvement_bonus),
                'action_thresholds': c.action_thresholds,
                'validation_periods': c.validation_periods,
                'description': c.description,
            }
            for c in configs
        ]

    def get_validation_summary(self, validation_run_id: str) -> Optional[dict]:
        """获取验证摘要"""
        try:
            summary = ValidationSummaryModel._default_manager.get(
                validation_run_id=validation_run_id
            )

            return {
                'validation_run_id': summary.validation_run_id,
                'run_date': summary.run_date.isoformat(),
                'evaluation_period_start': summary.evaluation_period_start.isoformat(),
                'evaluation_period_end': summary.evaluation_period_end.isoformat(),
                'total_indicators': summary.total_indicators,
                'approved_indicators': summary.approved_indicators,
                'rejected_indicators': summary.rejected_indicators,
                'pending_indicators': summary.pending_indicators,
                'avg_f1_score': float(summary.avg_f1_score) if summary.avg_f1_score else None,
                'avg_stability_score': float(summary.avg_stability_score) if summary.avg_stability_score else None,
                'overall_recommendation': summary.overall_recommendation,
                'status': summary.status,
                'is_shadow_mode': summary.is_shadow_mode,
                'error_message': summary.error_message,
            }
        except ValidationSummaryModel.DoesNotExist:
            return None

    def get_recent_validations(self, limit: int = 10) -> List[dict]:
        """获取最近的验证记录"""
        summaries = ValidationSummaryModel._default_manager.all().order_by('-run_date')[:limit]

        return [
            {
                'validation_run_id': s.validation_run_id,
                'run_date': s.run_date.isoformat(),
                'evaluation_period_start': s.evaluation_period_start.isoformat(),
                'evaluation_period_end': s.evaluation_period_end.isoformat(),
                'total_indicators': s.total_indicators,
                'approved_indicators': s.approved_indicators,
                'rejected_indicators': s.rejected_indicators,
                'pending_indicators': s.pending_indicators,
                'avg_f1_score': float(s.avg_f1_score) if s.avg_f1_score else None,
                'avg_stability_score': float(s.avg_stability_score) if s.avg_stability_score else None,
                'overall_recommendation': s.overall_recommendation,
                'status': s.status,
                'is_shadow_mode': s.is_shadow_mode,
            }
            for s in summaries
        ]

