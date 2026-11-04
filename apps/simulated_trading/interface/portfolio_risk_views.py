"""Owner-scoped, simulation-only portfolio risk API views."""

from __future__ import annotations

from typing import Any, cast

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter
from rest_framework import serializers, status
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import ParseError, UnsupportedMediaType
from rest_framework.parsers import JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.risk_center.application.portfolio_risk_contracts import (
    PortfolioRiskReportPayload,
)
from apps.simulated_trading.application.portfolio_risk_public import (
    PortfolioRiskAccountAccessDenied,
    PortfolioRiskUnavailable,
    get_owner_portfolio_pressure_options,
    get_owner_portfolio_risk,
    run_owner_portfolio_pressure,
)
from core.exceptions import DuplicateResourceError, InvalidInputError

from .sdk_contract_views import typed_extend_schema

_OUTCOMES = ("allowed", "blocked", "partial", "unknown")
_REPORT_FRESHNESS = ("qualified_snapshot", "expired", "unknown")
_REPORT_RELIABILITY = ("source_bound", "partial", "unknown")


class PortfolioRiskCheckResponseSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize one user-facing risk constraint and its bounded details."""

    dimension = serializers.CharField()
    status = serializers.ChoiceField(choices=_OUTCOMES)
    reason_codes = serializers.ListField(child=serializers.CharField())
    summary = serializers.CharField()
    details = serializers.JSONField()


class PortfolioRiskSourceResponseSerializer(serializers.Serializer[dict[str, object]]):
    """Publish source identity, original clocks, coverage, and restrictions."""

    source_id = serializers.CharField()
    source_record_id = serializers.CharField()
    raw_payload_sha256 = serializers.CharField(allow_null=True)
    observed_at = serializers.CharField(allow_null=True)
    observed_on = serializers.CharField(allow_null=True)
    observation_precision = serializers.CharField()
    available_at = serializers.CharField(allow_null=True)
    known_at = serializers.CharField(allow_null=True)
    cutoff = serializers.CharField()
    valid_until = serializers.CharField(allow_null=True)
    purpose = serializers.CharField()
    restrictions = serializers.ListField(child=serializers.CharField())
    must_not_use_for_decision = serializers.BooleanField()
    coverage_fraction = serializers.CharField(allow_null=True)
    coverage_basis = serializers.CharField()
    clock_evidence_proof = serializers.JSONField(required=False)


class PortfolioRiskReportResponseSerializer(serializers.Serializer[dict[str, object]]):
    """Describe an ordinary user's versioned, non-executable risk report."""

    account_id = serializers.IntegerField()
    as_of = serializers.CharField()
    outcome = serializers.ChoiceField(choices=_OUTCOMES)
    policy_version = serializers.CharField(allow_null=True)
    resource_snapshot_hash = serializers.CharField()
    checks = PortfolioRiskCheckResponseSerializer(many=True)
    sources = PortfolioRiskSourceResponseSerializer(many=True)
    freshness = serializers.ChoiceField(choices=_REPORT_FRESHNESS)
    reliability = serializers.ChoiceField(choices=_REPORT_RELIABILITY)
    must_not_use_for_decision = serializers.BooleanField()
    scope = serializers.ChoiceField(choices=("simulation_only",))
    must_not_execute = serializers.BooleanField()


class PortfolioPressureRunRequestSerializer(serializers.Serializer[dict[str, object]]):
    """Accept only a selected immutable Scenario revision and literal confirmation."""

    scenario_version_id = serializers.CharField(max_length=160, trim_whitespace=True)
    confirmed = serializers.BooleanField()


class PortfolioPressureOptionResponseSerializer(serializers.Serializer[dict[str, object]]):
    """Render one human-readable approved Scenario option with its bound revision value."""

    value = serializers.CharField(max_length=160)

    def get_fields(self) -> dict[str, serializers.Field[Any, Any, Any, Any]]:
        """Declare the JSON label without replacing the serializer's own label attribute."""

        fields = super().get_fields()
        fields["label"] = serializers.CharField()
        return fields


