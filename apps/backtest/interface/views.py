"""
Views for Backtest Module.

包含页面视图和 API 视图。
"""

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.throttling import BacktestRateThrottle, WriteRateThrottle

from ..application.interface_services import (
    backtest_exists,
    delete_backtest_payload,
    get_backtest_result_payload,
    get_backtest_statistics_payload,
    list_backtests_payload,
    load_backtest_create_context,
    load_backtest_detail_context,
    load_backtest_list_context,
    run_backtest_payload,
)
from .serializers import (
    BacktestStatisticsSerializer,
    RunBacktestSerializer,
)

# ==================== Page Views ====================

def backtest_list_view(request):
    """回测列表页面"""
    return render(request, 'backtest/list.html', load_backtest_list_context(limit=20))


def backtest_detail_view(request, backtest_id):
    """回测详情页面"""
    context = load_backtest_detail_context(backtest_id)
    if context is None:
        return JsonResponse({'error': 'Backtest not found'}, status=404)
    return render(request, 'backtest/detail.html', context)


def backtest_create_view(request):
    """创建回测页面"""
    return render(request, 'backtest/create.html', load_backtest_create_context())


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

        return Response(list_backtests_payload(status_filter=status_filter, limit=limit))

    def retrieve(self, request, pk=None):
        """获取回测详情"""
        response = get_backtest_result_payload(int(pk))

        if response['error']:
            return Response({'error': response['error']}, status=status.HTTP_404_NOT_FOUND)

        return Response({
            'id': response['backtest_id'],
            'name': response['name'],
            'status': response['status'],
            'result': response['result'],
        })

    def create(self, request):
        """创建并运行回测"""
        serializer = RunBacktestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({'errors': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

        response = run_backtest_payload(dict(serializer.validated_data))

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
        response = delete_backtest_payload(int(pk))

        if not response['success']:
            return Response({'error': response['error']}, status=status.HTTP_404_NOT_FOUND)

        return Response({'message': 'Backtest deleted successfully'})

    @action(detail=False, methods=['get'])
    def statistics(self, request):
        """获取统计信息"""
        serializer = BacktestStatisticsSerializer(get_backtest_statistics_payload())
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def rerun(self, request, pk=None):
        """重新运行回测"""
        if not backtest_exists(int(pk)):
            return Response({'error': 'Backtest not found'}, status=status.HTTP_404_NOT_FOUND)

        # 删除旧结果，准备重新运行
        # 实际实现中需要更复杂的逻辑
        return Response({'message': 'Rerun initiated'})


# ==================== Utility Views ====================

@require_http_methods(["GET"])
def backtest_statistics_api_view(request):
    """获取回测统计（独立 API）"""
    response = get_backtest_statistics_payload()

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
    response = run_backtest_payload(validated_data)

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
