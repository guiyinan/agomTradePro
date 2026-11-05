"""Session-only HTTP actions for the owner-scoped rebalance-plan journey.

The view layer accepts user intent and exact saved-revision pins only. Account
facts, prices, risk decisions, fees, and order quantities are always rebuilt
behind the public Application boundary.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from decimal import Decimal
from typing import Literal, Protocol, cast

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

from apps.simulated_trading.application.rebalance_journey_public import (
    RebalanceJourneyAccessDenied,
    RebalanceJourneyCommand,
    run_rebalance_journey,
)
from core.exceptions import AgomTradeProException, InvalidInputError

from .sdk_contract_views import typed_extend_schema

_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_REQUEST_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_PLAN_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
_PLAN_ACTIONS = ("list", "create", "read", "review", "successor", "reconcile", "preview_order")
_BASIS_CHOICES = ("market", "published_close")


def _idempotency_key_parameter() -> OpenApiParameter:
    """Describe the required header used to bind plan mutations and retries."""

    return OpenApiParameter(
        name="Idempotency-Key",
        type=OpenApiTypes.STR,
        location=OpenApiParameter.HEADER,
        required=True,
        description="同一操作重试时复用原键和原输入；不能用新键替代不确定结果。",
    )


def _revision_query_parameters() -> list[OpenApiParameter]:
    """Describe exact-revision query pins accepted by read-only plan routes."""

    return [
        OpenApiParameter(
            name="plan_version",
            type=OpenApiTypes.INT,
            location=OpenApiParameter.QUERY,
            required=True,
            description="必须来自当前账户计划列表的精确版本号。",
        ),
        OpenApiParameter(
            name="revision_hash",
            type=OpenApiTypes.STR,
            location=OpenApiParameter.QUERY,
            required=True,
            description="绑定该计划版本的 SHA-256；不支持 latest 别名。",
        ),
    ]


class RebalancePlanIdentityResponseSerializer(serializers.Serializer[dict[str, object]]):
    """Validate the exact immutable identity returned for one saved revision."""

    plan_id = serializers.CharField(max_length=64)
    family_id = serializers.CharField(max_length=64)
    root_plan_id = serializers.CharField(max_length=64)
    version = serializers.IntegerField(min_value=1)
    parent_plan_id = serializers.CharField(max_length=64, allow_null=True)
    parent_version = serializers.IntegerField(min_value=1, allow_null=True)
    parent_revision_hash = serializers.RegexField(_HASH_PATTERN, allow_null=True)
    account_id = serializers.IntegerField(min_value=1)
    owner_user_id = serializers.IntegerField(min_value=1)
    transition_plan_hash = serializers.RegexField(_HASH_PATTERN)
    revision_hash = serializers.RegexField(_HASH_PATTERN)
    recorded_at = serializers.CharField(max_length=80)
    valid_until = serializers.CharField(max_length=80)


class RebalancePlanRevisionResponseSerializer(serializers.Serializer[dict[str, object]]):
    """Keep the application's canonical revision body intact at the JSON edge."""

    identity = RebalancePlanIdentityResponseSerializer()
    transition_plan = serializers.JSONField()
    basis = serializers.JSONField()
    orders = serializers.ListField(child=serializers.JSONField())
    status = serializers.CharField(max_length=48)
    automatic_submission = serializers.BooleanField()

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        """Retain the canonical basis object while checking its required contract keys."""

        basis = attrs.get("basis")
        transition_plan = attrs.get("transition_plan")
        raw_orders = attrs.get("orders")
        required = {
            "account",
            "money_unit",
            "portfolio_snapshot",
            "decision",
            "target",
            "planning_policy",
            "risk",
            "fee_policy",
            "quantity_rule",
            "settlement_rule",
            "execution_calendar",
            "source_bindings",
            "current_positions",
            "target_positions",
            "business_date",
            "execution_session",
            "prepared_at",
            "valid_until",
        }
        if not isinstance(basis, Mapping) or not required.issubset(basis):
            raise serializers.ValidationError("计划依据结构不完整。")
        if not isinstance(transition_plan, Mapping):
            raise serializers.ValidationError("计划原始目标结构无效。")
        if not isinstance(raw_orders, list):
            raise serializers.ValidationError("计划订单结构无效。")
        order_fields = {
            "ordinal",
            "order_content_hash",
            "plan_order_binding_id",
            "asset_code",
            "security_id",
            "asset_type",
            "classification_content_hash",
            "side",
            "requested_quantity",
            "approved_quantity",
            "unapproved_quantity",
            "reference_price",
            "estimated_fee",
            "approved_limit_price",
            "quantity_unit",
            "money_unit",
            "status",
            "reason_codes",
        }
        for order in raw_orders:
            if not isinstance(order, Mapping) or not order_fields.issubset(order):
                raise serializers.ValidationError("计划订单依据不完整。")
            if order.get("side") not in {"buy", "sell"}:
                raise serializers.ValidationError("计划订单方向无效。")
            if not isinstance(order.get("asset_type"), str) or not _HASH_PATTERN.fullmatch(
                cast(str, order.get("classification_content_hash"))
                if isinstance(order.get("classification_content_hash"), str)
                else ""
            ):
                raise serializers.ValidationError("计划证券分类绑定无效。")
        if attrs.get("automatic_submission") is not False:
            raise serializers.ValidationError("调仓计划不能自动提交订单。")
        return attrs


