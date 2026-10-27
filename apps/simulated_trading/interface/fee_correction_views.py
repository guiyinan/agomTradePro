"""Owner API for immutable fee material, atomic corrections and exact-key readback."""

from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import UTC
from typing import Literal, cast

from django.db import DatabaseError
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter
from rest_framework.authentication import SessionAuthentication
from rest_framework.parsers import JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.simulated_trading.application.fee_correction import (
    AuthenticatedFeeCorrectionPrincipalProtocol,
    FeeCorrectionBlockedError,
)
from apps.simulated_trading.fee_correction_composition import (
    build_apply_simulated_fee_correction_use_case,
    build_fee_correction_confirmation_use_case,
    build_fee_correction_evidence_upload_use_case,
    build_fee_correction_head_use_case,
    build_fee_correction_preview_use_case,
)
from apps.simulated_trading.fee_correction_policy_composition import (
    build_fee_correction_policy_use_case,
)

from .fee_correction_serializers import (
    FeeCorrectionConfirmationRequestSerializer,
    FeeCorrectionHeadResponseSerializer,
    FeeCorrectionHeadSerializer,
    FeeCorrectionPreviewRequestSerializer,
    FeeCorrectionPreviewResponseSerializer,
    FeeCorrectionReceiptSerializer,
    FeeCorrectionRequestSerializer,
    FeeCorrectionResponseSerializer,
    FeeEvidenceReceiptSerializer,
    FeeEvidenceUploadRequestSerializer,
    FeeEvidenceUploadResponseSerializer,
)
from .fee_correction_session import fee_correction_browser_context
from .sdk_contract_views import typed_extend_schema
from .serializers import ManualTradeIdempotencyKeySerializer

logger = logging.getLogger(__name__)


def _request_key(request: Request) -> str:
    serializer = ManualTradeIdempotencyKeySerializer(
        data={"request_key": request.headers.get("Idempotency-Key")}
    )
    serializer.is_valid(raise_exception=True)
    return cast(str, serializer.validated_data["request_key"])


def _owner_principal(
    request: Request, account_id: int
) -> AuthenticatedFeeCorrectionPrincipalProtocol:
    principal = cast(AuthenticatedFeeCorrectionPrincipalProtocol, request.user)
    # Check ownership before the evidence verifier can reveal locator existence.
    # The write use cases recheck current ownership and policy under account locks.
    build_fee_correction_policy_use_case().get(account_id, principal=principal)
    return principal


def _blocked_response(error: FeeCorrectionBlockedError) -> Response:
    status_code = {
        "FEE_CORRECTION_INPUT_INVALID": 400,
        "FEE_CORRECTION_EVIDENCE_INPUT_INVALID": 400,
        "FEE_CORRECTION_OPERATOR_ATTESTATION_REQUIRED": 400,
        "FEE_CORRECTION_PRINCIPAL_INVALID": 403,
        "FEE_CORRECTION_AUTHORITY_UNAVAILABLE": 403,
        "FEE_CORRECTION_OWNER_MISMATCH": 403,
        "FEE_CORRECTION_ACCOUNT_UNAVAILABLE": 403,
        "FEE_CORRECTION_IDEMPOTENCY_CONFLICT": 409,
        "FEE_CORRECTION_EVIDENCE_IDEMPOTENCY_CONFLICT": 409,
        "FEE_CORRECTION_REVISION_CONFLICT": 409,
        "FEE_CORRECTION_TRADE_SNAPSHOT_CONFLICT": 409,
        "FEE_CORRECTION_CONFIRMATION_INVALID": 400,
        "FEE_CORRECTION_CONFIRMATION_EXPIRED": 409,
        "FEE_CORRECTION_SESSION_UNAVAILABLE": 403,
        "FEE_CORRECTION_CONFIRMATION_UNAVAILABLE": 503,
        "FEE_CORRECTION_CONFIRMATION_SESSION_INVALID": 403,
        "FEE_CORRECTION_CONFIRMATION_INPUT_INVALID": 400,
        "FEE_CORRECTION_CONFIRMATION_TOKEN_INVALID": 400,
        "FEE_CORRECTION_CONFIRMATION_TOKEN_TOO_LARGE": 400,
        "FEE_CORRECTION_CONFIRMATION_BINDING_MISMATCH": 409,
        "FEE_CORRECTION_CONFIRMATION_KEY_UNAVAILABLE": 503,
        "FEE_CORRECTION_CONFIRMATION_SESSION_UNAVAILABLE": 503,
    }.get(error.code, 422)
    return Response({"success": False, "code": error.code, "error": str(error)}, status=status_code)


