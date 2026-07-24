"""
DRF API Views for Signal Management.

提供 RESTful API 接口用于投资信号管理。
"""

import logging
from typing import Any, cast

from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, BasePermission, IsAdminUser, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.signal.application.query_services import (
    get_investment_signal_payload,
    get_signal_health_payload,
    get_signal_stats_payload,
    list_investment_signal_payloads,
    update_investment_signal_payload,
    update_investment_signal_status,
    validate_existing_signal_payload,
    validate_signal_eligibility_payload,
)

from .serializers import (
    InvestmentSignalCreateSerializer,
    InvestmentSignalSerializer,
    InvestmentSignalUpdateSerializer,
    InvestmentSignalValidateRequestSerializer,
    InvestmentSignalValidateResponseSerializer,
    SignalListQuerySerializer,
)

logger = logging.getLogger(__name__)


class SignalViewSet(viewsets.GenericViewSet[Any]):
    """
    Signal API ViewSet

    提供以下接口:
    - GET /api/signal/ - 获取信号列表
    - GET /api/signal/active/ - 获取已批准信号（兼容旧调用）
    - POST /api/signal/ - 创建信号
    - GET /api/signal/{id}/ - 获取信号详情
    - PUT /api/signal/{id}/ - 更新信号
    - DELETE /api/signal/{id}/ - 删除信号
    - POST /api/signal/{id}/validate/ - 验证信号准入
    - POST /api/signal/check_eligibility/ - 检查信号准入
    """

    serializer_class = InvestmentSignalSerializer
    permission_classes: list[type[BasePermission]] = [IsAuthenticated]

    def get_permissions(self) -> list[BasePermission]:
        """Restrict actionable signal mutations to administrators."""

        if self.action in {
            "approve",
            "create",
            "destroy",
            "invalidate",
            "partial_update",
            "reject",
            "update",
        }:
            return [IsAdminUser()]
        return [IsAuthenticated()]

    def get_serializer_class(self) -> type[serializers.BaseSerializer[Any]]:
        """根据操作选择 serializer"""
        if self.action == "create":
            return InvestmentSignalCreateSerializer
        if self.action in {"update", "partial_update"}:
            return InvestmentSignalUpdateSerializer
        return InvestmentSignalSerializer

    def _build_list_response(
        self,
        request: Request,
        *,
        status_override: str | None = None,
    ) -> Response:
        """Return a filtered signal list response."""

        query_serializer = SignalListQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        data = query_serializer.validated_data
        signals = list_investment_signal_payloads(
            status_filter=(
                status_override if status_override is not None else data.get("status") or ""
            ),
            asset_class=data.get("asset_class") or "",
            direction=data.get("direction") or "",
            search=data.get("search") or "",
            include_test=data.get("include_test", False),
            limit=data.get("limit", 50),
        )
        return Response(InvestmentSignalSerializer(cast(Any, signals), many=True).data)

    def list(self, request: Request) -> Response:
        """List signals via application query services."""
        return self._build_list_response(request)

    @action(detail=False, methods=["get"])
    def active(self, request: Request) -> Response:
        """Return approved signals for backward-compatible clients."""

        return self._build_list_response(request, status_override="approved")

    def retrieve(self, request: Request, pk: str | None = None) -> Response:
        """Retrieve one signal payload."""

        signal = get_investment_signal_payload(str(pk))
        if signal is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(InvestmentSignalSerializer(signal).data)

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """创建信号后统一返回标准输出结构。"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        signal = serializer.save()
        return Response(
            InvestmentSignalSerializer(signal).data,
            status=status.HTTP_201_CREATED,
        )

    def update(self, request: Request, pk: str | None = None) -> Response:
        """Update one signal via application query services."""

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            signal = update_investment_signal_payload(str(pk), **serializer.validated_data)
        except ValueError as exc:
            return Response(
                {"invalidation_logic": [str(exc)]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if signal is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(InvestmentSignalSerializer(signal).data)

    def partial_update(self, request: Request, pk: str | None = None) -> Response:
        """Treat PATCH as the same partial-field update path."""

        return self.update(request, pk=pk)

    def destroy(self, request: Request, pk: str | None = None) -> Response:
        """Delete one signal via application query services."""

        from apps.signal.application.query_services import delete_investment_signal_record

        asset_code = delete_investment_signal_record(str(pk))
        if asset_code is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    def validate(self, request: Request, pk: str | None = None) -> Response:
        """
        验证信号准入状态

        POST /api/signal/{id}/validate/
        """
        try:
            result = validate_existing_signal_payload(str(pk))
            if result is None:
                return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
            response_serializer = InvestmentSignalValidateResponseSerializer(result)
            return Response(response_serializer.data)

        except Exception:
            logger.exception("Signal validation failed")
            return Response(
                {"success": False, "error": "Signal validation failed"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=True, methods=["post"])
    def approve(self, request: Request, pk: str | None = None) -> Response:
        """审批信号。"""
        signal = update_investment_signal_status(
            signal_id=str(pk),
            status="approved",
            rejection_reason="",
        )
        if signal is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(InvestmentSignalSerializer(signal).data)

    @action(detail=True, methods=["post"])
    def reject(self, request: Request, pk: str | None = None) -> Response:
        """拒绝信号。"""
        reason = request.data.get("reason", "手动拒绝")
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 1000:
            return Response(
                {"reason": ["reason must be a non-empty string up to 1000 characters"]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        signal = update_investment_signal_status(
            signal_id=str(pk),
            status="rejected",
            rejection_reason=reason.strip(),
        )
        if signal is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(InvestmentSignalSerializer(signal).data)

    @action(detail=True, methods=["post"])
    def invalidate(self, request: Request, pk: str | None = None) -> Response:
        """证伪信号。"""
        reason = request.data.get("reason", "手动证伪")
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 1000:
            return Response(
                {"reason": ["reason must be a non-empty string up to 1000 characters"]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        signal = update_investment_signal_status(
            signal_id=str(pk),
            status="invalidated",
            rejection_reason=reason.strip(),
        )
        if signal is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(InvestmentSignalSerializer(signal).data)

    @action(detail=False, methods=["post"])
    def check_eligibility(self, request: Request) -> Response:
        """
        检查信号准入（不创建信号）

        POST /api/signal/check_eligibility/
        {
            "asset_code": "ASSET_CODE",
            "logic_desc": "PMI 回升，看好大盘",
            "invalidation_logic": "PMI 跌破 50",
            "invalidation_threshold": 49.5
        }
        """
        request_serializer = InvestmentSignalValidateRequestSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        try:
            result = validate_signal_eligibility_payload(request_serializer.validated_data)
        except LookupError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception:
            logger.exception("Signal eligibility check failed")
            return Response(
                {"success": False, "error": "Signal eligibility check failed"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        return Response(result)

    @action(detail=False, methods=["get"])
    def stats(self, request: Request) -> Response:
        """
        获取信号统计信息

        GET /api/signal/stats/
        """
        try:
            return Response({"success": True, "stats": get_signal_stats_payload()})

        except Exception:
            logger.exception("Signal statistics query failed")
            return Response(
                {"success": False, "error": "Signal statistics query failed"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class SignalHealthView(APIView):
    """Signal 服务健康检查"""

    permission_classes: list[type[BasePermission]] = [AllowAny]

    def get(self, request: Request) -> Response:
        """检查 Signal 服务健康状态"""
        try:
            return Response(get_signal_health_payload(), status=status.HTTP_200_OK)

        except Exception as e:
            return Response(
                {"status": "unhealthy", "service": "signal", "error": str(e)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