class RebalancePlanJourneyResponseSerializer(serializers.Serializer[dict[str, object]]):
    """Validate the bounded list or exact-revision response envelope."""

    success = serializers.BooleanField()
    account_id = serializers.IntegerField(min_value=1)
    plan = RebalancePlanRevisionResponseSerializer(required=False)
    plans = RebalancePlanRevisionResponseSerializer(many=True, required=False)
    review = serializers.JSONField(allow_null=True)
    progress = serializers.JSONField(allow_null=True)
    capabilities = serializers.JSONField()
    preview = serializers.JSONField(required=False)
    continuation = serializers.JSONField(required=False)

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        """Require exactly one response shape and bind every revision to the account."""

        if attrs.get("success") is not True:
            raise serializers.ValidationError("成功响应必须明确标记为成功。")
        has_plan = "plan" in attrs
        has_plans = "plans" in attrs
        if has_plan == has_plans:
            raise serializers.ValidationError("计划响应必须是单版或列表。")
        if "preview" in attrs and not isinstance(attrs["preview"], Mapping):
            raise serializers.ValidationError("单笔订单预览结构无效。")
        if "continuation" in attrs and not isinstance(attrs["continuation"], Mapping):
            raise serializers.ValidationError("订单确认步骤无法核对。")
        if "preview" in attrs and not _valid_plan_order_preview_handoff(
            cast(Mapping[str, object], attrs["preview"]),
            cast(Mapping[str, object], attrs.get("continuation")),
            cast(int, attrs["account_id"]),
        ):
            raise serializers.ValidationError("单笔预览与后续确认未绑定到同一模拟订单。")
        if "continuation" in attrs and "preview" not in attrs:
            raise serializers.ValidationError("没有单笔预览时不能返回订单确认步骤。")
        if has_plans and len(cast(list[object], attrs["plans"])) > 20:
            raise serializers.ValidationError("计划列表超过服务端上限。")
        plans: list[object] = [attrs["plan"]] if has_plan else cast(list[object], attrs["plans"])
        account_id = attrs["account_id"]
        for raw_plan in plans:
            plan = cast(dict[str, object], raw_plan)
            identity = cast(dict[str, object], plan["identity"])
            if identity.get("account_id") != account_id:
                raise serializers.ValidationError("计划版本账户范围不一致。")
        return attrs