def _unavailable_response(
    error: DatabaseError, *, operation: Literal["read", "upload", "apply"]
) -> Response:
    logger.warning("Fee correction storage unavailable: %s", type(error).__name__)
    if operation != "read":
        message = (
            "尚不能确认材料是否保存。请保留原请求编号和原内容；策略仍有效时，可按原编号和原内容重试上传。"
            "费用更正回执不能确认上传结果，请勿另建请求。"
            if operation == "upload"
            else "尚不能确认处理结果，请保留原请求编号并查询结果。不要另建请求重复更正。"
        )
        return Response(
            {
                "success": False,
                "code": "FEE_CORRECTION_RESULT_INDETERMINATE",
                "error": message,
                "effects_indeterminate": True,
                "recovery_required": True,
            },
            status=503,
        )
    return Response(
        {
            "success": False,
            "code": "FEE_CORRECTION_READ_UNAVAILABLE",
            "error": "暂时无法读取已验证的费用更正记录，请稍后重试读取。",
        },
        status=503,
    )


class FeeCorrectionEvidenceUploadAPIView(APIView):
    """Store owner-attested CSV bytes without posting a cash or cost adjustment."""

    permission_classes = (IsAuthenticated,)
    parser_classes = (JSONParser,)

    @typed_extend_schema(
        summary="上传模拟成交费用材料",
        description="以原请求编号保存 UTF-8 CSV 材料。材料为操作者声明，保存不代表更正已入账。",
        parameters=[
            OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, required=True)
        ],
        request=FeeEvidenceUploadRequestSerializer,
        responses={
            200: FeeEvidenceUploadResponseSerializer,
            400: OpenApiTypes.OBJECT,
            403: OpenApiTypes.OBJECT,
            409: OpenApiTypes.OBJECT,
            422: OpenApiTypes.OBJECT,
            503: OpenApiTypes.OBJECT,
        },
    )
    def post(self, request: Request, account_id: int, trade_id: int) -> Response:
        """Validate the bounded JSON transport and call the existing evidence store."""

        key = _request_key(request)
        serializer = FeeEvidenceUploadRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            principal = _owner_principal(request, account_id)
        except FeeCorrectionBlockedError as error:
            return _blocked_response(error)
        except DatabaseError as error:
            return _unavailable_response(error, operation="read")
        try:
            result = build_fee_correction_evidence_upload_use_case().execute(
                serializer.to_command(
                    account_id=account_id, trade_id=trade_id, idempotency_key=key
                ),
                principal=principal,
            )
        except FeeCorrectionBlockedError as error:
            return _blocked_response(error)
        except DatabaseError as error:
            return _unavailable_response(error, operation="upload")
        return Response(
            {
                "success": True,
                "evidence": FeeEvidenceReceiptSerializer(asdict(result)).data,
                "assurance_notice": "费用材料由账户所有者声明，不代表券商或发行方认证；保存材料不代表费用更正已入账。",
            }
        )


