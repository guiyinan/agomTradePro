"""SDK contract actions for the equity API."""

import re

from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.data_center.application.public import get_decision_publication_gate
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
        mode = str(query.validated_data["mode"])
        publication_key = str(query.validated_data["publication_key"])
        publication = None
        if mode == "published":
            publication = get_decision_publication_gate(
                "equity.financial.fact",
                publication_key,
            )
            if publication is None or bool(publication.get("must_not_use_for_decision")):
                return Response(
                    {
                        "stock_code": normalized_code,
                        "report_type": query.validated_data["report_type"],
                        "results": [],
                        "count": 0,
                        "status": "blocked",
                        "mode": mode,
                        "publication_key": publication_key,
                        "publication": publication,
                        "publication_id": (
                            publication.get("publication_id") if publication else None
                        ),
                        "must_not_use_for_decision": True,
                        "blocked_reason": (
                            publication.get("blocked_reason")
                            if publication
                            else "canonical_publication_missing"
                        ),
                    },
                    status=200,
                )
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
                "mode": mode,
                "publication_key": publication_key,
                "publication": publication,
            }
        )