class RebalancePlanErrorResponseSerializer(serializers.Serializer[dict[str, object]]):
    """Return a stable public error without exposing repository or authority details."""

    success = serializers.BooleanField()
    error = serializers.CharField(max_length=240)
    code = serializers.RegexField(r"^[A-Z0-9_]{1,80}$")


class RebalancePlanCreateRequestSerializer(serializers.Serializer[dict[str, object]]):
    """Accept user targets and reference-price choice, never financial inputs."""

    target_weights = serializers.CharField(max_length=2048, trim_whitespace=False)
    reference_price_basis = serializers.ChoiceField(choices=_BASIS_CHOICES)


class RebalancePlanExactRevisionRequestSerializer(serializers.Serializer[dict[str, object]]):
    """Bind a read or mutation to one exact plan revision."""

    plan_version = serializers.IntegerField(min_value=1)
    revision_hash = serializers.RegexField(_HASH_PATTERN)


class RebalancePlanReviewRequestSerializer(RebalancePlanExactRevisionRequestSerializer):
    """Require a deliberate human review of an exact inactive plan revision."""

    confirmed = serializers.BooleanField()


class RebalancePlanSuccessorRequestSerializer(RebalancePlanReviewRequestSerializer):
    """Accept only optional new target intent for a freshly prepared successor."""

    target_weights = serializers.CharField(max_length=2048, trim_whitespace=False, required=False)
    reference_price_basis = serializers.ChoiceField(
        choices=_BASIS_CHOICES,
        required=False,
    )


class ExactDecimalTextField(serializers.DecimalField):
    """Parse decimal text only, never a JSON binary floating-point value."""

    def to_internal_value(self, data: object) -> Decimal:
        """Require an unpadded decimal string before DRF numeric validation."""

        if type(data) is not str or data.strip() != data:
            raise serializers.ValidationError("请输入不带空格的精确数字文本。")
        return super().to_internal_value(data)


class RebalancePlanOrderPreviewRequestSerializer(serializers.Serializer[dict[str, object]]):
    """Accept one exact plan-order pin and explicit quantity/limit intent."""

    plan_version = serializers.IntegerField(min_value=1)
    revision_hash = serializers.RegexField(_HASH_PATTERN)
    order_content_hash = serializers.RegexField(_HASH_PATTERN)
    plan_order_binding_id = serializers.RegexField(_HASH_PATTERN)
    quantity = ExactDecimalTextField(min_value=Decimal("0.000001"), max_digits=22, decimal_places=6)
    limit_price = ExactDecimalTextField(
        min_value=Decimal("0.000001"), max_digits=20, decimal_places=6
    )
    reason = serializers.CharField(max_length=200, allow_blank=True, required=False)


class _RebalancePlanSessionAPIView(APIView):
    """Require a browser session so DRF enforces its normal CSRF contract."""

    authentication_classes = (SessionAuthentication,)
    permission_classes = (IsAuthenticated,)
    parser_classes = (JSONParser,)


class _AuthenticatedPrincipal(Protocol):
    """The authenticated session identity available at the interface boundary."""

    pk: int | None
    is_authenticated: bool
    is_active: bool


def _actor_id(request: Request) -> int | None:
    """Return only the authenticated principal's positive integer identity."""

    principal = cast(_AuthenticatedPrincipal, request.user)
    if principal.is_authenticated is not True or principal.is_active is not True:
        return None
    user_id: object = principal.pk
    return user_id if type(user_id) is int and user_id > 0 else None


def _access_denied() -> Response:
    """Avoid revealing whether an account or revision exists to a foreign user."""

    return Response(
        {
            "success": False,
            "error": "该模拟账户或调仓计划不可用，或当前用户无权查看。",
            "code": "REBALANCE_JOURNEY_ACCESS_DENIED",
        },
        status=status.HTTP_403_FORBIDDEN,
    )