class FeeCorrectionPreviewAPIView(APIView):
    """Prepare source-backed fee changes while leaving all financial records intact."""

    permission_classes = (IsAuthenticated,)
    parser_classes = (JSONParser,)

    @typed_extend_schema(
        summary="预览模拟成交费用更正",
        description="保存并核对费用材料，展示原费用、新费用和现金差额；预览不代表更正已入账。",
        parameters=[
            OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, required=True)
        ],
        request=FeeCorrectionPreviewRequestSerializer,
        responses={
            200: FeeCorrectionPreviewResponseSerializer,
            400: OpenApiTypes.OBJECT,
            403: OpenApiTypes.OBJECT,
            409: OpenApiTypes.OBJECT,
            422: OpenApiTypes.OBJECT,
            503: OpenApiTypes.OBJECT,
        },
    )
    def post(self, request: Request, account_id: int, trade_id: int) -> Response:
        """Pass bounded original material to the owner service without accepting a revision."""

        key = _request_key(request)
        serializer = FeeCorrectionPreviewRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            principal = _owner_principal(request, account_id)
        except FeeCorrectionBlockedError as error:
            return _blocked_response(error)
        except DatabaseError as error:
            return _unavailable_response(error, operation="read")
        continuation: dict[str, object] | None = None
        try:
            command = serializer.to_command(
                account_id=account_id, trade_id=trade_id, idempotency_key=key
            )
            if type(request.successful_authenticator) is SessionAuthentication:
                prepared = build_fee_correction_confirmation_use_case().prepare_preview(
                    command,
                    principal=principal,
                    browser_context=fee_correction_browser_context(request),
                )
                result = prepared.preview
                if prepared.confirmation_token is not None and prepared.expires_at is not None:
                    continuation = {
                        "action_key": "simulated-trading.fee-correction-confirm",
                        "input": {
                            "account_id": str(account_id),
                            "trade_id": str(trade_id),
                            "confirmation_token": prepared.confirmation_token,
                        },
                        "expires_at": prepared.expires_at.astimezone(UTC)
                        .isoformat()
                        .replace("+00:00", "Z"),
                    }
            else:
                result = build_fee_correction_preview_use_case().execute(
                    command, principal=principal
                )
        except FeeCorrectionBlockedError as error:
            return _blocked_response(error)
        except DatabaseError as error:
            return _unavailable_response(error, operation="upload")
        payload = {
            "success": True,
            "outcome": "noop" if result.status == "already_applied" else "success",
            "status": result.status,
            "preview": asdict(result.preview) if result.preview else None,
            "receipt": asdict(result.receipt) if result.receipt else None,
            "assurance_notice": "费用材料由账户所有者声明，不代表券商或发行方认证。",
            "message": (
                "本次更正已入账，无需再次确认。"
                if result.status == "already_applied"
                else "已保存并核对材料，费用更正尚未入账。"
            ),
        }
        if continuation is not None:
            payload["continuation"] = continuation
        return Response(FeeCorrectionPreviewResponseSerializer(payload).data)


class FeeCorrectionConfirmationAPIView(APIView):
    """Confirm an unexpired preview using the original key and a live browser session."""

    authentication_classes = (SessionAuthentication,)
    permission_classes = (IsAuthenticated,)
    parser_classes = (JSONParser,)

    @typed_extend_schema(
        summary="确认模拟成交费用更正",
        description="验证原预览、登录会话和有效期后更正费用；结果未知时先查询原请求。",
        parameters=[
            OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, required=True)
        ],
        request=FeeCorrectionConfirmationRequestSerializer,
        responses={
            200: FeeCorrectionResponseSerializer,
            400: OpenApiTypes.OBJECT,
            403: OpenApiTypes.OBJECT,
            409: OpenApiTypes.OBJECT,
            422: OpenApiTypes.OBJECT,
            503: OpenApiTypes.OBJECT,
        },
    )
    def post(self, request: Request, account_id: int, trade_id: int) -> Response:
        """Forward only the hidden context, authenticated session claims and original key."""

        key = _request_key(request)
        serializer = FeeCorrectionConfirmationRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            principal = _owner_principal(request, account_id)
            browser_context = fee_correction_browser_context(request)
        except FeeCorrectionBlockedError as error:
            return _blocked_response(error)
        except DatabaseError as error:
            return _unavailable_response(error, operation="read")
        try:
            receipt = build_fee_correction_confirmation_use_case().confirm(
                serializer.to_command(
                    account_id=account_id, trade_id=trade_id, idempotency_key=key
                ),
                principal=principal,
                browser_context=browser_context,
            )
        except FeeCorrectionBlockedError as error:
            return _blocked_response(error)
        except DatabaseError as error:
            return _unavailable_response(error, operation="apply")
        return Response(
            {
                "success": True,
                "receipt": FeeCorrectionReceiptSerializer(asdict(receipt)).data,
                "message": (
                    "费用更正已入账。" if not receipt.replayed else "已核对原请求，无需重复更正。"
                ),
            }
        )


