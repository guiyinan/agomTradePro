"""Indicator performance evaluation and threshold validation use cases."""

import logging
import uuid
from dataclasses import dataclass
from datetime import date

from apps.audit.application.attribution_use_cases import (
    RECOVERABLE_AUDIT_USE_CASE_EXCEPTIONS,
)
from apps.audit.application.repository_provider import DjangoAuditRepository
from apps.audit.domain.entities import (
    DynamicWeightConfig,
    IndicatorPerformanceReport,
    IndicatorThresholdConfig,
    RegimeSnapshot,
    ThresholdValidationReport,
    ValidationStatus,
)
from apps.audit.domain.services import IndicatorPerformanceAnalyzer

logger = logging.getLogger(__name__)
_THRESHOLD_VALIDATION_FAILURE = "threshold_validation_failed"

__all__ = [
    "AdjustIndicatorWeightsRequest",
    "AdjustIndicatorWeightsResponse",
    "AdjustIndicatorWeightsUseCase",
    "EvaluateIndicatorPerformanceRequest",
    "EvaluateIndicatorPerformanceResponse",
    "EvaluateIndicatorPerformanceUseCase",
    "ValidateThresholdsRequest",
    "ValidateThresholdsResponse",
    "ValidateThresholdsUseCase",
]


# ============ 指标表现评估用例 ============


@dataclass
class EvaluateIndicatorPerformanceRequest:
    """评估指标表现请求"""

    indicator_code: str
    start_date: date
    end_date: date
    use_shadow_mode: bool = False  # 影子模式：不保存结果
    validation_run_id: str | None = None


@dataclass
class EvaluateIndicatorPerformanceResponse:
    """评估指标表现响应"""

    success: bool
    report: IndicatorPerformanceReport | None = None
    report_id: int | None = None
    error: str | None = None


