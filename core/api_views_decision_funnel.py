from django.http import JsonResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from core.application.decision_context import DecisionContextUseCase


def _serialize_step6(step6):
    """Serialize Step 6 DTO to JSON-friendly structure."""
    return {
        "attribution_method": step6.attribution_method,
        "benchmark_return": step6.benchmark_return,
        "portfolio_return": step6.portfolio_return,
        "excess_return": step6.excess_return,
        "allocation_effect": step6.allocation_effect,
        "selection_effect": step6.selection_effect,
        "interaction_effect": step6.interaction_effect,
        "loss_source": step6.loss_source,
        "lesson_learned": step6.lesson_learned,
        "backtest_id": step6.backtest_id,
        "report_id": step6.report_id,
        "regime_accuracy": step6.regime_accuracy,
        "regime_predicted": step6.regime_predicted,
        "regime_actual": step6.regime_actual,
    }


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def decision_funnel_context_api_view(request):
    """
    Returns the full decision funnel context (Steps 1, 2, 3, 6) in JSON format.
    Steps 4 and 5 are dynamic lists and use their own endpoints.
    """
    trade_id = request.GET.get("trade_id", "unknown")
    backtest_id = request.GET.get("backtest_id")
    use_case = DecisionContextUseCase()

    step1 = use_case.get_step1_context()
    step2 = use_case.get_step2_direction()
    step3 = use_case.get_step3_sectors()
    step6 = use_case.get_step6_audit(
        trade_id=trade_id,
        backtest_id=int(backtest_id) if backtest_id and backtest_id.isdigit() else None,
    )

    return JsonResponse(
        {
            "success": True,
            "data": {
                "step1_environment": {
                    "regime_name": step1.regime_name,
                    "pulse_composite": step1.pulse_composite,
                    "regime_strength": step1.regime_strength,
                    "policy_level": step1.policy_level,
                    "overall_verdict": step1.overall_verdict,
                },
                "step2_direction": {
                    "action_recommendation": step2.action_recommendation,
                    "asset_weights": step2.asset_weights,
                    "risk_budget_pct": step2.risk_budget_pct,
                },
                "step3_sectors": {
                    "sector_recommendations": step3.sector_recommendations,
                    "rotation_signals": step3.rotation_signals,
                },
                "step6_audit": _serialize_step6(step6),
            },
        }
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def decision_audit_api_view(request):
    """Return Step 6 audit data as standalone JSON API."""
    trade_id = request.GET.get("trade_id")
    backtest_id = request.GET.get("backtest_id")
    use_case = DecisionContextUseCase()
    step6 = use_case.get_step6_audit(
        trade_id=trade_id,
        backtest_id=int(backtest_id) if backtest_id and backtest_id.isdigit() else None,
    )

    return JsonResponse(
        {
            "success": True,
            "data": _serialize_step6(step6),
        }
    )