def _input_error(message: str = "请求内容无效，请按当前页面重新提交。") -> Response:
    """Return a bounded client error without echoing submitted financial facts."""

    return Response(
        {"success": False, "error": message, "code": "REBALANCE_JOURNEY_INPUT_INVALID"},
        status=status.HTTP_400_BAD_REQUEST,
    )


def _unavailable() -> Response:
    """Return a stable unavailable response without exposing composition details."""

    return Response(
        {
            "success": False,
            "error": "调仓计划暂时不可用，请稍后重新读取。",
            "code": "REBALANCE_JOURNEY_UNAVAILABLE",
        },
        status=status.HTTP_503_SERVICE_UNAVAILABLE,
    )


def _application_error(error: AgomTradeProException) -> Response:
    """Map known application errors while keeping exact-pin conflicts actionable."""

    if isinstance(error, RebalanceJourneyAccessDenied):
        return _access_denied()
    if error.code == "REBALANCE_JOURNEY_UNAVAILABLE" or error.status_code >= 500:
        return _unavailable()
    if isinstance(error, InvalidInputError):
        return _input_error()
    if error.status_code == status.HTTP_404_NOT_FOUND:
        return Response(
            {
                "success": False,
                "error": "未找到当前计划版本，或该版本不可查看。",
                "code": _safe_error_code(error.code),
            },
            status=status.HTTP_404_NOT_FOUND,
        )
    if error.status_code in {status.HTTP_403_FORBIDDEN, status.HTTP_401_UNAUTHORIZED}:
        return _access_denied()
    return Response(
        {
            "success": False,
            "error": "计划版本已变化或当前条件不再满足，请重新读取后处理。",
            "code": _safe_error_code(error.code),
        },
        status=status.HTTP_409_CONFLICT,
    )


def _safe_error_code(value: str) -> str:
    """Preserve only stable uppercase error tokens from the Application boundary."""

    return value if re.fullmatch(r"[A-Z0-9_]{1,80}", value) else "REBALANCE_JOURNEY_BLOCKED"


def _request_key(request: Request) -> str | None:
    """Read the workbench's transport idempotency key without accepting body aliases."""

    value = request.headers.get("Idempotency-Key", "")
    return value if _REQUEST_KEY_PATTERN.fullmatch(value) is not None else None


def _json_body(request: Request, allowed: frozenset[str]) -> dict[str, object] | None:
    """Accept JSON objects with a closed key set; reject caller-supplied facts."""

    if request.content_type != JSONParser.media_type or request.query_params:
        return None
    try:
        raw_body: object = request.data
    except (ParseError, UnsupportedMediaType):
        return None
    if type(raw_body) is not dict or not set(raw_body).issubset(allowed):
        return None
    return cast(dict[str, object], raw_body)


def _query_values(request: Request, allowed: frozenset[str]) -> dict[str, object] | None:
    """Copy only declared exact-revision query values."""

    if set(request.query_params) != allowed:
        return None
    return {key: request.query_params.get(key) for key in allowed}


def _validate_output(
    output: dict[str, object],
    *,
    requested_account_id: int,
    expected_preview_attempt_key: str | None = None,
) -> Response:
    """Validate the Application JSON boundary before publishing any saved row."""

    public_output = dict(output)
    raw_preview = public_output.get("preview")
    raw_continuation = public_output.get("continuation")
    if raw_preview is not None:
        continuation = (
            cast(Mapping[str, object], raw_continuation)
            if isinstance(raw_continuation, Mapping)
            else None
        )
        if (
            continuation is None
            or continuation.get("action_key") != "simulated-trading.order-confirm"
        ):
            return _unavailable()
    serializer = RebalancePlanJourneyResponseSerializer(data=public_output)
    if (
        not serializer.is_valid()
        or serializer.validated_data.get("account_id") != requested_account_id
    ):
        return _unavailable()
    if "preview" in public_output:
        preview = cast(Mapping[str, object], public_output["preview"])
        binding = cast(Mapping[str, object], preview["binding"])
        if (
            expected_preview_attempt_key is None
            or binding.get("action_attempt_key") != expected_preview_attempt_key
        ):
            return _unavailable()
    return Response(serializer.data, status=status.HTTP_200_OK)


