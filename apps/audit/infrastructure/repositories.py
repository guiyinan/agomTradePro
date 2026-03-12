"""
Repository for Audit Domain.
"""

from typing import List, Optional
from datetime import date
from django.db.models import QuerySet
import logging

from .models import (
    AttributionReport,
    LossAnalysis,
    ExperienceSummary,
    IndicatorPerformanceModel,
    IndicatorThresholdConfigModel,
    ValidationSummaryModel,
)
from apps.backtest.infrastructure.models import BacktestResultModel


logger = logging.getLogger(__name__)


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

    # ============ 用于 Application 层解耦的方法 ============

    def get_threshold_config_by_indicator(
        self,
        indicator_code: str
    ) -> Optional[dict]:
        """
        获取指标的阈值配置

        Args:
            indicator_code: 指标代码

        Returns:
            Optional[dict]: 阈值配置字典，不存在则返回 None
        """
        try:
            config = IndicatorThresholdConfigModel._default_manager.get(
                indicator_code=indicator_code,
                is_active=True
            )
            return {
                'indicator_code': config.indicator_code,
                'indicator_name': config.indicator_name,
                'category': config.category,
                'level_low': float(config.level_low) if config.level_low is not None else None,
                'level_high': float(config.level_high) if config.level_high is not None else None,
                'base_weight': float(config.base_weight),
                'min_weight': float(config.min_weight),
                'max_weight': float(config.max_weight),
                'decay_threshold': float(config.decay_threshold),
                'decay_penalty': float(config.decay_penalty),
                'improvement_threshold': float(config.improvement_threshold),
                'improvement_bonus': float(config.improvement_bonus),
                'action_thresholds': config.action_thresholds or {},
                'validation_periods': config.validation_periods or {},
                'description': config.description,
            }
        except IndicatorThresholdConfigModel.DoesNotExist:
            return None

    def save_indicator_performance_record(
        self,
        indicator_code: str,
        evaluation_period_start: date,
        evaluation_period_end: date,
        f1_score: Optional[float] = None,
        precision_score: Optional[float] = None,
        recall_score: Optional[float] = None,
        stability_score: float = 0.0,
        recommended_action: str = 'keep',
        recommended_weight: float = 1.0,
        confidence_level: float = 0.5,
        analysis_details: Optional[dict] = None,
    ) -> int:
        """
        保存指标性能评估记录

        Returns:
            int: 记录 ID
        """
        record = IndicatorPerformanceModel._default_manager.create(
            indicator_code=indicator_code,
            evaluation_period_start=evaluation_period_start,
            evaluation_period_end=evaluation_period_end,
            true_positive_count=(analysis_details or {}).get('true_positive_count', 0),
            false_positive_count=(analysis_details or {}).get('false_positive_count', 0),
            true_negative_count=(analysis_details or {}).get('true_negative_count', 0),
            false_negative_count=(analysis_details or {}).get('false_negative_count', 0),
            f1_score=f1_score,
            precision=precision_score,
            recall=recall_score,
            accuracy=(analysis_details or {}).get('accuracy'),
            lead_time_mean=(analysis_details or {}).get('lead_time_mean', 0.0),
            lead_time_std=(analysis_details or {}).get('lead_time_std', 0.0),
            pre_2015_correlation=(analysis_details or {}).get('pre_2015_correlation'),
            post_2015_correlation=(analysis_details or {}).get('post_2015_correlation'),
            stability_score=stability_score,
            decay_rate=(analysis_details or {}).get('decay_rate', 0.0),
            signal_strength=(analysis_details or {}).get('signal_strength', 0.0),
            recommended_action=recommended_action,
            recommended_weight=recommended_weight,
            confidence_level=confidence_level,
        )
        return record.id

    def save_validation_summary_record(
        self,
        validation_run_id: str,
        run_date: date,
        evaluation_period_start: date,
        evaluation_period_end: date,
        total_indicators: int = 0,
        approved_indicators: int = 0,
        rejected_indicators: int = 0,
        pending_indicators: int = 0,
        avg_f1_score: Optional[float] = None,
        avg_stability_score: Optional[float] = None,
        overall_recommendation: str = '',
        status: str = 'pending',
        is_shadow_mode: bool = True,
        error_message: str = '',
    ) -> str:
        """
        保存验证摘要记录

        Returns:
            str: validation_run_id
        """
        ValidationSummaryModel._default_manager.create(
            validation_run_id=validation_run_id,
            run_date=run_date,
            evaluation_period_start=evaluation_period_start,
            evaluation_period_end=evaluation_period_end,
            total_indicators=total_indicators,
            approved_indicators=approved_indicators,
            rejected_indicators=rejected_indicators,
            pending_indicators=pending_indicators,
            avg_f1_score=avg_f1_score,
            avg_stability_score=avg_stability_score,
            overall_recommendation=overall_recommendation,
            status=status,
            is_shadow_mode=is_shadow_mode,
            error_message=error_message,
        )
        return validation_run_id

    def get_validation_summary_by_id(self, summary_id: int) -> Optional[dict]:
        """根据 ID 获取验证摘要"""
        try:
            summary = ValidationSummaryModel._default_manager.get(id=summary_id)
            return {
                'id': summary.id,
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

    def get_latest_validation_summary_record(self) -> Optional[dict]:
        """获取最新的验证摘要记录"""
        try:
            summary = ValidationSummaryModel._default_manager.all().latest('run_date')
            return {
                'id': summary.id,
                'validation_run_id': summary.validation_run_id,
                'run_date': summary.run_date.isoformat(),
                'status': summary.status,
                'is_shadow_mode': summary.is_shadow_mode,
            }
        except ValidationSummaryModel.DoesNotExist:
            return None

    def get_indicator_performance_reports(
        self,
        validation_run_id: Optional[str] = None,
        indicator_code: Optional[str] = None,
        limit: int = 100,
    ) -> List[dict]:
        """
        获取指标性能报告列表

        Args:
            validation_run_id: 验证运行 ID（可选）
            indicator_code: 指标代码（可选）
            limit: 返回数量限制

        Returns:
            List[dict]: 性能报告列表
        """
        queryset = IndicatorPerformanceModel._default_manager.all()

        if indicator_code:
            queryset = queryset.filter(indicator_code=indicator_code)

        queryset = queryset.order_by('-created_at')[:limit]

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
            }
            for p in queryset
        ]

    # ============ 跨模块查询包装方法 ============

    def get_macro_indicator_values(
        self,
        indicator_code: str,
        start_date: date,
        end_date: date,
    ) -> List[tuple]:
        """
        获取宏观指标历史值（跨模块查询包装）

        Args:
            indicator_code: 指标代码
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            List[tuple]: (reporting_period, value) 元组列表
        """
        from apps.macro.infrastructure.models import MacroIndicator

        queryset = MacroIndicator._default_manager.filter(
            code=indicator_code,
            reporting_period__gte=start_date,
            reporting_period__lte=end_date,
        ).order_by('reporting_period')

        return list(queryset.values_list('reporting_period', 'value'))

    def get_regime_log_values(
        self,
        start_date: date,
        end_date: date,
    ) -> List[dict]:
        """
        获取 Regime 日志历史（跨模块查询包装)

        Args:
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            List[dict]: Regime 日志字典列表
        """
        from apps.regime.infrastructure.models import RegimeLog

        queryset = RegimeLog._default_manager.filter(
            observed_at__gte=start_date,
            observed_at__lte=end_date,
        ).order_by('observed_at')

        return [
            {
                'observed_at': log.observed_at,
                'dominant_regime': log.dominant_regime,
                'confidence': float(log.confidence) if log.confidence else None,
                'growth_momentum_z': float(log.growth_momentum_z) if log.growth_momentum_z else None,
                'inflation_momentum_z': float(log.inflation_momentum_z) if log.inflation_momentum_z else None,
                'distribution': log.distribution or {},
            }
            for log in queryset
        ]

    # ============ ValidateThresholdsUseCase 所需方法 ============

    def get_active_threshold_configs_by_codes(
        self,
        indicator_codes: Optional[List[str]] = None
    ) -> List[dict]:
        """
        获取激活的阈值配置（可选按指标代码过滤）

        Args:
            indicator_codes: 指标代码列表，None 表示获取全部

        Returns:
            List[dict]: 阈值配置字典列表
        """
        queryset = IndicatorThresholdConfigModel._default_manager.filter(
            is_active=True
        )

        if indicator_codes:
            queryset = queryset.filter(indicator_code__in=indicator_codes)

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
                'action_thresholds': c.action_thresholds or {},
            }
            for c in queryset
        ]

    def count_active_threshold_configs(
        self,
        indicator_codes: Optional[List[str]] = None
    ) -> int:
        """统计激活的阈值配置数量"""
        queryset = IndicatorThresholdConfigModel._default_manager.filter(
            is_active=True
        )
        if indicator_codes:
            queryset = queryset.filter(indicator_code__in=indicator_codes)
        return queryset.count()

    def create_validation_summary_record(
        self,
        validation_run_id: str,
        evaluation_period_start: date,
        evaluation_period_end: date,
        total_indicators: int = 0,
        status: str = 'in_progress',
        is_shadow_mode: bool = True,
        run_date: Optional[date] = None,
    ) -> dict:
        """
        创建验证摘要记录

        Returns:
            dict: 创建的记录信息
        """
        summary = ValidationSummaryModel._default_manager.create(
            validation_run_id=validation_run_id,
            run_date=run_date or date.today(),
            evaluation_period_start=evaluation_period_start,
            evaluation_period_end=evaluation_period_end,
            total_indicators=total_indicators,
            status=status,
            is_shadow_mode=is_shadow_mode,
        )
        return {
            'id': summary.id,
            'validation_run_id': summary.validation_run_id,
            'status': summary.status,
        }

    def update_validation_summary_status(
        self,
        validation_run_id: str,
        status: str,
        approved_indicators: int = 0,
        rejected_indicators: int = 0,
        pending_indicators: int = 0,
        avg_f1_score: Optional[float] = None,
        avg_stability_score: Optional[float] = None,
        overall_recommendation: str = '',
        error_message: str = '',
    ) -> bool:
        """
        更新验证摘要状态

        Returns:
            bool: 是否更新成功
        """
        try:
            summary = ValidationSummaryModel._default_manager.get(
                validation_run_id=validation_run_id
            )
            summary.status = status
            summary.approved_indicators = approved_indicators
            summary.rejected_indicators = rejected_indicators
            summary.pending_indicators = pending_indicators
            if avg_f1_score is not None:
                summary.avg_f1_score = avg_f1_score
            if avg_stability_score is not None:
                summary.avg_stability_score = avg_stability_score
            summary.overall_recommendation = overall_recommendation
            if error_message:
                summary.error_message = error_message
            summary.save()
            return True
        except ValidationSummaryModel.DoesNotExist:
            return False

    def get_validation_summary_by_run_id(self, validation_run_id: str) -> Optional[dict]:
        """
        根据运行 ID 获取验证摘要

        Returns:
            Optional[dict]: 验证摘要字典，不存在返回 None
        """
        try:
            summary = ValidationSummaryModel._default_manager.get(
                validation_run_id=validation_run_id
            )
            return {
                'id': summary.id,
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

    def get_performance_reports_by_date_range(
        self,
        start_date: date,
        end_date: date,
    ) -> List[dict]:
        """
        根据日期范围获取指标性能报告

        Returns:
            List[dict]: 性能报告字典列表
        """
        queryset = IndicatorPerformanceModel._default_manager.filter(
            evaluation_period_start=start_date,
            evaluation_period_end=end_date,
        )

        return [
            {
                'id': r.id,
                'indicator_code': r.indicator_code,
                'evaluation_period_start': r.evaluation_period_start.isoformat(),
                'evaluation_period_end': r.evaluation_period_end.isoformat(),
                'f1_score': float(r.f1_score) if r.f1_score else None,
                'precision': float(r.precision) if r.precision else None,
                'recall': float(r.recall) if r.recall else None,
                'stability_score': float(r.stability_score) if r.stability_score else None,
                'recommended_action': r.recommended_action,
                'recommended_weight': float(r.recommended_weight) if r.recommended_weight else None,
                'confidence_level': float(r.confidence_level) if r.confidence_level else None,
            }
            for r in queryset
        ]

    def update_threshold_config_weight(
        self,
        indicator_code: str,
        new_weight: float,
    ) -> bool:
        """
        更新阈值配置的权重

        Returns:
            bool: 是否更新成功
        """
        try:
            config = IndicatorThresholdConfigModel._default_manager.get(
                indicator_code=indicator_code
            )
            config.base_weight = new_weight
            config.save()
            return True
        except IndicatorThresholdConfigModel.DoesNotExist:
            return False

    def get_indicator_performance_by_date_range(
        self,
        start_date: date,
        end_date: date,
    ) -> List[dict]:
        """
        根据日期范围获取指标表现报告

        Returns:
            List[dict]: 指标表现报告字典列表
        """
        queryset = IndicatorPerformanceModel._default_manager.filter(
            evaluation_period_start=start_date,
            evaluation_period_end=end_date,
        )

        return [
            {
                'id': r.id,
                'indicator_code': r.indicator_code,
                'evaluation_period_start': r.evaluation_period_start.isoformat(),
                'evaluation_period_end': r.evaluation_period_end.isoformat(),
                'f1_score': float(r.f1_score) if r.f1_score else None,
                'precision': float(r.precision) if r.precision else None,
                'recall': float(r.recall) if r.recall else None,
                'stability_score': float(r.stability_score) if r.stability_score else None,
                'recommended_action': r.recommended_action,
                'recommended_weight': float(r.recommended_weight) if r.recommended_weight else None,
                'confidence_level': float(r.confidence_level) if r.confidence_level else None,
                'decay_rate': float(r.decay_rate) if r.decay_rate else None,
            }
            for r in queryset
        ]

    # ============ MCP/SDK 操作审计日志相关方法 ============

    def save_operation_log(self, log_entity) -> str:
        """
        保存操作日志

        增强可观测性：
        - 失败时记录到失败计数器
        - 记录详细错误日志
        - 不抛出异常（让上层决定如何处理）

        Args:
            log_entity: OperationLog 域实体

        Returns:
            str: 日志 ID
        """
        from .models import OperationLogModel

        try:
            model = OperationLogModel._default_manager.create(
                id=log_entity.id,
                request_id=log_entity.request_id,
                user_id=log_entity.user_id,
                username=log_entity.username,
                ip_address=log_entity.ip_address,
                user_agent=log_entity.user_agent,
                source=log_entity.source.value,
                client_id=log_entity.client_id,
                operation_type=log_entity.operation_type.value,
                module=log_entity.module,
                action=log_entity.action.value,
                resource_type=log_entity.resource_type,
                resource_id=log_entity.resource_id,
                mcp_tool_name=log_entity.mcp_tool_name,
                mcp_client_id=log_entity.mcp_client_id,
                mcp_role=log_entity.mcp_role,
                sdk_version=log_entity.sdk_version,
                request_method=log_entity.request_method,
                request_path=log_entity.request_path,
                request_params=log_entity.request_params,
                response_payload=log_entity.response_payload,
                response_text=log_entity.response_text,
                response_status=log_entity.response_status,
                response_message=log_entity.response_message,
                error_code=log_entity.error_code,
                exception_traceback=log_entity.exception_traceback,
                duration_ms=log_entity.duration_ms,
                checksum=log_entity.checksum,
            )
            logger.debug(
                f"操作日志保存成功: log_id={model.id}, "
                f"user={log_entity.username}, module={log_entity.module}"
            )
            return str(model.id)

        except Exception as e:
            # 记录到失败计数器（增强可观测性）
            try:
                from .failure_counter import record_audit_failure
                record_audit_failure(
                    component="database",
                    reason=f"save_operation_log failed: {type(e).__name__}: {str(e)[:200]}",
                )
            except ImportError:
                pass

            # 记录详细错误日志
            logger.error(
                f"保存操作日志失败: user={log_entity.username}, "
                f"module={log_entity.module}, action={log_entity.action}, error={e}",
                exc_info=True,
            )
            # 重新抛出异常，让上层用例处理
            raise

    def query_operation_logs(
        self,
        user_id: Optional[int] = None,
        username: Optional[str] = None,
        operation_type: Optional[str] = None,
        module: Optional[str] = None,
        action: Optional[str] = None,
        mcp_tool_name: Optional[str] = None,
        mcp_client_id: Optional[str] = None,
        mcp_role: Optional[str] = None,
        response_status: Optional[int] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        resource_id: Optional[str] = None,
        source: Optional[str] = None,
        ordering: str = "-timestamp",
        page: int = 1,
        page_size: int = 20,
    ) -> tuple:
        """
        查询操作日志

        Args:
            各种过滤条件
            ordering: 排序字段
            page: 页码
            page_size: 每页数量

        Returns:
            tuple: (logs_list, total_count)
        """
        from .models import OperationLogModel
        from django.db.models import Q

        queryset = OperationLogModel._default_manager.all()

        # 应用过滤条件
        if user_id is not None:
            queryset = queryset.filter(user_id=user_id)
        if username:
            queryset = queryset.filter(username__icontains=username)
        if operation_type:
            queryset = queryset.filter(operation_type=operation_type)
        if module:
            queryset = queryset.filter(module=module)
        if action:
            queryset = queryset.filter(action=action)
        if mcp_tool_name:
            queryset = queryset.filter(mcp_tool_name__icontains=mcp_tool_name)
        if mcp_client_id:
            queryset = queryset.filter(mcp_client_id__icontains=mcp_client_id)
        if mcp_role:
            queryset = queryset.filter(mcp_role=mcp_role)
        if response_status is not None:
            queryset = queryset.filter(response_status=response_status)
        if start_date:
            queryset = queryset.filter(timestamp__date__gte=start_date)
        if end_date:
            queryset = queryset.filter(timestamp__date__lte=end_date)
        if resource_id:
            queryset = queryset.filter(resource_id=resource_id)
        if source:
            queryset = queryset.filter(source=source)

        # 统计总数
        total_count = queryset.count()

        # 排序
        queryset = queryset.order_by(ordering)

        # 分页
        offset = (page - 1) * page_size
        queryset = queryset[offset:offset + page_size]

        # 序列化
        logs = [
            {
                'id': str(log.id),
                'request_id': log.request_id,
                'user_id': log.user_id,
                'username': log.username,
                'ip_address': log.ip_address,
                'user_agent': log.user_agent,
                'source': log.source,
                'client_id': log.client_id,
                'operation_type': log.operation_type,
                'module': log.module,
                'action': log.action,
                'resource_type': log.resource_type,
                'resource_id': log.resource_id,
                'mcp_tool_name': log.mcp_tool_name,
                'mcp_client_id': log.mcp_client_id,
                'mcp_role': log.mcp_role,
                'sdk_version': log.sdk_version,
                'request_method': log.request_method,
                'request_path': log.request_path,
                'request_params': log.request_params,
                'response_payload': log.response_payload,
                'response_text': log.response_text,
                'response_status': log.response_status,
                'response_message': log.response_message,
                'error_code': log.error_code,
                'exception_traceback': log.exception_traceback,
                'timestamp': log.timestamp.isoformat(),
                'duration_ms': log.duration_ms,
                'checksum': log.checksum,
            }
            for log in queryset
        ]

        return logs, total_count

    def get_operation_log_by_id(self, log_id: str) -> Optional[dict]:
        """
        根据 ID 获取操作日志

        Args:
            log_id: 日志 ID

        Returns:
            Optional[dict]: 日志字典，不存在返回 None
        """
        from .models import OperationLogModel

        try:
            log = OperationLogModel._default_manager.get(id=log_id)
            return {
                'id': str(log.id),
                'request_id': log.request_id,
                'user_id': log.user_id,
                'username': log.username,
                'ip_address': log.ip_address,
                'user_agent': log.user_agent,
                'source': log.source,
                'client_id': log.client_id,
                'operation_type': log.operation_type,
                'module': log.module,
                'action': log.action,
                'resource_type': log.resource_type,
                'resource_id': log.resource_id,
                'mcp_tool_name': log.mcp_tool_name,
                'mcp_client_id': log.mcp_client_id,
                'mcp_role': log.mcp_role,
                'sdk_version': log.sdk_version,
                'request_method': log.request_method,
                'request_path': log.request_path,
                'request_params': log.request_params,
                'response_payload': log.response_payload,
                'response_text': log.response_text,
                'response_status': log.response_status,
                'response_message': log.response_message,
                'error_code': log.error_code,
                'exception_traceback': log.exception_traceback,
                'timestamp': log.timestamp.isoformat(),
                'duration_ms': log.duration_ms,
                'checksum': log.checksum,
            }
        except (OperationLogModel.DoesNotExist, ValueError):
            return None

    def get_operation_stats(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        group_by: str = "module",
    ) -> dict:
        """
        获取操作统计

        Args:
            start_date: 起始日期
            end_date: 结束日期
            group_by: 分组维度 (module/tool/user/status)

        Returns:
            dict: 统计结果
        """
        from .models import OperationLogModel
        from django.db.models import Count, Avg, Q

        queryset = OperationLogModel._default_manager.all()

        if start_date:
            queryset = queryset.filter(timestamp__date__gte=start_date)
        if end_date:
            queryset = queryset.filter(timestamp__date__lte=end_date)

        # 基础统计
        total_count = queryset.count()
        error_count = queryset.filter(response_status__gte=400).count()
        avg_duration = queryset.aggregate(avg=Avg('duration_ms'))['avg']

        stats = {
            'total_count': total_count,
            'error_count': error_count,
            'error_rate': error_count / total_count if total_count > 0 else 0,
            'avg_duration_ms': round(avg_duration, 2) if avg_duration else None,
            'period': {
                'start_date': start_date.isoformat() if start_date else None,
                'end_date': end_date.isoformat() if end_date else None,
            },
        }

        # 按维度分组统计
        if group_by == "module":
            breakdown = (
                queryset
                .values('module')
                .annotate(count=Count('id'))
                .order_by('-count')[:10]
            )
            stats['by_module'] = list(breakdown)

        elif group_by == "tool":
            breakdown = (
                queryset
                .values('mcp_tool_name')
                .annotate(count=Count('id'))
                .order_by('-count')[:10]
            )
            stats['by_tool'] = list(breakdown)

        elif group_by == "user":
            breakdown = (
                queryset
                .values('user_id', 'username')
                .annotate(count=Count('id'))
                .order_by('-count')[:10]
            )
            stats['by_user'] = list(breakdown)

        elif group_by == "status":
            breakdown = (
                queryset
                .values('response_status')
                .annotate(count=Count('id'))
                .order_by('-count')
            )
            stats['by_status'] = list(breakdown)

        return stats

    def cleanup_old_operation_logs(self, days: int = 90, dry_run: bool = False) -> int:
        """
        清理旧的操作日志

        Args:
            days: 保留天数
            dry_run: 是否只模拟运行

        Returns:
            int: 删除的记录数
        """
        from .models import OperationLogModel
        from datetime import timedelta
        from django.utils import timezone

        cutoff_date = timezone.now() - timedelta(days=days)
        queryset = OperationLogModel._default_manager.filter(timestamp__lt=cutoff_date)

        if dry_run:
            return queryset.count()

        count, _ = queryset.delete()
        return count

    def list_decision_traces(
        self,
        current_user_id: Optional[int] = None,
        is_admin: bool = False,
        mcp_client_id: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict], int]:
        """按 request_id 聚合 MCP/SDK 调用，生成决策链列表。"""
        from .models import OperationLogModel
        from django.db.models import Count, Max, Min

        queryset = OperationLogModel._default_manager.exclude(request_id="")
        if not is_admin and current_user_id is not None:
            queryset = queryset.filter(user_id=current_user_id)
        if mcp_client_id:
            queryset = queryset.filter(mcp_client_id__icontains=mcp_client_id)

        grouped = (
            queryset
            .values("request_id", "mcp_client_id")
            .annotate(
                started_at=Min("timestamp"),
                finished_at=Max("timestamp"),
                step_count=Count("id"),
                last_status=Max("response_status"),
            )
            .order_by("-finished_at")
        )

        total_count = grouped.count()
        offset = (page - 1) * page_size
        rows = list(grouped[offset:offset + page_size])
        trace_keys = [(row["request_id"], row["mcp_client_id"] or "") for row in rows]
        trace_ids = [row["request_id"] for row in rows]
        if not trace_keys:
            return [], total_count

        sample_logs = (
            queryset
            .filter(request_id__in=trace_ids)
            .order_by("request_id", "timestamp")
        )
        samples_by_request: dict[tuple[str, str], list] = {}
        for log in sample_logs:
            samples_by_request.setdefault((log.request_id, log.mcp_client_id or ""), []).append(log)

        traces = []
        for row in rows:
            request_id = row["request_id"]
            client_key = row["mcp_client_id"] or ""
            logs = samples_by_request.get((request_id, client_key), [])
            first_log = logs[0] if logs else None
            last_log = logs[-1] if logs else None
            traces.append({
                "request_id": request_id,
                "mcp_client_id": client_key,
                "username": first_log.username if first_log else "anonymous",
                "user_id": first_log.user_id if first_log else None,
                "source": first_log.source if first_log else "MCP",
                "started_at": row["started_at"].isoformat() if row["started_at"] else None,
                "finished_at": row["finished_at"].isoformat() if row["finished_at"] else None,
                "step_count": row["step_count"],
                "status": "failed" if (last_log and last_log.response_status >= 400) else "success",
                "last_status": last_log.response_status if last_log else 200,
                "modules": list(dict.fromkeys(log.module for log in logs if log.module)),
                "tools": [log.mcp_tool_name or log.operation_type for log in logs],
                "summary": self._build_decision_trace_summary(logs),
            })

        return traces, total_count

    def get_decision_trace(
        self,
        request_id: str,
        mcp_client_id: Optional[str] = None,
        current_user_id: Optional[int] = None,
        is_admin: bool = False,
    ) -> Optional[dict]:
        """获取单条决策链详情。"""
        from .models import OperationLogModel

        queryset = OperationLogModel._default_manager.filter(request_id=request_id).order_by("timestamp")
        if not is_admin and current_user_id is not None:
            queryset = queryset.filter(user_id=current_user_id)
        if mcp_client_id:
            queryset = queryset.filter(mcp_client_id=mcp_client_id)

        logs = list(queryset)
        if not logs:
            return None

        steps = []
        for index, log in enumerate(logs, start=1):
            steps.append({
                "step_index": index,
                "log_id": str(log.id),
                "timestamp": log.timestamp.isoformat(),
                "tool_name": log.mcp_tool_name or log.operation_type,
                "module": log.module,
                "action": log.action,
                "request_path": log.request_path,
                "response_status": log.response_status,
                "duration_ms": log.duration_ms,
                "summary": self._build_step_summary(log),
                "response_message": log.response_message,
            })

        first_log = logs[0]
        last_log = logs[-1]
        return {
            "request_id": request_id,
            "mcp_client_id": first_log.mcp_client_id,
            "username": first_log.username,
            "user_id": first_log.user_id,
            "source": first_log.source,
            "started_at": first_log.timestamp.isoformat(),
            "finished_at": last_log.timestamp.isoformat(),
            "step_count": len(steps),
            "status": "failed" if last_log.response_status >= 400 else "success",
            "final_summary": self._build_step_summary(last_log),
            "steps": steps,
            "logs": [
                {
                    "id": str(log.id),
                    "timestamp": log.timestamp.isoformat(),
                    "mcp_tool_name": log.mcp_tool_name,
                    "module": log.module,
                    "action": log.action,
                    "request_path": log.request_path,
                    "request_params": log.request_params,
                    "response_payload": log.response_payload,
                    "response_text": log.response_text,
                    "response_status": log.response_status,
                    "response_message": log.response_message,
                    "error_code": log.error_code,
                    "exception_traceback": log.exception_traceback,
                    "duration_ms": log.duration_ms,
                    "checksum": log.checksum,
                }
                for log in logs
            ],
        }

    @staticmethod
    def _build_decision_trace_summary(logs: list) -> str:
        """构建决策链摘要。"""
        if not logs:
            return ""
        final_log = logs[-1]
        if final_log.response_status >= 400:
            return f"{final_log.mcp_tool_name or final_log.operation_type} failed: {final_log.response_message or final_log.error_code}"
        return DjangoAuditRepository._build_step_summary(final_log)

    @staticmethod
    def _build_step_summary(log) -> str:
        """从单条日志提炼步骤摘要。"""
        payload = log.response_payload
        if isinstance(payload, dict):
            for key in ("summary", "message", "decision", "status", "result", "recommendation"):
                value = payload.get(key)
                if value:
                    return str(value)
        if log.response_message:
            return log.response_message
        if log.response_text:
            return log.response_text[:160]
        return log.mcp_tool_name or log.operation_type

