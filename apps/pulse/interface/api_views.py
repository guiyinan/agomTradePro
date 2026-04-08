"""Pulse API Views"""

import logging
from datetime import date

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger(__name__)


class PulseCurrentView(APIView):
    """获取最新 Pulse 快照

    GET /api/pulse/current/
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            from apps.pulse.application.use_cases import GetLatestPulseUseCase

            use_case = GetLatestPulseUseCase()
            snapshot = use_case.execute(
                as_of_date=date.today(),
                refresh_if_stale=True,
            )

            if not snapshot:
                return Response(
                    {"success": False, "error": "No pulse data available"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            return Response({"success": True, "data": _serialize_snapshot(snapshot)})

        except Exception as e:
            logger.exception(f"Error getting pulse: {e}")
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class PulseHistoryView(APIView):
    """获取历史 Pulse 记录

    GET /api/pulse/history/?months=6
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            months = int(request.query_params.get("months", 6))
            from apps.pulse.infrastructure.repositories import PulseRepository

            repo = PulseRepository()
            logs = repo.get_history(months=months)

            data = [
                {
                    "observed_at": log.observed_at.isoformat(),
                    "regime_context": log.regime_context,
                    "composite_score": log.composite_score,
                    "regime_strength": log.regime_strength,
                    "growth_score": log.growth_score,
                    "inflation_score": log.inflation_score,
                    "liquidity_score": log.liquidity_score,
                    "sentiment_score": log.sentiment_score,
                    "transition_warning": log.transition_warning,
                    "transition_direction": log.transition_direction,
                }
                for log in logs
            ]

            return Response({"success": True, "count": len(data), "data": data})

        except Exception as e:
            logger.exception(f"Error getting pulse history: {e}")
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class PulseCalculateView(APIView):
    """手动触发 Pulse 计算

    POST /api/pulse/calculate/
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not request.user.is_staff:
            return Response(
                {"success": False, "error": "Staff only"},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            from apps.pulse.application.use_cases import CalculatePulseUseCase

            use_case = CalculatePulseUseCase()
            snapshot = use_case.execute()

            if not snapshot:
                return Response(
                    {"success": False, "error": "Pulse calculation failed"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

            return Response({
                "success": True,
                "data": {
                    "composite_score": snapshot.composite_score,
                    "regime_strength": snapshot.regime_strength,
                    "transition_warning": snapshot.transition_warning,
                },
            })

        except Exception as e:
            logger.exception(f"Error calculating pulse: {e}")
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


def _serialize_snapshot(snapshot) -> dict:
    """Serialize a pulse snapshot into the public API contract."""
    return {
        "observed_at": snapshot.observed_at.isoformat(),
        "regime_context": snapshot.regime_context,
        "composite_score": snapshot.composite_score,
        "regime_strength": snapshot.regime_strength,
        "transition_warning": snapshot.transition_warning,
        "transition_direction": snapshot.transition_direction,
        "transition_reasons": snapshot.transition_reasons,
        "data_source": snapshot.data_source,
        "is_reliable": snapshot.is_reliable,
        "dimensions": {
            ds.dimension: {
                "score": ds.score,
                "signal": ds.signal,
                "indicator_count": ds.indicator_count,
                "description": ds.description,
            }
            for ds in snapshot.dimension_scores
        },
        "indicators": [
            {
                "code": r.code,
                "name": r.name,
                "dimension": r.dimension,
                "value": r.value,
                "signal": r.signal,
                "signal_score": r.signal_score,
                "direction": r.direction,
                "is_stale": r.is_stale,
            }
            for r in snapshot.indicator_readings
        ],
    }
