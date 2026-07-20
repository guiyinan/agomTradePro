"""Indicator performance and threshold-config persistence for Audit.

Owns ORM persistence for indicator performance records, threshold configs,
and the cross-module read wrappers (macro facts, regime logs).
"""

from datetime import date

from apps.data_center.infrastructure.macro_fact_selection import (
    configured_macro_source,
    select_macro_fact_series,
)
from apps.data_center.infrastructure.models import IndicatorCatalogModel, MacroFactModel

from .models import (
    IndicatorPerformanceModel,
    IndicatorThresholdConfigModel,
)

__all__ = ["IndicatorRepositoryMixin"]


class IndicatorRepositoryMixin:
    """Indicator performance and threshold configuration persistence."""

    def get_indicator_performance(
        self,
        indicator_code: str,
        start_date: date,
        end_date: date,
    ) -> list[dict]:
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

    def get_latest_indicator_performance(self, indicator_code: str) -> dict | None:
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

    def get_latest_indicator_performance_detail(self, indicator_code: str) -> dict | None:
        """获取指标最新表现的完整详情。"""
        try:
            performance = (
                IndicatorPerformanceModel._default_manager.filter(indicator_code=indicator_code)
                .order_by("-evaluation_period_end")
                .first()
            )
            if performance is None:
                return None
            return {
                "indicator_code": performance.indicator_code,
                "evaluation_period_start": performance.evaluation_period_start,
                "evaluation_period_end": performance.evaluation_period_end,
                "true_positive_count": performance.true_positive_count,
                "false_positive_count": performance.false_positive_count,
                "true_negative_count": performance.true_negative_count,
                "false_negative_count": performance.false_negative_count,
                "precision": float(performance.precision)
                if performance.precision is not None
                else None,
                "recall": float(performance.recall) if performance.recall is not None else None,
                "f1_score": float(performance.f1_score)
                if performance.f1_score is not None
                else None,
                "accuracy": float(performance.accuracy)
                if performance.accuracy is not None
                else None,
                "lead_time_mean": float(performance.lead_time_mean)
                if performance.lead_time_mean is not None
                else None,
                "lead_time_std": float(performance.lead_time_std)
                if performance.lead_time_std is not None
                else None,
                "stability_score": float(performance.stability_score)
                if performance.stability_score is not None
                else None,
                "decay_rate": float(performance.decay_rate)
                if performance.decay_rate is not None
                else None,
                "signal_strength": float(performance.signal_strength)
                if performance.signal_strength is not None
                else None,
                "recommended_action": performance.recommended_action,
                "recommended_weight": float(performance.recommended_weight)
                if performance.recommended_weight is not None
                else None,
                "confidence_level": float(performance.confidence_level)
                if performance.confidence_level is not None
                else None,
            }
        except IndicatorPerformanceModel.DoesNotExist:
            return None

    def get_active_threshold_configs(self) -> list[dict]:
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

    def get_threshold_config_by_indicator(
        self,
        indicator_code: str
    ) -> dict | None:
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
        f1_score: float | None = None,
        precision_score: float | None = None,
        recall_score: float | None = None,
        stability_score: float = 0.0,
        recommended_action: str = 'keep',
        recommended_weight: float = 1.0,
        confidence_level: float = 0.5,
        analysis_details: dict | None = None,
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

    def get_indicator_performance_reports(
        self,
        validation_run_id: str | None = None,
        indicator_code: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
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

    def get_indicator_performance_records_by_period(
        self,
        start_date: date,
        end_date: date,
    ) -> list[IndicatorPerformanceModel]:
        """按评估周期返回指标表现 ORM 记录。"""
        return list(
            IndicatorPerformanceModel._default_manager.filter(
                evaluation_period_start=start_date,
                evaluation_period_end=end_date,
            ).order_by("indicator_code")
        )

    def get_recent_indicator_performance_records(
        self,
        indicator_code: str,
        *,
        limit: int = 3,
    ) -> list[IndicatorPerformanceModel]:
        """返回某个指标最近的若干条表现记录。"""
        return list(
            IndicatorPerformanceModel._default_manager.filter(indicator_code=indicator_code)
            .order_by("-evaluation_period_end")[:limit]
        )

    def get_macro_indicator_values(
        self,
        indicator_code: str,
        start_date: date,
        end_date: date,
    ) -> list[tuple]:
        """
        获取宏观指标历史值（跨模块查询包装）

        Args:
            indicator_code: 指标代码
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            List[tuple]: (reporting_period, value) 元组列表
        """
        queryset = MacroFactModel._default_manager.filter(
            indicator_code=indicator_code,
            reporting_period__gte=start_date,
            reporting_period__lte=end_date,
        ).order_by('reporting_period', 'id')
        catalog = IndicatorCatalogModel._default_manager.filter(code=indicator_code).first()
        selection = select_macro_fact_series(
            list(queryset),
            preferred_source=configured_macro_source(catalog.extra if catalog else {}),
        )

        return [(fact.reporting_period, fact.value) for fact in selection.facts]

    def get_regime_log_values(
        self,
        start_date: date,
        end_date: date,
    ) -> list[dict]:
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

    def get_active_threshold_configs_by_codes(
        self,
        indicator_codes: list[str] | None = None
    ) -> list[dict]:
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
        indicator_codes: list[str] | None = None
    ) -> int:
        """统计激活的阈值配置数量"""
        queryset = IndicatorThresholdConfigModel._default_manager.filter(
            is_active=True
        )
        if indicator_codes:
            queryset = queryset.filter(indicator_code__in=indicator_codes)
        return queryset.count()

    def get_performance_reports_by_date_range(
        self,
        start_date: date,
        end_date: date,
    ) -> list[dict]:
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

    def update_threshold_config_levels(
        self,
        indicator_code: str,
        *,
        level_low: float,
        level_high: float,
    ) -> bool:
        """更新阈值配置的高低阈值。"""
        try:
            config = IndicatorThresholdConfigModel._default_manager.get(
                indicator_code=indicator_code,
                is_active=True,
            )
            config.level_low = level_low
            config.level_high = level_high
            config.save(update_fields=["level_low", "level_high", "updated_at"])
            return True
        except IndicatorThresholdConfigModel.DoesNotExist:
            return False

    def get_indicator_performance_by_date_range(
        self,
        start_date: date,
        end_date: date,
    ) -> list[dict]:
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
