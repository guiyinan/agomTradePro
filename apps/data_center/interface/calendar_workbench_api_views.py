"""Session-authenticated JSON owner endpoints for the calendar workbench."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar, cast

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.parsers import JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import JSONRenderer
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.data_center.application.formal_exchange_calendar_publication import (
    CalendarPublicationTransition,
)
from apps.data_center.calendar_workbench_composition import (
    confirm_calendar_workbench_preview,
    prepare_calendar_workbench_preview,
)
from apps.data_center.calendar_workbench_current_composition import (
    read_calendar_workbench_current,
)
from apps.data_center.calendar_workbench_scope_composition import (
    read_calendar_workbench_scope_context,
)
from apps.data_center.interface.calendar_workbench_api_presenters import (
    present_calendar_workbench_commit,
    present_calendar_workbench_continuation,
    present_calendar_workbench_current,
    present_calendar_workbench_preview,
    present_calendar_workbench_scope,
)
from apps.data_center.interface.calendar_workbench_api_schema import (
    CalendarWorkbenchApiErrorResponseSerializer,
    CalendarWorkbenchConfirmInputSchemaSerializer,
    CalendarWorkbenchConfirmSuccessResponseSerializer,
    CalendarWorkbenchCurrentSuccessResponseSerializer,
    CalendarWorkbenchPrepareSuccessResponseSerializer,
    CalendarWorkbenchScopeSuccessResponseSerializer,
)
from apps.data_center.interface.calendar_workbench_api_serializers import (
    CalendarWorkbenchConfirmInputSerializer,
    CalendarWorkbenchCurrentQuerySerializer,
    CalendarWorkbenchPrepareInputSerializer,
    CalendarWorkbenchScopeQuerySerializer,
)
from core.exceptions import AgomTradeProException

_ViewMethod = TypeVar("_ViewMethod", bound=Callable[..., object])
_typed_extend_schema = cast(
    Callable[..., Callable[[_ViewMethod], _ViewMethod]],
    extend_schema,
)


class _CalendarWorkbenchJsonAPIView(APIView):
    """Require a real authenticated Django session and JSON request/response."""

    authentication_classes = (SessionAuthentication,)
    permission_classes = (IsAuthenticated,)
    parser_classes = (JSONParser,)
    renderer_classes = (JSONRenderer,)


def _error_responses() -> dict[int, OpenApiResponse]:
    """Describe JSON errors reachable from the workbench owner wrappers."""

    return {
        status.HTTP_400_BAD_REQUEST: OpenApiResponse(
            response=CalendarWorkbenchApiErrorResponseSerializer,
            description="Strict JSON fields or opaque token input are invalid.",
        ),
        status.HTTP_401_UNAUTHORIZED: OpenApiResponse(
            response=CalendarWorkbenchApiErrorResponseSerializer,
            description="The request session cannot be bound to a database user.",
        ),
        status.HTTP_403_FORBIDDEN: OpenApiResponse(
            response=CalendarWorkbenchApiErrorResponseSerializer,
            description="The authenticated session lacks current calendar publish permission.",
        ),
        status.HTTP_405_METHOD_NOT_ALLOWED: OpenApiResponse(
            response=CalendarWorkbenchApiErrorResponseSerializer,
            description="Only the documented JSON method is supported.",
        ),
        status.HTTP_406_NOT_ACCEPTABLE: OpenApiResponse(
            response=CalendarWorkbenchApiErrorResponseSerializer,
            description="Only JSON responses are available.",
        ),
        status.HTTP_409_CONFLICT: OpenApiResponse(
            response=CalendarWorkbenchApiErrorResponseSerializer,
            description="The source-age window or current publication state changed.",
        ),
        status.HTTP_413_REQUEST_ENTITY_TOO_LARGE: OpenApiResponse(
            response=CalendarWorkbenchApiErrorResponseSerializer,
            description="The opaque continuation exceeds the supported size.",
        ),
        status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: OpenApiResponse(
            response=CalendarWorkbenchApiErrorResponseSerializer,
            description="Write requests accept application/json only.",
        ),
        status.HTTP_422_UNPROCESSABLE_ENTITY: OpenApiResponse(
            response=CalendarWorkbenchApiErrorResponseSerializer,
            description="A calendar publication invariant blocked the operation.",
        ),
        status.HTTP_503_SERVICE_UNAVAILABLE: OpenApiResponse(
            response=CalendarWorkbenchApiErrorResponseSerializer,
            description="The configured source or encryption key is unavailable.",
        ),
    }


def _read_error_responses() -> dict[int, OpenApiResponse]:
    """Describe authenticated read errors without implying publisher access."""

    return {
        status.HTTP_400_BAD_REQUEST: OpenApiResponse(
            response=CalendarWorkbenchApiErrorResponseSerializer,
            description="The exchange query is invalid or contains unsupported fields.",
        ),
        status.HTTP_401_UNAUTHORIZED: OpenApiResponse(
            response=CalendarWorkbenchApiErrorResponseSerializer,
            description="A valid authenticated session is required.",
        ),
        status.HTTP_403_FORBIDDEN: OpenApiResponse(
            response=CalendarWorkbenchApiErrorResponseSerializer,
            description="The authenticated session cannot access this read.",
        ),
        status.HTTP_405_METHOD_NOT_ALLOWED: OpenApiResponse(
            response=CalendarWorkbenchApiErrorResponseSerializer,
            description="Only GET is supported.",
        ),
        status.HTTP_406_NOT_ACCEPTABLE: OpenApiResponse(
            response=CalendarWorkbenchApiErrorResponseSerializer,
            description="Only JSON responses are available.",
        ),
        status.HTTP_409_CONFLICT: OpenApiResponse(
            response=CalendarWorkbenchApiErrorResponseSerializer,
            description="The current publication or its source-age window changed.",
        ),
        status.HTTP_422_UNPROCESSABLE_ENTITY: OpenApiResponse(
            response=CalendarWorkbenchApiErrorResponseSerializer,
            description="The current publication failed a typed integrity check.",
        ),
        status.HTTP_503_SERVICE_UNAVAILABLE: OpenApiResponse(
            response=CalendarWorkbenchApiErrorResponseSerializer,
            description="The selected configuration or current evidence is unavailable.",
        ),
    }


def _operation_error_response(error: AgomTradeProException) -> Response:
    """Map recognized owner failures to bounded, actionable Chinese JSON."""

    code = error.code
    response_status: int
    if code in {
        "CALENDAR_PREVIEW_TOKEN_EXPIRED",
        "CALENDAR_PUBLICATION_RESPONSE_EXPIRED",
        "CALENDAR_FORMAL_TTL_EXPIRED",
    }:
        response_status = status.HTTP_409_CONFLICT
        message = "预览已过期，请重新准备日历预览后再确认。"
    elif code in {
        "CALENDAR_PUBLICATION_POINTER_CHANGED",
        "CALENDAR_PUBLICATION_PREVIEW_STALE",
        "CALENDAR_PUBLICATION_PREVIEW_HASH_MISMATCH",
    }:
        response_status = status.HTTP_409_CONFLICT
        message = "发布条件已变化，请重新准备预览并核对后再确认。"
    elif error.status_code == status.HTTP_403_FORBIDDEN:
        response_status = status.HTTP_403_FORBIDDEN
        message = "当前登录账户没有日历发布权限，请联系管理员配置权限。"
    elif error.status_code == status.HTTP_401_UNAUTHORIZED:
        response_status = status.HTTP_401_UNAUTHORIZED
        message = "无法验证当前登录会话，请重新登录后重试。"
    elif error.status_code == status.HTTP_503_SERVICE_UNAVAILABLE:
        response_status = status.HTTP_503_SERVICE_UNAVAILABLE
        message = "日历来源或加密配置暂不可用，请稍后重试或联系管理员检查配置。"
    elif error.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE:
        response_status = status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
        message = "确认信息超过允许大小，请重新准备预览。"
    elif error.status_code in (status.HTTP_400_BAD_REQUEST, status.HTTP_422_UNPROCESSABLE_ENTITY):
        response_status = error.status_code
        message = "日历操作未能通过校验，请检查输入或重新准备预览。"
    elif error.status_code == status.HTTP_409_CONFLICT:
        response_status = status.HTTP_409_CONFLICT
        message = "预览状态已变化，请重新准备日历预览后重试。"
    else:
        response_status = status.HTTP_503_SERVICE_UNAVAILABLE
        message = "日历操作暂不可用，请稍后重试或联系管理员。"
    return Response({"error": message, "code": code}, status=response_status)


def _read_operation_error_response(error: AgomTradeProException) -> Response:
    """Map authenticated read failures without suggesting publisher authority."""

    code = error.code
    response_status: int
    if error.status_code == status.HTTP_400_BAD_REQUEST:
        response_status = status.HTTP_400_BAD_REQUEST
        message = "交易所参数无效，请检查后重新查询。"
    elif error.status_code == status.HTTP_401_UNAUTHORIZED:
        response_status = status.HTTP_401_UNAUTHORIZED
        message = "无法验证当前登录会话，请重新登录后重试。"
    elif error.status_code == status.HTTP_403_FORBIDDEN:
        response_status = status.HTTP_403_FORBIDDEN
        message = "当前登录账户无权读取该日历信息，请联系管理员检查读取权限。"
    elif error.status_code == status.HTTP_409_CONFLICT:
        response_status = status.HTTP_409_CONFLICT
        message = "当前日历状态或来源有效期已变化，请重新查询。"
    elif error.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY:
        response_status = status.HTTP_422_UNPROCESSABLE_ENTITY
        message = "当前发布日历未通过完整性检查，已阻断读取。"
    else:
        response_status = status.HTTP_503_SERVICE_UNAVAILABLE
        message = "当前配置或发布证据暂不可用，请联系管理员检查或稍后重试。"
    return Response({"error": message, "code": code}, status=response_status)


class CalendarWorkbenchPrepareView(_CalendarWorkbenchJsonAPIView):
    """Capture and preview one explicit exchange-calendar range for confirmation."""

    @_typed_extend_schema(
        request=CalendarWorkbenchPrepareInputSerializer,
        responses={
            status.HTTP_201_CREATED: CalendarWorkbenchPrepareSuccessResponseSerializer,
            **_error_responses(),
        },
        operation_id="prepareCalendarPublicationWorkbench",
        tags=("Data Center Calendar Workbench",),
    )
    def post(self, request: Request) -> Response:
        """Return visible reference status and a separate hidden TUI continuation."""

        intent = CalendarWorkbenchPrepareInputSerializer(data=request.data).to_intent()
        try:
            result = prepare_calendar_workbench_preview(request, intent)
        except AgomTradeProException as error:
            return _operation_error_response(error)
        return Response(
            {
                "outcome": "success",
                "success": True,
                "data": present_calendar_workbench_preview(result),
                "continuation": present_calendar_workbench_continuation(result),
            },
            status=status.HTTP_201_CREATED,
        )


class CalendarWorkbenchConfirmView(_CalendarWorkbenchJsonAPIView):
    """Confirm one hidden preview token through the existing permission owner."""

    @_typed_extend_schema(
        request=CalendarWorkbenchConfirmInputSchemaSerializer,
        responses={
            status.HTTP_200_OK: CalendarWorkbenchConfirmSuccessResponseSerializer,
            status.HTTP_201_CREATED: CalendarWorkbenchConfirmSuccessResponseSerializer,
            **_error_responses(),
        },
        operation_id="confirmCalendarPublicationWorkbench",
        tags=("Data Center Calendar Workbench",),
    )
    def post(self, request: Request) -> Response:
        """Revalidate the hidden token under current session and publisher authority."""

        token = CalendarWorkbenchConfirmInputSerializer(data=request.data).to_token()
        try:
            result = confirm_calendar_workbench_preview(request, token)
        except AgomTradeProException as error:
            return _operation_error_response(error)
        response_status = (
            status.HTTP_201_CREATED
            if result.transition is CalendarPublicationTransition.FIRST_PUBLISH
            else status.HTTP_200_OK
        )
        return Response(
            {
                "outcome": "success",
                "success": True,
                "data": present_calendar_workbench_commit(result),
            },
            status=response_status,
        )


class CalendarWorkbenchScopeView(_CalendarWorkbenchJsonAPIView):
    """Read global calendar capture metadata without selecting an exchange."""

    @_typed_extend_schema(
        parameters=[],
        responses={
            status.HTTP_200_OK: CalendarWorkbenchScopeSuccessResponseSerializer,
            **_read_error_responses(),
        },
        operation_id="readCalendarWorkbenchScope",
        tags=("Data Center Calendar Workbench",),
    )
    def get(self, request: Request) -> Response:
        """Return metadata selection status without reading credentials or current state."""

        CalendarWorkbenchScopeQuerySerializer(data=request.query_params).to_scope_query()
        del request
        try:
            result = read_calendar_workbench_scope_context()
        except AgomTradeProException as error:
            return _read_operation_error_response(error)
        return Response(
            {
                "outcome": "success",
                "success": True,
                "data": present_calendar_workbench_scope(result),
            },
            status=status.HTTP_200_OK,
        )


class CalendarWorkbenchCurrentView(_CalendarWorkbenchJsonAPIView):
    """Read the current reference calendar for the selected capture dataset."""

    @_typed_extend_schema(
        parameters=[CalendarWorkbenchCurrentQuerySerializer],
        responses={
            status.HTTP_200_OK: CalendarWorkbenchCurrentSuccessResponseSerializer,
            **_read_error_responses(),
        },
        operation_id="readCalendarWorkbenchCurrent",
        tags=("Data Center Calendar Workbench",),
    )
    def get(self, request: Request) -> Response:
        """Accept one exchange while keeping dataset and server cutoff server-owned."""

        exchange = CalendarWorkbenchCurrentQuerySerializer(data=request.query_params).to_exchange()
        try:
            result = read_calendar_workbench_current(exchange)
        except AgomTradeProException as error:
            return _read_operation_error_response(error)
        return Response(
            {
                "outcome": "success",
                "success": True,
                "data": present_calendar_workbench_current(result),
            },
            status=status.HTTP_200_OK,
        )


__all__ = [
    "CalendarWorkbenchConfirmView",
    "CalendarWorkbenchCurrentView",
    "CalendarWorkbenchPrepareView",
    "CalendarWorkbenchScopeView",
]
