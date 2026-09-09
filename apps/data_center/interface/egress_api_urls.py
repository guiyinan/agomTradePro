"""Data Center egress management routes."""

from django.urls import path

from . import egress_api_views as views

urlpatterns = [
    path("endpoints/", views.egress_endpoint_list, name="egress-endpoint-list"),
    path(
        "endpoints/<int:endpoint_id>/", views.egress_endpoint_detail, name="egress-endpoint-detail"
    ),
    path(
        "endpoints/<int:endpoint_id>/test/", views.egress_endpoint_test, name="egress-endpoint-test"
    ),
    path("rules/", views.egress_rule_list, name="egress-rule-list"),
    path("rules/preview/", views.egress_rule_preview, name="egress-rule-preview"),
    path("rules/<int:rule_id>/", views.egress_rule_detail, name="egress-rule-detail"),
    path("diagnostics/", views.egress_diagnostics, name="egress-diagnostics"),
]
