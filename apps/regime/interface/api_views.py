"""
DRF API Views for Regime Calculation.

提供 RESTful API 接口用于 Regime 判定。

重构说明 (2026-03-11):
- 使用 MacroRepositoryAdapter 替代直接导入 DjangoMacroRepository
- 保持 API 完全兼容
"""

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from datetime import date
from django.utils import timezone

from apps.regime.application.current_regime import resolve_current_regime
from apps.regime.application.use_cases import CalculateRegimeV2UseCase, CalculateRegimeV2Request
from apps.regime.infrastructure.macro_data_provider import MacroRepositoryAdapter
from apps.regime.infrastructure.repositories import DjangoRegimeRepository
from apps.regime.infrastructure.models import RegimeLog
from .serializers import (
    RegimeSnapshotSerializer,
    RegimeCalculateRequestSerializer,
    RegimeCalculateResponseSerializer,
    RegimeLogSerializer,
    RegimeHistoryQuerySerializer,
)


class RegimeViewSet(viewsets.ViewSet):
    """
    Regime API ViewSet

    提供以下接口:
    - GET /api/regime/current/ - 获取当前 Regime
    - POST /api/regime/calculate/ - 计算 Regime
    - GET /api/regime/history/ - 获取历史记录
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.repository = DjangoRegimeRepository()
        # 重构说明 (2026-03-11): 使用 MacroRepositoryAdapter 替代 DjangoMacroRepository
        self.use_case = CalculateRegimeV2UseCase(MacroRepositoryAdapter())

    @action(detail=False, methods=['get'])
    def current(self, request):
        """
        获取当前 Regime 状态

        GET /api/regime/current/
        """
        try:
            latest = resolve_current_regime(as_of_date=date.today())
            return Response({
                'success': True,
                'data': {
                    'observed_at': latest.observed_at,
                    'dominant_regime': latest.dominant_regime,
                    'confidence': latest.confidence,
                    'growth_momentum_z': 0.0,
                    'inflation_momentum_z': 0.0,
                    'distribution': latest.distribution or {},
                    'source': latest.data_source,
                    'is_fallback': latest.is_fallback,
                    'warnings': latest.warnings,
                }
            })

        except Exception as e:
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['post'])
    def calculate(self, request):
        """
        计算 Regime 判定

        POST /api/regime/calculate/
        {
            "as_of_date": "2024-01-15",  // 可选，默认今天
            "use_pit": true,               // 可选，是否使用 Point-in-Time 数据
            "growth_indicator": "PMI",     // 可选，默认 PMI
            "inflation_indicator": "CPI",  // 可选，默认 CPI
            "data_source": "akshare"       // 可选，默认 akshare
        }
        """
        try:
            # 验证请求参数
            request_serializer = RegimeCalculateRequestSerializer(data=request.data)
            request_serializer.is_valid(raise_exception=True)
            data = request_serializer.validated_data

            # 构建 Use Case 请求
            uc_request = CalculateRegimeV2Request(
                as_of_date=data.get('as_of_date', date.today()),
                use_pit=data.get('use_pit', True),
                growth_indicator=data.get('growth_indicator', 'PMI'),
                inflation_indicator=data.get('inflation_indicator', 'CPI'),
                data_source=data.get('data_source', 'akshare')
            )

            # 执行计算
            response = self.use_case.execute(uc_request)

            snapshot_data = None
            if response.success and response.result:
                snapshot_data = {
                    "observed_at": uc_request.as_of_date,
                    "dominant_regime": response.result.regime.value,
                    "confidence": float(response.result.confidence),
                    "growth_momentum_z": 0.0,
                    "inflation_momentum_z": 0.0,
                    "regime_distribution": response.result.distribution,
                    "data_source": uc_request.data_source or "akshare",
                    "created_at": timezone.now(),
                }

            payload = {
                "success": response.success,
                "snapshot": snapshot_data,
                "warnings": response.warnings or [],
                "error": response.error,
                "raw_data": response.raw_data,
                "intermediate_data": None,
            }
            response_serializer = RegimeCalculateResponseSerializer(payload)
            return Response(response_serializer.data)

        except Exception as e:
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['get'])
    def history(self, request):
        """
        获取 Regime 历史记录

        GET /api/regime/history/?start_date=2024-01-01&end_date=2024-12-31&regime=Recovery&limit=100
        """
        try:
            # 验证查询参数
            query_serializer = RegimeHistoryQuerySerializer(data=request.query_params)
            query_serializer.is_valid(raise_exception=True)
            params = query_serializer.validated_data

            # 构建查询
            queryset = RegimeLog._default_manager.all()

            if params.get('start_date'):
                queryset = queryset.filter(observed_at__gte=params['start_date'])
            if params.get('end_date'):
                queryset = queryset.filter(observed_at__lte=params['end_date'])
            if params.get('regime'):
                queryset = queryset.filter(dominant_regime=params['regime'])

            # 排序和限制
            queryset = queryset.order_by('-observed_at')[:params.get('limit', 100)]

            # 序列化结果
            serializer = RegimeLogSerializer(queryset, many=True)

            return Response({
                'success': True,
                'count': len(serializer.data),
                'data': serializer.data
            })

        except Exception as e:
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['get'])
    def distribution(self, request):
        """
        获取 Regime 分布统计

        GET /api/regime/distribution/?start_date=2024-01-01&end_date=2024-12-31
        """
        try:
            from django.db.models import Count

            # 获取日期范围
            start_date = request.query_params.get('start_date')
            end_date = request.query_params.get('end_date')

            queryset = RegimeLog._default_manager.all()
            if start_date:
                queryset = queryset.filter(observed_at__gte=start_date)
            if end_date:
                queryset = queryset.filter(observed_at__lte=end_date)

            # 统计各 Regime 数量
            stats = queryset.values('dominant_regime').annotate(
                count=Count('id')
            ).order_by('-count')

            # 计算总数和百分比
            total = sum(s['count'] for s in stats)
            for stat in stats:
                stat['percentage'] = round(stat['count'] / total * 100, 2) if total > 0 else 0

            return Response({
                'success': True,
                'total': total,
                'distribution': list(stats)
            })

        except Exception as e:
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class RegimeHealthView(APIView):
    """Regime 服务健康检查"""

    def get(self, request):
        """检查 Regime 服务健康状态"""
        try:
            # 检查数据库连接
            count = RegimeLog._default_manager.count()

            return Response({
                'status': 'healthy',
                'service': 'regime',
                'records_count': count
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({
                'status': 'unhealthy',
                'service': 'regime',
                'error': str(e)
            }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
