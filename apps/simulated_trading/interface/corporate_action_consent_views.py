"""Session-only preparation, explicit consent and withdrawal for simulated dividends."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Literal, cast

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

from apps.account.application.simulated_corporate_action_write_grant import (
    SimulatedCorporateActionWriteGrantConflict,
    SimulatedCorporateActionWriteGrantUnavailable,
)
from apps.account.simulated_corporate_action_consent_composition import (
    read_authenticated_withdrawal_session_deadline,
)
from apps.simulated_trading.application.simulated_account_row_source_v2 import (
    SimulatedAccountRowSourceV2Conflict,
    SimulatedAccountRowSourceV2Corruption,
    SimulatedAccountRowSourceV2Unavailable,
)
from apps.simulated_trading.corporate_action_consent_composition import (
    SimulatedActionConsentPayload,
    confirm_owner_simulated_action_consent,
    prepare_owner_simulated_action_consent,
    prepare_owner_simulated_action_withdrawal,
    withdraw_owner_simulated_action_consent,
)
from core.exceptions import AuthenticationError, AuthorizationError, ExternalServiceError

from .sdk_contract_views import typed_extend_schema


class _ConsentInputSerializer(serializers.Serializer[dict[str, Any]]):
    """Preserve exact explicit JSON confirmation and reject extra scope selectors."""

    confirmed = serializers.BooleanField(required=True)

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        """Validate primitive JSON types before DRF's normal field validation."""
        if not isinstance(data, Mapping) or set(data) - set(self.fields):
            raise serializers.ValidationError(
                {"non_field_errors": ["授权请求包含未知字段或不是对象。"]}
            )
        if data.get("confirmed") is not True:
            raise serializers.ValidationError({"confirmed": "请明确确认本次操作。"})
        for name, field in self.fields.items():
            if (
                isinstance(field, serializers.CharField)
                and name in data
                and type(data[name]) is not str
            ):
                raise serializers.ValidationError({name: "必须为字符串。"})
        return cast(dict[str, Any], super().to_internal_value(data))


class SimulatedActionConsentRequestSerializer(_ConsentInputSerializer):
    """Confirm only the server-prepared consent terms."""

    consent_token = serializers.CharField(max_length=16384, trim_whitespace=False)


class SimulatedActionWithdrawalRequestSerializer(_ConsentInputSerializer):
    """Withdraw only the server-prepared exact historical locator."""

    withdrawal_token = serializers.CharField(max_length=16384, trim_whitespace=False)


class SimulatedActionConsentResponseSerializer(serializers.Serializer[dict[str, object]]):
    """Publish preparation status and original source clocks separately from consent validity."""

    account_id = serializers.IntegerField()
    outcome = serializers.CharField()
    consent_status = serializers.CharField()
    summary = serializers.CharField()
    blocking_reason = serializers.CharField(allow_null=True)
    source_observed_at = serializers.CharField(allow_null=True)
    source_valid_until = serializers.CharField(allow_null=True)
    consent_valid_until = serializers.CharField(allow_null=True)
    consent_token = serializers.CharField(allow_null=True)
    withdrawal_token = serializers.CharField(allow_null=True)
    grant_id = serializers.CharField(allow_null=True)
    grant_version = serializers.CharField(allow_null=True)
    grant_content_hash = serializers.CharField(allow_null=True)
    must_not_execute = serializers.BooleanField()


class SimulatedActionConsentPreparationResponseSerializer(SimulatedActionConsentResponseSerializer):
    """Expose sealed terms only inside the existing protected TUI continuation envelope."""

    continuation = serializers.JSONField(required=False)


def _public_receipt(payload: SimulatedActionConsentPayload) -> dict[str, object]:
    """Keep opaque preparation locators out of ordinary mutation receipts."""
    result: dict[str, object] = dict(payload)
    result["consent_token"] = None
    result["withdrawal_token"] = None
    return result


def _preparation_response(
    payload: SimulatedActionConsentPayload,
    *,
    purpose: Literal["consent", "withdrawal"],
    withdrawal_session_deadline: datetime | None = None,
) -> Response:
    """Format one exact protected continuation without duplicating its token in display data."""
    token = payload["consent_token"] if purpose == "consent" else payload["withdrawal_token"]
    result = _public_receipt(payload)
    if token is None and result["outcome"] == "success":
        result["outcome"] = "noop"
    if token is not None and payload["outcome"] == "success":
        expires = payload["consent_valid_until"]
        if purpose == "withdrawal":
            if withdrawal_session_deadline is None:
                raise SimulatedCorporateActionWriteGrantUnavailable(
                    "withdrawal session expiry is unavailable"
                )
            expires_at = withdrawal_session_deadline
        else:
            if expires is None:
                raise SimulatedCorporateActionWriteGrantUnavailable(
                    "preparation expiry is unavailable"
                )
            expires_at = datetime.fromisoformat(expires)
        if (
            expires_at.tzinfo is None
            or expires_at.utcoffset() is None
            or expires_at <= timezone.now()
        ):
            raise SimulatedCorporateActionWriteGrantUnavailable("preparation expiry is invalid")
        field = "consent_token" if purpose == "consent" else "withdrawal_token"
        target = "confirm" if purpose == "consent" else "withdraw"
        result["continuation"] = {
            "action_key": f"simulated-trading.corporate-action-consent-{target}",
            "input": {"account_id": str(payload["account_id"]), field: token},
            "expires_at": expires_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        }
    return Response(result, status=status.HTTP_200_OK)


