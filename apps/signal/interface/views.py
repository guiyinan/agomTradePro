"""
Page Views for Investment Signal Management.
"""

from django.shortcuts import render
from apps.signal.infrastructure.models import InvestmentSignalModel
from django.db.models import Count, Q


def signal_manage_view(request):
    """投资信号管理页面"""
    # 获取筛选参数
    status_filter = request.GET.get('status', '')
    asset_class = request.GET.get('asset_class', '')
    direction = request.GET.get('direction', '')
    search = request.GET.get('search', '')

    # 基础查询
    queryset = InvestmentSignalModel.objects.all()

    # 应用筛选
    if status_filter:
        queryset = queryset.filter(status=status_filter)
    if asset_class:
        queryset = queryset.filter(asset_class=asset_class)
    if direction:
        queryset = queryset.filter(direction=direction)
    if search:
        queryset = queryset.filter(
            Q(asset_code__icontains=search) | Q(logic_desc__icontains=search)
        )

    # 获取信号列表
    signals = queryset.order_by('-created_at')[:50]

    # 统计信息
    stats = {
        'total': InvestmentSignalModel.objects.count(),
        'pending': InvestmentSignalModel.objects.filter(status='pending').count(),
        'approved': InvestmentSignalModel.objects.filter(status='approved').count(),
        'rejected': InvestmentSignalModel.objects.filter(status='rejected').count(),
        'invalidated': InvestmentSignalModel.objects.filter(status='invalidated').count(),
    }

    # 获取所有资产类别和方向
    asset_classes = InvestmentSignalModel.objects.values('asset_class').distinct()
    directions = InvestmentSignalModel.objects.values('direction').distinct()

    context = {
        'signals': signals,
        'stats': stats,
        'asset_classes': [ac['asset_class'] for ac in asset_classes],
        'directions': [d['direction'] for d in directions],
        'filter_status': status_filter,
        'filter_asset_class': asset_class,
        'filter_direction': direction,
        'filter_search': search,
    }

    return render(request, 'signal/manage.html', context)
