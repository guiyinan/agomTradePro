"""Explicit session-authenticated matching of an owner's existing simulated order."""

from __future__ import annotations

from datetime import date
from typing import cast

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter
from rest_framework import status
from rest_framework.exceptions import ParseError, UnsupportedMediaType
from rest_framework.parsers import JSONParser
from rest_framework.request import Request
from rest_framework.response import Response

from apps.simulated_trading.owner_order_matching_composition import (
    build_owner_order_matching_use_case,
)

from .owner_order_matching_response import (
    OwnerOrderMatchRequestSerializer,
    OwnerOrderMatchResponseSerializer,
    order_matched_payload,
)
from .owner_order_operation_response import OwnerOrderOperationErrorResponseSerializer
from .owner_order_operation_views import _input_error, _OwnerOrderOperationAPIView
from .sdk_contract_views import typed_extend_schema


class OwnerOrderMatchAPIView(_OwnerOrderOperationAPIView):
    """Save or replay one daily matching decision without applying its fill."""

    @typed_extend_schema(
        summary="撮合本人已有模拟订单",
        description="选择交易日并明确确认；仅保存撮合决定，入账仍需单独确认原决定。",
        parameters=[
            OpenApiParameter("account_id", OpenApiTypes.INT, OpenApiParameter.PATH),
            OpenApiParameter("order_id", OpenApiTypes.INT, OpenApiParameter.PATH),
        ],
        request=OwnerOrderMatchRequestSerializer,
        responses={
            200: OwnerOrderMatchResponseSerializer,
            400: OwnerOrderOperationErrorResponseSerializer,
            401: OwnerOrderOperationErrorResponseSerializer,
            403: OwnerOrderOperationErrorResponseSerializer,
            404: OwnerOrderOperationErrorResponseSerializer,
            409: OwnerOrderOperationErrorResponseSerializer,
            415: OpenApiTypes.OBJECT,
            503: OwnerOrderOperationErrorResponseSerializer,
        },
    )
    def post(self, request: Request, account_id: int, order_id: int) -> Response:
        """Accept exactly one day and literal confirmation within the current session."""
        if any(type(value) is not int or value <= 0 for value in (account_id, order_id)):
            return _input_error()
        actor_id = self._actor_id(request)
        if isinstance(actor_id, Response):
            return actor_id
        session_date = self._selected_session(request)
        if isinstance(session_date, Response):
            return session_date
        try:
            operation = build_owner_order_matching_use_case().execute(
                account_id=account_id,
                user_id=actor_id,
                order_id=order_id,
                session_date=session_date,
                confirmed=True,
            )
            payload = order_matched_payload(operation)
        except Exception as error:
            return self._handle_error(error, operation="match")
        return Response(payload, status=status.HTTP_200_OK)

    @staticmethod
    def _selected_session(request: Request) -> date | Response:
        """Reject query parameters, source claims, coercible booleans and non-ISO dates."""
        if request.content_type != JSONParser.media_type or request.query_params:
            return _input_error()
        try:
            payload = request.data
        except (ParseError, UnsupportedMediaType):
            return _input_error()
        if (
            type(payload) is not dict
            or set(payload) != {"session_date", "confirmed"}
            or payload.get("confirmed") is not True
            or type(payload.get("session_date")) is not str
        ):
            return _input_error()
        raw_date = cast(str, payload["session_date"])
        try:
            selected = date.fromisoformat(raw_date)
        except ValueError:
            return _input_error()
        if selected.isoformat() != raw_date:
            return _input_error()
        return selected
