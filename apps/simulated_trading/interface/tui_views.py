"""Typed TUI-facing views for simulated-trading account operations."""

from __future__ import annotations

from typing import Any

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.simulated_trading.application import interface_services
from apps.simulated_trading.interface.tui_serializers import (
    InspectionNotificationConfigRequestSerializer,
)


def _notification_payload(context: dict[str, Any]) -> dict[str, Any]:
    """Project the persisted notification model into a stable JSON envelope."""

    account = context["account"]
    config = context["config"]
    return {
        "success": True,
        "account_id": account.id,
        "account_name": account.account_name,
        "config": {
            "is_enabled": config.is_enabled,
            "notify_on": config.notify_on,
            "include_owner_email": config.include_owner_email,
            "recipient_emails": list(config.recipient_emails or []),
            "updated_at": config.updated_at.isoformat(),
        },
    }


class InspectionNotificationConfigAPIView(APIView):
    """Read or update the current user's account notification settings."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, account_id: int) -> Response:
        """Return notification settings after enforcing owner scope."""

        context = interface_services.build_inspection_notify_context(request.user, account_id)
        if context is None:
            return Response(
                {"success": False, "error": "账户不存在或无权访问"},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(_notification_payload(context))

    def patch(self, request: Request, account_id: int) -> Response:
        """Validate and persist notification settings within owner scope."""

        context = interface_services.build_inspection_notify_context(request.user, account_id)
        if context is None:
            return Response(
                {"success": False, "error": "账户不存在或无权访问"},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = InspectionNotificationConfigRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        saved = interface_services.save_inspection_notification_config(
            account_id=account_id,
            is_enabled=bool(data["is_enabled"]),
            include_owner_email=bool(data["include_owner_email"]),
            notify_on=str(data["notify_on"]),
            recipient_emails=list(data["recipient_emails"]),
        )
        if saved is None:
            return Response(
                {"success": False, "error": "巡检通知配置保存失败"},
                status=status.HTTP_409_CONFLICT,
            )

        refreshed = interface_services.build_inspection_notify_context(request.user, account_id)
        if refreshed is None:
            return Response(
                {"success": False, "error": "巡检通知配置读取失败"},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(_notification_payload(refreshed))
