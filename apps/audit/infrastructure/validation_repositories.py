"""Validation summary persistence for Audit.

Owns ORM persistence for threshold validation summary records.
"""

from datetime import date

from .models import ValidationSummaryModel

__all__ = ["ValidationRepositoryMixin"]


class ValidationRepositoryMixin:
    """Threshold validation summary persistence."""

    def get_validation_summary(self, validation_run_id: str) -> dict | None:
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

    def get_recent_validations(self, limit: int = 10) -> list[dict]:
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
        avg_f1_score: float | None = None,
        avg_stability_score: float | None = None,
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

    def get_validation_summary_by_id(self, summary_id: int) -> dict | None:
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

    def get_validation_summary_record_by_id(
        self, summary_id: int
    ) -> ValidationSummaryModel | None:
        """根据 ID 获取验证摘要 ORM 记录。"""
        try:
            return ValidationSummaryModel._default_manager.get(id=summary_id)
        except ValidationSummaryModel.DoesNotExist:
            return None

    def get_latest_validation_summary_model(
        self,
        *,
        is_shadow_mode: bool | None = None,
    ) -> ValidationSummaryModel | None:
        """获取最新的验证摘要 ORM 记录。"""
        queryset = ValidationSummaryModel._default_manager.all()
        if is_shadow_mode is not None:
            queryset = queryset.filter(is_shadow_mode=is_shadow_mode)
        return queryset.order_by("-run_date").first()

    def get_latest_validation_summary_record(self) -> dict | None:
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

    def create_validation_summary_record(
        self,
        validation_run_id: str,
        evaluation_period_start: date,
        evaluation_period_end: date,
        total_indicators: int = 0,
        status: str = 'in_progress',
        is_shadow_mode: bool = True,
        run_date: date | None = None,
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
        avg_f1_score: float | None = None,
        avg_stability_score: float | None = None,
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

    def get_validation_summary_by_run_id(self, validation_run_id: str) -> dict | None:
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
