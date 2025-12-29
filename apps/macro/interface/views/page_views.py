"""
Page Views for Macro Data Management.

Contains view functions for rendering HTML pages.
"""

from django.shortcuts import render
from django.db.models import Q, Count, Max
from apps.macro.infrastructure.models import MacroIndicator, DataSourceConfig
from apps.macro.infrastructure.repositories import DjangoMacroRepository
from apps.macro.application.data_management import (
    GetDataManagementSummaryUseCase,
    ScheduleDataFetchUseCase,
)
from datetime import datetime, timedelta

from .helpers import get_repository


def macro_data_view(request):
    """宏观数据管理页面"""
    # 获取查询参数
    indicator_code = request.GET.get('code', '')
    source = request.GET.get('source', '')
    days = int(request.GET.get('days', 30))

    # 基础查询
    queryset = MacroIndicator.objects.all()

    # 应用筛选
    if indicator_code:
        queryset = queryset.filter(code__icontains=indicator_code)
    if source:
        queryset = queryset.filter(source=source)

    # 日期范围
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=days)

    # 按指标代码分组，获取最新数据
    indicators = queryset.filter(reporting_period__gte=start_date).values('code').annotate(
        latest_date=Count('reporting_period'),
        count=Count('id')
    ).order_by('-latest_date', 'code')

    # 获取每个指标的最新记录
    latest_data = []
    for ind in indicators[:50]:  # 限制显示前50个
        records = MacroIndicator.objects.filter(
            code=ind['code']
        ).order_by('-reporting_period', '-revision_number')[:1]
        if records:
            latest_data.append(records[0])

    # 统计信息
    stats = {
        'total_indicators': MacroIndicator.objects.values('code').distinct().count(),
        'total_records': MacroIndicator.objects.count(),
        'latest_date': MacroIndicator.objects.aggregate(
            latest=Max('reporting_period')
        )['latest'] or '-',
        'sources': MacroIndicator.objects.values('source').annotate(
            count=Count('id')
        ).order_by('-count')
    }

    # 数据源列表
    data_sources = DataSourceConfig.objects.filter(is_active=True).order_by('priority')

    context = {
        'indicators': latest_data,
        'stats': stats,
        'data_sources': data_sources,
        'filter_code': indicator_code,
        'filter_source': source,
        'filter_days': days,
    }

    return render(request, 'macro/data.html', context)


def datasource_config_view(request):
    """数据源配置页面"""
    data_sources = DataSourceConfig.objects.all().order_by('priority', 'name')

    # 统计信息
    stats = {
        'total': data_sources.count(),
        'active': data_sources.filter(is_active=True).count(),
        'by_type': {}
    }

    for source_type, _ in DataSourceConfig.SOURCE_TYPE_CHOICES:
        count = data_sources.filter(source_type=source_type).count()
        if count > 0:
            stats['by_type'][source_type] = count

    context = {
        'data_sources': data_sources,
        'stats': stats,
        'source_type_choices': DataSourceConfig.SOURCE_TYPE_CHOICES,
    }

    return render(request, 'datasource/config.html', context)


def data_controller_view(request):
    """
    统一数据管理器页面

    提供数据抓取、定时任务配置、数据删除等功能
    """
    repo = get_repository()
    summary_use_case = GetDataManagementSummaryUseCase(repo)
    schedule_use_case = ScheduleDataFetchUseCase(repo)

    # 获取概览信息
    summary = summary_use_case.execute()

    # 获取可调度的指标配置
    scheduled_indicators = schedule_use_case.get_scheduled_indicators()

    # 获取所有可用指标
    all_indicators = MacroIndicator.objects.values('code').annotate(
        count=Count('id'),
        latest=Max('reporting_period')
    ).order_by('code')

    # 获取所有数据源
    sources = MacroIndicator.objects.values('source').annotate(
        count=Count('id')
    ).order_by('-count')

    context = {
        'summary': summary,
        'scheduled_indicators': scheduled_indicators,
        'all_indicators': list(all_indicators),
        'sources': list(sources),
    }

    return render(request, 'macro/data_controller.html', context)
