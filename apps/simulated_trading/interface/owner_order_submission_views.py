"""Session-authenticated preview and explicit confirmation of local paper orders."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, cast
from uuid import uuid4

from rest_framework import serializers, status
from rest_framework.exceptions import ParseError, UnsupportedMediaType
from rest_framework.parsers import JSONParser
from rest_framework.request import Request
from rest_framework.response import Response

from apps.simulated_trading.application.manual_trade_execution import ManualSimulatedTradeRequest
from apps.simulated_trading.application.order_submission_market import OwnerOrderStoredReadback
from apps.simulated_trading.application.owner_order_submission import (
    OwnerOrderPreview,
    OwnerOrderSubmissionResult,
)
from apps.simulated_trading.domain.execution_settlement_uow import SimulatedTradeSide
from apps.simulated_trading.owner_order_submission_composition import (
    build_owner_order_submission_use_case,
)

from .owner_order_operation_response import OwnerOrderOperationErrorResponseSerializer
from .owner_order_operation_views import _input_error, _OwnerOrderOperationAPIView
from .sdk_contract_views import typed_extend_schema

_LOCAL_MARKET_PURPOSE = "local_simulation_only"
_CLOSE_MARKET_PURPOSE = "close_snapshot_simulation"
_SUPPORTED_MARKET_PURPOSES = (_LOCAL_MARKET_PURPOSE, _CLOSE_MARKET_PURPOSE)
_CLOSE_MARKET_NOTICE = "使用新浪供应商盘后末笔报价进行本地模拟；该报价不是官方收盘价。"


class OwnerOrderDraftSerializer(serializers.Serializer[dict[str, object]]):
    """Describe user intent; security mapping, clocks and source facts stay server-owned."""

    asset_code = serializers.CharField(max_length=100)
    asset_name = serializers.CharField(max_length=100)
    side = serializers.ChoiceField(choices=("buy", "sell"))
    quantity = serializers.DecimalField(max_digits=22, decimal_places=6)
    limit_price = serializers.DecimalField(max_digits=20, decimal_places=6)
    fee_budget = serializers.DecimalField(
        max_digits=18, decimal_places=2, allow_null=True, required=False
    )
    reason = serializers.CharField(max_length=200, allow_blank=True, required=False)
    market_purpose = serializers.ChoiceField(
        choices=_SUPPORTED_MARKET_PURPOSES,
        required=False,
        default=_LOCAL_MARKET_PURPOSE,
    )


class OwnerOrderConfirmSerializer(serializers.Serializer[dict[str, object]]):
    """Confirm the exact original preview, retaining its server-created order key."""

    preview_token = serializers.CharField(max_length=131072, trim_whitespace=False)
    confirmed = serializers.BooleanField()
    market_purpose = serializers.ChoiceField(
        choices=_SUPPORTED_MARKET_PURPOSES,
        required=False,
    )


class OwnerOrderSubmissionResponseSerializer(serializers.Serializer[dict[str, object]]):
    """Publish local order resources and safe provenance without raw source bodies."""

    success = serializers.BooleanField()
    outcome = serializers.CharField()
    execution_submitted = serializers.BooleanField()
    purpose = serializers.CharField()
    market_purpose = serializers.CharField()
    message = serializers.CharField()
    continuation = serializers.JSONField(required=False)
    order_id = serializers.IntegerField(required=False)
    account_id = serializers.IntegerField()
    order_key = serializers.CharField(required=False)
    replayed = serializers.BooleanField()
    order = serializers.JSONField()
    market = serializers.JSONField(required=False)
    market_qualification = serializers.JSONField(required=False)
    market_notice = serializers.CharField(required=False)

    def get_fields(self) -> dict[str, serializers.Field[Any, Any, Any, Any]]:
        """Declare the JSON flag without shadowing DRF's own read_only attribute."""
        fields = super().get_fields()
        fields["read_only"] = serializers.BooleanField()
        return fields


def _payload(
    request: Request, *, allowed: frozenset[str], required: frozenset[str]
) -> dict[str, object] | None:
    """Accept exactly the declared JSON intent fields and no query parameters."""
    if request.content_type != JSONParser.media_type or request.query_params:
        return None
    try:
        value = request.data
    except (ParseError, UnsupportedMediaType):
        return None
    if type(value) is not dict or any(type(key) is not str for key in value):
        return None
    values = cast(dict[str, object], value)
    if not required <= set(values) <= allowed:
        return None
    return values


