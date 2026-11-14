"""Session-bound HTTP adapters for the owner simulated corporate-action workflow."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from typing import Any, cast

from django.db import DatabaseError
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.authentication import SessionAuthentication
from rest_framework.parsers import JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import JSONRenderer
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.simulated_trading.corporate_action_owner_workflow_composition import (
    confirm_owner_corporate_action_workflow,
    prepare_owner_corporate_action_workflow,
    read_owner_corporate_action_events,
    read_owner_corporate_action_workflow,
    refresh_owner_corporate_action_workflow,
)
from core.exceptions import (
    AgomTradeProException,
    AuthenticationError,
    AuthorizationError,
    BusinessLogicError,
    ExternalServiceError,
)

from .corporate_action_workflow_serializers import (
    MAX_CONTINUATION_TOKEN_LENGTH,
    OwnerCorporateActionWorkflowConfirmRequestSerializer,
    OwnerCorporateActionWorkflowPrepareRequestSerializer,
    OwnerCorporateActionWorkflowRefreshRequestSerializer,
    OwnerCorporateActionWorkflowResponseSerializer,
)
from .sdk_contract_views import typed_extend_schema

_CONFIRM_ACTION_KEY = "simulated-trading.corporate-action-workflow-confirm"


def _contains_text(value: object, secret: str) -> bool:
    """Detect accidental duplication of a continuation secret in public fields."""
    if type(value) is str:
        return secret in value
    if isinstance(value, Mapping):
        return any(_contains_text(item, secret) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return any(_contains_text(item, secret) for item in value)
    return False


def _valid_continuation(
    value: object,
    *,
    account_id: int,
) -> dict[str, object] | None:
    """Validate the exact target, path account, opaque token, and UTC expiry envelope."""
    if not isinstance(value, Mapping) or set(value) != {"action_key", "input", "expires_at"}:
        return None
    if value.get("action_key") != _CONFIRM_ACTION_KEY:
        return None
    raw_input = value.get("input")
    if not isinstance(raw_input, Mapping) or set(raw_input) != {
        "account_id",
        "continuation_token",
    }:
        return None
    account_value = raw_input.get("account_id")
    token = raw_input.get("continuation_token")
    expires_at_text = value.get("expires_at")
    if (
        type(account_value) is not str
        or account_value != str(account_id)
        or type(token) is not str
        or not token
        or len(token) > MAX_CONTINUATION_TOKEN_LENGTH
        or type(expires_at_text) is not str
        or not expires_at_text
    ):
        return None
    normalized_expiry = (
        expires_at_text[:-1] + "+00:00" if expires_at_text.endswith("Z") else expires_at_text
    )
    try:
        expires_at = datetime.fromisoformat(normalized_expiry)
    except ValueError:
        return None
    if (
        expires_at.tzinfo is None
        or expires_at.utcoffset() != UTC.utcoffset(expires_at)
        or expires_at.astimezone(UTC) <= timezone.now().astimezone(UTC)
    ):
        return None
    return {
        "action_key": _CONFIRM_ACTION_KEY,
        "input": {"account_id": str(account_id), "continuation_token": token},
        "expires_at": expires_at_text,
    }


def _response_payload(
    value: object,
    *,
    account_id: int,
    allow_continuation: bool,
) -> dict[str, Any] | None:
    """Return only contract fields and fail closed on malformed service output."""
    if not isinstance(value, Mapping) or type(value.get("account_id")) is not int:
        return None
    if value.get("account_id") != account_id:
        return None
    if value.get("must_not_use_for_decision") is not True:
        return None
    for key in ("outcome", "summary", "freshness_status", "reliability_status"):
        if type(value.get(key)) is not str:
            return None
    for key in ("blocking_reason", "source_observed_at", "checked_at"):
        if value.get(key) is not None and type(value.get(key)) is not str:
            return None
    for key in (
        "book_cash",
        "spendable_cash",
        "net_asset_value",
        "dividend_receivable",
        "share_receivable",
        "tax_payable",
    ):
        if value.get(key) is not None and type(value.get(key)) is not str:
            return None
    if type(value.get("events")) is not list or type(value.get("audit_receipts")) is not list:
        return None
    event_rows: list[dict[str, object]] = []
    for raw_event in cast(list[object], value["events"]):
        if not isinstance(raw_event, Mapping):
            return None
        raw_event_account_id = raw_event.get("account_id")
        if raw_event_account_id is not None and (
            type(raw_event_account_id) is not int or raw_event_account_id != account_id
        ):
            return None
        event = dict(cast(Mapping[str, object], raw_event))
        event["account_id"] = account_id
        event_rows.append(event)
    raw_continuation = value.get("continuation")
    continuation: dict[str, object] | None = None
    if raw_continuation is not None:
        if not allow_continuation or value.get("outcome") != "success":
            return None
        continuation = _valid_continuation(raw_continuation, account_id=account_id)
        if continuation is None:
            return None
        token = cast(str, cast(Mapping[str, object], continuation["input"])["continuation_token"])
        if any(_contains_text(item, token) for key, item in value.items() if key != "continuation"):
            return None
    elif allow_continuation and value.get("outcome") == "success":
        return None
    normalized = dict(value)
    normalized["events"] = event_rows
    normalized.pop("continuation", None)
    if continuation is not None:
        normalized["continuation"] = continuation
    serializer = OwnerCorporateActionWorkflowResponseSerializer(data=normalized)
    try:
        serializer.is_valid(raise_exception=True)
    except serializers.ValidationError:
        return None
    return cast(dict[str, Any], serializer.validated_data)


def _safe_failure(
    *, outcome: str, message: str, account_id: int | None = None
) -> dict[str, object]:
    """Build a bounded non-decision failure without exposing service details."""
    payload: dict[str, object] = {
        "outcome": outcome,
        "summary": message,
        "blocking_reason": message,
        "must_not_use_for_decision": True,
    }
    if account_id is not None:
        payload["account_id"] = account_id
    return payload


def _cancelled_payload(account_id: int) -> dict[str, object]:
    """Return an explicit cancellation receipt without calling a write service."""
    return {
        "account_id": account_id,
        "outcome": "noop",
        "summary": "已取消，本次没有办理公司行为或刷新账户证据。",
        "blocking_reason": None,
        "source_observed_at": None,
        "checked_at": None,
        "freshness_status": "not_checked",
        "reliability_status": "not_checked",
        "must_not_use_for_decision": True,
        "book_cash": None,
        "spendable_cash": None,
        "net_asset_value": None,
        "dividend_receivable": None,
        "share_receivable": None,
        "tax_payable": None,
        "events": [],
        "audit_receipts": [],
    }


class _OwnerCorporateActionWorkflowAPIView(APIView):
    """Keep the workflow behind browser SessionAuthentication and CSRF protection."""

    authentication_classes = (SessionAuthentication,)
    permission_classes = (IsAuthenticated,)
    parser_classes = (JSONParser,)
    renderer_classes = (JSONRenderer,)

    def handle_exception(self, exc: Exception) -> Response:
        """Map owner, business, and infrastructure failures without private details."""
        if isinstance(exc, AuthenticationError):
            return Response(
                _safe_failure(outcome="blocked", message="请登录后重新读取本人模拟账户。"),
                status=status.HTTP_401_UNAUTHORIZED,
            )
        if isinstance(exc, AuthorizationError):
            return Response(
                _safe_failure(outcome="blocked", message="当前会话无权操作该模拟账户。"),
                status=status.HTTP_403_FORBIDDEN,
            )
        if isinstance(exc, BusinessLogicError):
            return Response(
                _safe_failure(outcome="blocked", message="本次操作被当前业务条件阻止。"),
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        if isinstance(exc, (ExternalServiceError, DatabaseError)):
            return Response(
                _safe_failure(outcome="blocked", message="公司行为服务暂不可用，请稍后重试。"),
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        if isinstance(exc, AgomTradeProException):
            response_status = int(exc.status_code)
            if response_status not in {400, 404, 409, 422, 503}:
                response_status = status.HTTP_503_SERVICE_UNAVAILABLE
            return Response(
                _safe_failure(
                    outcome="blocked",
                    message="公司行为资料已变化或暂不可用，请重新读取。",
                ),
                status=response_status,
            )
        return super().handle_exception(exc)

    @staticmethod
    def _reject_query_scope(request: Request) -> Response | None:
        """Reject uncontracted query parameters before owner use cases run."""
        if request.query_params:
            return Response({"detail": "公司行为请求不接受额外查询参数。"}, status=400)
        return None

    @staticmethod
    def _account_id_matches(data: Mapping[str, object], account_id: int) -> bool:
        """Bind any duplicated body account ID to the authenticated URL scope."""
        raw = data.get("account_id")
        return raw is None or (type(raw) is int and raw == account_id)

    @staticmethod
    def _public_response(
        payload: object,
        *,
        account_id: int,
        allow_continuation: bool = False,
    ) -> Response:
        """Return the allowlisted owner result or a generic blocked response."""
        safe_payload = _response_payload(
            payload,
            account_id=account_id,
            allow_continuation=allow_continuation,
        )
        if safe_payload is None:
            return Response(
                _safe_failure(
                    outcome="blocked",
                    message="公司行为结果不可用，请重新读取账户与事件资料。",
                    account_id=account_id,
                ),
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response(safe_payload, status=status.HTTP_200_OK)


class OwnerCorporateActionWorkflowReadAPIView(_OwnerCorporateActionWorkflowAPIView):
    """Read one account's owner-scoped cash, share, tax, event, and audit summary."""

    http_method_names = ("get", "options")

    @typed_extend_schema(responses={200: OwnerCorporateActionWorkflowResponseSerializer})
    def get(self, request: Request, account_id: int) -> Response:
        """Read the current workflow without accepting client-provided account facts."""
        query_error = self._reject_query_scope(request)
        if query_error is not None:
            return query_error
        return self._public_response(
            read_owner_corporate_action_workflow(request, account_id=account_id),
            account_id=account_id,
        )


