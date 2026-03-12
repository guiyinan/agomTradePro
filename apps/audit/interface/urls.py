"""
URL Configuration for Audit API.
"""

from django.urls import path
from django.shortcuts import redirect
from . import views

app_name = 'audit'


def audit_home_redirect(request):
    """Redirect root /audit/ to audit page"""
    return redirect('audit:audit-page')


urlpatterns = [
    # Root route - redirect to audit page
    path('', audit_home_redirect, name='home'),

    # API routes - Attribution
    path('api/reports/generate/', views.GenerateAttributionReportView.as_view(), name='generate-report'),
    path('api/summary/', views.AuditSummaryView.as_view(), name='audit-summary'),
    path('api/attribution-chart-data/<int:report_id>/', views.AttributionChartDataView.as_view(), name='attribution-chart-data'),

    # API routes - Indicator Performance
    path('api/indicator-performance/<str:indicator_code>/', views.IndicatorPerformanceDetailView.as_view(), name='indicator-performance-detail'),
    path('api/indicator-performance-data/<int:validation_id>/', views.IndicatorPerformanceChartDataView.as_view(), name='indicator-performance-chart-data'),
    path('api/validate-all-indicators/', views.ValidateAllIndicatorsView.as_view(), name='validate-all-indicators'),
    path('api/update-threshold/', views.UpdateThresholdView.as_view(), name='update-threshold'),

    # API routes - Threshold Validation
    path('api/threshold-validation-data/<int:summary_id>/', views.ThresholdValidationDataView.as_view(), name='threshold-validation-data'),
    path('api/run-validation/', views.RunValidationView.as_view(), name='run-validation'),

    # API routes - Operation Logs (MCP/SDK 审计日志)
    # 注意：具体路径必须在参数化路径之前，否则会被吞掉
    path('api/operation-logs/', views.OperationLogListView.as_view(), name='operation-log-list'),
    path('api/operation-logs/export/', views.OperationLogExportView.as_view(), name='operation-log-export'),
    path('api/operation-logs/stats/', views.OperationLogStatsView.as_view(), name='operation-log-stats'),
    path('api/operation-logs/<str:log_id>/', views.OperationLogDetailView.as_view(), name='operation-log-detail'),
    path('api/internal/operation-logs/', views.OperationLogIngestView.as_view(), name='operation-log-ingest'),
    path('api/decision-traces/', views.DecisionTraceListView.as_view(), name='decision-trace-list'),
    path('api/decision-traces/<str:request_id>/', views.DecisionTraceDetailView.as_view(), name='decision-trace-detail'),

    # API routes - Health Check & Observability
    path('api/health/', views.AuditHealthCheckView.as_view(), name='audit-health-check'),
    path('api/failure-counter/', views.AuditFailureCounterView.as_view(), name='audit-failure-counter'),
    path('api/metrics/', views.AuditMetricsView.as_view(), name='audit-metrics'),

    # HTML page routes
    path('page/', views.AuditPageView.as_view(), name='audit-page'),
    path('reports/', views.AuditPageView.as_view(), name='reports'),
    path('reports/<int:report_id>/', views.AttributionDetailView.as_view(), name='report_detail'),
    path('indicator-performance/', views.IndicatorPerformancePageView.as_view(), name='indicator_performance'),
    path('threshold-validation/', views.ThresholdValidationPageView.as_view(), name='threshold_validation'),
    path('review/', views.AuditPageView.as_view(), name='review'),

    # HTML page routes - Operation Logs
    path('operation-logs/', views.OperationLogsAdminPageView.as_view(), name='operation_logs_admin'),
    path('my-logs/', views.MyOperationLogsPageView.as_view(), name='my_operation_logs'),
    path('decision-traces/', views.DecisionTracesAdminPageView.as_view(), name='decision_traces_admin'),
    path('my-decision-traces/', views.MyDecisionTracesPageView.as_view(), name='my_decision_traces'),
]
