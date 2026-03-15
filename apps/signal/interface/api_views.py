"""
DRF API Views for Signal Management.

提供 RESTful API 接口用于投资信号管理。
"""

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone

from apps.signal.infrastructure.models import InvestmentSignalModel
from apps.signal.application.use_cases import ValidateSignalUseCase
from .serializers import (
    InvestmentSignalSerializer,
    InvestmentSignalCreateSerializer,
    InvestmentSignalValidateRequestSerializer,
    InvestmentSignalValidateResponseSerializer,
    SignalListQuerySerializer,
)


def _infer_asset_class(asset_code: str) -> str:
    """
    根据资产代码推断资产类别。

    说明:
    - 当前用于 check_eligibility 快速检查场景，优先保证接口稳定可用。
    - 无法精确识别时默认按 A 股权益处理。
    """
    code = (asset_code or "").upper()

    if code.startswith(("511", "128", "019")):
        return "china_bond"
    if code.startswith(("518", "159934")):
        return "gold"
    if code.startswith(("159985", "510170")):
        return "commodity"
    if code.startswith(("511880", "511990")):
        return "cash"
    return "a_share_growth"


class SignalViewSet(viewsets.ModelViewSet):
    """
    Signal API ViewSet

    提供以下接口:
    - GET /api/signal/ - 获取信号列表
    - POST /api/signal/ - 创建信号
    - GET /api/signal/{id}/ - 获取信号详情
    - PUT /api/signal/{id}/ - 更新信号
    - DELETE /api/signal/{id}/ - 删除信号
    - POST /api/signal/{id}/validate/ - 验证信号准入
    - POST /api/signal/check_eligibility/ - 检查信号准入
    """

    queryset = InvestmentSignalModel._default_manager.all()
    serializer_class = InvestmentSignalSerializer

    def get_serializer_class(self):
        """根据操作选择 serializer"""
        if self.action == 'create':
            return InvestmentSignalCreateSerializer
        return InvestmentSignalSerializer

    def create(self, request, *args, **kwargs):
        """创建信号后统一返回标准输出结构。"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        signal = serializer.save()
        return Response(
            InvestmentSignalSerializer(signal).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['post'])
    def validate(self, request, pk=None):
        """
        验证信号准入状态

        POST /api/signal/{id}/validate/
        """
        try:
            signal = get_object_or_404(InvestmentSignalModel, pk=pk)

            use_case = ValidateSignalUseCase()
            result = use_case.execute(signal)

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
        signal = get_object_or_404(InvestmentSignalModel, pk=pk)
        signal.status = 'approved'
        signal.rejection_reason = ''
        signal.save(update_fields=['status', 'rejection_reason', 'updated_at'])
        return Response(InvestmentSignalSerializer(signal).data)

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        """拒绝信号。"""
        signal = get_object_or_404(InvestmentSignalModel, pk=pk)
        reason = request.data.get('reason', '手动拒绝')
        signal.status = 'rejected'
        signal.rejection_reason = reason
        signal.save(update_fields=['status', 'rejection_reason', 'updated_at'])
        return Response(InvestmentSignalSerializer(signal).data)

    @action(detail=True, methods=['post'])
    def invalidate(self, request, pk=None):
        """证伪信号。"""
        signal = get_object_or_404(InvestmentSignalModel, pk=pk)
        reason = request.data.get('reason', '手动证伪')
        signal.status = 'invalidated'
        signal.rejection_reason = reason
        signal.invalidated_at = timezone.now()
        signal.save(update_fields=['status', 'rejection_reason', 'invalidated_at', 'updated_at'])
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
            # 验证请求
            request_serializer = InvestmentSignalValidateRequestSerializer(data=request.data)
            request_serializer.is_valid(raise_exception=True)
            data = request_serializer.validated_data

            from apps.signal.domain.rules import check_eligibility
            from apps.regime.application.current_regime import resolve_current_regime

            # 获取当前 Regime
            current_regime = resolve_current_regime()

            if not current_regime or current_regime.dominant_regime == "Unknown":
                return Response({
                    'success': False,
                    'error': 'No regime data available'
                }, status=status.HTTP_400_BAD_REQUEST)

            asset_code = data.get('asset_code', '')
            asset_class = _infer_asset_class(asset_code)

            eligibility = check_eligibility(
                asset_class=asset_class,
                regime=current_regime.dominant_regime
            )

            is_eligible = eligibility.value != 'hostile'
            rejection_reason = None if is_eligible else (
                f"当前 Regime ({current_regime.dominant_regime}) 对资产类别 {asset_class} 不友好"
            )

            return Response({
                'success': True,
                'is_eligible': is_eligible,
                'eligibility': eligibility.value if eligibility else None,
                'regime_match': is_eligible,
                'policy_match': True,
                'current_regime': current_regime.dominant_regime,
                'rejection_reason': rejection_reason
            })

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
            stats = self._get_stats()
            return Response({
                'success': True,
                'stats': stats
            })

        except Exception as e:
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def _get_stats(self) -> dict:
        """获取统计信息"""
        total = InvestmentSignalModel._default_manager.count()
        return {
            'total': total,
            'pending': InvestmentSignalModel._default_manager.filter(status='pending').count(),
            'approved': InvestmentSignalModel._default_manager.filter(status='approved').count(),
            'rejected': InvestmentSignalModel._default_manager.filter(status='rejected').count(),
            'invalidated': InvestmentSignalModel._default_manager.filter(status='invalidated').count(),
        }


class SignalHealthView(APIView):
    """Signal 服务健康检查"""

    def get(self, request):
        """检查 Signal 服务健康状态"""
        try:
            count = InvestmentSignalModel._default_manager.count()

            return Response({
                'status': 'healthy',
                'service': 'signal',
                'records_count': count
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({
                'status': 'unhealthy',
                'service': 'signal',
                'error': str(e)
            }, status=status.HTTP_503_SERVICE_UNAVAILABLE)

