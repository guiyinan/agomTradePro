"""Indicator performance and threshold-config persistence for Audit.

Owns ORM persistence for indicator performance records, threshold configs,
and the cross-module read wrappers (macro facts, regime logs).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import date

from apps.audit.domain.interfaces import (
    IndicatorPerformanceRecord,
    IndicatorThresholdRecord,
    RegimeLogRecord,
)
from apps.data_center.infrastructure.macro_fact_selection import (
    configured_macro_source,
    select_macro_fact_series,
)
from apps.data_center.infrastructure.models import IndicatorCatalogModel, MacroFactModel

from .indicator_repository_values import MacroFactCandidate as _MacroFactCandidate
from .indicator_repository_values import json_float_mapping as _json_float_mapping
from .indicator_repository_values import json_mapping as _json_mapping
from .indicator_repository_values import json_object_list as _json_object_list
from .indicator_repository_values import nonnegative_int as _nonnegative_int
from .indicator_repository_values import optional_finite_float as _optional_finite_float
from .indicator_repository_values import required_finite_float as _required_finite_float
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
    ) -> list[dict[str, object]]:
        """获取指标在指定时间段内的表现记录"""
        if start_date > end_date:
            raise ValueError("start_date must not be after end_date")
        performances = IndicatorPerformanceModel._default_manager.filter(
            indicator_code=indicator_code,
            evaluation_period_start__gte=start_date,
            evaluation_period_end__lte=end_date,
        ).order_by("-evaluation_period_end")

        return [
            {
                "id": p.id,
                "indicator_code": p.indicator_code,
                "evaluation_period_start": p.evaluation_period_start.isoformat(),
                "evaluation_period_end": p.evaluation_period_end.isoformat(),
                "validation_run_id": p.validation_run_id,
                "f1_score": _optional_finite_float(p.f1_score),
                "stability_score": _required_finite_float(
                    p.stability_score, field_name="stability_score"
                ),
                "recommended_action": p.recommended_action,
                "recommended_weight": float(p.recommended_weight),
                "confidence_level": float(p.confidence_level),
                "created_at": p.created_at.isoformat(),
            }
            for p in performances
        ]

    def get_latest_indicator_performance(self, indicator_code: str) -> dict[str, object] | None:
        """获取指标最新的表现记录"""
        try:
            performance = IndicatorPerformanceModel._default_manager.filter(
                indicator_code=indicator_code
            ).latest("evaluation_period_end")

            return {
                "id": performance.id,
                "indicator_code": performance.indicator_code,
                "evaluation_period_start": performance.evaluation_period_start.isoformat(),
                "evaluation_period_end": performance.evaluation_period_end.isoformat(),
                "validation_run_id": performance.validation_run_id,
                "f1_score": _optional_finite_float(performance.f1_score),
                "stability_score": float(performance.stability_score),
                "recommended_action": performance.recommended_action,
                "recommended_weight": float(performance.recommended_weight),
                "confidence_level": float(performance.confidence_level),
                "created_at": performance.created_at.isoformat(),
            }
        except IndicatorPerformanceModel.DoesNotExist:
            return None

    def get_latest_indicator_performance_detail(
        self, indicator_code: str
    ) -> dict[str, object] | None:
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
                "validation_run_id": performance.validation_run_id,
                "evaluation_period_start": performance.evaluation_period_start,
                "evaluation_period_end": performance.evaluation_period_end,
                "true_positive_count": performance.true_positive_count,
                "false_positive_count": performance.false_positive_count,
                "true_negative_count": performance.true_negative_count,
                "false_negative_count": performance.false_negative_count,
                "precision": (
                    float(performance.precision) if performance.precision is not None else None
                ),
                "recall": float(performance.recall) if performance.recall is not None else None,
                "f1_score": (
                    float(performance.f1_score) if performance.f1_score is not None else None
                ),
                "accuracy": (
                    float(performance.accuracy) if performance.accuracy is not None else None
                ),
                "lead_time_mean": (
                    float(performance.lead_time_mean)
                    if performance.lead_time_mean is not None
                    else None
                ),
                "lead_time_std": (
                    float(performance.lead_time_std)
                    if performance.lead_time_std is not None
                    else None
                ),
                "stability_score": (
                    float(performance.stability_score)
                    if performance.stability_score is not None
                    else None
                ),
                "decay_rate": (
                    float(performance.decay_rate) if performance.decay_rate is not None else None
                ),
                "signal_strength": (
                    float(performance.signal_strength)
                    if performance.signal_strength is not None
                    else None
                ),
                "recommended_action": performance.recommended_action,
                "recommended_weight": (
                    float(performance.recommended_weight)
                    if performance.recommended_weight is not None
                    else None
                ),
                "confidence_level": (
                    float(performance.confidence_level)
                    if performance.confidence_level is not None
                    else None
                ),
            }
        except IndicatorPerformanceModel.DoesNotExist:
            return None

    def get_active_threshold_configs(self) -> list[IndicatorThresholdRecord]:
        """获取所有激活的阈值配置"""
        configs = IndicatorThresholdConfigModel._default_manager.filter(is_active=True).order_by(
            "category", "indicator_code"
        )

        return [
            {
                "indicator_code": c.indicator_code,
                "indicator_name": c.indicator_name,
                "category": c.category,
                "level_low": float(c.level_low) if c.level_low is not None else None,
                "level_high": float(c.level_high) if c.level_high is not None else None,
                "base_weight": float(c.base_weight),
                "min_weight": float(c.min_weight),
                "max_weight": float(c.max_weight),
                "decay_threshold": float(c.decay_threshold),
                "decay_penalty": float(c.decay_penalty),
                "improvement_threshold": float(c.improvement_threshold),
                "improvement_bonus": float(c.improvement_bonus),
                "action_thresholds": _json_float_mapping(c.action_thresholds),
                "validation_periods": _json_object_list(c.validation_periods),
                "description": c.description,
            }
            for c in configs
        ]

    def get_threshold_config_by_indicator(
        self, indicator_code: str
    ) -> IndicatorThresholdRecord | None:
        """
        获取指标的阈值配置

        Args:
            indicator_code: 指标代码

        Returns:
            Optional[dict]: 阈值配置字典，不存在则返回 None
        """
        try:
            config = IndicatorThresholdConfigModel._default_manager.get(
                indicator_code=indicator_code, is_active=True
            )
            return {
                "indicator_code": config.indicator_code,
                "indicator_name": config.indicator_name,
                "category": config.category,
                "level_low": float(config.level_low) if config.level_low is not None else None,
                "level_high": float(config.level_high) if config.level_high is not None else None,
                "base_weight": float(config.base_weight),
                "min_weight": float(config.min_weight),
                "max_weight": float(config.max_weight),
                "decay_threshold": float(config.decay_threshold),
                "decay_penalty": float(config.decay_penalty),
                "improvement_threshold": float(config.improvement_threshold),
                "improvement_bonus": float(config.improvement_bonus),
                "action_thresholds": _json_float_mapping(config.action_thresholds),
                "validation_periods": _json_object_list(config.validation_periods),
                "description": config.description,
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
        recommended_action: str = "keep",
        recommended_weight: float = 1.0,
        confidence_level: float = 0.5,
        analysis_details: Mapping[str, object] | None = None,
        validation_run_id: str | None = None,
    ) -> int:
        """
        保存指标性能评估记录

        Returns:
            int: 记录 ID
        """
        normalized_code = indicator_code.strip()
        if not normalized_code:
            raise ValueError("indicator_code is required")
        if evaluation_period_start > evaluation_period_end:
            raise ValueError("evaluation period start must not be after end")
        normalized_run_id = (validation_run_id or "").strip() or None
        details = dict(analysis_details or {})
        record = IndicatorPerformanceModel._default_manager.create(
            indicator_code=normalized_code,
            validation_run_id=normalized_run_id,
            evaluation_period_start=evaluation_period_start,
            evaluation_period_end=evaluation_period_end,
            true_positive_count=_nonnegative_int(
                details.get("true_positive_count", 0),
                field_name="true_positive_count",
            ),
            false_positive_count=_nonnegative_int(
                details.get("false_positive_count", 0),
                field_name="false_positive_count",
            ),
            true_negative_count=_nonnegative_int(
                details.get("true_negative_count", 0),
                field_name="true_negative_count",
            ),
            false_negative_count=_nonnegative_int(
                details.get("false_negative_count", 0),
                field_name="false_negative_count",
            ),
            f1_score=(
                _required_finite_float(f1_score, field_name="f1_score")
                if f1_score is not None
                else None
            ),
            precision=(
                _required_finite_float(precision_score, field_name="precision")
                if precision_score is not None
                else None
            ),
            recall=(
                _required_finite_float(recall_score, field_name="recall")
                if recall_score is not None
                else None
            ),
            accuracy=(
                _required_finite_float(details["accuracy"], field_name="accuracy")
                if details.get("accuracy") is not None
                else None
            ),
            lead_time_mean=_required_finite_float(
                details.get("lead_time_mean", 0.0), field_name="lead_time_mean"
            ),
            lead_time_std=_required_finite_float(
                details.get("lead_time_std", 0.0), field_name="lead_time_std"
            ),
            pre_2015_correlation=(
                _required_finite_float(
                    details["pre_2015_correlation"],
                    field_name="pre_2015_correlation",
                )
                if details.get("pre_2015_correlation") is not None
                else None
            ),
            post_2015_correlation=(
                _required_finite_float(
                    details["post_2015_correlation"],
                    field_name="post_2015_correlation",
                )
                if details.get("post_2015_correlation") is not None
                else None
            ),
            stability_score=_required_finite_float(stability_score, field_name="stability_score"),
            decay_rate=_required_finite_float(
                details.get("decay_rate", 0.0), field_name="decay_rate"
            ),
            signal_strength=_required_finite_float(
                details.get("signal_strength", 0.0), field_name="signal_strength"
            ),
            recommended_action=recommended_action,
            recommended_weight=_required_finite_float(
                recommended_weight, field_name="recommended_weight"
            ),
            confidence_level=_required_finite_float(
                confidence_level, field_name="confidence_level"
            ),
        )
        if record.id is None:
            raise RuntimeError("Indicator performance record was not persisted")
        return int(record.id)

    def get_indicator_performance_reports(
        self,
        validation_run_id: str | None = None,
        indicator_code: str | None = None,
        limit: int | None = 100,
    ) -> list[IndicatorPerformanceRecord]:
        """
        获取指标性能报告列表

        Args:
            validation_run_id: 验证运行 ID（可选）
            indicator_code: 指标代码（可选）
            limit: 返回数量限制

        Returns:
            List[dict]: 性能报告列表
        """
        if limit is not None and (limit < 1 or limit > 1000):
            raise ValueError("limit must be between 1 and 1000")
        queryset = IndicatorPerformanceModel._default_manager.all()

        if validation_run_id:
            queryset = queryset.filter(validation_run_id=validation_run_id)
        if indicator_code:
            queryset = queryset.filter(indicator_code=indicator_code)

        queryset = queryset.order_by("-created_at")
        if limit is not None:
            queryset = queryset[:limit]

        return [
            {
                "id": p.id,
                "indicator_code": p.indicator_code,
                "validation_run_id": p.validation_run_id,
                "evaluation_period_start": p.evaluation_period_start.isoformat(),
                "evaluation_period_end": p.evaluation_period_end.isoformat(),
                "f1_score": _optional_finite_float(p.f1_score),
                "precision": _optional_finite_float(p.precision),
                "recall": _optional_finite_float(p.recall),
                "stability_score": _optional_finite_float(p.stability_score),
                "recommended_action": p.recommended_action,
                "recommended_weight": float(p.recommended_weight),
                "confidence_level": float(p.confidence_level),
                "decay_rate": _optional_finite_float(p.decay_rate),
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
            IndicatorPerformanceModel._default_manager.filter(
                indicator_code=indicator_code
            ).order_by("-evaluation_period_end")[:limit]
        )

    def get_macro_indicator_values(
        self,
        indicator_code: str,
        start_date: date,
        end_date: date,
    ) -> list[tuple[date, float]]:
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
        ).order_by("reporting_period", "id")
        catalog = IndicatorCatalogModel._default_manager.filter(code=indicator_code).first()
        candidates = [
            _MacroFactCandidate(
                indicator_code=fact.indicator_code,
                reporting_period=fact.reporting_period,
                value=float(fact.value),
                source=fact.source,
                revision_number=fact.revision_number,
                published_at=fact.published_at,
                fetched_at=fact.fetched_at,
                extra=_json_mapping(fact.extra),
            )
            for fact in queryset
        ]
        selection = select_macro_fact_series(
            candidates,
            preferred_source=configured_macro_source(catalog.extra if catalog else {}),
        )

        return [(fact.reporting_period, fact.value) for fact in selection.facts]

    def get_regime_log_values(
        self,
        start_date: date,
        end_date: date,
    ) -> list[RegimeLogRecord]:
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
        ).order_by("observed_at")

        return [
            {
                "observed_at": log.observed_at,
                "dominant_regime": log.dominant_regime,
                "confidence": _required_finite_float(log.confidence, field_name="confidence"),
                "growth_momentum_z": _required_finite_float(
                    log.growth_momentum_z, field_name="growth_momentum_z"
                ),
                "inflation_momentum_z": _required_finite_float(
                    log.inflation_momentum_z, field_name="inflation_momentum_z"
                ),
                "distribution": _json_float_mapping(log.distribution),
            }
            for log in queryset
        ]

    def get_active_threshold_configs_by_codes(
        self, indicator_codes: list[str] | None = None
    ) -> list[IndicatorThresholdRecord]:
        """
        获取激活的阈值配置（可选按指标代码过滤）

        Args:
            indicator_codes: 指标代码列表，None 表示获取全部

        Returns:
            List[dict]: 阈值配置字典列表
        """
        queryset = IndicatorThresholdConfigModel._default_manager.filter(is_active=True)

        if indicator_codes:
            queryset = queryset.filter(indicator_code__in=indicator_codes)

        return [
            {
                "indicator_code": c.indicator_code,
                "indicator_name": c.indicator_name,
                "category": c.category,
                "level_low": float(c.level_low) if c.level_low is not None else None,
                "level_high": float(c.level_high) if c.level_high is not None else None,
                "base_weight": float(c.base_weight),
                "min_weight": float(c.min_weight),
                "max_weight": float(c.max_weight),
                "decay_threshold": float(c.decay_threshold),
                "decay_penalty": float(c.decay_penalty),
                "improvement_threshold": float(c.improvement_threshold),
                "improvement_bonus": float(c.improvement_bonus),
                "action_thresholds": _json_float_mapping(c.action_thresholds),
                "validation_periods": _json_object_list(c.validation_periods),
                "description": c.description,
            }
            for c in queryset
        ]

    def count_active_threshold_configs(self, indicator_codes: list[str] | None = None) -> int:
        """统计激活的阈值配置数量"""
        queryset = IndicatorThresholdConfigModel._default_manager.filter(is_active=True)
        if indicator_codes:
            queryset = queryset.filter(indicator_code__in=indicator_codes)
        return queryset.count()

    def get_performance_reports_by_date_range(
        self,
        start_date: date,
        end_date: date,
    ) -> list[IndicatorPerformanceRecord]:
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
                "id": r.id,
                "indicator_code": r.indicator_code,
                "evaluation_period_start": r.evaluation_period_start.isoformat(),
                "evaluation_period_end": r.evaluation_period_end.isoformat(),
                "validation_run_id": r.validation_run_id,
                "f1_score": _optional_finite_float(r.f1_score),
                "precision": _optional_finite_float(r.precision),
                "recall": _optional_finite_float(r.recall),
                "stability_score": _optional_finite_float(r.stability_score),
                "recommended_action": r.recommended_action,
                "recommended_weight": _optional_finite_float(r.recommended_weight),
                "confidence_level": _optional_finite_float(r.confidence_level),
                "decay_rate": _optional_finite_float(r.decay_rate),
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
        if not math.isfinite(new_weight):
            return False
        return bool(
            IndicatorThresholdConfigModel._default_manager.filter(
                indicator_code=indicator_code,
                is_active=True,
                min_weight__lte=new_weight,
                max_weight__gte=new_weight,
            ).update(base_weight=new_weight)
        )

    def update_threshold_config_levels(
        self,
        indicator_code: str,
        *,
        level_low: float,
        level_high: float,
    ) -> bool:
        """更新阈值配置的高低阈值。"""
        if not math.isfinite(level_low) or not math.isfinite(level_high) or level_low >= level_high:
            return False
        return bool(
            IndicatorThresholdConfigModel._default_manager.filter(
                indicator_code=indicator_code,
                is_active=True,
            ).update(level_low=level_low, level_high=level_high)
        )

    def get_indicator_performance_by_date_range(
        self,
        start_date: date,
        end_date: date,
    ) -> list[IndicatorPerformanceRecord]:
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
                "id": r.id,
                "indicator_code": r.indicator_code,
                "evaluation_period_start": r.evaluation_period_start.isoformat(),
                "evaluation_period_end": r.evaluation_period_end.isoformat(),
                "validation_run_id": r.validation_run_id,
                "f1_score": _optional_finite_float(r.f1_score),
                "precision": _optional_finite_float(r.precision),
                "recall": _optional_finite_float(r.recall),
                "stability_score": _optional_finite_float(r.stability_score),
                "recommended_action": r.recommended_action,
                "recommended_weight": _optional_finite_float(r.recommended_weight),
                "confidence_level": _optional_finite_float(r.confidence_level),
                "decay_rate": _optional_finite_float(r.decay_rate),
            }
            for r in queryset
        ]
