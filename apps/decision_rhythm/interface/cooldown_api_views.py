"""Cooldown query API views for decision rhythm."""

from __future__ import annotations

from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.response import Response

from ..application.query_workflows import (
    GetActiveCooldownByAssetRequest,
    GetCooldownRemainingHoursRequest,
)
from .api_response_utils import bad_request_response, internal_error_response
from .dependencies import (
    build_get_active_cooldown_by_asset_use_case,
    build_get_cooldown_remaining_hours_use_case,
    build_list_active_cooldowns_use_case,
)
from .serializers import (
    CooldownByAssetQuerySerializer,
    CooldownPeriodSerializer,
    CooldownRemainingHoursQuerySerializer,
)


class CooldownPeriodViewSet(viewsets.ViewSet):
    """Cooldown query endpoints."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.list_use_case = build_list_active_cooldowns_use_case()
        self.get_by_asset_use_case = build_get_active_cooldown_by_asset_use_case()
        self.remaining_hours_use_case = build_get_cooldown_remaining_hours_use_case()

    def list(self, request) -> Response:
        """GET /api/decision-rhythm/cooldowns/"""
        try:
            cooldowns = self.list_use_case.execute()
            serializer = CooldownPeriodSerializer(cooldowns, many=True)
            return Response(
                {
                    "success": True,
                    "count": len(cooldowns),
                    "results": serializer.data,
                }
            )
        except Exception as exc:
            return internal_error_response("Failed to list cooldowns", exc)

    @action(detail=False, methods=["GET"], url_path="by-asset/(?P<asset_code>[^/]+)")
    def by_asset(self, request, asset_code=None) -> Response:
        """GET /api/decision-rhythm/cooldowns/by-asset/{asset_code}/"""
        try:
            if not asset_code:
                return bad_request_response("asset_code is required")

            serializer = CooldownByAssetQuerySerializer(data=request.query_params)
            serializer.is_valid(raise_exception=True)
            data = serializer.validated_data

            cooldown = self.get_by_asset_use_case.execute(
                GetActiveCooldownByAssetRequest(
                    asset_code=asset_code,
                    direction=data.get("direction") or None,
                )
            )
            if cooldown is None:
                return Response(
                    {
                        "success": True,
                        "result": None,
                        "message": "No active cooldown for this asset",
                    }
                )

            response_serializer = CooldownPeriodSerializer(cooldown)
            return Response({"success": True, "result": response_serializer.data})
        except DRFValidationError as exc:
            return bad_request_response(exc.detail)
        except Exception as exc:
            return internal_error_response("Failed to get cooldown by asset", exc)

    @action(detail=False, methods=["GET"], url_path="remaining-hours")
    def remaining_hours(self, request) -> Response:
        """GET /api/decision-rhythm/cooldowns/remaining-hours/"""
        try:
            serializer = CooldownRemainingHoursQuerySerializer(data=request.query_params)
            serializer.is_valid(raise_exception=True)
            data = serializer.validated_data

            remaining = self.remaining_hours_use_case.execute(
                GetCooldownRemainingHoursRequest(
                    asset_code=data["asset_code"],
                    direction=data.get("direction") or None,
                )
            )
            return Response(
                {
                    "success": True,
                    "result": {
                        "asset_code": remaining.asset_code,
                        "remaining_hours": remaining.remaining_hours,
                        "is_active": remaining.is_active,
                    },
                }
            )
        except DRFValidationError as exc:
            return bad_request_response(exc.detail)
        except Exception as exc:
            return internal_error_response("Failed to get remaining hours", exc)