def _valid_plan_order_preview_handoff(
    preview_envelope: Mapping[str, object],
    raw_continuation: Mapping[str, object] | None,
    account_id: int,
) -> bool:
    """Bind the hidden ordinary-order continuation to the exact displayed preview."""

    if set(preview_envelope) != {"binding", "revision_recorded_at", "preview"}:
        return False
    preview = preview_envelope.get("preview")
    binding = preview_envelope.get("binding")
    if not isinstance(preview, Mapping) or not isinstance(binding, Mapping):
        return False
    if raw_continuation is None or set(raw_continuation) != {"action_key", "input", "expires_at"}:
        return False
    continuation_input = raw_continuation.get("input")
    order = preview.get("order")
    if not isinstance(continuation_input, Mapping) or not isinstance(order, Mapping):
        return False
    if set(continuation_input) != {"account_id", "order_key", "preview_token"}:
        return False
    order_key = continuation_input.get("order_key")
    preview_token = continuation_input.get("preview_token")
    continuation_account = continuation_input.get("account_id")
    return (
        raw_continuation.get("action_key") == "simulated-trading.order-confirm"
        and continuation_account == str(account_id)
        and binding.get("account_id") == account_id
        and preview.get("account_id") == account_id
        and type(order_key) is str
        and bool(order_key)
        and order.get("idempotency_key") == order_key
        and type(preview_token) is str
        and bool(preview_token)
        and "continuation" not in preview
        and "preview_token" not in preview
        and type(raw_continuation.get("expires_at")) is str
        and bool(cast(str, raw_continuation.get("expires_at")))
        and preview.get("success") is True
        and preview.get("read_only") is True
        and preview.get("execution_submitted") is False
    )


def _run(
    request: Request,
    *,
    action: Literal["list", "create", "read", "review", "successor", "reconcile", "preview_order"],
    account_id: int,
    plan_id: str | None = None,
    order_ordinal: int | None = None,
    values: Mapping[str, object] | None = None,
) -> Response:
    """Build one server-scoped command and delegate to the public Application facade."""

    actor = _actor_id(request)
    if actor is None or type(account_id) is not int or account_id <= 0:
        return _access_denied()
    data = values or {}
    key = (
        _request_key(request)
        if action in {"create", "review", "successor", "preview_order"}
        else None
    )
    if action in {"create", "review", "successor", "preview_order"} and key is None:
        return _input_error("本次操作标识无效，请重新打开任务后提交。")
    try:
        command = RebalanceJourneyCommand(
            action=action,
            user_id=actor,
            account_id=account_id,
            plan_id=plan_id,
            plan_version=(cast(int, data["plan_version"]) if "plan_version" in data else None),
            revision_hash=(cast(str, data["revision_hash"]) if "revision_hash" in data else None),
            request_key=key,
            target_weights=(
                cast(str, data["target_weights"]) if "target_weights" in data else None
            ),
            reference_price_basis=cast(
                Literal["market", "published_close"],
                data.get("reference_price_basis", "market"),
            ),
            order_ordinal=order_ordinal,
            order_content_hash=(
                cast(str, data["order_content_hash"]) if "order_content_hash" in data else None
            ),
            plan_order_binding_id=(
                cast(str, data["plan_order_binding_id"])
                if "plan_order_binding_id" in data
                else None
            ),
            quantity=cast(Decimal, data["quantity"]) if "quantity" in data else None,
            limit_price=cast(Decimal, data["limit_price"]) if "limit_price" in data else None,
            reason=cast(str, data["reason"]) if "reason" in data else None,
        )
        output = run_rebalance_journey(command)
    except RebalanceJourneyAccessDenied:
        return _access_denied()
    except AgomTradeProException as error:
        return _application_error(error)
    return _validate_output(
        output,
        requested_account_id=account_id,
        expected_preview_attempt_key=key if action == "preview_order" else None,
    )


