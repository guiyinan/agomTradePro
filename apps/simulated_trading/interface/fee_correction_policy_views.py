"""Read or replace fee evidence eligibility for the authenticated account owner."""

from __future__ import annotations

from dataclasses import asdict
from typing import cast

from drf_spectacular.types import OpenApiTypes
from rest_framework.parsers import JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.simulated_trading.application.fee_correction import (
    AuthenticatedFeeCorrectionPrincipalProtocol,
    FeeCorrectionBlockedError,
)
from apps.simulated_trading.application.fee_correction_evidence import (
    ASSURANCE_OPERATOR_ATTESTED_UPLOAD,
)
from apps.simulated_trading.application.fee_correction_policy import FeeCorrectionPolicyState
from apps.simulated_trading.fee_correction_policy_composition import (
    build_fee_correction_policy_use_case,
)

from .fee_correction_policy_serializers import (
    FeeCorrectionPolicyRequestSerializer,
    FeeCorrectionPolicyResponseSerializer,
    FeeCorrectionPolicyStateSerializer,
)
from .sdk_contract_views import typed_extend_schema


def _policy_response(policy: FeeCorrectionPolicyState) -> Response:
    payload = asdict(policy)
    payload.update(
        assurance_class=ASSURANCE_OPERATOR_ATTESTED_UPLOAD,
        assurance_notice="费用材料由账户所有者声明，不代表券商或发行方认证。",
    )
    return Response({"success": True, "policy": FeeCorrectionPolicyStateSerializer(payload).data})


def _blocked_response(error: FeeCorrectionBlockedError) -> Response:
    status_code = {
        "FEE_CORRECTION_POLICY_CONFLICT": 409,
        "FEE_CORRECTION_POLICY_INPUT_INVALID": 400,
        "FEE_CORRECTION_PRINCIPAL_INVALID": 403,
        "FEE_CORRECTION_AUTHORITY_UNAVAILABLE": 403,
    }.get(error.code, 422)
    return Response({"success": False, "code": error.code, "error": str(error)}, status=status_code)


class FeeCorrectionPolicyAPIView(APIView):
    """Manage evidence eligibility; this endpoint never corrects or executes a trade."""

    permission_classes = (IsAuthenticated,)
    parser_classes = (JSONParser,)

    @typed_extend_schema(
        summary="读取模拟费用材料策略",
        responses={200: FeeCorrectionPolicyResponseSerializer, 403: OpenApiTypes.OBJECT},
    )
    def get(self, request: Request, account_id: int) -> Response:
        """Return the owner's policy or an unpersisted, disabled version zero."""

        try:
            result = build_fee_correction_policy_use_case().get(
                account_id,
                principal=cast(AuthenticatedFeeCorrectionPrincipalProtocol, request.user),
            )
        except FeeCorrectionBlockedError as error:
            return _blocked_response(error)
        return _policy_response(result)

    @typed_extend_schema(
        summary="设置模拟费用材料策略",
        description=(
            "账户所有者明示启用或禁用操作者声明材料。必须提交读取到的版本；"
            "版本冲突需重新读取，不应自动覆盖。此操作不会更正费用或发出订单。"
        ),
        request=FeeCorrectionPolicyRequestSerializer,
        responses={
            200: FeeCorrectionPolicyResponseSerializer,
            400: OpenApiTypes.OBJECT,
            403: OpenApiTypes.OBJECT,
            409: OpenApiTypes.OBJECT,
        },
    )
    def put(self, request: Request, account_id: int) -> Response:
        """Validate explicit owner settings and delegate the version-checked write."""

        serializer = FeeCorrectionPolicyRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = build_fee_correction_policy_use_case().save(
                serializer.to_command(account_id),
                principal=cast(AuthenticatedFeeCorrectionPrincipalProtocol, request.user),
            )
        except FeeCorrectionBlockedError as error:
            return _blocked_response(error)
        return _policy_response(result)
