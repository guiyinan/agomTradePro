"""Typed TUI read adapters for the current user's account analytics."""

from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.account.application import interface_services
from apps.account.application.volatility_use_cases import VolatilityAnalysisUseCase

from .permissions import GeneralPermission


def _user_id(request: Request) -> int:
    """Return the persisted authenticated user ID."""

    user_id = getattr(request.user, "id", None)
    if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
        raise ValueError("用户身份无效")
    return user_id


class AccountTuiVolatilityView(APIView):
    """Return chart-ready volatility evidence for the current user's active portfolio."""

    permission_classes = [IsAuthenticated, GeneralPermission]

    def get(self, request: Request) -> Response:
        """Return percentage-valued current metrics, adjustment, and history."""

        try:
            user_id = _user_id(request)
            portfolio = interface_services.get_active_portfolio_for_user(user_id)
            if portfolio is None:
                return Response(
                    {
                        "success": True,
                        "has_portfolio": False,
                        "message": "暂无活跃投资组合",
                        "history": [],
                    }
                )
            analysis = VolatilityAnalysisUseCase().analyze_portfolio_volatility(
                portfolio_id=portfolio.id,
                user_id=user_id,
            )
        except ValueError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        target_percent = round(analysis.target_volatility * 100, 6)
        history = [
            {
                "date": metric.as_of_date.isoformat(),
                "annualized_volatility_percent": round(
                    metric.annualized_volatility * 100,
                    6,
                ),
                "target_percent": target_percent,
                "target_upper_percent": target_percent * 1.2,
                "target_lower_percent": target_percent * 0.8,
            }
            for metric in analysis.volatility_history
        ]
        adjustment = analysis.adjustment_result
        return Response(
            {
                "success": True,
                "has_portfolio": True,
                "portfolio_id": analysis.portfolio_id,
                "volatility_30d_percent": round(analysis.current_volatility_30d * 100, 6),
                "volatility_60d_percent": round(analysis.current_volatility_60d * 100, 6),
                "volatility_90d_percent": round(analysis.current_volatility_90d * 100, 6),
                "target_percent": target_percent,
                "should_reduce": bool(adjustment and adjustment.should_reduce),
                "reduction_reason": (adjustment.reduction_reason if adjustment is not None else ""),
                "suggested_multiplier_percent": (
                    round(adjustment.suggested_position_multiplier * 100, 6)
                    if adjustment is not None
                    else None
                ),
                "history": history,
            }
        )
