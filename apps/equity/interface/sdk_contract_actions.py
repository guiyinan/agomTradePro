"""SDK contract actions for the equity API."""

import re

from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.equity.application.query_services import list_stock_financial_payloads

from .serializers import FinancialHistoryQuerySerializer

_STOCK_CODE_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,32}$")


class EquitySDKContractActionsMixin:
    """Expose equity endpoints required by the public SDK contract."""

    @action(
        detail=False,
        methods=["get"],
        url_path="financials/(?P<stock_code>[^/]+)",
        permission_classes=[IsAuthenticated],
    )
    def financials(self, request: Request, stock_code: str) -> Response:
        """Return persisted financial snapshots for one stock."""

        normalized_code = stock_code.strip().upper()
        if _STOCK_CODE_PATTERN.fullmatch(normalized_code) is None:
            raise ValidationError({"stock_code": ["Invalid stock code."]})
        query = FinancialHistoryQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        results = list_stock_financial_payloads(
            stock_code=normalized_code,
            report_type=query.validated_data["report_type"],
            limit=query.validated_data["limit"],
        )
        return Response(
            {
                "stock_code": normalized_code,
                "report_type": query.validated_data["report_type"],
                "results": results,
                "count": len(results),
            }
        )