class OwnerCorporateActionWorkflowEventsAPIView(_OwnerCorporateActionWorkflowAPIView):
    """Read retained event choices without reconstructing balances or authorizing writes."""

    http_method_names = ("get", "options")

    @typed_extend_schema(responses={200: OwnerCorporateActionWorkflowResponseSerializer})
    def get(self, request: Request, account_id: int) -> Response:
        """Bind event discovery to the real Session owner and exact path account."""
        query_error = self._reject_query_scope(request)
        if query_error is not None:
            return query_error
        return self._public_response(
            read_owner_corporate_action_events(request, account_id=account_id),
            account_id=account_id,
        )


class OwnerCorporateActionWorkflowPrepareAPIView(_OwnerCorporateActionWorkflowAPIView):
    """Prepare one exact server-verified event operation for explicit confirmation."""

    http_method_names = ("post", "options")

    @typed_extend_schema(
        request=OwnerCorporateActionWorkflowPrepareRequestSerializer,
        responses={200: OwnerCorporateActionWorkflowResponseSerializer},
    )
    def post(self, request: Request, account_id: int) -> Response:
        """Prepare a signed continuation using only an event ID, action, and date."""
        query_error = self._reject_query_scope(request)
        if query_error is not None:
            return query_error
        serializer = OwnerCorporateActionWorkflowPrepareRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = cast(Mapping[str, object], serializer.validated_data)
        if not self._account_id_matches(values, account_id):
            return Response({"detail": "请求账户与路径账户不一致。"}, status=400)
        settlement_date = cast(date | None, values.get("settlement_date"))
        result = prepare_owner_corporate_action_workflow(
            request,
            account_id=account_id,
            event_id=cast(str, values["event_id"]),
            action=cast(str, values["action"]),
            settlement_date=settlement_date,
            correction_mode=cast(str, values["correction_mode"]),
        )
        return self._public_response(result, account_id=account_id, allow_continuation=True)