def _response_payload(result: OwnerOrderPreview | OwnerOrderSubmissionResult) -> dict[str, object]:
    """Format reviewed or durable resources while preserving unknown cash as null."""
    preview = isinstance(result, OwnerOrderPreview)
    reserved = result.result.reservation
    book = result.result.book
    payload: dict[str, object] = {
        "success": True,
        "outcome": "success",
        "read_only": preview,
        "account_id": reserved.identity.account_id,
        "order_key": reserved.identity.idempotency_key,
        "execution_submitted": False,
        "purpose": (
            result.market_receipt["purpose"]
            if isinstance(result, OwnerOrderPreview)
            else result.purpose
        ),
        "message": (
            "请核对数量、费用和预留后确认"
            if preview
            else (
                "已核对原订单，未重复预留；请查看当前状态"
                if result.result.replayed
                else "订单已预留，尚未成交；可在订单历史继续操作"
            )
        ),
        "replayed": result.result.replayed,
        "order": {
            "idempotency_key": reserved.identity.idempotency_key,
            "security_id": reserved.identity.security_id,
            "side": reserved.side.value,
            "quantity": str(reserved.quantity),
            "limit_price": str(reserved.limit_price),
            "notional": str(reserved.notional),
            "fee_estimate": str(reserved.fee_estimate),
            "fee_budget": str(reserved.fee_budget) if reserved.fee_budget is not None else None,
            "cash_reserved": str(reserved.cash_reserved),
            "shares_reserved": str(reserved.shares_reserved),
            "available_cash": str(book.available_cash) if book.available_cash is not None else None,
            "available_shares": (
                str(book.available_shares) if book.available_shares is not None else None
            ),
            "withdrawable_cash": (
                str(book.withdrawable_cash) if book.withdrawable_cash is not None else None
            ),
            "status": reserved.status.value,
        },
    }
    purpose = cast(str, payload["purpose"])
    if purpose not in _SUPPORTED_MARKET_PURPOSES:
        raise ValueError("订单回执行情用途无效")
    payload["market_purpose"] = purpose
    if purpose == _CLOSE_MARKET_PURPOSE:
        payload["market_notice"] = _CLOSE_MARKET_NOTICE
    if isinstance(result, OwnerOrderPreview):
        payload["continuation"] = {
            "action_key": "simulated-trading.order-confirm",
            "input": {
                "account_id": str(reserved.identity.account_id),
                "order_key": reserved.identity.idempotency_key,
                "preview_token": result.token,
            },
            "expires_at": result.expires_at.isoformat(),
        }
        market = result.market_receipt.get("market")
        if type(market) is dict:
            market_values = cast(dict[str, object], market)
            evidence = market_values.get("market_evidence_v1")
            if type(evidence) is dict:
                values = cast(dict[str, object], evidence)
                market_view: dict[str, object] = {
                    key: values.get(key)
                    for key in (
                        "market_source_id",
                        "market_observed_at",
                        "market_available_at",
                        "market_valid_until",
                        "security_state",
                        "reference_price",
                        "lower_limit_price",
                        "upper_limit_price",
                        "price_boundary_mode",
                        "session_state",
                    )
                }
                market_view["market_session"] = values.get("session_state")
                market_view["trade_date"] = values.get("trading_date")
                if purpose == _CLOSE_MARKET_PURPOSE:
                    snapshot_kind = market_values.get("price_observation_kind")
                    provenance = result.market_receipt.get("provenance")
                    if type(provenance) is not dict:
                        raise ValueError("盘后来源回执缺少来源凭据")
                    retained_bundle = cast(dict[str, object], provenance).get(
                        "retained_market_bundle"
                    )
                    if type(retained_bundle) is not dict:
                        raise ValueError("盘后来源回执缺少保留行情包")
                    policy = cast(dict[str, object], retained_bundle).get("policy")
                    if type(policy) is not dict:
                        raise ValueError("盘后来源回执缺少价格规则")
                    price_rule = cast(dict[str, object], policy).get("price_rule")
                    if type(snapshot_kind) is not str or type(price_rule) is not str:
                        raise ValueError("盘后来源回执类型无效")
                    market_view["snapshot_kind"] = snapshot_kind
                    market_view["price_rule"] = price_rule
                payload["market"] = market_view
                payload["market_qualification"] = result.market_receipt["qualification"]
                if purpose == _LOCAL_MARKET_PURPOSE:
                    payload["market_notice"] = (
                        "新浪报告状态；价界按明确配置推导，仅用于本地模拟。"
                        "可用时点为本地接收完成时间，不是新浪发布时间"
                    )
    else:
        payload["order_id"] = result.order_id
    return payload


