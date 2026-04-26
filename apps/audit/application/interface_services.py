"""Application-side builders and query services for audit interface views."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from apps.backtest.infrastructure.providers import DjangoBacktestRepository

from .repository_provider import get_audit_repository
from .use_cases import (
    ExportOperationLogsRequest,
    ExportOperationLogsUseCase,
    GenerateAttributionReportRequest,
    GenerateAttributionReportUseCase,
    GetAuditSummaryRequest,
    GetAuditSummaryUseCase,
    GetOperationLogDetailRequest,
    GetOperationLogDetailUseCase,
    GetOperationStatsRequest,
    GetOperationStatsUseCase,
    LogOperationRequest,
    LogOperationUseCase,
    QueryOperationLogsRequest,
    QueryOperationLogsUseCase,
    ValidateThresholdsRequest,
    ValidateThresholdsUseCase,
)


def _get_backtest_repository() -> DjangoBacktestRepository:
    return DjangoBacktestRepository()


def generate_attribution_report_payload(backtest_id: int) -> dict[str, Any]:
    """Generate an attribution report and return the serialized payload."""
    audit_repo = get_audit_repository()
    response = GenerateAttributionReportUseCase(
        audit_repository=audit_repo,
        backtest_repository=_get_backtest_repository(),
    ).execute(GenerateAttributionReportRequest(backtest_id=backtest_id))
    if not response.success:
        return {"success": False, "error": response.error, "report": None}

    report = audit_repo.get_attribution_report(response.report_id)
    if report:
        report["loss_analyses"] = audit_repo.get_loss_analyses(response.report_id)
        report["experience_summaries"] = audit_repo.get_experience_summaries(response.report_id)
    return {"success": True, "error": None, "report": report}


def get_attribution_chart_data_payload(report_id: int) -> dict[str, Any] | None:
    """Return chart-ready data for a single attribution report."""
    audit_repo = get_audit_repository()
    report = audit_repo.get_attribution_report(report_id)
    if report is None:
        return None
    return {
        "report_id": report_id,
        "total_pnl": report.get("total_pnl", 0),
        "regime_timing_pnl": report.get("regime_timing_pnl", 0),
        "asset_selection_pnl": report.get("asset_selection_pnl", 0),
        "interaction_pnl": report.get("interaction_pnl", 0),
        "regime_accuracy": report.get("regime_accuracy", 0),
        "period_attributions": report.get("period_attributions", []),
        "loss_analyses": report.get("loss_analyses", []),
        "experience_summaries": report.get("experience_summaries", []),
    }


def get_audit_summary_payload(
    *,
    backtest_id: int | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, Any]:
    """Query attribution report summaries for the API layer."""
    request = GetAuditSummaryRequest(
        backtest_id=backtest_id,
        start_date=start_date,
        end_date=end_date,
    )
    response = GetAuditSummaryUseCase(audit_repository=get_audit_repository()).execute(request)
    return {
        "success": response.success,
        "reports": response.reports,
        "error": response.error,
    }


def get_indicator_performance_detail_payload(indicator_code: str) -> dict[str, Any] | None:
    """Return the latest performance detail payload for one indicator."""
    return get_audit_repository().get_latest_indicator_performance_detail(indicator_code)


def get_indicator_performance_chart_payload(validation_id: int) -> dict[str, Any] | None:
    """Return chart-ready payload for one validation summary."""
    audit_repo = get_audit_repository()
    summary = audit_repo.get_validation_summary_record_by_id(validation_id)
    if summary is None:
        return None

    performances = audit_repo.get_indicator_performance_records_by_period(
        summary.evaluation_period_start,
        summary.evaluation_period_end,
    )
    return {
        "validation_run_id": summary.validation_run_id,
        "evaluation_period": {
            "start": summary.evaluation_period_start,
            "end": summary.evaluation_period_end,
        },
        "total_indicators": summary.total_indicators,
        "approved_indicators": summary.approved_indicators,
        "rejected_indicators": summary.rejected_indicators,
        "pending_indicators": summary.pending_indicators,
        "avg_f1_score": float(summary.avg_f1_score) if summary.avg_f1_score is not None else None,
        "avg_stability_score": float(summary.avg_stability_score)
        if summary.avg_stability_score is not None
        else None,
        "indicators": [
            {
                "indicator_code": performance.indicator_code,
                "f1_score": float(performance.f1_score)
                if performance.f1_score is not None
                else None,
                "stability_score": float(performance.stability_score)
                if performance.stability_score is not None
                else None,
                "recommended_action": performance.recommended_action,
            }
            for performance in performances
        ],
    }


def get_threshold_validation_data_payload(summary_id: int) -> dict[str, Any] | None:
    """Return detailed validation data for one summary record."""
    audit_repo = get_audit_repository()
    summary = audit_repo.get_validation_summary_record_by_id(summary_id)
    if summary is None:
        return None

    performances = audit_repo.get_indicator_performance_records_by_period(
        summary.evaluation_period_start,
        summary.evaluation_period_end,
    )
    return {
        "summary": {
            "validation_run_id": summary.validation_run_id,
            "run_date": summary.run_date,
            "evaluation_period_start": summary.evaluation_period_start,
            "evaluation_period_end": summary.evaluation_period_end,
            "total_indicators": summary.total_indicators,
            "approved_indicators": summary.approved_indicators,
            "rejected_indicators": summary.rejected_indicators,
            "pending_indicators": summary.pending_indicators,
            "avg_f1_score": float(summary.avg_f1_score) if summary.avg_f1_score is not None else None,
            "avg_stability_score": float(summary.avg_stability_score)
            if summary.avg_stability_score is not None
            else None,
            "overall_recommendation": summary.overall_recommendation,
            "status": summary.status,
        },
        "indicator_reports": [
            {
                "indicator_code": performance.indicator_code,
                "f1_score": float(performance.f1_score) if performance.f1_score is not None else None,
                "precision": float(performance.precision)
                if performance.precision is not None
                else None,
                "recall": float(performance.recall) if performance.recall is not None else None,
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
            }
            for performance in performances
        ],
        "threshold_configs": [
            {
                "indicator_code": config["indicator_code"],
                "indicator_name": config["indicator_name"],
                "level_low": config["level_low"],
                "level_high": config["level_high"],
                "base_weight": config["base_weight"],
            }
            for config in audit_repo.get_active_threshold_configs()
        ],
    }


def run_threshold_validation(
    *,
    start_date: date,
    end_date: date,
    use_shadow_mode: bool,
):
    """Execute threshold validation through the application use case."""
    return ValidateThresholdsUseCase(audit_repository=get_audit_repository()).execute(
        ValidateThresholdsRequest(
            start_date=start_date,
            end_date=end_date,
            use_shadow_mode=use_shadow_mode,
        )
    )


def update_indicator_threshold_levels(
    *,
    indicator_code: str,
    level_low: float,
    level_high: float,
) -> bool:
    """Persist threshold level changes for a single indicator."""
    return get_audit_repository().update_threshold_config_levels(
        indicator_code,
        level_low=level_low,
        level_high=level_high,
    )


def build_audit_overview_context() -> dict[str, Any]:
    """Build the audit overview page context."""
    audit_repo = get_audit_repository()
    backtest_repo = _get_backtest_repository()
    recent_reports = audit_repo.list_attribution_report_records(limit=5)
    for report in recent_reports:
        report.loss_analyses_count = len(audit_repo.get_loss_analysis_records(report.id))

    report_backtest_ids = audit_repo.get_reported_backtest_ids()
    completed_backtests = backtest_repo.get_backtests_by_status("completed")[:50]
    pending_backtests = [
        backtest for backtest in completed_backtests if backtest.id not in report_backtest_ids
    ][:5]

    return {
        "latest_validation": audit_repo.get_latest_validation_summary_model(is_shadow_mode=False),
        "recent_reports": recent_reports,
        "pending_backtests": pending_backtests,
        "report_total_count": audit_repo.count_attribution_reports(),
        "completed_backtest_count": len(completed_backtests),
    }


def build_report_list_context(method_filter: str) -> dict[str, Any]:
    """Build the attribution report list page context."""
    audit_repo = get_audit_repository()
    backtest_repo = _get_backtest_repository()
    existing_backtest_ids = audit_repo.get_reported_backtest_ids()
    return {
        "reports": audit_repo.list_attribution_report_records(
            attribution_method=method_filter or None,
            limit=50,
        ),
        "method_filter": method_filter,
        "total_count": audit_repo.count_attribution_reports(),
        "backtests": backtest_repo.get_backtests_by_status("completed")[:50],
        "existing_backtest_ids": existing_backtest_ids,
    }


def build_attribution_detail_context(report_id: int) -> dict[str, Any]:
    """Build the attribution detail page context."""
    audit_repo = get_audit_repository()
    report = audit_repo.get_attribution_report_record(report_id)
    if report is None:
        return {"report": None}
    return {
        "report": report,
        "loss_analyses": audit_repo.get_loss_analysis_records(report_id),
        "experience_summaries": audit_repo.get_experience_summary_records(report_id),
    }


def build_indicator_performance_page_context() -> dict[str, Any]:
    """Build the indicator performance page context."""
    audit_repo = get_audit_repository()
    latest_summary = audit_repo.get_latest_validation_summary_model(is_shadow_mode=False)
    if latest_summary is None:
        return {
            "total_indicators": 0,
            "approved_indicators": 0,
            "pending_indicators": 0,
            "rejected_indicators": 0,
            "avg_f1_score": 0,
            "avg_stability_score": 0,
            "indicator_reports": [],
            "indicator_data": "[]",
        }

    threshold_configs = {
        config["indicator_code"]: config for config in audit_repo.get_active_threshold_configs()
    }
    performances = audit_repo.get_indicator_performance_records_by_period(
        latest_summary.evaluation_period_start,
        latest_summary.evaluation_period_end,
    )

    indicator_reports = []
    for performance in performances:
        config = threshold_configs.get(performance.indicator_code, {})
        indicator_reports.append(
            {
                "indicator_code": performance.indicator_code,
                "indicator_name": config.get("indicator_name", performance.indicator_code),
                "category": config.get("category", ""),
                "f1_score": float(performance.f1_score) if performance.f1_score is not None else None,
                "stability_score": float(performance.stability_score)
                if performance.stability_score is not None
                else None,
                "lead_time_mean": float(performance.lead_time_mean)
                if performance.lead_time_mean is not None
                else None,
                "recommended_action": performance.recommended_action,
                "recommended_weight": float(performance.recommended_weight)
                if performance.recommended_weight is not None
                else None,
                "true_positive_count": performance.true_positive_count,
                "false_positive_count": performance.false_positive_count,
                "true_negative_count": performance.true_negative_count,
                "false_negative_count": performance.false_negative_count,
            }
        )

    return {
        "total_indicators": latest_summary.total_indicators,
        "approved_indicators": latest_summary.approved_indicators,
        "pending_indicators": latest_summary.pending_indicators,
        "rejected_indicators": latest_summary.rejected_indicators,
        "avg_f1_score": float(latest_summary.avg_f1_score)
        if latest_summary.avg_f1_score is not None
        else 0,
        "avg_stability_score": float(latest_summary.avg_stability_score)
        if latest_summary.avg_stability_score is not None
        else 0,
        "indicator_reports": indicator_reports,
        "indicator_data": json.dumps(indicator_reports, ensure_ascii=False),
    }


def build_threshold_validation_page_context() -> dict[str, Any]:
    """Build the threshold validation page context."""
    audit_repo = get_audit_repository()
    threshold_configs = audit_repo.get_active_threshold_configs()
    configs_with_history = []
    for config in threshold_configs:
        history_records = audit_repo.get_recent_indicator_performance_records(
            config["indicator_code"],
            limit=3,
        )
        config_with_history = dict(config)
        config_with_history["validation_history"] = [
            {
                "validation_date": record.evaluation_period_end,
                "f1_score": float(record.f1_score) if record.f1_score is not None else None,
                "stability_score": float(record.stability_score)
                if record.stability_score is not None
                else None,
            }
            for record in history_records
        ]
        configs_with_history.append(config_with_history)

    latest_validation = audit_repo.get_latest_validation_summary_model(is_shadow_mode=False)
    if latest_validation is None:
        validation_status = "pending"
        validation_status_label = "待运行"
        validation_message = "尚未运行验证"
    else:
        validation_status = latest_validation.status
        validation_status_label = latest_validation.get_status_display()
        validation_message = (
            f"验证于 {latest_validation.run_date.strftime('%Y-%m-%d %H:%M')} 运行"
        )

    return {
        "threshold_configs": configs_with_history,
        "threshold_data": json.dumps(
            {
                config["indicator_code"]: {
                    "level_low": float(config["level_low"] or 0),
                    "level_high": float(config["level_high"] or 0),
                }
                for config in configs_with_history
            },
            ensure_ascii=False,
        ),
        "validation_status": validation_status,
        "validation_status_label": validation_status_label,
        "validation_message": validation_message,
    }


def query_operation_logs_payload(**kwargs) -> dict[str, Any]:
    """Query operation logs for the interface layer."""
    response = QueryOperationLogsUseCase(audit_repository=get_audit_repository()).execute(
        QueryOperationLogsRequest(**kwargs)
    )
    return {
        "success": response.success,
        "logs": response.logs,
        "total_count": response.total_count,
        "page": response.page,
        "page_size": response.page_size,
        "error": response.error,
    }


def get_operation_log_detail_payload(
    *,
    log_id: str,
    current_user_id: int | None,
    is_admin: bool,
) -> dict[str, Any]:
    """Fetch one operation log for the interface layer."""
    response = GetOperationLogDetailUseCase(audit_repository=get_audit_repository()).execute(
        GetOperationLogDetailRequest(
            log_id=log_id,
            current_user_id=current_user_id,
            is_admin=is_admin,
        )
    )
    return {"success": response.success, "log": response.log, "error": response.error}


def export_operation_logs_payload(
    *,
    start_date: date | None,
    end_date: date | None,
    mcp_client_id: str | None,
    format: str,
) -> dict[str, Any]:
    """Export operation logs for the interface layer."""
    response = ExportOperationLogsUseCase(audit_repository=get_audit_repository()).execute(
        ExportOperationLogsRequest(
            start_date=start_date,
            end_date=end_date,
            mcp_client_id=mcp_client_id,
            format=format,
        )
    )
    return {
        "success": response.success,
        "data": response.data,
        "filename": response.filename,
        "row_count": response.row_count,
        "error": response.error,
    }


def get_operation_stats_payload(
    *,
    start_date: date | None,
    end_date: date | None,
    group_by: str,
) -> dict[str, Any]:
    """Return operation log stats payload."""
    response = GetOperationStatsUseCase(audit_repository=get_audit_repository()).execute(
        GetOperationStatsRequest(
            start_date=start_date,
            end_date=end_date,
            group_by=group_by,
        )
    )
    return {"success": response.success, "stats": response.stats, "error": response.error}


def log_operation_payload(**kwargs) -> dict[str, Any]:
    """Persist an operation log via the application use case."""
    response = LogOperationUseCase(audit_repository=get_audit_repository()).execute(
        LogOperationRequest(**kwargs)
    )
    return {"success": response.success, "log_id": response.log_id, "error": response.error}


def list_decision_traces_payload(
    *,
    current_user_id: int | None,
    is_admin: bool,
    mcp_client_id: str | None,
    page: int,
    page_size: int,
) -> tuple[list[dict[str, Any]], int]:
    """List decision traces through the audit repository."""
    return get_audit_repository().list_decision_traces(
        current_user_id=current_user_id,
        is_admin=is_admin,
        mcp_client_id=mcp_client_id,
        page=page,
        page_size=page_size,
    )


def get_decision_trace_payload(
    *,
    request_id: str,
    mcp_client_id: str | None,
    current_user_id: int | None,
    is_admin: bool,
) -> dict[str, Any] | None:
    """Fetch one decision trace through the audit repository."""
    return get_audit_repository().get_decision_trace(
        request_id=request_id,
        mcp_client_id=mcp_client_id,
        current_user_id=current_user_id,
        is_admin=is_admin,
    )


def get_audit_failure_stats() -> dict[str, Any]:
    """Return the current audit failure counter snapshot."""
    from apps.audit.infrastructure.failure_counter import get_audit_failure_counter

    return get_audit_failure_counter().get_failure_stats().to_dict()


def reset_audit_failure_counter() -> None:
    """Reset the audit failure counter."""
    from apps.audit.infrastructure.failure_counter import get_audit_failure_counter

    get_audit_failure_counter().reset()


def get_audit_metrics_summary_payload() -> dict[str, Any]:
    """Return the JSON-friendly audit metrics summary."""
    from apps.audit.infrastructure.metrics import get_audit_metrics_summary

    return get_audit_metrics_summary()


def export_audit_metrics_payload() -> str:
    """Return Prometheus text output for audit metrics."""
    from apps.audit.infrastructure.metrics import export_metrics

    return export_metrics()