class _OwnerConsentAPIView(APIView):
    """Keep every consent surface on the browser Session/CSRF contract."""

    authentication_classes = (SessionAuthentication,)
    permission_classes = (IsAuthenticated,)
    parser_classes = (JSONParser,)
    renderer_classes = (JSONRenderer,)

    def handle_exception(self, exc: Exception) -> Response:
        """Map known owner/consent failures to bounded JSON responses."""
        if isinstance(exc, (AuthenticationError, AuthorizationError)):
            return Response({"detail": "当前会话无权操作该模拟账户授权。"}, status=403)
        if isinstance(exc, SimulatedCorporateActionWriteGrantConflict):
            return Response({"detail": "授权记录已变化，请重新读取核对。"}, status=409)
        if isinstance(
            exc,
            (
                SimulatedCorporateActionWriteGrantUnavailable,
                SimulatedAccountRowSourceV2Conflict,
                SimulatedAccountRowSourceV2Corruption,
                SimulatedAccountRowSourceV2Unavailable,
            ),
        ):
            return Response({"detail": "授权资料已变化或不可用，请重新读取核对。"}, status=422)
        if isinstance(exc, (ExternalServiceError, DatabaseError)):
            return Response({"detail": "授权服务暂时不可用，请稍后重试。"}, status=503)
        return super().handle_exception(exc)


class SimulatedActionConsentAPIView(_OwnerConsentAPIView):
    """Read displayed consent terms and explicitly save a finite owner consent."""

    http_method_names = ("get", "post", "options")

    @typed_extend_schema(responses={200: SimulatedActionConsentResponseSerializer})
    def get(self, request: Request, account_id: int) -> Response:
        """Read owner terms without creating grants or financial entries."""
        if request.query_params:
            return Response({"detail": "授权读取不接受额外查询参数。"}, status=400)
        result = prepare_owner_simulated_action_consent(request, account_id=account_id)
        return Response(result, status=status.HTTP_200_OK)

    @typed_extend_schema(
        request=SimulatedActionConsentRequestSerializer,
        responses={200: SimulatedActionConsentResponseSerializer},
    )
    def post(self, request: Request, account_id: int) -> Response:
        """Confirm only the unchanged server-prepared terms through real credentials."""
        if request.query_params:
            return Response({"detail": "授权操作不接受额外查询参数。"}, status=400)
        serializer = SimulatedActionConsentRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = confirm_owner_simulated_action_consent(
            request,
            account_id=account_id,
            consent_token=cast(str, serializer.validated_data["consent_token"]),
            confirmed=cast(bool, serializer.validated_data["confirmed"]),
        )
        return Response(_public_receipt(result), status=status.HTTP_200_OK)


class SimulatedActionConsentWithdrawalAPIView(_OwnerConsentAPIView):
    """Explicitly revoke an original consent without requiring its old policy to remain live."""

    http_method_names = ("post", "options")

    @typed_extend_schema(
        request=SimulatedActionWithdrawalRequestSerializer,
        responses={200: SimulatedActionConsentResponseSerializer},
    )
    def post(self, request: Request, account_id: int) -> Response:
        """Withdraw only the prepared exact owner target after explicit confirmation."""
        if request.query_params:
            return Response({"detail": "撤销操作不接受额外查询参数。"}, status=400)
        serializer = SimulatedActionWithdrawalRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = withdraw_owner_simulated_action_consent(
            request,
            account_id=account_id,
            withdrawal_token=cast(str, serializer.validated_data["withdrawal_token"]),
            confirmed=cast(bool, serializer.validated_data["confirmed"]),
        )
        return Response(_public_receipt(result), status=status.HTTP_200_OK)


class SimulatedActionConsentPreparationAPIView(_OwnerConsentAPIView):
    """Prepare a protected confirmation using the existing authenticated POST-read contract."""

    http_method_names = ("post", "options")

    @typed_extend_schema(responses={200: SimulatedActionConsentPreparationResponseSerializer})
    def post(self, request: Request, account_id: int) -> Response:
        """Read exact terms without issuing consent or writing financial state."""
        if request.query_params or request.data != {}:
            return Response({"detail": "准备操作只接受空对象。"}, status=400)
        return _preparation_response(
            prepare_owner_simulated_action_consent(request, account_id=account_id),
            purpose="consent",
        )


class SimulatedActionWithdrawalPreparationAPIView(_OwnerConsentAPIView):
    """Prepare one exact withdrawal independently of current trading eligibility."""

    http_method_names = ("post", "options")

    @typed_extend_schema(responses={200: SimulatedActionConsentPreparationResponseSerializer})
    def post(self, request: Request, account_id: int) -> Response:
        """Read an original withdrawal locator without revoking it yet."""
        if request.query_params or request.data != {}:
            return Response({"detail": "撤销准备只接受空对象。"}, status=400)
        return _preparation_response(
            prepare_owner_simulated_action_withdrawal(request, account_id=account_id),
            purpose="withdrawal",
            withdrawal_session_deadline=read_authenticated_withdrawal_session_deadline(request),
        )
