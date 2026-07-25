"""Application-side builders and query services for audit interface views."""

from __future__ import annotations

import json
import math
from datetime import date
from typing import Any, cast

from apps.account.application.manual_trade_sync import ManualTradeReviewSummaryUseCase
from apps.audit.application.attribution_use_cases import BacktestRepositoryProtocol
from apps.backtest.application.repository_provider import (
    DjangoBacktestRepository,
    get_backtest_repository,
)
from core.integration.decision_execution_links import list_decision_execution_links

from .repository_provider import (
    export_audit_metrics,
    get_audit_failure_counter,
    get_audit_metrics_summary,
    get_audit_repository,
)
from .use_cases import (
    ExportOperationLogsRequest,
    ExportOperationLogsUseCase,
    GenerateAttributionReportRequest,
    GenerateAttributionReportResponse,
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
    ValidateThresholdsResponse,
    ValidateThresholdsUseCase,
)


def _get_backtest_repository() -> DjangoBacktestRepository:
    return get_backtest_repository()


def build_manual_trade_review_context_payload(user_id: int) -> dict[str, Any]:
    """Build manual trade review context through the owning account module."""

    return ManualTradeReviewSummaryUseCase().execute(user_id=user_id)


def generate_attribution_report_payload(backtest_id: int) -> dict[str, Any]:
    """Generate an attribution report and return the serialized payload."""
    if isinstance(backtest_id, bool) or backtest_id <= 0:
        return {"success": False, "error": "backtest_id must be positive", "report": None}

    audit_repo = get_audit_repository()
    response = GenerateAttributionReportUseCase(
        audit_repository=audit_repo,
        backtest_repository=_get_backtest_repository(),
    ).execute(GenerateAttributionReportRequest(backtest_id=backtest_id))
    if not response.success:
        return {"success": False, "error": response.error, "report": None}
    if response.report_id is None:
        return {
            "success": False,
            "error": "归因报告未返回有效 ID",
            "report": None,
        }

    report = audit_repo.get_attribution_report(response.report_id)
    if report is None:
        return {
            "success": False,
            "error": "归因报告已生成但无法读取",
            "report": None,
        }
    report["loss_analyses"] = audit_repo.get_loss_analyses(response.report_id)
    report["experience_summaries"] = audit_repo.get_experience_summaries(response.report_id)
    return {"success": True, "error": None, "report": report}


def preview_attribution_report_generation(*, backtest_id: int) -> dict[str, Any]:
    """Describe one attribution report generation without external I/O or writes."""

    if isinstance(backtest_id, bool) or backtest_id <= 0:
        raise ValueError("backtest_id must be positive")
    backtest = _get_backtest_repository().get_backtest_by_id(backtest_id)
    if backtest is None:
        raise LookupError(f"backtest {backtest_id} does not exist")
    if backtest.status != "completed":
        raise ValueError(f"backtest {backtest_id} is not completed")

    existing_reports = get_audit_repository().get_reports_by_backtest(backtest_id)
    return {
        "backtest": {
            "id": backtest.id,
            "name": backtest.name,
            "status": backtest.status,
            "start_date": backtest.start_date.isoformat(),
            "end_date": backtest.end_date.isoformat(),
        },
        "existing_report_count": len(existing_reports),
        "external_reads": ["historical_asset_prices"],
        "writes": [
            "audit_attribution_report",
            "audit_loss_analysis_if_applicable",
            "audit_experience_summary",
        ],
        "duplicate_reports_allowed": True,
        "partial_write_possible": True,
    }


def generate_attribution_report_for_backtest(
    backtest_id: int,
    backtest_repository: BacktestRepositoryProtocol,
) -> GenerateAttributionReportResponse:
    """Generate an attribution report using the provided backtest repository."""

    if isinstance(backtest_id, bool) or backtest_id <= 0:
        return GenerateAttributionReportResponse(
            success=False,
            error="backtest_id must be positive",
        )
    return GenerateAttributionReportUseCase(
        audit_repository=get_audit_repository(),
        backtest_repository=backtest_repository,
    ).execute(GenerateAttributionReportRequest(backtest_id=backtest_id))