class EvaluateIndicatorPerformanceUseCase:
    """评估指标表现用例"""

    def __init__(self, audit_repository: DjangoAuditRepository):
        self.audit_repo = audit_repository

    def execute(
        self,
        request: EvaluateIndicatorPerformanceRequest,
    ) -> EvaluateIndicatorPerformanceResponse:
        """
        执行评估

        数据流：
        1. 从 MacroIndicator 表获取指标历史值
        2. 从 RegimeLog 表获取 Regime 判定历史
        3. 从 IndicatorThresholdConfigModel 获取阈值配置
        4. 调用 IndicatorPerformanceAnalyzer
        5. 保存报告（除非影子模式）
        """
        try:
            # 1. 获取阈值配置 (通过 Repository)
            threshold_dict = self.audit_repo.get_threshold_config_by_indicator(
                indicator_code=request.indicator_code
            )

            if not threshold_dict:
                return EvaluateIndicatorPerformanceResponse(
                    success=False, error=f"指标 {request.indicator_code} 的阈值配置不存在"
                )

            # 转换为 Domain 层实体
            threshold_config = IndicatorThresholdConfig(
                indicator_code=threshold_dict["indicator_code"],
                indicator_name=threshold_dict["indicator_name"],
                level_low=threshold_dict["level_low"],
                level_high=threshold_dict["level_high"],
                base_weight=threshold_dict["base_weight"],
                min_weight=threshold_dict["min_weight"],
                max_weight=threshold_dict["max_weight"],
                decay_threshold=threshold_dict["decay_threshold"],
                decay_penalty=threshold_dict["decay_penalty"],
                improvement_threshold=threshold_dict["improvement_threshold"],
                improvement_bonus=threshold_dict["improvement_bonus"],
                keep_min_f1=threshold_dict["action_thresholds"].get("keep_min_f1", 0.6),
                reduce_min_f1=threshold_dict["action_thresholds"].get("reduce_min_f1", 0.4),
                remove_max_f1=threshold_dict["action_thresholds"].get("remove_max_f1", 0.3),
            )

            # 2. 获取指标历史值 (通过 Repository)
            indicator_values = self.audit_repo.get_macro_indicator_values(
                indicator_code=request.indicator_code,
                start_date=request.start_date,
                end_date=request.end_date,
            )

            if not indicator_values:
                return EvaluateIndicatorPerformanceResponse(
                    success=False,
                    error=f"指标 {request.indicator_code} 在 {request.start_date} 到 {request.end_date} 期间无数据",
                )

            # 3. 获取 Regime 判定历史 (通过 Repository)
            regime_log_dicts = self.audit_repo.get_regime_log_values(
                start_date=request.start_date, end_date=request.end_date
            )

            # 转换为 RegimeSnapshot (从字典列表)
            regime_snapshots = [
                RegimeSnapshot(
                    observed_at=log_dict["observed_at"],
                    dominant_regime=log_dict["dominant_regime"],
                    confidence=log_dict["confidence"],
                    growth_momentum_z=log_dict["growth_momentum_z"],
                    inflation_momentum_z=log_dict["inflation_momentum_z"],
                    distribution=log_dict["distribution"],
                )
                for log_dict in regime_log_dicts
            ]

            # 4. 调用 Domain 层分析器
            analyzer = IndicatorPerformanceAnalyzer(threshold_config)
            report = analyzer.analyze_performance(
                indicator_code=request.indicator_code,
                indicator_values=indicator_values,
                regime_history=regime_snapshots,
                evaluation_start=request.start_date,
                evaluation_end=request.end_date,
            )

            # 5. 保存报告（除非影子模式）
            report_id = None
            if not request.use_shadow_mode:
                try:
                    report_id = self.audit_repo.save_indicator_performance_record(
                        indicator_code=report.indicator_code,
                        evaluation_period_start=report.evaluation_period_start,
                        evaluation_period_end=report.evaluation_period_end,
                        f1_score=report.f1_score,
                        precision_score=report.precision,
                        recall_score=report.recall,
                        stability_score=report.stability_score,
                        recommended_action=report.recommended_action,
                        recommended_weight=report.recommended_weight,
                        confidence_level=report.confidence_level,
                        validation_run_id=request.validation_run_id,
                        analysis_details={
                            "true_positive_count": report.true_positive_count,
                            "false_positive_count": report.false_positive_count,
                            "true_negative_count": report.true_negative_count,
                            "false_negative_count": report.false_negative_count,
                            "accuracy": report.accuracy,
                            "lead_time_mean": report.lead_time_mean,
                            "lead_time_std": report.lead_time_std,
                            "pre_2015_correlation": report.pre_2015_correlation,
                            "post_2015_correlation": report.post_2015_correlation,
                            "decay_rate": report.decay_rate,
                            "signal_strength": report.signal_strength,
                        },
                    )
                except RECOVERABLE_AUDIT_USE_CASE_EXCEPTIONS as save_error:
                    message = str(save_error)
                    if (
                        "Database access not allowed" in message
                        or "You cannot call this from an async context" in message
                    ):
                        logger.warning("评估结果未落库（测试环境数据库写入受限）")
                    else:
                        raise

            logger.info(
                f"指标 {request.indicator_code} 评估完成: "
                f"F1={report.f1_score:.3f}, 稳定性={report.stability_score:.3f}"
            )

            return EvaluateIndicatorPerformanceResponse(
                success=True,
                report=report,
                report_id=report_id,
            )

        except RECOVERABLE_AUDIT_USE_CASE_EXCEPTIONS as e:
            logger.error(f"评估指标 {request.indicator_code} 失败: {e}", exc_info=True)
            return EvaluateIndicatorPerformanceResponse(success=False, error=str(e))


@dataclass
class ValidateThresholdsRequest:
    """验证阈值请求"""

    start_date: date
    end_date: date
    indicator_codes: list[str] | None = None  # None 表示验证所有指标
    use_shadow_mode: bool = False


