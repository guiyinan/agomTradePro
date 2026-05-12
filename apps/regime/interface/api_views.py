"""
DRF API Views for Regime Calculation.

提供 RESTful API 接口用于 Regime 判定。

重构说明 (2026-03-11):
- 使用 MacroRepositoryAdapter 替代直接导入 DjangoMacroRepository
- 保持 API 完全兼容
"""

from datetime import date

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.regime.application.interface_services import (
    calculate_regime_payload,
    get_regime_current_payload,
    get_regime_distribution_payload,
    get_regime_health_payload,
    get_regime_history_payload,
)

from .serializers import (
    RegimeCalculateRequestSerializer,
    RegimeCalculateResponseSerializer,
    RegimeHistoryQuerySerializer,
    RegimeLogSerializer,
)


class RegimeViewSet(viewsets.ViewSet):
    """
    Regime API ViewSet

    提供以下接口:
    - GET /api/regime/current/ - 获取当前 Regime
    - POST /api/regime/calculate/ - 计算 Regime
    - GET /api/regime/history/ - 获取历史记录
    """

    @action(detail=False, methods=['get'])
    def current(self, request):
        """
        获取当前 Regime 状态

        GET /api/regime/current/
        """
        try:
            return Response(get_regime_current_payload(as_of_date=date.today()))

        except Exception as e:
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['post'])
    def calculate(self, request):
        """
        计算 Regime 判定

        POST /api/regime/calculate/
        {
            "as_of_date": "2024-01-15",  // 可选，默认今天
            "use_pit": true,               // 可选，是否使用 Point-in-Time 数据
            "growth_indicator": "PMI",     // 可选，默认 PMI
            "inflation_indicator": "CPI",  // 可选，默认 CPI
            "data_source": "akshare"       // 可选，默认 akshare
        }
        """
        try:
            # 验证请求参数
            request_serializer = RegimeCalculateRequestSerializer(data=request.data)
            request_serializer.is_valid(raise_exception=True)
            data = request_serializer.validated_data

            payload = calculate_regime_payload(data=data)
            response_serializer = RegimeCalculateResponseSerializer(payload)
            return Response(response_serializer.data)

        except Exception as e:
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['get'])
    def history(self, request):
        """
        获取 Regime 历史记录

        GET /api/regime/history/?start_date=2024-01-01&end_date=2024-12-31&regime=Recovery&limit=100
        """
        try:
            # 验证查询参数
            query_serializer = RegimeHistoryQuerySerializer(data=request.query_params)
            query_serializer.is_valid(raise_exception=True)
            params = query_serializer.validated_data
            payload = get_regime_history_payload(
                start_date=params.get("start_date"),
                end_date=params.get("end_date"),
                regime=params.get("regime"),
                limit=params.get("limit", 100),
            )
            serializer = RegimeLogSerializer(payload["data"], many=True)
            return Response(
                {
                    "success": payload["success"],
                    "count": payload["count"],
                    "data": serializer.data,
                }
            )

        except Exception as e:
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['get'])
    def distribution(self, request):
        """
        获取 Regime 分布统计

        GET /api/regime/distribution/?start_date=2024-01-01&end_date=2024-12-31
        """
        try:
            payload = get_regime_distribution_payload(
                start_date=request.query_params.get("start_date"),
                end_date=request.query_params.get("end_date"),
            )
            return Response(payload)

        except Exception as e:
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class RegimeHealthView(APIView):
    """Regime 服务健康检查"""

    def get(self, request):
        """检查 Regime 服务健康状态"""
        try:
            return Response(get_regime_health_payload(), status=status.HTTP_200_OK)

        except Exception as e:
            return Response({
                'status': 'unhealthy',
                'service': 'regime',
                'error': str(e)
            }, status=status.HTTP_503_SERVICE_UNAVAILABLE)


