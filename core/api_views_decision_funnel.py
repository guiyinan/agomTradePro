from django.http import JsonResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated

from core.application.decision_context import DecisionContextUseCase


class DecisionFunnelStep1EnvironmentSerializer(serializers.Serializer):
    regime_name = serializers.CharField()
    pulse_composite = serializers.FloatField()
    regime_strength = serializers.CharField()
    policy_level = serializers.CharField(allow_null=True)
    overall_verdict = serializers.CharField()


class DecisionFunnelStep2DirectionSerializer(serializers.Serializer):
    action_recommendation = serializers.DictField()
    asset_weights = serializers.DictField(child=serializers.FloatField())
    risk_budget_pct = serializers.FloatField()


class DecisionFunnelStep3SectorRecommendationSerializer(serializers.Serializer):
    name = serializers.CharField()
    score = serializers.FloatField()
    alignment = serializers.CharField()
    momentum = serializers.CharField()


class DecisionFunnelStep3RotationSignalSerializer(serializers.Serializer):
    sector = serializers.CharField()
    signal = serializers.CharField()
    strength = serializers.FloatField()


class DecisionFunnelStep3SectorsSerializer(serializers.Serializer):
    sector_recommendations = DecisionFunnelStep3SectorRecommendationSerializer(many=True)
    rotation_signals = DecisionFunnelStep3RotationSignalSerializer(many=True)
    rotation_data_source = serializers.CharField(allow_null=True, required=False)
    rotation_is_stale = serializers.BooleanField()
    rotation_warning_message = serializers.CharField(allow_null=True, required=False)
    rotation_signal_date = serializers.CharField(allow_null=True, required=False)


class DecisionFunnelStep6AuditSerializer(serializers.Serializer):
    attribution_method = serializers.CharField()
    benchmark_return = serializers.FloatField()
    portfolio_return = serializers.FloatField()
    excess_return = serializers.FloatField()
    allocation_effect = serializers.FloatField()
    selection_effect = serializers.FloatField()
    interaction_effect = serializers.FloatField()
    loss_source = serializers.CharField(allow_null=True)
    lesson_learned = serializers.CharField()
    backtest_id = serializers.IntegerField(allow_null=True, required=False)
    report_id = serializers.IntegerField(allow_null=True, required=False)
    regime_accuracy = serializers.FloatField(allow_null=True, required=False)
    regime_predicted = serializers.CharField(allow_null=True, required=False)
    regime_actual = serializers.CharField(allow_null=True, required=False)


class DecisionFunnelContextDataSerializer(serializers.Serializer):
    step1_environment = DecisionFunnelStep1EnvironmentSerializer()
    step2_direction = DecisionFunnelStep2DirectionSerializer()
    step3_sectors = DecisionFunnelStep3SectorsSerializer()
    step6_audit = DecisionFunnelStep6AuditSerializer(required=False)


class DecisionFunnelContextResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    data = DecisionFunnelContextDataSerializer()


@extend_schema(
    parameters=[
        OpenApiParameter(
            name="trade_id",
            type=OpenApiTypes.STR,
            location=OpenApiParameter.QUERY,
            required=False,
            description="Legacy audit replay identifier for Step 6.",
        ),
        OpenApiParameter(
            name="backtest_id",
            type=OpenApiTypes.INT,
            location=OpenApiParameter.QUERY,
            required=False,
            description="Optional backtest id for deterministic Step 6 audit replay.",
        ),
    ],
    responses={200: DecisionFunnelContextResponseSerializer},
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def decision_funnel_context_api_view(request):
    """
    Returns the system-level decision funnel context (Steps 1, 2, 3) in JSON format.
    Steps 4 and 5 are dynamic lists and use their own endpoints.
    When a legacy audit query is provided, include the historical Step 6 audit
    payload as a backward-compatible extension.
    """
    use_case = DecisionContextUseCase()

    step1 = use_case.get_step1_context()
    step2 = use_case.get_step2_direction()
    step3 = use_case.get_step3_sectors()
    backtest_id = request.GET.get("backtest_id")
    trade_id = request.GET.get("trade_id")

    data = {
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
            "rotation_data_source": step3.rotation_data_source,
            "rotation_is_stale": step3.rotation_is_stale,
            "rotation_warning_message": step3.rotation_warning_message,
            "rotation_signal_date": step3.rotation_signal_date,
        },
    }

    if trade_id or backtest_id:
        step6 = use_case.get_step6_audit(
            trade_id=trade_id,
            backtest_id=int(backtest_id) if backtest_id and backtest_id.isdigit() else None,
        )
        data["step6_audit"] = {
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

    return JsonResponse(
        {
            "success": True,
            "data": data,
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
            "data": {
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
            },
        }
    )