class FeeCorrectionAPIView(APIView):
    """Apply a verified source using the existing locked, idempotent ledger service."""

    permission_classes = (IsAuthenticated,)
    parser_classes = (JSONParser,)

    @typed_extend_schema(
        summary="更正模拟成交费用",
        description="使用上传时的原请求编号及已读版本。结果不确定时先按原编号回读，不另建请求重试。",
        parameters=[
            OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, required=True)
        ],
        request=FeeCorrectionRequestSerializer,
        responses={
            200: FeeCorrectionResponseSerializer,
            400: OpenApiTypes.OBJECT,
            403: OpenApiTypes.OBJECT,
            409: OpenApiTypes.OBJECT,
            422: OpenApiTypes.OBJECT,
            503: OpenApiTypes.OBJECT,
        },
    )
    def post(self, request: Request, account_id: int, trade_id: int) -> Response:
        """Accept a locator and revision; amounts come only from persisted evidence."""

        key = _request_key(request)
        serializer = FeeCorrectionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            principal = _owner_principal(request, account_id)
        except FeeCorrectionBlockedError as error:
            return _blocked_response(error)
        except DatabaseError as error:
            return _unavailable_response(error, operation="read")
        try:
            result = build_apply_simulated_fee_correction_use_case().execute(
                serializer.to_request(
                    account_id=account_id, trade_id=trade_id, idempotency_key=key
                ),
                principal=principal,
            )
        except FeeCorrectionBlockedError as error:
            return _blocked_response(error)
        except DatabaseError as error:
            return _unavailable_response(error, operation="apply")
        return Response(
            {"success": True, "receipt": FeeCorrectionReceiptSerializer(asdict(result)).data}
        )


class FeeCorrectionHeadAPIView(APIView):
    """Read validated ledger state and a prior request even after policy revocation."""

    permission_classes = (IsAuthenticated,)

    @typed_extend_schema(
        summary="读取模拟费用更正版本及请求结果",
        description="可带原请求编号查询确切回执；未找到回执不代表请求失败，也不代表无副作用。",
        parameters=[
            OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, required=False)
        ],
        responses={
            200: FeeCorrectionHeadResponseSerializer,
            400: OpenApiTypes.OBJECT,
            403: OpenApiTypes.OBJECT,
            409: OpenApiTypes.OBJECT,
            422: OpenApiTypes.OBJECT,
            503: OpenApiTypes.OBJECT,
        },
    )
    def get(self, request: Request, account_id: int, trade_id: int) -> Response:
        """Return explicit version fields; never serialize the private trade entity."""

        key = _request_key(request) if "Idempotency-Key" in request.headers else None
        try:
            result = build_fee_correction_head_use_case().get_head(
                account_id,
                trade_id,
                principal=cast(AuthenticatedFeeCorrectionPrincipalProtocol, request.user),
                request_key=key,
            )
        except FeeCorrectionBlockedError as error:
            return _blocked_response(error)
        except DatabaseError as error:
            return _unavailable_response(error, operation="read")
        payload = {
            "account_id": result.account_id,
            "trade_id": result.trade_id,
            "revision": result.revision,
            "expected_predecessor_id": result.expected_predecessor_id,
            "as_of": result.as_of,
            "request_receipt": asdict(result.request_receipt) if result.request_receipt else None,
        }
        confirmed = key is None or result.request_receipt is not None
        return Response(
            {
                "success": True,
                "outcome": "success" if confirmed else "partial",
                "head": FeeCorrectionHeadSerializer(payload).data,
                "message": (
                    "已核对原请求，费用更正已入账。"
                    if result.request_receipt is not None
                    else (
                        "尚未找到原请求回执，结果仍未确认；请保留原请求，不要另建请求重复更正。"
                        if key is not None
                        else "已读取当前费用更正记录。"
                    )
                ),
            }
        )