class RebalancePlanListCreateAPIView(_RebalancePlanSessionAPIView):
    """List exact owner-visible revisions or create one explicitly requested revision."""

    http_method_names = ("get", "post", "options")

    @typed_extend_schema(
        summary="查看或生成模拟调仓计划",
        description=(
            "GET 只读列出本人或已授权查看的精确计划版本。POST 仅提交目标意图、"
            "参考价格口径和会话幂等标识；服务器重新读取资金、持仓、来源、费用和规则。"
        ),
        responses={
            200: RebalancePlanJourneyResponseSerializer,
            400: RebalancePlanErrorResponseSerializer,
            403: RebalancePlanErrorResponseSerializer,
            409: RebalancePlanErrorResponseSerializer,
            503: RebalancePlanErrorResponseSerializer,
        },
    )
    def get(self, request: Request, account_id: int) -> Response:
        """Read the bounded list of exact saved plan revisions."""

        if request.query_params:
            return _input_error("计划列表不接受额外查询参数。")
        return _run(request, action="list", account_id=account_id)

    @typed_extend_schema(
        summary="按当前事实生成模拟调仓计划",
        description=(
            "只接受目标意图和参考价格口径；资金、持仓、价格、费用、风险与证券身份由服务端重读。"
            "此操作保存精确计划版本，不会自动提交订单。"
        ),
        request=RebalancePlanCreateRequestSerializer,
        parameters=[_idempotency_key_parameter()],
        responses={
            200: RebalancePlanJourneyResponseSerializer,
            400: RebalancePlanErrorResponseSerializer,
            403: RebalancePlanErrorResponseSerializer,
            409: RebalancePlanErrorResponseSerializer,
            503: RebalancePlanErrorResponseSerializer,
        },
    )
    def post(self, request: Request, account_id: int) -> Response:
        """Create a revision only from user-selected target intent and current server facts."""

        values = _json_body(request, frozenset({"target_weights", "reference_price_basis"}))
        if values is None:
            return _input_error()
        serializer = RebalancePlanCreateRequestSerializer(data=values)
        if not serializer.is_valid():
            return _input_error()
        return _run(
            request, action="create", account_id=account_id, values=serializer.validated_data
        )


class RebalancePlanExactAPIView(_RebalancePlanSessionAPIView):
    """Read one exact immutable plan revision by its server-issued identity."""

    http_method_names = ("get", "options")

    @typed_extend_schema(
        summary="读取一个精确调仓计划版本",
        description="需要原计划编号、版本和版本摘要；不会使用最新版本别名或写入业务状态。",
        parameters=_revision_query_parameters(),
        responses={
            200: RebalancePlanJourneyResponseSerializer,
            400: RebalancePlanErrorResponseSerializer,
            403: RebalancePlanErrorResponseSerializer,
            404: RebalancePlanErrorResponseSerializer,
            409: RebalancePlanErrorResponseSerializer,
            503: RebalancePlanErrorResponseSerializer,
        },
    )
    def get(self, request: Request, account_id: int, plan_id: str) -> Response:
        """Return only the revision matching all exact query pins."""

        if _PLAN_TOKEN_PATTERN.fullmatch(plan_id) is None:
            return _input_error("计划编号无效，请从计划列表重新选择。")
        values = _query_values(request, frozenset({"plan_version", "revision_hash"}))
        if values is None:
            return _input_error("请选择列表中的精确计划版本。")
        serializer = RebalancePlanExactRevisionRequestSerializer(data=values)
        if not serializer.is_valid():
            return _input_error("计划版本或摘要无效，请重新读取计划列表。")
        return _run(
            request,
            action="read",
            account_id=account_id,
            plan_id=plan_id,
            values=serializer.validated_data,
        )