@dataclass
class ValidateThresholdsResponse:
    """验证阈值响应"""

    success: bool
    validation_report: ThresholdValidationReport | None = None
    validation_run_id: str | None = None
    error: str | None = None


class ValidateThresholdsUseCase:
    """验证阈值用例"""

    def __init__(self, audit_repository: DjangoAuditRepository):
        self.audit_repo = audit_repository

    def execute(
        self,
        request: ValidateThresholdsRequest,
    ) -> ValidateThresholdsResponse:
        """
        执行阈值验证

        步骤：
        1. 获取所有待验证指标的阈值配置
        2. 对每个指标调用 EvaluateIndicatorPerformanceUseCase
        3. 汇总结果，生成总体建议
        4. 保存验证摘要
        """
        validation_run_id: str | None = None
        try:
            validation_run_id = f"validation_{uuid.uuid4().hex[:12]}"
            run_date = date.today()

            # 1. 获取待验证的指标 (通过 Repository)
            threshold_configs = self.audit_repo.get_active_threshold_configs_by_codes(
                indicator_codes=request.indicator_codes
            )

            total_indicators = len(threshold_configs)
            if total_indicators == 0:
                return ValidateThresholdsResponse(success=False, error="没有找到待验证的指标")

            # 2. 创建验证摘要记录 (通过 Repository)
            if not request.use_shadow_mode:
                self.audit_repo.create_validation_summary_record(
                    validation_run_id=validation_run_id,
                    evaluation_period_start=request.start_date,
                    evaluation_period_end=request.end_date,
                    total_indicators=total_indicators,
                    status="in_progress",
                    is_shadow_mode=request.use_shadow_mode,
                    run_date=run_date,
                )

            # 3. 逐个评估指标
            evaluate_use_case = EvaluateIndicatorPerformanceUseCase(self.audit_repo)
            indicator_reports = []

            approved_count = 0
            rejected_count = 0
            pending_count = 0

            for threshold_config in threshold_configs:
                response = evaluate_use_case.execute(
                    EvaluateIndicatorPerformanceRequest(
                        indicator_code=threshold_config["indicator_code"],
                        start_date=request.start_date,
                        end_date=request.end_date,
                        use_shadow_mode=request.use_shadow_mode,
                        validation_run_id=validation_run_id,
                    )
                )

                if response.success and response.report:
                    indicator_reports.append(response.report)

                    # 统计
                    if (
                        response.report.recommended_action == "KEEP"
                        or response.report.recommended_action == "INCREASE"
                    ):
                        approved_count += 1
                    elif response.report.recommended_action == "REMOVE":
                        rejected_count += 1
                    else:
                        pending_count += 1
                else:
                    pending_count += 1

            # 4. 计算总体统计
            if indicator_reports:
                avg_f1 = sum(r.f1_score for r in indicator_reports) / len(indicator_reports)
                avg_stability = sum(r.stability_score for r in indicator_reports) / len(
                    indicator_reports
                )
            else:
                avg_f1 = 0.0
                avg_stability = 0.0

            # 5. 生成总体建议
            overall_recommendation = self._generate_overall_recommendation(
                approved_count,
                rejected_count,
                pending_count,
                avg_f1,
                avg_stability,
            )

            # 6. 构建验证报告
            validation_report = ThresholdValidationReport(
                validation_run_id=validation_run_id,
                run_date=run_date,
                evaluation_period_start=request.start_date,
                evaluation_period_end=request.end_date,
                total_indicators=total_indicators,
                approved_indicators=approved_count,
                rejected_indicators=rejected_count,
                pending_indicators=pending_count,
                indicator_reports=indicator_reports,
                overall_recommendation=overall_recommendation,
                status=(
                    ValidationStatus.PASSED
                    if not request.use_shadow_mode
                    else ValidationStatus.SHADOW_RUN
                ),
            )

            # 7. 更新验证摘要 (通过 Repository)
            if not request.use_shadow_mode:
                self.audit_repo.update_validation_summary_status(
                    validation_run_id=validation_run_id,
                    status="completed",
                    approved_indicators=approved_count,
                    rejected_indicators=rejected_count,
                    pending_indicators=pending_count,
                    avg_f1_score=avg_f1,
                    avg_stability_score=avg_stability,
                    overall_recommendation=overall_recommendation,
                )

            logger.info(
                f"阈值验证完成: {validation_run_id}, " f"{approved_count}/{total_indicators} 通过"
            )

            return ValidateThresholdsResponse(
                success=True,
                validation_report=validation_report,
                validation_run_id=validation_run_id,
            )

        except RECOVERABLE_AUDIT_USE_CASE_EXCEPTIONS as exc:
            logger.error(
                "Threshold validation failed",
                extra={"exception_type": type(exc).__name__},
            )

            # 更新验证摘要为失败状态 (通过 Repository)
            if not request.use_shadow_mode and validation_run_id is not None:
                try:
                    self.audit_repo.update_validation_summary_status(
                        validation_run_id=validation_run_id,
                        status="failed",
                        error_message=_THRESHOLD_VALIDATION_FAILURE,
                    )
                except RECOVERABLE_AUDIT_USE_CASE_EXCEPTIONS as persistence_exc:
                    logger.error(
                        "Threshold validation failure status persistence failed",
                        extra={"exception_type": type(persistence_exc).__name__},
                    )

            return ValidateThresholdsResponse(
                success=False,
                error=_THRESHOLD_VALIDATION_FAILURE,
            )

    def _generate_overall_recommendation(
        self,
        approved: int,
        rejected: int,
        pending: int,
        avg_f1: float,
        avg_stability: float,
    ) -> str:
        """生成总体建议"""
        total = approved + rejected + pending

        if total == 0:
            return "无指标可评估"

        approval_rate = approved / total if total > 0 else 0

        if approval_rate >= 0.8 and avg_f1 >= 0.6:
            return (
                f"整体表现优秀，{approved}/{total} 个指标通过验证。"
                f"建议保持当前配置，关注表现不佳的指标。"
            )
        elif approval_rate >= 0.5 and avg_f1 >= 0.5:
            return (
                f"整体表现良好，{approved}/{total} 个指标通过验证。" f"建议优化部分指标的阈值配置。"
            )
        elif approval_rate >= 0.3:
            return (
                f"整体表现一般，{approved}/{total} 个指标通过验证。"
                f"建议重新评估阈值配置，考虑引入新指标。"
            )
        else:
            return (
                f"整体表现较差，{approved}/{total} 个指标通过验证。"
                f"强烈建议全面重构指标体系和阈值配置。"
            )


