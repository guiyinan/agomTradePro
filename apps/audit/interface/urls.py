"""
URL Configuration for Audit API.
"""

from django.urls import path
from .views import GenerateAttributionReportView, AuditSummaryView

app_name = 'audit'

urlpatterns = [
    path('reports/generate/', GenerateAttributionReportView.as_view(), name='generate-report'),
    path('reports/', AuditSummaryView.as_view(), name='audit-summary'),
]
