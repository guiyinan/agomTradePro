"""Read-only HTTP boundary for the governed equity research snapshot."""

from __future__ import annotations

import re
from typing import Any, Protocol, cast

from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.equity.application.research_snapshot import (
    EquityResearchSnapshotRequest,
    EquityResearchSnapshotResult,
)

from .serializers import StrictFieldsSerializer

_RESEARCH_ASSET_IDENTIFIER_PATTERN = re.compile(r"^[\w.*+-]{1,32}$", re.UNICODE)


class EquityResearchSnapshotQuerySerializer(StrictFieldsSerializer):
    """Validate the bounded read contract for one equity research snapshot."""

    history_limit = serializers.IntegerField(default=252, min_value=1, max_value=1000)
    financial_limit = serializers.IntegerField(default=20, min_value=1, max_value=100)
    valuation_limit = serializers.IntegerField(default=252, min_value=1, max_value=1000)
    news_limit = serializers.IntegerField(default=20, min_value=1, max_value=100)
    capital_flow_limit = serializers.IntegerField(default=60, min_value=1, max_value=1000)


class EquityResearchSnapshotPathSerializer(StrictFieldsSerializer):
    """Validate the asset code or exact name supplied by the URL path."""

    stock_code = serializers.CharField(min_length=1, max_length=32, trim_whitespace=True)

    def validate_stock_code(self, value: str) -> str:
        """Normalize a code/name while rejecting unsafe path identifiers."""

        normalized = value.strip().upper()
        if (
            normalized in {".", ".."}
            or _RESEARCH_ASSET_IDENTIFIER_PATTERN.fullmatch(normalized) is None
        ):
            raise serializers.ValidationError("Invalid stock code or exact stock name.")
        return normalized


class _EquityResearchSnapshotUseCase(Protocol):
    """Narrow application contract consumed by the HTTP boundary."""

    def execute(self, request: EquityResearchSnapshotRequest) -> EquityResearchSnapshotResult:
        """Return one governed research snapshot."""


def make_equity_research_snapshot_use_case() -> _EquityResearchSnapshotUseCase:
    """Resolve the Application composition without assembling dependencies here."""

    from apps.equity.research_snapshot_composition import (
        make_equity_research_snapshot_use_case as make_application_use_case,
    )

    return cast(_EquityResearchSnapshotUseCase, make_application_use_case())


class EquityResearchSnapshotAPIView(APIView):
    """Return one read-only, fail-closed equity research snapshot."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, stock_code: str) -> Response:
        """Validate the request and delegate snapshot construction to Application."""

        path_serializer = EquityResearchSnapshotPathSerializer(data={"stock_code": stock_code})
        path_serializer.is_valid(raise_exception=True)
        query_serializer = EquityResearchSnapshotQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        path_data = cast(dict[str, Any], path_serializer.validated_data)
        query_data = cast(dict[str, Any], query_serializer.validated_data)

        use_case_request = EquityResearchSnapshotRequest(
            stock_code=cast(str, path_data["stock_code"]),
            history_limit=cast(int, query_data["history_limit"]),
            financial_limit=cast(int, query_data["financial_limit"]),
            valuation_limit=cast(int, query_data["valuation_limit"]),
            news_limit=cast(int, query_data["news_limit"]),
            capital_flow_limit=cast(int, query_data["capital_flow_limit"]),
        )
        result = make_equity_research_snapshot_use_case().execute(use_case_request)
        return Response(result.to_payload(), status=status.HTTP_200_OK)


__all__ = [
    "EquityResearchSnapshotAPIView",
    "EquityResearchSnapshotPathSerializer",
    "EquityResearchSnapshotQuerySerializer",
]