class OwnerCorporateActionWorkflowConfirmAPIView(_OwnerCorporateActionWorkflowAPIView):
    """Confirm only an unchanged server-prepared operation through a real session."""

    http_method_names = ("post", "options")

    @typed_extend_schema(
        request=OwnerCorporateActionWorkflowConfirmRequestSerializer,
        responses={200: OwnerCorporateActionWorkflowResponseSerializer},
    )
    def post(self, request: Request, account_id: int) -> Response:
        """Commit only literal-true confirmation for the exact opaque continuation."""
        query_error = self._reject_query_scope(request)
        if query_error is not None:
            return query_error
        serializer = OwnerCorporateActionWorkflowConfirmRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = cast(Mapping[str, object], serializer.validated_data)
        if not self._account_id_matches(values, account_id):
            return Response({"detail": "请求账户与路径账户不一致。"}, status=400)
        if values.get("confirmed") is not True:
            return self._public_response(_cancelled_payload(account_id), account_id=account_id)
        result = confirm_owner_corporate_action_workflow(
            request,
            account_id=account_id,
            continuation_token=cast(str, values["continuation_token"]),
            confirmed=True,
        )
        return self._public_response(result, account_id=account_id)


class OwnerCorporateActionWorkflowRefreshAPIView(_OwnerCorporateActionWorkflowAPIView):
    """Explicitly refresh authenticated owner evidence without granting authority."""

    http_method_names = ("post", "options")

    @typed_extend_schema(
        request=OwnerCorporateActionWorkflowRefreshRequestSerializer,
        responses={200: OwnerCorporateActionWorkflowResponseSerializer},
    )
    def post(self, request: Request, account_id: int) -> Response:
        """Refresh only after explicit true and leave financial entries untouched."""
        query_error = self._reject_query_scope(request)
        if query_error is not None:
            return query_error
        serializer = OwnerCorporateActionWorkflowRefreshRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = cast(Mapping[str, object], serializer.validated_data)
        if not self._account_id_matches(values, account_id):
            return Response({"detail": "请求账户与路径账户不一致。"}, status=400)
        if values.get("confirmed") is not True:
            return self._public_response(_cancelled_payload(account_id), account_id=account_id)
        result = refresh_owner_corporate_action_workflow(
            request,
            account_id=account_id,
            confirmed=True,
        )
        return self._public_response(result, account_id=account_id)


__all__: tuple[str, ...] = (
    "OwnerCorporateActionWorkflowConfirmAPIView",
    "OwnerCorporateActionWorkflowEventsAPIView",
    "OwnerCorporateActionWorkflowPrepareAPIView",
    "OwnerCorporateActionWorkflowReadAPIView",
    "OwnerCorporateActionWorkflowRefreshAPIView",
)
