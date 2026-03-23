"""
DRF API Views for Filter Operations.

REST API endpoints for filter operations.
"""

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from ..application.use_cases import (
    ApplyFilterRequest,
    ApplyFilterUseCase,
    CompareFiltersRequest,
    CompareFiltersUseCase,
    GetFilterDataRequest,
    GetFilterDataUseCase,
)
from ..domain.entities import FilterType
from ..infrastructure.repositories import DjangoFilterRepository
from .serializers import (
    ApplyFilterRequestSerializer,
    ApplyFilterResponseSerializer,
    CompareFiltersRequestSerializer,
    CompareFiltersResponseSerializer,
    FilterSeriesSerializer,
    GetFilterDataRequestSerializer,
    GetFilterDataResponseSerializer,
)


class FilterViewSet(viewsets.ViewSet):
    """
    滤波器 API ViewSet

    提供：
    - apply: 应用滤波器
    - get_data: 获取已保存的滤波数据
    - compare: 对比 HP 和 Kalman 滤波
    - indicators: 获取可用指标列表
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.repository = DjangoFilterRepository()
        self.apply_use_case = ApplyFilterUseCase(self.repository)
        self.get_use_case = GetFilterDataUseCase(self.repository)
        self.compare_use_case = CompareFiltersUseCase(self.apply_use_case)

    def create(self, request):
        """
        应用滤波器

        POST /api/filter/
        {
            "indicator_code": "PMI",
            "filter_type": "HP",
            "limit": 200,
            "save_results": true
        }
        """
        serializer = ApplyFilterRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {'success': False, 'error': str(serializer.errors)},
                status=status.HTTP_400_BAD_REQUEST
            )

        data = serializer.validated_data
        filter_type = FilterType.HP if data['filter_type'] == 'HP' else FilterType.KALMAN

        req = ApplyFilterRequest(
            indicator_code=data['indicator_code'],
            filter_type=filter_type,
            start_date=data.get('start_date'),
            end_date=data.get('end_date'),
            limit=data.get('limit', 200),
            save_results=data.get('save_results', True),
        )

        response = self.apply_use_case.execute(req)

        if response.success:
            response_data = {
                'success': True,
                'series': _serialize_series(response.series),
                'warnings': response.warnings,
            }
            return Response(response_data)
        else:
            return Response(
                {'success': False, 'error': response.error},
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=False, methods=['POST'], url_path='get-data')
    def get_data(self, request):
        """
        获取已保存的滤波数据

        POST /api/filter/get-data/
        {
            "indicator_code": "PMI",
            "filter_type": "HP"
        }
        """
        serializer = GetFilterDataRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {'success': False, 'error': str(serializer.errors)},
                status=status.HTTP_400_BAD_REQUEST
            )

        data = serializer.validated_data
        filter_type = FilterType.HP if data['filter_type'] == 'HP' else FilterType.KALMAN

        req = GetFilterDataRequest(
            indicator_code=data['indicator_code'],
            filter_type=filter_type,
            start_date=data.get('start_date'),
            end_date=data.get('end_date'),
        )

        response = self.get_use_case.execute(req)

        if response.success:
            return Response({
                'success': True,
                'dates': response.dates,
                'original_values': response.original_values,
                'filtered_values': response.filtered_values,
                'slopes': response.slopes,
            })
        else:
            return Response(
                {'success': False, 'error': response.error},
                status=status.HTTP_404_NOT_FOUND
            )

    @action(detail=False, methods=['POST'], url_path='compare')
    def compare(self, request):
        """
        对比 HP 和 Kalman 滤波

        POST /api/filter/compare/
        {
            "indicator_code": "PMI",
            "limit": 200
        }
        """
        serializer = CompareFiltersRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {'success': False, 'error': str(serializer.errors)},
                status=status.HTTP_400_BAD_REQUEST
            )

        data = serializer.validated_data

        req = CompareFiltersRequest(
            indicator_code=data['indicator_code'],
            start_date=data.get('start_date'),
            end_date=data.get('end_date'),
            limit=data.get('limit', 200),
        )

        response = self.compare_use_case.execute(req)

        if response.success:
            return Response({
                'success': True,
                'hp_results': response.hp_results,
                'kalman_results': response.kalman_results,
            })
        else:
            return Response(
                {'success': False, 'error': response.error},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=['GET'], url_path='indicators')
    def indicators(self, request):
        """
        获取可用指标列表

        GET /api/filter/indicators/
        """
        indicators = self.repository.get_available_indicators()
        return Response({
            'success': True,
            'indicators': indicators,
        })

    @action(detail=False, methods=['GET'], url_path='config/(?P<indicator_code>[^/]+)')
    def config(self, request, indicator_code=None):
        """
        获取滤波器配置

        GET /api/filter/config/PMI/
        """
        if not indicator_code:
            return Response(
                {'success': False, 'error': 'Missing indicator_code'},
                status=status.HTTP_400_BAD_REQUEST
            )

        config = self.repository.get_filter_config(indicator_code)
        config['indicator_code'] = indicator_code
        return Response({
            'success': True,
            'config': config,
        })


class FilterHealthView(APIView):
    """滤波器健康检查"""

    def get(self, request):
        return Response({
            'status': 'healthy',
            'service': 'Filter API',
            'filters_available': ['HP', 'Kalman'],
        })


def _serialize_series(series) -> dict:
    """序列化滤波序列"""
    return {
        'indicator_code': series.indicator_code,
        'filter_type': series.filter_type.value,
        'params': series.params,
        'dates': [r.date.isoformat() for r in series.results],
        'original_values': [r.original_value for r in series.results],
        'filtered_values': [r.filtered_value for r in series.results],
        'slopes': [r.slope for r in series.results],
        'calculated_at': series.calculated_at.isoformat(),
    }
