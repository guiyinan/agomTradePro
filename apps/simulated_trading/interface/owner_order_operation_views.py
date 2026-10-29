"""Authenticated JSON routes for applying retained fills and cancelling holds."""

from __future__ import annotations

import logging
from typing import Protocol, cast

from django.db import DatabaseError
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import ParseError, UnsupportedMediaType
from rest_framework.parsers import JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeAccountScopeUnavailable,
    SimulatedTradeExecutionBlocked,
    SimulatedTradeExecutionInputError,
    SimulatedTradeExecutionResultUnknown,
)
from apps.simulated_trading.owner_order_operations_composition import (
    build_owner_order_operations_use_case,
)
from core.exceptions import (
    BusinessLogicError,
    DuplicateResourceError,
    InvalidInputError,
    MissingConfigError,
    ResourceNotFoundError,
)

from .owner_order_operation_response import (
    OwnerOrderCancelledResponseSerializer,
    OwnerOrderFillAppliedResponseSerializer,
    OwnerOrderOperationConfirmationSerializer,
    OwnerOrderOperationErrorResponseSerializer,
    fill_applied_payload,
    order_cancelled_payload,
)
from .sdk_contract_views import typed_extend_schema

logger = logging.getLogger(__name__)

_CONFIRMED_KEYS = frozenset(("confirmed",))
_BAD_REQUEST = "订单操作请求无效"
_NOT_FOUND = "未找到本人模拟订单或撮合决定"
_BLOCKED = "当前订单状态不允许该操作"
_UNKNOWN = "操作结果暂无法确认，请先核对订单历史后使用相同目标重试"


class _AuthenticatedActor(Protocol):
    """The exact active principal identity used by the owner operation port."""

    id: int | None
    is_authenticated: bool
    is_active: bool


class _OwnerOrderOperationAPIView(APIView):
    """Share strict session, JSON, confirmation, and safe error handling."""

    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def _actor_id(self, request: Request) -> int | Response:
        """Require one active session principal without reading owner data here."""

        actor = cast(_AuthenticatedActor, request.user)
        if actor.is_authenticated is not True:
            return _error(
                status_code=status.HTTP_401_UNAUTHORIZED,
                code="AUTHENTICATION_REQUIRED",
                message="请先登录",
            )
        if type(actor.id) is not int or actor.id <= 0:
            return _error(
                status_code=status.HTTP_401_UNAUTHORIZED,
                code="AUTHENTICATED_ACTOR_INVALID",
                message="当前用户身份不可验证",
            )
        if actor.is_active is not True:
            return _error(
                status_code=status.HTTP_403_FORBIDDEN,
                code="AUTHENTICATED_ACTOR_INACTIVE",
                message="当前用户不可用",
            )
        return actor.id

    def _confirmed(self, request: Request) -> bool | Response:
        """Accept only JSON with one literal true and no query/body extras."""

        if request.content_type != JSONParser.media_type:
            return _input_error()
        if request.query_params:
            return _input_error()
        try:
            payload = request.data
        except (ParseError, UnsupportedMediaType):
            return _input_error()
        if (
            type(payload) is not dict
            or set(payload) != _CONFIRMED_KEYS
            or payload.get("confirmed") is not True
        ):
            return _input_error()
        serializer = OwnerOrderOperationConfirmationSerializer(data=payload)
        if not serializer.is_valid():
            return _input_error()
        return True

    @staticmethod
    def _scope_denied() -> Response:
        return _error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="OWNER_ORDER_NOT_FOUND",
            message=_NOT_FOUND,
        )

    @staticmethod
    def _handle_error(error: Exception, *, operation: str) -> Response:
        """Map known application outcomes to stable public codes and messages."""

        if isinstance(error, (SimulatedTradeAccountScopeUnavailable, ResourceNotFoundError)):
            return _OwnerOrderOperationAPIView._scope_denied()
        if isinstance(error, SimulatedTradeExecutionResultUnknown):
            return _error(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                code=error.code,
                message=_UNKNOWN,
                effects_indeterminate=True,
            )
        if isinstance(error, DatabaseError):
            logger.warning(
                "Owner order operation database failure; operation=%s exception_type=%s",
                operation,
                type(error).__name__,
            )
            return _error(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                code="OWNER_ORDER_OPERATION_UNAVAILABLE",
                message=_UNKNOWN,
                effects_indeterminate=True,
            )
        if isinstance(error, SimulatedTradeExecutionInputError):
            return _error(
                status_code=status.HTTP_400_BAD_REQUEST,
                code=error.code,
                message=_BAD_REQUEST,
            )
        if isinstance(error, InvalidInputError):
            return _error(
                status_code=status.HTTP_400_BAD_REQUEST,
                code=error.code,
                message=_BAD_REQUEST,
            )
        if isinstance(error, SimulatedTradeExecutionBlocked):
            return _error(
                status_code=status.HTTP_409_CONFLICT,
                code=error.code,
                message=_BLOCKED,
            )
        if isinstance(error, DuplicateResourceError):
            return _error(
                status_code=status.HTTP_409_CONFLICT,
                code=error.code,
                message=_BLOCKED,
            )
        if isinstance(error, (BusinessLogicError, MissingConfigError)):
            return _error(
                status_code=status.HTTP_409_CONFLICT,
                code=error.code,
                message=_BLOCKED,
            )
        logger.error(
            "Owner order operation failed; operation=%s exception_type=%s",
            operation,
            type(error).__name__,
        )
        return _error(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="OWNER_ORDER_OPERATION_RESULT_UNKNOWN",
            message=_UNKNOWN,
            effects_indeterminate=True,
        )


