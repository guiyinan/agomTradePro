"""
URL Configuration for Audit API.
"""

from django.urls import path
from django.shortcuts import redirect
from .views import GenerateAttributionReportView, AuditSummaryView, AuditPageView

app_name = 'audit'


def audit_home_redirect(request):
    """Redirect root /audit/ to reports page"""
    return redirect('audit:audit-reports')


urlpatterns = [
    # Root route - redirect to reports page
    path('', audit_home_redirect, name='home'),

    # API routes
    path('reports/generate/', GenerateAttributionReportView.as_view(), name='generate-report'),
    path('api/summary/', AuditSummaryView.as_view(), name='audit-summary'),

    # HTML page routes
    path('reports/', AuditPageView.as_view(), name='audit-reports'),
    path('review/', AuditPageView.as_view(), name='review'),
]
