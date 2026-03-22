"""URL Configuration for Audit pages and legacy API aliases."""

from django.urls import include, path
from django.shortcuts import redirect
from . import views

app_name = 'audit'


def audit_home_redirect(request):
    """Redirect root /audit/ to audit page"""
    return redirect('audit:audit-page')


urlpatterns = [
    # Root route - redirect to audit page
    path('', audit_home_redirect, name='home'),
    # Legacy API compatibility under /audit/api/*
    path('api/', include(('apps.audit.interface.api_urls', 'audit_api'), namespace='legacy_audit_api')),

    # HTML page routes
    path('page/', views.AuditPageView.as_view(), name='audit-page'),
    path('reports/', views.ReportListView.as_view(), name='reports'),
    path('reports/<int:report_id>/', views.AttributionDetailView.as_view(), name='report_detail'),
    path('indicator-performance/', views.IndicatorPerformancePageView.as_view(), name='indicator_performance'),
    path('threshold-validation/', views.ThresholdValidationPageView.as_view(), name='threshold_validation'),
    path('review/', views.AuditReviewPageView.as_view(), name='review'),

    # HTML page routes - Operation Logs
    path('operation-logs/', views.OperationLogsAdminPageView.as_view(), name='operation_logs_admin'),
    path('my-logs/', views.MyOperationLogsPageView.as_view(), name='my_operation_logs'),
    path('decision-traces/', views.DecisionTracesAdminPageView.as_view(), name='decision_traces_admin'),
    path('my-decision-traces/', views.MyDecisionTracesPageView.as_view(), name='my_decision_traces'),
]
