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

from apps.signal.infrastructure.models import InvestmentSignalModel
from apps.signal.application.use_cases import ValidateSignalUseCase
from .serializers import (
    InvestmentSignalSerializer,
    InvestmentSignalCreateSerializer,
    InvestmentSignalValidateRequestSerializer,
    InvestmentSignalValidateResponseSerializer,
    SignalListQuerySerializer,
)


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

    queryset = InvestmentSignalModel.objects.all()
    serializer_class = InvestmentSignalSerializer

    def get_serializer_class(self):
        """根据操作选择 serializer"""
        if self.action == 'create':
            return InvestmentSignalCreateSerializer
        return InvestmentSignalSerializer

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

    @action(detail=False, methods=['post'])
    def check_eligibility(self, request):
        """
        检查信号准入（不创建信号）

        POST /api/signal/check_eligibility/
        {
            "asset_code": "000001.SH",
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

            # 创建临时信号对象
            from apps.signal.domain.entities import InvestmentSignal
            from apps.signal.domain.rules import check_eligibility, should_reject_signal
            from apps.regime.infrastructure.repositories import DjangoRegimeRepository

            # 获取当前 Regime
            regime_repo = DjangoRegimeRepository()
            current_regime = regime_repo.get_latest_regime()

            if not current_regime:
                return Response({
                    'success': False,
                    'error': 'No regime data available'
                }, status=status.HTTP_400_BAD_REQUEST)

            # 检查准入
            eligibility = check_eligibility(
                asset_code=data.get('asset_code', ''),
                current_regime=current_regime.dominant_regime
            )

            rejection_reason = None
            if should_reject_signal(eligibility):
                rejection_reason = f"当前 Regime ({current_regime.dominant_regime}) 对该资产不友好"

            return Response({
                'success': True,
                'is_eligible': not should_reject_signal(eligibility),
                'eligibility': eligibility.value if eligibility else None,
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
        total = InvestmentSignalModel.objects.count()
        return {
            'total': total,
            'pending': InvestmentSignalModel.objects.filter(status='pending').count(),
            'approved': InvestmentSignalModel.objects.filter(status='approved').count(),
            'rejected': InvestmentSignalModel.objects.filter(status='rejected').count(),
            'invalidated': InvestmentSignalModel.objects.filter(status='invalidated').count(),
        }


class SignalHealthView(APIView):
    """Signal 服务健康检查"""

    def get(self, request):
        """检查 Signal 服务健康状态"""
        try:
            count = InvestmentSignalModel.objects.count()

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
