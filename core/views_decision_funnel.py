"""
Decision Funnel Views

These views map to the 6 steps of the decision funnel and return HTML partials
rendered via HTMX.
"""

from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from core.application.decision_context import DecisionContextUseCase


@login_required
def funnel_step1_view(request):
    """Step 1: 环境评估"""
    use_case = DecisionContextUseCase()
    context_data = use_case.get_step1_context()

    return render(
        request,
        "decision/steps/environment.html",
        {
            "regime_name": context_data.regime_name,
            "pulse_composite": context_data.pulse_composite,
            "regime_strength": context_data.regime_strength,
            "policy_level": context_data.policy_level,
            "overall_verdict": context_data.overall_verdict,
        },
    )


@login_required
def funnel_step2_view(request):
    """Step 2: 方向选择"""
    use_case = DecisionContextUseCase()
    direction_data = use_case.get_step2_direction()

    return render(
        request,
        "decision/steps/direction.html",
        {
            "asset_weights": direction_data.asset_weights,
            "risk_budget_pct": direction_data.risk_budget_pct,
            "action_recommendation": direction_data.action_recommendation,
        },
    )


@login_required
def funnel_step3_view(request):
    """Step 3: 板块偏好"""
    use_case = DecisionContextUseCase()
    sectors_data = use_case.get_step3_sectors(
        category=request.GET.get("category", "equity"),
    )

    return render(
        request,
        "decision/steps/sector.html",
        {
            "sector_recommendations": sectors_data.sector_recommendations,
            "rotation_signals": sectors_data.rotation_signals,
        },
    )


@login_required
def funnel_step4_view(request):
    """Step 4: 推优筛选 (Unified Recommendations)"""
    # This renders the shell for the recommendations list.
    # The actual list is fetched dynamically via the unified API.
    return render(request, "decision/steps/screen.html")


@login_required
def funnel_step5_view(request):
    """Step 5: 交易计划"""
    return render(request, "decision/steps/plan.html")


@login_required
def funnel_step6_view(request):
    """Step 6: 审批执行"""
    return render(request, "decision/steps/execute.html")
