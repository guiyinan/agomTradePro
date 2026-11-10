"""Session-only API for reading published financial facts for one holding."""

from __future__ import annotations

from typing import Any

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter
from rest_framework import serializers, status
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.simulated_trading.application.holding_disclosures import (
    HoldingDisclosureUnavailable,
    read_owned_holding_disclosures,
)

from .sdk_contract_views import typed_extend_schema


class HoldingDisclosureQuerySerializer(serializers.Serializer[dict[str, object]]):
    """Validate the exact selected asset token from the account read request."""

    asset_code = serializers.CharField(max_length=20, trim_whitespace=False)

    def validate_asset_code(self, value: str) -> str:
        """Reject padding so invalid tokens use the documented detail response."""

        if not value or value.strip() != value:
            raise serializers.ValidationError("The asset_code is invalid.")
        return value


class HoldingDisclosureRowResponseSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize one source-bound financial metric and its original timestamps."""

    asset_code = serializers.CharField()
    metric_code = serializers.CharField()
    value = serializers.FloatField()
    unit = serializers.CharField(allow_blank=True)
    period_end = serializers.CharField()
    period_type = serializers.CharField()
    report_date = serializers.CharField(allow_null=True)
    announced_at = serializers.CharField(allow_null=True)
    available_at = serializers.CharField(allow_null=True)
    fetched_at = serializers.CharField()
    source_record_id = serializers.CharField(allow_null=True, allow_blank=True)
    raw_payload_hash = serializers.CharField(allow_null=True, allow_blank=True)

    def get_fields(self) -> dict[str, serializers.Field[Any, Any, Any, Any]]:
        """Declare the source label without replacing Serializer.source."""

        fields = super().get_fields()
        fields["source"] = serializers.CharField(allow_blank=True)
        return fields


class HoldingDisclosureResponseSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize the read-only account and coverage contract."""

    account_id = serializers.IntegerField()
    asset_code = serializers.CharField()
    as_of = serializers.DateTimeField(format="iso-8601")
    outcome = serializers.ChoiceField(choices=("partial", "blocked"))
    scope = serializers.ChoiceField(choices=("simulation_only",))
    must_not_use_for_decision = serializers.BooleanField()
    must_not_execute = serializers.BooleanField()
    coverage_note = serializers.CharField()
    blocked_reason = serializers.CharField(allow_blank=True)
    freshness = serializers.CharField()
    reliability = serializers.CharField()
    rows = HoldingDisclosureRowResponseSerializer(many=True)

    def get_fields(self) -> dict[str, serializers.Field[Any, Any, Any, Any]]:
        """Declare the read-only label without replacing Serializer.read_only."""

        fields = super().get_fields()
        fields["read_only"] = serializers.BooleanField()
        return fields


class HoldingDisclosureErrorResponseSerializer(serializers.Serializer[dict[str, object]]):
    """Return a bounded interface error without account or provider internals."""

    detail = serializers.CharField()


class HoldingDisclosureAPIView(APIView):
    """Read source-bound financial references for one exact held security."""

    authentication_classes = (SessionAuthentication,)
    permission_classes = (IsAuthenticated,)

    @typed_extend_schema(
        summary="读取有权查看账户的持仓证券已发布财报指标",
        description=(
            "仅读取当前发布的财务指标，不代表完整公告或公司行为覆盖；结果禁止用于决策和执行。"
        ),
        parameters=[
            OpenApiParameter(
                name="asset_code",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=True,
            )
        ],
        responses={
            200: HoldingDisclosureResponseSerializer,
            400: HoldingDisclosureErrorResponseSerializer,
            403: HoldingDisclosureErrorResponseSerializer,
            404: HoldingDisclosureResponseSerializer,
            503: HoldingDisclosureErrorResponseSerializer,
        },
    )
    def get(self, request: Request, account_id: int) -> Response:
        """Return the bounded disclosure review for an authorized account holding."""

        if any(key != "asset_code" for key in request.query_params.keys()):
            return Response(
                {"detail": "Unsupported query parameter."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        asset_codes = request.query_params.getlist("asset_code")
        if len(asset_codes) != 1:
            return Response(
                {"detail": "Provide exactly one asset_code."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        query = HoldingDisclosureQuerySerializer(data={"asset_code": asset_codes[0]})
        if not query.is_valid():
            return Response(
                {"detail": "The asset_code is invalid."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        actor_user_id: object = getattr(request.user, "pk", None)
        if type(actor_user_id) is not int or actor_user_id <= 0:
            return Response(
                {"detail": "The requested account holding is unavailable."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            payload = read_owned_holding_disclosures(
                user_id=actor_user_id,
                account_id=account_id,
                asset_code=query.validated_data["asset_code"],
            )
        except HoldingDisclosureUnavailable:
            return Response(
                {"detail": "The holding disclosure read is temporarily unavailable."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        result_serializer = HoldingDisclosureResponseSerializer(instance=payload)
        response_status = (
            status.HTTP_404_NOT_FOUND
            if payload.get("blocked_reason") == "account_scope_or_holding_unavailable"
            else (
                status.HTTP_400_BAD_REQUEST
                if payload.get("blocked_reason") == "invalid_asset_code"
                else status.HTTP_200_OK
            )
        )
        return Response(result_serializer.data, status=response_status)


__all__: tuple[str, ...] = (
    "HoldingDisclosureAPIView",
    "HoldingDisclosureErrorResponseSerializer",
    "HoldingDisclosureQuerySerializer",
    "HoldingDisclosureResponseSerializer",
)
