"""Typed TUI-facing views for fund research."""

from __future__ import annotations

from typing import Any

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.fund.application import interface_services
from apps.fund.interface.tui_serializers import FundTuiMultiDimScreenRequestSerializer


class FundTuiMultiDimScreenAPIView(APIView):
    """Run multidimensional fund screening with flat scalar inputs."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        """Validate flat fields and delegate to the owner Application service."""

        serializer = FundTuiMultiDimScreenRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        filters: dict[str, Any] = {}
        context_data: dict[str, Any] = {}
        for key in ("fund_type", "investment_style", "min_scale"):
            value = data.get(key)
            if value not in (None, ""):
                filters[key] = value
        for key in ("regime", "policy_level", "sentiment_index"):
            value = data.get(key)
            if value not in (None, ""):
                context_data[key] = value

        payload = interface_services.screen_funds_multidim(
            filters=filters,
            context_data=context_data,
            max_count=int(data["max_count"]),
        )
        result = payload["result"]
        context = payload["context"]
        return Response(
            {
                "success": result["success"],
                "count": result["count"],
                "context": {
                    "regime": context.current_regime,
                    "policy_level": context.policy_level,
                    "sentiment_index": context.sentiment_index,
                    "active_signals_count": payload["active_signals_count"],
                },
                "funds": result["funds"],
            },
            status=(status.HTTP_200_OK if result["success"] else status.HTTP_404_NOT_FOUND),
        )