class OwnerOrderDecisionApplyAPIView(_OwnerOrderOperationAPIView):
    """Apply or exactly replay the retained MATCHED event for one owner decision."""

    @typed_extend_schema(
        summary="入账本人已保存的撮合决定",
        description=(
            "仅接受本人订单和已保存的撮合决定编号；服务端读取原事件及摘要。"
            "请求不接受价格、数量、来源或幂等键。"
        ),
        parameters=[
            OpenApiParameter("account_id", OpenApiTypes.INT, OpenApiParameter.PATH),
            OpenApiParameter("order_id", OpenApiTypes.INT, OpenApiParameter.PATH),
            OpenApiParameter("decision_id", OpenApiTypes.INT, OpenApiParameter.PATH),
        ],
        request=OwnerOrderOperationConfirmationSerializer,
        responses={
            200: OwnerOrderFillAppliedResponseSerializer,
            400: OwnerOrderOperationErrorResponseSerializer,
            401: OwnerOrderOperationErrorResponseSerializer,
            403: OwnerOrderOperationErrorResponseSerializer,
            404: OwnerOrderOperationErrorResponseSerializer,
            409: OwnerOrderOperationErrorResponseSerializer,
            500: OwnerOrderOperationErrorResponseSerializer,
            503: OwnerOrderOperationErrorResponseSerializer,
        },
    )
    def post(
        self,
        request: Request,
        account_id: int,
        order_id: int,
        decision_id: int,
    ) -> Response:
        """Validate the exact confirmation before composing or calling the use case."""

        if any(
            type(value) is not int or value <= 0 for value in (account_id, order_id, decision_id)
        ):
            return _input_error()
        actor_id = self._actor_id(request)
        if isinstance(actor_id, Response):
            return actor_id
        confirmed = self._confirmed(request)
        if isinstance(confirmed, Response):
            return confirmed
        try:
            operation = build_owner_order_operations_use_case().apply_retained_fill(
                account_id=account_id,
                user_id=actor_id,
                order_id=order_id,
                decision_id=decision_id,
                confirmed=confirmed,
            )
            payload = fill_applied_payload(operation)
        except Exception as error:
            return self._handle_error(error, operation="apply")
        return Response(payload, status=status.HTTP_200_OK)


class OwnerOrderCancelAPIView(_OwnerOrderOperationAPIView):
    """Cancel or replay cancellation of the current owner's remaining hold."""

    @typed_extend_schema(
        summary="撤销本人模拟订单的剩余预留",
        description=(
            "仅释放未成交的本地预留；released_* 是该订单自创建以来的累计值，"
            "不是本次增量，也不撤销已入账成交。"
        ),
        parameters=[
            OpenApiParameter("account_id", OpenApiTypes.INT, OpenApiParameter.PATH),
            OpenApiParameter("order_id", OpenApiTypes.INT, OpenApiParameter.PATH),
        ],
        request=OwnerOrderOperationConfirmationSerializer,
        responses={
            200: OwnerOrderCancelledResponseSerializer,
            400: OwnerOrderOperationErrorResponseSerializer,
            401: OwnerOrderOperationErrorResponseSerializer,
            403: OwnerOrderOperationErrorResponseSerializer,
            404: OwnerOrderOperationErrorResponseSerializer,
            409: OwnerOrderOperationErrorResponseSerializer,
            500: OwnerOrderOperationErrorResponseSerializer,
            503: OwnerOrderOperationErrorResponseSerializer,
        },
    )
    def post(self, request: Request, account_id: int, order_id: int) -> Response:
        """Validate the exact confirmation before composing or calling the use case."""

        if any(type(value) is not int or value <= 0 for value in (account_id, order_id)):
            return _input_error()
        actor_id = self._actor_id(request)
        if isinstance(actor_id, Response):
            return actor_id
        confirmed = self._confirmed(request)
        if isinstance(confirmed, Response):
            return confirmed
        try:
            operation = build_owner_order_operations_use_case().cancel_remaining(
                account_id=account_id,
                user_id=actor_id,
                order_id=order_id,
                confirmed=confirmed,
            )
            payload = order_cancelled_payload(operation)
        except Exception as error:
            return self._handle_error(error, operation="cancel")
        return Response(payload, status=status.HTTP_200_OK)


def _input_error() -> Response:
    """Return the stable public malformed-request response."""

    return _error(
        status_code=status.HTTP_400_BAD_REQUEST,
        code="OWNER_ORDER_INPUT_INVALID",
        message=_BAD_REQUEST,
    )


def _error(
    *,
    status_code: int,
    code: str,
    message: str,
    effects_indeterminate: bool | None = None,
) -> Response:
    """Build a safe error envelope containing no stored keys or exception text."""

    payload: dict[str, object] = {"success": False, "code": code, "message": message}
    if effects_indeterminate is not None:
        payload["effects_indeterminate"] = effects_indeterminate
    return Response(payload, status=status_code)


__all__ = ("OwnerOrderCancelAPIView", "OwnerOrderDecisionApplyAPIView")