class PortfolioPressureOptionsResponseSerializer(serializers.Serializer[dict[str, object]]):
    """Return the read-only, account-scoped options accepted by the pressure form."""

    account_id = serializers.IntegerField()
    options = PortfolioPressureOptionResponseSerializer(many=True)
    scope = serializers.ChoiceField(choices=("simulation_only",))

    def get_fields(self) -> dict[str, serializers.Field[Any, Any, Any, Any]]:
        """Declare the response flag without replacing the serializer's read-only setting."""

        fields = super().get_fields()
        fields["read_only"] = serializers.BooleanField()
        return fields


class PortfolioRiskErrorResponseSerializer(serializers.Serializer[dict[str, object]]):
    """Return bounded interface errors without internal exception details."""

    detail = serializers.CharField()


def _request_actor_id(request: Request) -> int | None:
    """Return only a positive integer identity from an authenticated principal."""

    user_id: object = getattr(request.user, "pk", None)
    if type(user_id) is not int or user_id <= 0:
        return None
    return user_id


def _input_error(detail: str) -> Response:
    """Return a bounded validation message without exposing internal details."""

    return Response({"detail": detail}, status=status.HTTP_400_BAD_REQUEST)


def _access_denied() -> Response:
    """Hide whether the requested account exists when access is not granted."""

    return Response(
        {"detail": "该模拟账户不可用，或当前用户无权查看。"},
        status=status.HTTP_403_FORBIDDEN,
    )


def _risk_unavailable() -> Response:
    """Return the stable response for an unavailable consistent risk read."""

    return Response(
        {"detail": "模拟账户风险暂时不可用，请稍后重试。"},
        status=status.HTTP_503_SERVICE_UNAVAILABLE,
    )


def _report_response(report: PortfolioRiskReportPayload) -> Response:
    """Serialize one typed risk report without changing business outcome status."""

    if report["scope"] != "simulation_only" or report["must_not_execute"] is not True:
        return _risk_unavailable()
    serializer = PortfolioRiskReportResponseSerializer(cast(dict[str, object], report))
    return Response(serializer.data, status=status.HTTP_200_OK)


class _PortfolioRiskSessionAPIView(APIView):
    """Share the browser-session authentication contract for portfolio-risk views."""

    authentication_classes = (SessionAuthentication,)
    permission_classes = (IsAuthenticated,)


class PortfolioRiskReportAPIView(_PortfolioRiskSessionAPIView):
    """Read the owner-scoped simulated-account risk report."""

    http_method_names = ("get", "options")

    @typed_extend_schema(
        summary="读取有权查看的模拟账户风险约束",
        description=(
            "只读返回账户版本、资源快照、检查结果和原始来源时点；"
            "allowed/blocked/partial/unknown 都是业务结果，不代表交易许可。"
        ),
        parameters=[OpenApiParameter("account_id", OpenApiTypes.INT, OpenApiParameter.PATH)],
        responses={
            200: PortfolioRiskReportResponseSerializer,
            403: PortfolioRiskErrorResponseSerializer,
            503: PortfolioRiskErrorResponseSerializer,
        },
    )
    def get(self, request: Request, account_id: int) -> Response:
        """Read a report without executing a Scenario or writing business state."""

        if request.query_params:
            return _input_error("风险核对不接受额外查询参数。")
        actor_id = _request_actor_id(request)
        if actor_id is None or type(account_id) is not int or account_id <= 0:
            return _access_denied()
        try:
            report = get_owner_portfolio_risk(user_id=actor_id, account_id=account_id)
        except PortfolioRiskAccountAccessDenied:
            return _access_denied()
        except PortfolioRiskUnavailable:
            return _risk_unavailable()
        return _report_response(report)


