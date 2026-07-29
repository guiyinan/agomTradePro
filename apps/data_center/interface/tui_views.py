"""Typed Data Center API adapters for TUI-only task contracts."""

from __future__ import annotations

from typing import Any

from rest_framework import status
from rest_framework.parsers import JSONParser
from rest_framework.permissions import IsAdminUser
from rest_framework.renderers import JSONRenderer
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.data_center.application.interface_services import (
    load_macro_governance_payload,
    make_manage_market_thermometer_config_use_case,
    run_macro_governance_action,
)

from .tui_serializers import (
    MacroGovernanceTuiActionSerializer,
    MarketThermometerTuiConfigSerializer,
)

_THRESHOLD_KEYS: tuple[str, ...] = (
    "warm_threshold",
    "hot_threshold",
    "overheat_threshold",
    "extreme_threshold",
)


class MacroGovernanceTuiView(APIView):
    """Expose the staff-only governance snapshot and confirmed repair actions."""

    permission_classes = [IsAdminUser]
    parser_classes = [JSONParser]
    renderer_classes = [JSONRenderer]

    def get(self, request: Request) -> Response:
        """Return the current bounded governance evidence snapshot."""

        del request
        return Response({"success": True, "snapshot": load_macro_governance_payload()})

    def post(self, request: Request) -> Response:
        """Run one allow-listed governance action through the Application service."""

        serializer = MacroGovernanceTuiActionSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {
                    "success": False,
                    "error": "参数验证失败",
                    "details": serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        action = str(serializer.validated_data["action"])
        return Response(run_macro_governance_action(action))


class MarketThermometerTuiConfigView(APIView):
    """Read and patch global thermometer config through flat scalar fields."""

    permission_classes = [IsAdminUser]
    parser_classes = [JSONParser]
    renderer_classes = [JSONRenderer]

    def get(self, request: Request) -> Response:
        """Return the current global thermometer configuration."""

        del request
        config = make_manage_market_thermometer_config_use_case().get()
        return Response(config.to_dict())

    def patch(self, request: Request) -> Response:
        """Merge flat threshold fields into the owner's nested config contract."""

        serializer = MarketThermometerTuiConfigSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {
                    "success": False,
                    "error": "参数验证失败",
                    "details": serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        values = dict(serializer.validated_data)
        update_values: dict[str, Any] = {
            key: value for key, value in values.items() if key not in _THRESHOLD_KEYS
        }
        threshold_patch = {key: values[key] for key in _THRESHOLD_KEYS if key in values}
        if threshold_patch:
            current = make_manage_market_thermometer_config_use_case().get().to_dict()
            current_thresholds = dict(current.get("thresholds") or {})
            current_thresholds.update(threshold_patch)
            update_values["thresholds"] = current_thresholds

        updated = make_manage_market_thermometer_config_use_case().update(**update_values)
        return Response(updated.to_dict())