class RegimeNavigatorView(APIView):
    """Regime 导航仪完整输出

    GET /api/regime/navigator/
    """

    def get(self, request):
        try:
            from apps.regime.application.navigator_use_cases import BuildRegimeNavigatorUseCase

            as_of_date_str = request.query_params.get("as_of_date")
            try:
                as_of_date = (
                    date.fromisoformat(as_of_date_str) if as_of_date_str else date.today()
                )
            except ValueError:
                return Response(
                    {"success": False, "error": f"Invalid as_of_date: {as_of_date_str}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            use_case = BuildRegimeNavigatorUseCase()
            navigator = use_case.execute(as_of_date)

            if not navigator:
                return Response(
                    {"success": False, "error": "Navigator data not available"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            data = {
                "regime_name": navigator.regime_name,
                "confidence": navigator.confidence,
                "distribution": navigator.distribution,
                "generated_at": navigator.generated_at.isoformat(),
                "data_freshness": navigator.data_freshness,
                "is_transitioning": navigator.is_transitioning,
                "movement": {
                    "direction": navigator.movement.direction,
                    "transition_target": navigator.movement.transition_target,
                    "transition_probability": navigator.movement.transition_probability,
                    "leading_indicators": navigator.movement.leading_indicators,
                    "momentum_summary": navigator.movement.momentum_summary,
                },
                "asset_guidance": {
                    "weight_ranges": [
                        {
                            "category": wr.category,
                            "lower": wr.lower,
                            "upper": wr.upper,
                            "label": wr.label,
                        }
                        for wr in navigator.asset_guidance.weight_ranges
                    ],
                    "risk_budget_pct": navigator.asset_guidance.risk_budget_pct,
                    "recommended_sectors": navigator.asset_guidance.recommended_sectors,
                    "benefiting_styles": navigator.asset_guidance.benefiting_styles,
                    "reasoning": navigator.asset_guidance.reasoning,
                },
                "watch_indicators": [
                    {
                        "code": w.code,
                        "name": w.name,
                        "threshold": w.threshold,
                        "significance": w.significance,
                    }
                    for w in navigator.watch_indicators
                ],
            }

            return Response({"success": True, "data": data})

        except Exception as e:
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class RegimeActionView(APIView):
    """Regime + Pulse 联合行动建议

    GET /api/regime/action/
    """

    def get(self, request):
        try:
            from apps.regime.application.navigator_use_cases import GetActionRecommendationUseCase

            as_of_date_str = request.query_params.get("as_of_date")
            try:
                as_of_date = (
                    date.fromisoformat(as_of_date_str) if as_of_date_str else date.today()
                )
            except ValueError:
                return Response(
                    {"success": False, "error": f"Invalid as_of_date: {as_of_date_str}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            use_case = GetActionRecommendationUseCase()
            action = use_case.execute(as_of_date)

            if not action:
                return Response(
                    {"success": False, "error": "Action recommendation not available"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            contract = {
                "must_not_use_for_decision": bool(action.must_not_use_for_decision),
                "blocked_reason": action.blocked_reason,
                "blocked_code": action.blocked_code,
                "pulse_observed_at": (
                    action.pulse_observed_at.isoformat() if action.pulse_observed_at else None
                ),
                "pulse_is_reliable": bool(action.pulse_is_reliable),
                "stale_indicator_codes": list(action.stale_indicator_codes or []),
            }
            data = {
                "asset_weights": action.asset_weights,
                "risk_budget_pct": action.risk_budget_pct,
                "position_limit_pct": action.position_limit_pct,
                "recommended_sectors": action.recommended_sectors,
                "benefiting_styles": action.benefiting_styles,
                "hedge_recommendation": action.hedge_recommendation,
                "reasoning": action.reasoning,
                "regime_contribution": action.regime_contribution,
                "pulse_contribution": action.pulse_contribution,
                "generated_at": action.generated_at.isoformat(),
                "confidence": action.confidence,
                "must_not_use_for_decision": contract["must_not_use_for_decision"],
                "blocked_reason": contract["blocked_reason"],
                "blocked_code": contract["blocked_code"],
                "pulse_observed_at": contract["pulse_observed_at"],
                "pulse_is_reliable": contract["pulse_is_reliable"],
                "stale_indicator_codes": contract["stale_indicator_codes"],
                "contract": contract,
            }

            return Response({"success": True, "data": data})

        except Exception as e:
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class RegimeNavigatorHistoryView(APIView):
    """Regime 导航仪历史序列与叠加

    GET /api/regime/navigator/history/?months=12
    """

    def get(self, request):
        try:
            from datetime import timedelta

            from apps.regime.application.navigator_use_cases import GetRegimeNavigatorHistoryUseCase

            months_str = request.query_params.get("months", "12")
            try:
                months = int(months_str)
            except ValueError:
                months = 12

            end_date = date.today()
            start_date = end_date - timedelta(days=30 * months)

            use_case = GetRegimeNavigatorHistoryUseCase()
            data = use_case.execute(start_date, end_date)

            return Response({"success": True, "data": data})

        except Exception as e:
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