@dataclass
class AdjustIndicatorWeightsRequest:
    """调整指标权重请求"""

    validation_run_id: str
    auto_apply: bool = False  # 是否自动应用权重调整


@dataclass
class AdjustIndicatorWeightsResponse:
    """调整指标权重响应"""

    success: bool
    adjusted_weights: list[DynamicWeightConfig] | None = None
    error: str | None = None


class AdjustIndicatorWeightsUseCase:
    """调整指标权重用例"""

    def __init__(self, audit_repository: DjangoAuditRepository):
        self.audit_repo = audit_repository

    def execute(
        self,
        request: AdjustIndicatorWeightsRequest,
    ) -> AdjustIndicatorWeightsResponse:
        """
        执行权重调整

        步骤：
        1. 从验证摘要获取评估结果
        2. 根据建议计算新权重
        3. 更新 IndicatorThresholdConfigModel（如果 auto_apply=True）
        """
        try:
            # 1. 获取验证摘要 (通过 Repository)
            summary = self.audit_repo.get_validation_summary_by_run_id(
                validation_run_id=request.validation_run_id
            )

            if not summary:
                return AdjustIndicatorWeightsResponse(
                    success=False, error=f"验证记录 {request.validation_run_id} 不存在"
                )

            # 2. 获取本次验证的所有指标表现报告 (通过 Repository)
            performance_reports = self.audit_repo.get_indicator_performance_reports(
                validation_run_id=request.validation_run_id,
                limit=None,
            )
            if not performance_reports:
                return AdjustIndicatorWeightsResponse(
                    success=False,
                    error=f"验证记录 {request.validation_run_id} 没有批次关联的指标表现",
                )

            adjusted_weights: list[DynamicWeightConfig] = []

            for report in performance_reports:
                # 获取对应的阈值配置 (通过 Repository)
                threshold_config = self.audit_repo.get_threshold_config_by_indicator(
                    indicator_code=report["indicator_code"]
                )

                if not threshold_config:
                    return AdjustIndicatorWeightsResponse(
                        success=False,
                        error=f"指标 {report['indicator_code']} 的激活阈值配置不存在",
                    )

                original_weight = threshold_config["base_weight"]
                current_weight = report["recommended_weight"]
                f1_score = report["f1_score"]
                stability_score = report["stability_score"]
                confidence = report["confidence_level"]
                decay_rate = report["decay_rate"]
                recommended_action = report["recommended_action"]
                if (
                    current_weight is None
                    or f1_score is None
                    or stability_score is None
                    or confidence is None
                    or decay_rate is None
                    or recommended_action is None
                ):
                    return AdjustIndicatorWeightsResponse(
                        success=False,
                        error=f"指标 {report['indicator_code']} 的表现数据不完整",
                    )

                # 计算调整系数
                if original_weight > 0:
                    adjustment_factor = current_weight / original_weight
                else:
                    adjustment_factor = 1.0

                # 生成调整原因
                reason = self._generate_adjustment_reason(
                    recommended_action,
                    f1_score,
                    stability_score,
                )

                # 置信度
                weight_config = DynamicWeightConfig(
                    indicator_code=report["indicator_code"],
                    current_weight=current_weight,
                    original_weight=original_weight,
                    f1_score=f1_score,
                    stability_score=stability_score,
                    decay_rate=decay_rate,
                    adjustment_factor=adjustment_factor,
                    new_weight=current_weight,
                    reason=reason,
                    confidence=confidence,
                )

                adjusted_weights.append(weight_config)

                # 自动应用权重调整 (通过 Repository)
                if request.auto_apply:
                    self.audit_repo.update_threshold_config_weight(
                        indicator_code=report["indicator_code"],
                        new_weight=current_weight,
                    )

            logger.info(
                f"权重调整完成: {len(adjusted_weights)} 个指标, " f"auto_apply={request.auto_apply}"
            )

            return AdjustIndicatorWeightsResponse(
                success=True,
                adjusted_weights=adjusted_weights,
            )

        except RECOVERABLE_AUDIT_USE_CASE_EXCEPTIONS as e:
            logger.error(f"权重调整失败: {e}", exc_info=True)
            return AdjustIndicatorWeightsResponse(success=False, error=str(e))

    def _generate_adjustment_reason(
        self,
        action: str,
        f1_score: float,
        stability_score: float,
    ) -> str:
        """生成调整原因"""
        if action == "INCREASE":
            return f"F1分数({f1_score:.2f})和稳定性({stability_score:.2f})优秀，建议增加权重"
        elif action == "KEEP":
            return f"F1分数({f1_score:.2f})和稳定性({stability_score:.2f})良好，保持当前权重"
        elif action == "DECREASE":
            return f"F1分数({f1_score:.2f})或稳定性({stability_score:.2f})一般，降低权重"
        elif action == "REMOVE":
            return f"F1分数({f1_score:.2f})过低，建议移除或大幅降低权重"
        else:
            return "未知原因"
