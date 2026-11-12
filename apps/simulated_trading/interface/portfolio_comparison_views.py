"""Read-only HTTP endpoint for comparing two authorized portfolios."""

from dataclasses import asdict
from typing import Any, cast

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.simulated_trading.composition import build_portfolio_comparison_use_case
from apps.simulated_trading.interface.performance_views import (
    _ACCOUNT_REPO,
    _OBSERVER_GRANT_REPO,
    _get_account_or_403,
)
from apps.simulated_trading.interface.portfolio_comparison_serializers import (
    PortfolioComparisonQuerySerializer,
    PortfolioComparisonResponseSerializer,
)

from ._portfolio_views import typed_extend_schema


class PortfolioComparisonAPIView(APIView):
    """Compare two visible accounts without changing financial records."""

    permission_classes = [IsAuthenticated]

    @typed_extend_schema(
        summary="对比两个投资组合",
        parameters=[PortfolioComparisonQuerySerializer],
        responses={200: PortfolioComparisonResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        """Validate common inputs, enforce account visibility and return comparison data."""

        serializer = PortfolioComparisonQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        values = cast(dict[str, Any], serializer.validated_data)
        for key in ("left_account_id", "right_account_id"):
            account = _get_account_or_403(request, values[key], _ACCOUNT_REPO, _OBSERVER_GRANT_REPO)
            if account is None:
                return Response({"success": False, "error": "投资组合不存在"}, status=404)
            if account == "forbidden":
                return Response({"success": False, "error": "无权查看该投资组合"}, status=403)

        try:
            result = build_portfolio_comparison_use_case().execute(**values)
        except ValueError as exc:
            return Response({"success": False, "error": str(exc)}, status=400)
        payload = asdict(result)
        payload.update(
            {
                "success": True,
                "start_date": values["start_date"],
                "end_date": values["end_date"],
            }
        )
        return Response(payload, status=200)