class PortfolioPressureRunAPIView(_PortfolioRiskSessionAPIView):
    """Run pressure only on the explicitly named pressure-run subresource."""

    http_method_names = ("post", "options")

    @typed_extend_schema(
        summary="明确运行一次本人模拟账户退出压力情景",
        description=(
            "仅保存既有 ScenarioRunEvidence，不生成订单、不释放预留或改变账户账本；"
            "需要已审批情景版本、浏览器会话、幂等键和明确确认。"
        ),
        parameters=[OpenApiParameter("account_id", OpenApiTypes.INT, OpenApiParameter.PATH)],
        request=PortfolioPressureRunRequestSerializer,
        responses={
            200: PortfolioRiskReportResponseSerializer,
            400: PortfolioRiskErrorResponseSerializer,
            403: PortfolioRiskErrorResponseSerializer,
            409: PortfolioRiskErrorResponseSerializer,
            503: PortfolioRiskErrorResponseSerializer,
        },
    )
    def post(self, request: Request, account_id: int) -> Response:
        """Run one confirmed pressure assessment under SessionAuthentication/CSRF."""

        if request.query_params or request.content_type != JSONParser.media_type:
            return _input_error("请选择情景版本并按提示确认后再运行。")
        try:
            raw_body: object = request.data
        except (ParseError, UnsupportedMediaType):
            return _input_error("请求内容无效，请重新打开风险任务。")
        if type(raw_body) is not dict or set(raw_body) != {"scenario_version_id", "confirmed"}:
            return _input_error("请求内容无效，请重新打开风险任务。")
        body = cast(dict[str, object], raw_body)
        if body.get("confirmed") is not True:
            return _input_error("请明确确认只运行模拟压力核对。")
        serializer = PortfolioPressureRunRequestSerializer(data=body)
        if not serializer.is_valid():
            return _input_error("情景版本或确认信息无效。")
        idempotency_key = request.headers.get("Idempotency-Key", "")
        if (
            not idempotency_key
            or len(idempotency_key) > 192
            or any(character.isspace() for character in idempotency_key)
        ):
            return _input_error("运行标识无效，请重新提交本次明确确认。")
        actor_id = _request_actor_id(request)
        if actor_id is None or type(account_id) is not int or account_id <= 0:
            return _access_denied()
        try:
            report = run_owner_portfolio_pressure(
                user_id=actor_id,
                account_id=account_id,
                scenario_version_id=cast(str, serializer.validated_data["scenario_version_id"]),
                idempotency_key=idempotency_key,
                confirmed=True,
            )
        except PortfolioRiskAccountAccessDenied:
            return _access_denied()
        except PortfolioRiskUnavailable:
            return _risk_unavailable()
        except DuplicateResourceError:
            return Response(
                {"detail": "该运行标识已用于不同的压力输入，请重新读取后再提交。"},
                status=status.HTTP_409_CONFLICT,
            )
        except InvalidInputError:
            return _input_error("情景版本、幂等标识或确认信息无效。")
        return _report_response(report)


class PortfolioPressureOptionsAPIView(_PortfolioRiskSessionAPIView):
    """Read active approved Scenario choices for one account-scoped pressure form."""

    http_method_names = ("get", "options")

    @typed_extend_schema(
        summary="读取本人模拟账户可选的已审批压力情景",
        description=(
            "只读返回当前账户有权使用的情景名称、业务版本和对应不可变版本值；"
            "不会创建、审批、激活或运行情景。"
        ),
        parameters=[OpenApiParameter("account_id", OpenApiTypes.INT, OpenApiParameter.PATH)],
        responses={
            200: PortfolioPressureOptionsResponseSerializer,
            400: PortfolioRiskErrorResponseSerializer,
            403: PortfolioRiskErrorResponseSerializer,
            503: PortfolioRiskErrorResponseSerializer,
        },
    )
    def get(self, request: Request, account_id: int) -> Response:
        """Return only the current approved choice catalog under account read scope."""

        if request.query_params:
            return _input_error("情景目录不接受额外查询参数。")
        actor_id = _request_actor_id(request)
        if actor_id is None or type(account_id) is not int or account_id <= 0:
            return _access_denied()
        try:
            options = get_owner_portfolio_pressure_options(
                user_id=actor_id,
                account_id=account_id,
            )
        except PortfolioRiskAccountAccessDenied:
            return _access_denied()
        except PortfolioRiskUnavailable:
            return _risk_unavailable()
        serializer = PortfolioPressureOptionsResponseSerializer(cast(dict[str, object], options))
        return Response(serializer.data, status=status.HTTP_200_OK)


__all__ = [
    "PortfolioPressureRunAPIView",
    "PortfolioPressureRunRequestSerializer",
    "PortfolioPressureOptionResponseSerializer",
    "PortfolioPressureOptionsAPIView",
    "PortfolioPressureOptionsResponseSerializer",
    "PortfolioRiskCheckResponseSerializer",
    "PortfolioRiskErrorResponseSerializer",
    "PortfolioRiskReportAPIView",
    "PortfolioRiskReportResponseSerializer",
    "PortfolioRiskSourceResponseSerializer",
]
