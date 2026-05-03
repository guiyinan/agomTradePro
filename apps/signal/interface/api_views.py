"""
DRF API Views for Signal Management.

提供 RESTful API 接口用于投资信号管理。
"""

from rest_framework import status, viewsets
from rest_framework.decorators import action
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


class SignalViewSet(viewsets.GenericViewSet):
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

    def get_serializer_class(self):
        """根据操作选择 serializer"""
        if self.action == "create":
            return InvestmentSignalCreateSerializer
        if self.action in {"update", "partial_update"}:
            return InvestmentSignalUpdateSerializer
        return InvestmentSignalSerializer

    def _build_list_response(self, request, *, status_override: str | None = None):
        """Return a filtered signal list response."""

        query_serializer = SignalListQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        data = query_serializer.validated_data
        signals = list_investment_signal_payloads(
            status_filter=status_override if status_override is not None else data.get("status") or "",
            asset_class=data.get("asset_class") or "",
            direction=data.get("direction") or "",
            search=data.get("search") or "",
            limit=data.get("limit", 50),
        )
        return Response(InvestmentSignalSerializer(signals, many=True).data)

    def list(self, request):
        """List signals via application query services."""
        return self._build_list_response(request)

    @action(detail=False, methods=["get"])
    def active(self, request):
        """Return approved signals for backward-compatible clients."""

        return self._build_list_response(request, status_override="approved")

    def retrieve(self, request, pk=None):
        """Retrieve one signal payload."""

        signal = get_investment_signal_payload(str(pk))
        if signal is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(InvestmentSignalSerializer(signal).data)

    def create(self, request, *args, **kwargs):
        """创建信号后统一返回标准输出结构。"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        signal = serializer.save()
        return Response(
            InvestmentSignalSerializer(signal).data,
            status=status.HTTP_201_CREATED,
        )

    def update(self, request, pk=None):
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

    def partial_update(self, request, pk=None):
        """Treat PATCH as the same partial-field update path."""

        return self.update(request, pk=pk)

    def destroy(self, request, pk=None):
        """Delete one signal via application query services."""

        from apps.signal.application.query_services import delete_investment_signal_record

        asset_code = delete_investment_signal_record(str(pk))
        if asset_code is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'])
    def validate(self, request, pk=None):
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

        except Exception as e:
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        """审批信号。"""
        signal = update_investment_signal_status(
            signal_id=str(pk),
            status="approved",
            rejection_reason="",
        )
        if signal is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(InvestmentSignalSerializer(signal).data)

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        """拒绝信号。"""
        reason = request.data.get('reason', '手动拒绝')
        signal = update_investment_signal_status(
            signal_id=str(pk),
            status="rejected",
            rejection_reason=reason,
        )
        if signal is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(InvestmentSignalSerializer(signal).data)

    @action(detail=True, methods=['post'])
    def invalidate(self, request, pk=None):
        """证伪信号。"""
        reason = request.data.get('reason', '手动证伪')
        signal = update_investment_signal_status(
            signal_id=str(pk),
            status="invalidated",
            rejection_reason=reason,
        )
        if signal is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(InvestmentSignalSerializer(signal).data)

    @action(detail=False, methods=['post'])
    def check_eligibility(self, request):
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
        try:
            request_serializer = InvestmentSignalValidateRequestSerializer(data=request.data)
            request_serializer.is_valid(raise_exception=True)
            try:
                result = validate_signal_eligibility_payload(request_serializer.validated_data)
            except LookupError as exc:
                return Response(
                    {'success': False, 'error': str(exc)},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            return Response(result)

        except Exception as e:
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['get'])
    def stats(self, request):
        """
        获取信号统计信息

        GET /api/signal/stats/
        """
        try:
            return Response({
                'success': True,
                'stats': get_signal_stats_payload()
            })

        except Exception as e:
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class SignalHealthView(APIView):
    """Signal 服务健康检查"""

    def get(self, request):
        """检查 Signal 服务健康状态"""
        try:
            return Response(get_signal_health_payload(), status=status.HTTP_200_OK)

        except Exception as e:
            return Response({
                'status': 'unhealthy',
                'service': 'signal',
                'error': str(e)
            }, status=status.HTTP_503_SERVICE_UNAVAILABLE)

