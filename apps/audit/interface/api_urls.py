"""Audit API URL configuration."""

from django.urls import path
from rest_framework.response import Response
from rest_framework.views import APIView

from . import views

app_name = "audit_api"


class AuditApiRootView(APIView):
    """Return discoverable audit API endpoints."""

    def get(self, request):
        return Response(
            {
                "endpoints": {
                    "reports_generate": "/api/audit/reports/generate/",
                    "summary": "/api/audit/summary/",
                    "attribution_chart_data": "/api/audit/attribution-chart-data/{report_id}/",
                    "indicator_performance": "/api/audit/indicator-performance/{indicator_code}/",
                    "indicator_performance_chart": "/api/audit/indicator-performance-data/{validation_id}/",
                    "validate_all_indicators": "/api/audit/validate-all-indicators/",
                    "update_threshold": "/api/audit/update-threshold/",
                    "threshold_validation_data": "/api/audit/threshold-validation-data/{summary_id}/",
                    "run_validation": "/api/audit/run-validation/",
                    "operation_logs": "/api/audit/operation-logs/",
                    "operation_logs_export": "/api/audit/operation-logs/export/",
                    "operation_logs_stats": "/api/audit/operation-logs/stats/",
                    "operation_log_detail": "/api/audit/operation-logs/{log_id}/",
                    "operation_log_ingest": "/api/audit/internal/operation-logs/",
                    "decision_traces": "/api/audit/decision-traces/",
                    "decision_trace_detail": "/api/audit/decision-traces/{request_id}/",
                    "health": "/api/audit/health/",
                    "failure_counter": "/api/audit/failure-counter/",
                    "metrics": "/api/audit/metrics/",
                }
            }
        )


urlpatterns = [
    path("", AuditApiRootView.as_view(), name="api-root"),
    path("reports/generate/", views.GenerateAttributionReportView.as_view(), name="generate-report"),
    path("summary/", views.AuditSummaryView.as_view(), name="audit-summary"),
    path("attribution-chart-data/<int:report_id>/", views.AttributionChartDataView.as_view(), name="attribution-chart-data"),
    path("indicator-performance/<str:indicator_code>/", views.IndicatorPerformanceDetailView.as_view(), name="indicator-performance-detail"),
    path("indicator-performance-data/<int:validation_id>/", views.IndicatorPerformanceChartDataView.as_view(), name="indicator-performance-chart-data"),
    path("validate-all-indicators/", views.ValidateAllIndicatorsView.as_view(), name="validate-all-indicators"),
    path("update-threshold/", views.UpdateThresholdView.as_view(), name="update-threshold"),
    path("threshold-validation-data/<int:summary_id>/", views.ThresholdValidationDataView.as_view(), name="threshold-validation-data"),
    path("run-validation/", views.RunValidationView.as_view(), name="run-validation"),
    path("operation-logs/", views.OperationLogListView.as_view(), name="operation-log-list"),
    path("operation-logs/export/", views.OperationLogExportView.as_view(), name="operation-log-export"),
    path("operation-logs/stats/", views.OperationLogStatsView.as_view(), name="operation-log-stats"),
    path("operation-logs/<str:log_id>/", views.OperationLogDetailView.as_view(), name="operation-log-detail"),
    path("internal/operation-logs/", views.OperationLogIngestView.as_view(), name="operation-log-ingest"),
    path("decision-traces/", views.DecisionTraceListView.as_view(), name="decision-trace-list"),
    path("decision-traces/<str:request_id>/", views.DecisionTraceDetailView.as_view(), name="decision-trace-detail"),
    path("health/", views.AuditHealthCheckView.as_view(), name="audit-health-check"),
    path("failure-counter/", views.AuditFailureCounterView.as_view(), name="audit-failure-counter"),
    path("metrics/", views.AuditMetricsView.as_view(), name="audit-metrics"),
]
