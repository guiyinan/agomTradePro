"""Dedicated simulated-trading views required by the public SDK contract."""

import logging

from django.db import DatabaseError
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.simulated_trading.application import interface_services

from .serializers import ClosePositionRequestSerializer, ResetAccountRequestSerializer

logger = logging.getLogger(__name__)

_ACCESS_ERROR_CODES = {
    status.HTTP_401_UNAUTHORIZED: "authentication_required",
    status.HTTP_403_FORBIDDEN: "simulated_account_access_denied",
    status.HTTP_404_NOT_FOUND: "simulated_account_not_found",
}
_POSITION_CLOSE_ERROR_STATUS = {
    "simulated_position_not_found": status.HTTP_404_NOT_FOUND,
    "simulated_position_state_invalid": status.HTTP_409_CONFLICT,
    "close_shares_invalid": status.HTTP_400_BAD_REQUEST,
    "close_shares_exceeds_position": status.HTTP_400_BAD_REQUEST,
    "close_price_invalid": status.HTTP_400_BAD_REQUEST,
}
_SERVICE_EXCEPTIONS = (
    DatabaseError,
    ArithmeticError,
    AttributeError,
    ConnectionError,
    LookupError,
    OSError,
    RuntimeError,
    TypeError,
)


def _account_access_denial(
    request: Request,
    account_id: int,
    *,
    action: str,
) -> Response | None:
    if isinstance(account_id, bool) or account_id <= 0:
        return Response(
            {"success": False, "error": "simulated_account_id_invalid"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    access = interface_services.get_account_access(
        user=request.user,
        account_id=account_id,
        action=action,
    )
    if access.allowed:
        return None
    status_code = access.status_code
    if not isinstance(status_code, int) or status_code not in _ACCESS_ERROR_CODES:
        status_code = status.HTTP_403_FORBIDDEN
    return Response(
        {"success": False, "error": _ACCESS_ERROR_CODES[status_code]},
        status=status_code,
    )


class PositionCloseAPIView(APIView):
    """Close all or part of one account position."""

    def post(self, request: Request, account_id: int) -> Response:
        """Validate and execute one owned-account position close."""

        denial = _account_access_denial(request, account_id, action="操作")
        if denial is not None:
            return denial

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
            error_code = str(exc)
            error_status = _POSITION_CLOSE_ERROR_STATUS.get(error_code)
            if error_status is None:
                logger.warning(
                    "Simulated position close validation failed; exception_type=%s",
                    type(exc).__name__,
                )
                error_code = "simulated_position_close_failed"
                error_status = status.HTTP_400_BAD_REQUEST
            return Response(
                {"success": False, "error": error_code},
                status=error_status,
            )
        except _SERVICE_EXCEPTIONS as exc:
            logger.warning(
                "Simulated position close failed; exception_type=%s",
                type(exc).__name__,
            )
            return Response(
                {"success": False, "error": "simulated_position_close_unavailable"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response({"success": True, **result})


class AccountResetAPIView(APIView):
    """Reset one account ledger while retaining account configuration."""

    def post(self, request: Request, account_id: int) -> Response:
        """Validate and execute one owned-account ledger reset."""

        denial = _account_access_denial(request, account_id, action="重置")
        if denial is not None:
            return denial

        serializer = ResetAccountRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            summary = interface_services.reset_account_with_summary(
                account_id=account_id,
                new_initial_capital=serializer.validated_data.get("new_initial_capital"),
            )
        except _SERVICE_EXCEPTIONS as exc:
            logger.warning(
                "Simulated account reset failed; exception_type=%s",
                type(exc).__name__,
            )
            return Response(
                {"success": False, "error": "simulated_account_reset_unavailable"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        if summary is None:
            return Response(
                {"success": False, "error": "simulated_account_not_found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response({"success": True, **summary})
