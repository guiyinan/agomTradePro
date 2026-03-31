"""Account sizing context API views."""

from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.account.application.use_cases import GetSizingContextUseCase


class SizingContextView(APIView):
    """返回当前用户投资组合的宏观仓位系数上下文。"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        portfolio_id = request.query_params.get("portfolio_id")
        if portfolio_id is None:
            portfolio = request.user.portfolios.filter(is_active=True).first()
            if portfolio is None:
                return Response(
                    {"detail": "暂无投资组合"},
                    status=status.HTTP_404_NOT_FOUND,
                )
            portfolio_id = portfolio.id

        try:
            portfolio_id = int(portfolio_id)
        except (TypeError, ValueError):
            return Response(
                {"detail": "portfolio_id 必须为整数"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            output = GetSizingContextUseCase().execute(
                portfolio_id=portfolio_id,
                user_id=request.user.id,
            )
        except ValueError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_404_NOT_FOUND,
            )

        result = output.multiplier_result
        return Response(
            {
                "multiplier": result.multiplier,
                "action_hint": result.action_hint,
                "reasoning": result.reasoning,
                "components": {
                    "regime_factor": result.regime_factor,
                    "pulse_factor": result.pulse_factor,
                    "drawdown_factor": result.drawdown_factor,
                },
                "context": {
                    "regime": output.regime_name,
                    "regime_confidence": output.regime_confidence,
                    "pulse_composite": output.pulse_composite,
                    "pulse_warning": output.pulse_warning,
                    "portfolio_drawdown_pct": output.portfolio_drawdown_pct,
                },
                "config_version": result.config_version,
                "warnings": output.warnings,
                "calculated_at": timezone.now().isoformat(),
            }
        )