class OwnerOrderPreviewAPIView(_OwnerOrderOperationAPIView):
    """Preview a new order with an explicit source capture and no ledger writes."""

    @typed_extend_schema(
        summary="预览本人模拟订单",
        request=OwnerOrderDraftSerializer,
        responses={
            200: OwnerOrderSubmissionResponseSerializer,
            400: OwnerOrderOperationErrorResponseSerializer,
            403: OwnerOrderOperationErrorResponseSerializer,
            404: OwnerOrderOperationErrorResponseSerializer,
            409: OwnerOrderOperationErrorResponseSerializer,
            503: OwnerOrderOperationErrorResponseSerializer,
        },
    )
    def post(self, request: Request, account_id: int) -> Response:
        """Validate intent and active session before asking the application for a preview."""
        actor = self._actor_id(request)
        if isinstance(actor, Response):
            return actor
        values = _payload(
            request,
            allowed=frozenset(
                {
                    "asset_code",
                    "asset_name",
                    "side",
                    "quantity",
                    "limit_price",
                    "fee_budget",
                    "reason",
                    "market_purpose",
                }
            ),
            required=frozenset({"asset_code", "asset_name", "side", "quantity", "limit_price"}),
        )
        if type(account_id) is not int or account_id <= 0 or values is None:
            return _input_error()
        serializer = OwnerOrderDraftSerializer(data=values)
        if not serializer.is_valid():
            return _input_error()
        data = serializer.validated_data
        market_purpose = cast(str, data["market_purpose"])
        try:
            use_case = (
                build_owner_order_submission_use_case()
                if market_purpose == _LOCAL_MARKET_PURPOSE
                else build_owner_order_submission_use_case(market_purpose=market_purpose)
            )
            result = use_case.preview(
                ManualSimulatedTradeRequest(
                    account_id=account_id,
                    user_id=actor,
                    idempotency_key=f"owner-order:{uuid4().hex}",
                    asset_code=cast(str, data["asset_code"]),
                    asset_name=cast(str, data["asset_name"]),
                    asset_type="equity",
                    side=SimulatedTradeSide(cast(str, data["side"])),
                    quantity=cast(Decimal, data["quantity"]),
                    price=cast(Decimal, data["limit_price"]),
                    reason=cast(str, data.get("reason", "")),
                    signal_id=None,
                ),
                fee_budget=cast(Decimal | None, data.get("fee_budget")),
            )
        except Exception as error:
            response = self._handle_error(error, operation="preview")
            if type(response.data) is dict:
                response.data["effects_indeterminate"] = False
                response.data["read_only"] = True
            return response
        return Response(_response_payload(result), status=status.HTTP_200_OK)


