"""Dedicated simulated-trading views required by the public SDK contract."""

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.simulated_trading.application import interface_services

from .serializers import ClosePositionRequestSerializer, ResetAccountRequestSerializer


def _owned_account_or_response(request, account_id: int, *, action: str):
    access = interface_services.get_account_access(
        user=request.user,
        account_id=account_id,
        action=action,
    )
    if access.allowed:
        return access.account
    return Response(
        {"success": False, "error": access.error},
        status=access.status_code,
    )


class PositionCloseAPIView(APIView):
    """Close all or part of one account position."""

    def post(self, request, account_id):
        account = _owned_account_or_response(request, account_id, action="操作")
        if isinstance(account, Response):
            return account

        serializer = ClosePositionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            result = interface_services.close_account_position(
                account_id=account_id,
                asset_code=data["asset_code"].strip(),
                close_shares=data.get("close_shares"),
                close_price=data.get("close_price"),
                reason=data.get("reason", "平仓"),
            )
        except ValueError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response({"success": True, **result})


class AccountResetAPIView(APIView):
    """Reset one account ledger while retaining account configuration."""

    def post(self, request, account_id):
        account = _owned_account_or_response(request, account_id, action="重置")
        if isinstance(account, Response):
            return account

        serializer = ResetAccountRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        summary = interface_services.reset_account_with_summary(
            account_id=account_id,
            new_initial_capital=serializer.validated_data.get("new_initial_capital"),
        )
        if summary is None:
            return Response(
                {"success": False, "error": f"账户不存在: {account_id}"},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response({"success": True, **summary})
