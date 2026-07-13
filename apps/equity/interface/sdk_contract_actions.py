"""SDK contract actions for the equity API."""

from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.equity.application.query_services import list_stock_financial_payloads

from .serializers import FinancialHistoryQuerySerializer


class EquitySDKContractActionsMixin:
    """Expose equity endpoints required by the public SDK contract."""

    @action(
        detail=False,
        methods=["get"],
        url_path="financials/(?P<stock_code>[^/]+)",
        permission_classes=[IsAuthenticated],
    )
    def financials(self, request, stock_code: str):
        """Return persisted financial snapshots for one stock."""

        query = FinancialHistoryQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        results = list_stock_financial_payloads(
            stock_code=stock_code,
            report_type=query.validated_data["report_type"],
            limit=query.validated_data["limit"],
        )
        return Response(
            {
                "stock_code": stock_code,
                "report_type": query.validated_data["report_type"],
                "results": results,
                "count": len(results),
            }
        )