class RebalancePlanReviewAPIView(_RebalancePlanSessionAPIView):
    """Record an explicit human review without activating execution authority."""

    http_method_names = ("post", "options")

    @typed_extend_schema(
        summary="人工复核一个调仓计划版本",
        description="只记录对精确计划版本的人工核对；不会启用该版本的订单执行权限。",
        request=RebalancePlanReviewRequestSerializer,
        parameters=[_idempotency_key_parameter()],
        responses={
            200: RebalancePlanJourneyResponseSerializer,
            400: RebalancePlanErrorResponseSerializer,
            403: RebalancePlanErrorResponseSerializer,
            404: RebalancePlanErrorResponseSerializer,
            409: RebalancePlanErrorResponseSerializer,
            503: RebalancePlanErrorResponseSerializer,
        },
    )
    def post(self, request: Request, account_id: int, plan_id: str) -> Response:
        """Persist only the review audit for a still-exact revision."""

        if _PLAN_TOKEN_PATTERN.fullmatch(plan_id) is None:
            return _input_error("计划编号无效，请重新读取计划。")
        values = _json_body(
            request,
            frozenset({"plan_version", "revision_hash", "confirmed"}),
        )
        if values is None:
            return _input_error()
        serializer = RebalancePlanReviewRequestSerializer(data=values)
        if not serializer.is_valid() or serializer.validated_data.get("confirmed") is not True:
            return _input_error("请明确确认人工复核；复核不会开通订单执行。")
        return _run(
            request,
            action="review",
            account_id=account_id,
            plan_id=plan_id,
            values=serializer.validated_data,
        )


class RebalancePlanSuccessorAPIView(_RebalancePlanSessionAPIView):
    """Create a reviewed successor from fresh server inputs after plan progress changes."""

    http_method_names = ("post", "options")

    @typed_extend_schema(
        summary="按当前事实生成调仓计划后继版本",
        description=(
            "仅基于精确父版本、实际成交进度和当前服务器来源生成后继；"
            "数量、价格、费用、现金或持仓事实不接受客户端输入。"
        ),
        request=RebalancePlanSuccessorRequestSerializer,
        parameters=[_idempotency_key_parameter()],
        responses={
            200: RebalancePlanJourneyResponseSerializer,
            400: RebalancePlanErrorResponseSerializer,
            403: RebalancePlanErrorResponseSerializer,
            404: RebalancePlanErrorResponseSerializer,
            409: RebalancePlanErrorResponseSerializer,
            503: RebalancePlanErrorResponseSerializer,
        },
    )
    def post(self, request: Request, account_id: int, plan_id: str) -> Response:
        """Submit an explicit successor request without reviving old approval."""

        if _PLAN_TOKEN_PATTERN.fullmatch(plan_id) is None:
            return _input_error("计划编号无效，请重新读取计划。")
        values = _json_body(
            request,
            frozenset(
                {
                    "plan_version",
                    "revision_hash",
                    "confirmed",
                    "target_weights",
                    "reference_price_basis",
                }
            ),
        )
        if values is None:
            return _input_error()
        serializer = RebalancePlanSuccessorRequestSerializer(data=values)
        if not serializer.is_valid() or serializer.validated_data.get("confirmed") is not True:
            return _input_error("请明确确认创建后继版本，并选择精确父版本。")
        return _run(
            request,
            action="successor",
            account_id=account_id,
            plan_id=plan_id,
            values=serializer.validated_data,
        )


