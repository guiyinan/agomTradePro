"""
Views for Backtest Module.

包含页面视图和 API 视图。
"""

from datetime import date

from django.http import JsonResponse
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_http_methods
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.throttling import BacktestRateThrottle, WriteRateThrottle

from ..application.use_cases import (
    DeleteBacktestRequest,
    DeleteBacktestUseCase,
    GetBacktestResultRequest,
    GetBacktestResultUseCase,
    GetBacktestStatisticsUseCase,
    ListBacktestsRequest,
    ListBacktestsUseCase,
    RunBacktestRequest,
    RunBacktestUseCase,
)
from ..infrastructure.models import BacktestResultModel, BacktestTradeModel
from ..infrastructure.repositories import DjangoBacktestRepository
from .serializers import (
    BacktestListSerializer,
    BacktestResultSerializer,
    BacktestStatisticsSerializer,
    RunBacktestSerializer,
)

# ==================== Page Views ====================

def backtest_list_view(request):
    """回测列表页面"""
    repository = DjangoBacktestRepository()
    backtests = repository.get_all_backtests(limit=20)
    stats = repository.get_statistics()

    context = {
        'backtests': backtests,
        'stats': stats,
    }

    return render(request, 'backtest/list.html', context)


def backtest_detail_view(request, backtest_id):
    """回测详情页面"""
    repository = DjangoBacktestRepository()
    backtest = repository.get_backtest_by_id(backtest_id)

    if not backtest:
        return JsonResponse({'error': 'Backtest not found'}, status=404)

    # 转换为 Domain 实体获取详细信息
    if backtest.status == 'completed':
        domain_result = DjangoBacktestRepository.to_domain_entity(backtest)
        summary = domain_result.to_summary_dict()
    else:
        summary = None

    context = {
        'backtest': backtest,
        'summary': summary,
        'is_completed': backtest.status == 'completed',
    }

    return render(request, 'backtest/detail.html', context)


def backtest_create_view(request):
    """创建回测页面"""
    from apps.regime.infrastructure.repositories import DjangoRegimeRepository

    # 获取可用的日期范围
    regime_repo = DjangoRegimeRepository()
    earliest = regime_repo.get_earliest_date()
    latest = regime_repo.get_latest_date()

    context = {
        'earliest_date': earliest,
        'latest_date': latest,
        'frequencies': [
            ('monthly', '月度'),
            ('quarterly', '季度'),
            ('yearly', '年度'),
        ],
    }

    return render(request, 'backtest/create.html', context)


# ==================== API Views (DRF) ====================

