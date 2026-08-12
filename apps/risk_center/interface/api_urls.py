"""API routes for risk center."""

from django.urls import path

from apps.risk_center.interface.api_views import (
    AccountRiskPolicyByAccountView,
    AccountRiskPolicyDetailView,
    AccountRiskPolicyListCreateView,
    ApplyTemplateToPolicyView,
    EffectiveRiskPolicyView,
    PostInvestmentRiskCheckView,
    PreTradeRiskCheckView,
    RiskCenterApiHomeView,
    RiskCenterDailyReportView,
    RiskExceptionListCreateView,
    RiskFloorView,
    RiskTemplateDetailView,
    RiskTemplateListCreateView,
)
from apps.risk_center.interface.evidence_operator_spec_approval_api_views import (
    ApproveEvidenceOperatorSpecView,
    RegisterEvidenceOperatorSpecApprovalSubjectView,
)
from apps.risk_center.interface.scenario_api_views import (
    ActivateScenarioSetView,
    ActiveScenarioSetView,
    PreviewScenarioGovernanceView,
    ProposeScenarioRevisionView,
    RetireScenarioView,
    ReviewScenarioProposalView,
    RollbackScenarioSetView,
    ScenarioResearchUnavailableView,
    StressScenarioDetailView,
    StressScenarioListView,
    ValidateScenarioRevisionView,
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
    path(
        "post-investment-check/",
        PostInvestmentRiskCheckView.as_view(),
        name="post-investment-check",
    ),
    path("daily-report/", RiskCenterDailyReportView.as_view(), name="daily-report"),
    path(
        "evidence/operator-spec-approval-subjects/",
        RegisterEvidenceOperatorSpecApprovalSubjectView.as_view(),
        name="evidence-operator-spec-approval-subject-register",
    ),
    path(
        "evidence/operator-spec-approvals/",
        ApproveEvidenceOperatorSpecView.as_view(),
        name="evidence-operator-spec-approve",
    ),
    path("stress-scenarios/", StressScenarioListView.as_view(), name="stress-scenarios"),
    path(
        "stress-scenarios/validate-revision/",
        ValidateScenarioRevisionView.as_view(),
        name="stress-scenario-validate-revision",
    ),
    path(
        "stress-scenarios/preview-revision/",
        PreviewScenarioGovernanceView.as_view(),
        name="stress-scenario-preview-revision",
    ),
    path(
        "stress-scenarios/propose-revision/",
        ProposeScenarioRevisionView.as_view(),
        name="stress-scenario-propose-revision",
    ),
    path(
        "stress-scenarios/<str:scenario_key>/retire/",
        RetireScenarioView.as_view(),
        name="stress-scenario-retire",
    ),
    path(
        "stress-scenarios/<str:scenario_key>/",
        StressScenarioDetailView.as_view(),
        name="stress-scenario-detail",
    ),
    path(
        "stress-scenario-sets/active/",
        ActiveScenarioSetView.as_view(),
        name="active-stress-scenario-set",
    ),
    path(
        "stress-scenario-sets/activate/",
        ActivateScenarioSetView.as_view(),
        name="stress-scenario-set-activate",
    ),
    path(
        "stress-scenario-sets/rollback/",
        RollbackScenarioSetView.as_view(),
        name="stress-scenario-set-rollback",
    ),
    path(
        "stress-scenario-proposals/<int:proposal_id>/<str:decision>/",
        ReviewScenarioProposalView.as_view(),
        name="stress-scenario-proposal-review",
    ),
    path(
        "stress-scenario-sets/impact-preview/",
        ScenarioResearchUnavailableView.as_view(),
        name="stress-scenario-impact-preview",
    ),
    path(
        "research/market-state/",
        ScenarioResearchUnavailableView.as_view(),
        name="market-state-evidence",
    ),
    path(
        "research/decision-scorecard/",
        ScenarioResearchUnavailableView.as_view(),
        name="decision-scorecard",
    ),
    path(
        "research/strategy-brief/",
        ScenarioResearchUnavailableView.as_view(),
        name="strategy-brief",
    ),
]