def get_attribution_chart_data_payload(report_id: int) -> dict[str, Any] | None:
    """Return chart-ready data for a single attribution report."""
    if isinstance(report_id, bool) or report_id <= 0:
        return None
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
        "loss_analyses": audit_repo.get_loss_analyses(report_id),
        "experience_summaries": audit_repo.get_experience_summaries(report_id),
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
        "avg_stability_score": (
            float(summary.avg_stability_score) if summary.avg_stability_score is not None else None
        ),
        "indicators": [
            {
                "indicator_code": performance.indicator_code,
                "f1_score": (
                    float(performance.f1_score) if performance.f1_score is not None else None
                ),
                "stability_score": (
                    float(performance.stability_score)
                    if performance.stability_score is not None
                    else None
                ),
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
            "avg_f1_score": (
                float(summary.avg_f1_score) if summary.avg_f1_score is not None else None
            ),
            "avg_stability_score": (
                float(summary.avg_stability_score)
                if summary.avg_stability_score is not None
                else None
            ),
            "overall_recommendation": summary.overall_recommendation,
            "status": summary.status,
        },
        "indicator_reports": [
            {
                "indicator_code": performance.indicator_code,
                "f1_score": (
                    float(performance.f1_score) if performance.f1_score is not None else None
                ),
                "precision": (
                    float(performance.precision) if performance.precision is not None else None
                ),
                "recall": float(performance.recall) if performance.recall is not None else None,
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
) -> ValidateThresholdsResponse:
    """Execute threshold validation through the application use case."""
    if start_date > end_date:
        raise ValueError("start_date must not be after end_date")
    return ValidateThresholdsUseCase(audit_repository=get_audit_repository()).execute(
        ValidateThresholdsRequest(
            start_date=start_date,
            end_date=end_date,
            use_shadow_mode=use_shadow_mode,
        )
    )


def preview_threshold_validation(*, start_date: date, end_date: date) -> dict[str, Any]:
    """Return validation targets and write impact without running validation."""

    if start_date > end_date:
        raise ValueError("start_date must not be after end_date")
    configs = get_audit_repository().get_active_threshold_configs_by_codes(indicator_codes=None)
    indicator_codes = [
        str(config.get("indicator_code") or "").strip()
        for config in configs
        if str(config.get("indicator_code") or "").strip()
    ]
    return {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "active_indicator_count": len(indicator_codes),
        "indicator_codes": indicator_codes,
        "writes": ["validation_summary", "indicator_performance_reports"],
    }


def update_indicator_threshold_levels(
    *,
    indicator_code: str,
    level_low: float,
    level_high: float,
) -> bool:
    """Persist threshold level changes for a single indicator."""
    _validate_threshold_levels(
        indicator_code=indicator_code,
        level_low=level_low,
        level_high=level_high,
    )
    return get_audit_repository().update_threshold_config_levels(
        indicator_code,
        level_low=level_low,
        level_high=level_high,
    )


def preview_indicator_threshold_levels(
    *,
    indicator_code: str,
    level_low: float,
    level_high: float,
) -> dict[str, Any]:
    """Return current and target levels without changing persisted configuration."""

    _validate_threshold_levels(
        indicator_code=indicator_code,
        level_low=level_low,
        level_high=level_high,
    )
    config = get_audit_repository().get_threshold_config_by_indicator(indicator_code)
    if config is None:
        raise LookupError(f"indicator {indicator_code} threshold config does not exist")

    current = {
        "level_low": config.get("level_low"),
        "level_high": config.get("level_high"),
    }
    target = {"level_low": level_low, "level_high": level_high}
    changed_fields = [name for name in target if current[name] != target[name]]
    if not changed_fields:
        raise ValueError("threshold levels are unchanged")
    return {
        "indicator_code": indicator_code,
        "indicator_name": config.get("indicator_name", ""),
        "current": current,
        "target": target,
        "changed_fields": changed_fields,
        "writes": ["audit_indicator_threshold_config"],
    }


def _validate_threshold_levels(
    *,
    indicator_code: str,
    level_low: float,
    level_high: float,
) -> None:
    """Validate threshold values for HTTP and non-HTTP application callers."""

    if not indicator_code.strip():
        raise ValueError("indicator_code must be non-empty")
    if (
        isinstance(level_low, bool)
        or isinstance(level_high, bool)
        or not math.isfinite(level_low)
        or not math.isfinite(level_high)
    ):
        raise ValueError("threshold levels must be finite numbers")
    if level_low >= level_high:
        raise ValueError("level_low must be less than level_high")


def build_audit_overview_context() -> dict[str, Any]:
    """Build the audit overview page context."""
    audit_repo = get_audit_repository()
    backtest_repo = _get_backtest_repository()
    recent_reports = audit_repo.list_attribution_report_records(limit=5)
    for report in recent_reports:
        report_with_context = cast(Any, report)
        report_with_context.loss_analyses_count = len(
            audit_repo.get_loss_analysis_records(report.id)
        )

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


def build_manual_trade_review_context(user_id: int) -> dict[str, Any]:
    """Build the manual trade review page context."""

    return build_manual_trade_review_context_payload(user_id)


def build_report_list_context(method_filter: str) -> dict[str, Any]:
    """Build the attribution report list page context."""
    normalized_filter = method_filter.strip().lower()
    if normalized_filter not in {"", "heuristic", "brinson"}:
        normalized_filter = ""
    audit_repo = get_audit_repository()
    backtest_repo = _get_backtest_repository()
    existing_backtest_ids = audit_repo.get_reported_backtest_ids()
    return {
        "reports": audit_repo.list_attribution_report_records(
            attribution_method=normalized_filter or None,
            limit=50,
        ),
        "method_filter": normalized_filter,
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
                "f1_score": (
                    float(performance.f1_score) if performance.f1_score is not None else None
                ),
                "stability_score": (
                    float(performance.stability_score)
                    if performance.stability_score is not None
                    else None
                ),
                "lead_time_mean": (
                    float(performance.lead_time_mean)
                    if performance.lead_time_mean is not None
                    else None
                ),
                "recommended_action": performance.recommended_action,
                "recommended_weight": (
                    float(performance.recommended_weight)
                    if performance.recommended_weight is not None
                    else None
                ),
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
        "avg_f1_score": (
            float(latest_summary.avg_f1_score) if latest_summary.avg_f1_score is not None else 0
        ),
        "avg_stability_score": (
            float(latest_summary.avg_stability_score)
            if latest_summary.avg_stability_score is not None
            else 0
        ),
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
                "stability_score": (
                    float(record.stability_score) if record.stability_score is not None else None
                ),
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
        validation_message = f"验证于 {latest_validation.run_date.strftime('%Y-%m-%d %H:%M')} 运行"

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


def query_operation_logs_payload(**kwargs: Any) -> dict[str, Any]:
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
    is_admin: bool,
) -> dict[str, Any]:
    """Export operation logs for the interface layer."""
    response = ExportOperationLogsUseCase(audit_repository=get_audit_repository()).execute(
        ExportOperationLogsRequest(
            start_date=start_date,
            end_date=end_date,
            mcp_client_id=mcp_client_id,
            format=format,
            is_admin=is_admin,
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
    is_admin: bool,
) -> dict[str, Any]:
    """Return operation log stats payload."""
    response = GetOperationStatsUseCase(audit_repository=get_audit_repository()).execute(
        GetOperationStatsRequest(
            start_date=start_date,
            end_date=end_date,
            group_by=group_by,
            is_admin=is_admin,
        )
    )
    return {"success": response.success, "stats": response.stats, "error": response.error}


def log_operation_payload(**kwargs: Any) -> dict[str, Any]:
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
    if not is_admin and current_user_id is None:
        return [], 0
    if page <= 0 or page_size <= 0 or page_size > 100:
        raise ValueError("page and page_size are outside the allowed range")
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
    if not is_admin and current_user_id is None:
        return None
    if not request_id.strip():
        return None
    return get_audit_repository().get_decision_trace(
        request_id=request_id,
        mcp_client_id=mcp_client_id,
        current_user_id=current_user_id,
        is_admin=is_admin,
    )


def list_execution_links_payload(
    *,
    current_user_id: int | None,
    is_admin: bool,
    account_id: str | None,
    recommendation_id: str | None,
    transaction_source: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    """List recommendation execution links for audit review surfaces."""

    return list_decision_execution_links(
        current_user_id=current_user_id,
        is_admin=is_admin,
        account_id=account_id,
        recommendation_id=recommendation_id,
        transaction_source=transaction_source,
        limit=limit,
    )


def get_audit_failure_stats() -> dict[str, Any]:
    """Return public-safe aggregate failure counts without raw reasons."""

    stats = get_audit_failure_counter().get_failure_stats()
    return {
        "total_count": stats.total_count,
        "by_component": dict(stats.by_component),
    }


def reset_audit_failure_counter() -> None:
    """Reset the audit failure counter."""
    get_audit_failure_counter().reset()


def get_audit_metrics_summary_payload() -> dict[str, Any]:
    """Return the JSON-friendly audit metrics summary."""
    return get_audit_metrics_summary()


def export_audit_metrics_payload() -> str:
    """Return Prometheus text output for audit metrics."""
    return export_audit_metrics()