class RebalancePlanReconciliationAPIView(_RebalancePlanSessionAPIView):
    """Read actual fills, active holds and remaining plan quantities for one revision."""

    http_method_names = ("get", "options")

    @typed_extend_schema(
        summary="对账一个精确调仓计划版本",
        description=(
            "只读取已核验成交、仍有效的预留、已释放余量和账户事实；"
            "未成交卖出不计入可用资金，未知值保持未知。"
        ),
        parameters=_revision_query_parameters(),
        responses={
            200: RebalancePlanJourneyResponseSerializer,
            400: RebalancePlanErrorResponseSerializer,
            403: RebalancePlanErrorResponseSerializer,
            404: RebalancePlanErrorResponseSerializer,
            409: RebalancePlanErrorResponseSerializer,
            503: RebalancePlanErrorResponseSerializer,
        },
    )
    def get(self, request: Request, account_id: int, plan_id: str) -> Response:
        """Read the same exact revision's current ledger reconciliation."""

        if _PLAN_TOKEN_PATTERN.fullmatch(plan_id) is None:
            return _input_error("计划编号无效，请重新读取计划。")
        values = _query_values(request, frozenset({"plan_version", "revision_hash"}))
        if values is None:
            return _input_error("请选择列表中的精确计划版本。")
        serializer = RebalancePlanExactRevisionRequestSerializer(data=values)
        if not serializer.is_valid():
            return _input_error("计划版本或摘要无效，请重新读取计划列表。")
        return _run(
            request,
            action="reconcile",
            account_id=account_id,
            plan_id=plan_id,
            values=serializer.validated_data,
        )


class RebalancePlanOrderPreviewAPIView(_RebalancePlanSessionAPIView):
    """Preview one explicitly chosen quantity from one exact saved plan order."""

    http_method_names = ("post", "options")

    @typed_extend_schema(
        summary="预览一个调仓计划订单",
        description=(
            "只提交精确计划和订单绑定、用户选择数量及限价；证券身份和方向由服务器从计划行读取。"
            "预览不创建预留，确认仍走既有模拟订单流程。"
        ),
        request=RebalancePlanOrderPreviewRequestSerializer,
        parameters=[_idempotency_key_parameter()],
        responses={
            200: RebalancePlanJourneyResponseSerializer,
            400: RebalancePlanErrorResponseSerializer,
            403: RebalancePlanErrorResponseSerializer,
            404: RebalancePlanErrorResponseSerializer,
            409: RebalancePlanErrorResponseSerializer,
            503: RebalancePlanErrorResponseSerializer,
        },
    )
    def post(
        self,
        request: Request,
        account_id: int,
        plan_id: str,
        order_ordinal: int,
    ) -> Response:
        """Read exact plan pins and send only the user's single-line order intent."""

        if (
            _PLAN_TOKEN_PATTERN.fullmatch(plan_id) is None
            or type(order_ordinal) is not int
            or order_ordinal < 0
        ):
            return _input_error("计划订单编号无效，请从精确计划版本重新选择。")
        values = _json_body(
            request,
            frozenset(
                {
                    "plan_version",
                    "revision_hash",
                    "order_content_hash",
                    "plan_order_binding_id",
                    "quantity",
                    "limit_price",
                    "reason",
                }
            ),
        )
        if values is None:
            return _input_error()
        serializer = RebalancePlanOrderPreviewRequestSerializer(data=values)
        if not serializer.is_valid():
            return _input_error("数量、限价或计划订单版本无效，请重新读取。")
        return _run(
            request,
            action="preview_order",
            account_id=account_id,
            plan_id=plan_id,
            order_ordinal=order_ordinal,
            values=serializer.validated_data,
        )


__all__ = [
    "RebalancePlanCreateRequestSerializer",
    "RebalancePlanErrorResponseSerializer",
    "RebalancePlanExactAPIView",
    "RebalancePlanJourneyResponseSerializer",
    "RebalancePlanListCreateAPIView",
    "RebalancePlanOrderPreviewAPIView",
    "RebalancePlanReconciliationAPIView",
    "RebalancePlanReviewAPIView",
    "RebalancePlanSuccessorAPIView",
]
