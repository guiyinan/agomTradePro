"""API routes for risk center."""

from django.urls import path

from apps.risk_center.interface.api_views import (
    AccountRiskPolicyByAccountView,
    AccountRiskPolicyDetailView,
    AccountRiskPolicyListCreateView,
    ApplyTemplateToPolicyView,
    EffectiveRiskPolicyView,
    PreTradeRiskCheckView,
    RiskCenterApiHomeView,
    RiskExceptionListCreateView,
    RiskFloorView,
    RiskTemplateDetailView,
    RiskTemplateListCreateView,
)

app_name = "api_risk_center"

urlpatterns = [
    path("", RiskCenterApiHomeView.as_view(), name="home"),
    path("floor/", RiskFloorView.as_view(), name="floor"),
    path("templates/", RiskTemplateListCreateView.as_view(), name="templates"),
    path("templates/<int:template_id>/", RiskTemplateDetailView.as_view(), name="template-detail"),
    path("account-policies/", AccountRiskPolicyListCreateView.as_view(), name="account-policies"),
    path(
        "account-policies/by-account/<int:account_id>/",
        AccountRiskPolicyByAccountView.as_view(),
        name="account-policy-by-account",
    ),
    path(
        "account-policies/<int:policy_id>/",
        AccountRiskPolicyDetailView.as_view(),
        name="account-policy-detail",
    ),
    path(
        "account-policies/<int:policy_id>/apply-template/",
        ApplyTemplateToPolicyView.as_view(),
        name="account-policy-apply-template",
    ),
    path("exceptions/", RiskExceptionListCreateView.as_view(), name="exceptions"),
    path("effective-policy/", EffectiveRiskPolicyView.as_view(), name="effective-policy"),
    path("pre-trade-check/", PreTradeRiskCheckView.as_view(), name="pre-trade-check"),
]