class BacktestViewSet(viewsets.ViewSet):
    """回测 API 视图集

    P0-2: 应用分层限流（限流逻辑在 throttle 类内部按请求方法过滤）

    限流策略：
    - BacktestRateThrottle: 仅对 POST (create) 生效，10/hour
    - WriteRateThrottle: 对 POST/PUT/PATCH/DELETE 生效，100/hour
    - GET (list/retrieve/statistics): 仅使用默认全局限流，不受上述限制

    配置方式（settings.py 或环境变量）：
    - REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']['backtest'] 或 DRF_THROTTLE_BACKTEST
    - REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']['write'] 或 DRF_THROTTLE_WRITE
    """

    # P0-2: 分层限流配置
    # 注意：限流类内部已实现方法过滤，GET 请求不会触发这些限流
    throttle_classes = [BacktestRateThrottle, WriteRateThrottle]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.repository = DjangoBacktestRepository()

    def list(self, request):
        """列出所有回测"""
        status_filter = request.query_params.get('status')
        limit_param = request.query_params.get('limit')
        limit = None
        if limit_param not in (None, ''):
            try:
                limit = int(limit_param)
            except (TypeError, ValueError):
                return Response(
                    {'error': 'limit must be an integer'},
                    status=status.HTTP_400_BAD_REQUEST
                )

        use_case = ListBacktestsUseCase(self.repository)
        req = ListBacktestsRequest(status=status_filter, limit=limit)
        response = use_case.execute(req)

        serializer = BacktestListSerializer(
            self.repository.get_all_backtests(limit=limit or None),
            many=True
        )

        return Response({
            'backtests': response.backtests,
            'total_count': response.total_count,
        })

    def retrieve(self, request, pk=None):
        """获取回测详情"""
        use_case = GetBacktestResultUseCase(self.repository)
        req = GetBacktestResultRequest(backtest_id=int(pk))
        response = use_case.execute(req)

        if response.error:
            return Response({'error': response.error}, status=status.HTTP_404_NOT_FOUND)

        return Response({
            'id': response.backtest_id,
            'name': response.name,
            'status': response.status,
            'result': response.result,
        })

    def create(self, request):
        """创建并运行回测"""
        serializer = RunBacktestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({'errors': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data

        # 创建数据获取函数
        def get_regime(as_of_date: date):
            from apps.regime.infrastructure.repositories import DjangoRegimeRepository
            regime_repo = DjangoRegimeRepository()
            snapshot = regime_repo.get_regime_by_date(as_of_date)
            if snapshot:
                return {
                    'dominant_regime': snapshot.dominant_regime,
                    'confidence': snapshot.confidence,
                    'growth_momentum_z': snapshot.growth_momentum_z,
                    'inflation_momentum_z': snapshot.inflation_momentum_z,
                    'distribution': snapshot.distribution,
                }
            return None

        def get_asset_price(asset_class: str, as_of_date: date):
            from shared.config.secrets import get_secrets

            from ..infrastructure.adapters import create_default_price_adapter

            # 创建价格适配器（使用组合适配器支持 failover）
            try:
                token = get_secrets().data_sources.tushare_token
            except Exception:
                token = None

            adapter = create_default_price_adapter(tushare_token=token)
            return adapter.get_price(asset_class, as_of_date)

        use_case = RunBacktestUseCase(self.repository, get_regime, get_asset_price)
        req = RunBacktestRequest(
            name=data['name'],
            start_date=data['start_date'],
            end_date=data['end_date'],
            initial_capital=data['initial_capital'],
            rebalance_frequency=data['rebalance_frequency'],
            use_pit_data=data.get('use_pit_data', False),
            transaction_cost_bps=data.get('transaction_cost_bps', 10.0),
        )

        response = use_case.execute(req)

        if response.status == 'failed':
            return Response({
                'error': 'Backtest failed',
                'errors': response.errors,
                'warnings': response.warnings,
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({
            'backtest_id': response.backtest_id,
            'status': response.status,
            'result': response.result,
            'warnings': response.warnings,
        }, status=status.HTTP_201_CREATED)

    def destroy(self, request, pk=None):
        """删除回测"""
        use_case = DeleteBacktestUseCase(self.repository)
        req = DeleteBacktestRequest(backtest_id=int(pk))
        response = use_case.execute(req)

        if not response.success:
            return Response({'error': response.error}, status=status.HTTP_404_NOT_FOUND)

        return Response({'message': 'Backtest deleted successfully'})

    @action(detail=False, methods=['get'])
    def statistics(self, request):
        """获取统计信息"""
        use_case = GetBacktestStatisticsUseCase(self.repository)
        response = use_case.execute()

        serializer = BacktestStatisticsSerializer(response)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def rerun(self, request, pk=None):
        """重新运行回测"""
        backtest = self.repository.get_backtest_by_id(int(pk))
        if not backtest:
            return Response({'error': 'Backtest not found'}, status=status.HTTP_404_NOT_FOUND)

        # 删除旧结果，准备重新运行
        # 实际实现中需要更复杂的逻辑
        return Response({'message': 'Rerun initiated'})


# ==================== Utility Views ====================

@require_http_methods(["GET"])
def backtest_statistics_api_view(request):
    """获取回测统计（独立 API）"""
    repository = DjangoBacktestRepository()
    use_case = GetBacktestStatisticsUseCase(repository)
    response = use_case.execute()

    return JsonResponse({
        'total': response.total,
        'by_status': response.by_status,
        'avg_return': response.avg_return,
        'max_return': response.max_return,
        'min_return': response.min_return,
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def run_backtest_api_view(request):
    """运行回测（独立 API）"""
    serializer = RunBacktestSerializer(data=request.data)
    if not serializer.is_valid():
        return Response({'errors': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    validated_data = dict(serializer.validated_data)
    validated_data.pop("run_async", None)

    repository = DjangoBacktestRepository()

    def get_regime(as_of_date: date):
        from apps.regime.infrastructure.repositories import DjangoRegimeRepository
        regime_repo = DjangoRegimeRepository()
        snapshot = regime_repo.get_regime_by_date(as_of_date)
        if snapshot:
            return {
                'dominant_regime': snapshot.dominant_regime,
                'confidence': snapshot.confidence,
                'growth_momentum_z': snapshot.growth_momentum_z,
                'inflation_momentum_z': snapshot.inflation_momentum_z,
                'distribution': snapshot.distribution,
            }
        return None

    def get_asset_price(asset_class: str, as_of_date: date):
        from shared.config.secrets import get_secrets

        from ..infrastructure.adapters import create_default_price_adapter

        try:
            token = get_secrets().data_sources.tushare_token
        except Exception:
            token = None

        adapter = create_default_price_adapter(tushare_token=token)
        return adapter.get_price(asset_class, as_of_date)

    use_case = RunBacktestUseCase(repository, get_regime, get_asset_price)
    req = RunBacktestRequest(**validated_data)

    response = use_case.execute(req)

    if response.status == 'failed':
        return Response({
            'error': 'Backtest failed',
            'errors': response.errors,
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    return Response({
        'backtest_id': response.backtest_id,
        'status': response.status,
        'result': response.result,
        'warnings': response.warnings,
    })