class OwnerOrderConfirmAPIView(_OwnerOrderOperationAPIView):
    """Commit or recover the exact signed order; no source facts are caller inputs."""

    @typed_extend_schema(
        summary="确认本人模拟订单预留",
        request=OwnerOrderConfirmSerializer,
        responses={
            200: OwnerOrderSubmissionResponseSerializer,
            400: OwnerOrderOperationErrorResponseSerializer,
            403: OwnerOrderOperationErrorResponseSerializer,
            404: OwnerOrderOperationErrorResponseSerializer,
            409: OwnerOrderOperationErrorResponseSerializer,
            503: OwnerOrderOperationErrorResponseSerializer,
        },
    )
    def post(self, request: Request, account_id: int, order_key: str) -> Response:
        """Accept only literal confirmation and the complete original preview token."""
        actor = self._actor_id(request)
        if isinstance(actor, Response):
            return actor
        values = _payload(
            request,
            allowed=frozenset({"preview_token", "confirmed", "market_purpose"}),
            required=frozenset({"preview_token", "confirmed"}),
        )
        if (
            type(account_id) is not int
            or account_id <= 0
            or values is None
            or values["confirmed"] is not True
        ):
            return _input_error()
        serializer = OwnerOrderConfirmSerializer(data=values)
        if not serializer.is_valid():
            return _input_error()
        try:
            result = build_owner_order_submission_use_case().confirm(
                account_id=account_id,
                user_id=actor,
                token=cast(str, serializer.validated_data["preview_token"]),
                confirmed=True,
                expected_key=order_key,
                market_purpose=cast(
                    str | None,
                    serializer.validated_data.get("market_purpose"),
                ),
            )
        except Exception as error:
            return self._handle_error(error, operation="reserve")
        return Response(_response_payload(result), status=status.HTTP_200_OK)


class OwnerOrderReadbackAPIView(_OwnerOrderOperationAPIView):
    """Read the original order after a lost response without authorizing a retry."""

    @typed_extend_schema(
        summary="核对本人原预览的模拟订单",
        responses={
            200: OwnerOrderSubmissionResponseSerializer,
            400: OwnerOrderOperationErrorResponseSerializer,
            403: OwnerOrderOperationErrorResponseSerializer,
            404: OwnerOrderOperationErrorResponseSerializer,
            503: OwnerOrderOperationErrorResponseSerializer,
        },
    )
    def get(self, request: Request, account_id: int, order_key: str) -> Response:
        """Use the non-secret owner-scoped locator without reading or refreshing market data."""
        actor = self._actor_id(request)
        if isinstance(actor, Response):
            return actor
        query = request.query_params
        purpose_values = query.getlist("market_purpose")
        if (
            type(account_id) is not int
            or account_id <= 0
            or set(query.keys()) - {"market_purpose"}
            or len(purpose_values) > 1
        ):
            return _input_error()
        market_purpose = purpose_values[0] if purpose_values else None
        if market_purpose is not None and market_purpose not in _SUPPORTED_MARKET_PURPOSES:
            return _input_error()
        try:
            result = build_owner_order_submission_use_case().readback(
                account_id=account_id,
                user_id=actor,
                order_key=order_key,
                market_purpose=market_purpose,
            )
        except Exception as error:
            response = self._handle_error(error, operation="recover")
            if type(response.data) is dict:
                response.data["read_only"] = True
            return response
        return Response(_readback_payload(result), status=status.HTTP_200_OK)


def _readback_payload(result: OwnerOrderStoredReadback) -> dict[str, object]:
    """Describe the original order state without inventing current account balances."""
    order = result.reservation
    payload: dict[str, object] = {
        "success": True,
        "outcome": "success",
        "read_only": True,
        "execution_submitted": False,
        "purpose": result.market_purpose,
        "market_purpose": result.market_purpose,
        "message": "已找到原订单；未创建新单或重新读取行情",
        "account_id": order.identity.account_id,
        "order_key": order.identity.idempotency_key,
        "order_id": result.order_id,
        "replayed": True,
        "order": {
            "idempotency_key": order.identity.idempotency_key,
            "security_id": order.identity.security_id,
            "side": order.side.value,
            "quantity": str(order.quantity),
            "limit_price": str(order.limit_price),
            "fee_estimate": str(order.fee_estimate),
            "status": order.status.value,
            "filled_quantity": str(order.filled_quantity),
            "cash_reserved": str(order.cash_reserved),
            "shares_reserved": str(order.shares_reserved),
            "cash_released": str(order.cash_released),
            "shares_released": str(order.shares_released),
            "reserved_at": order.reserved_at.isoformat(),
        },
    }
    if result.market_purpose == _CLOSE_MARKET_PURPOSE:
        payload["market_notice"] = f"{_CLOSE_MARKET_NOTICE} 当前回读不刷新行情。"
    elif result.market_purpose != _LOCAL_MARKET_PURPOSE:
        raise ValueError("订单回读行情用途无效")
    return payload
