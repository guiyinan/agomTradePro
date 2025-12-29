"""
Page Views for AI Provider Management.

页面视图，用于渲染HTML页面。
"""

from django.shortcuts import render
from django.db.models import Q, Count, Sum
from datetime import date

from ...infrastructure.models import AIProviderConfig, AIUsageLog
from ...infrastructure.repositories import AIProviderRepository, AIUsageRepository


def ai_manage_view(request):
    """
    AI接口管理页面

    显示所有AI提供商配置及其使用统计。
    """
    provider_repo = AIProviderRepository()
    usage_repo = AIUsageRepository()

    # 获取所有启用的提供商
    providers = provider_repo.get_active_providers()

    # 为每个提供商获取今日统计
    providers_with_stats = []
    for p in providers:
        today_usage = usage_repo.get_daily_usage(p.id, date.today())

        # 获取本月统计
        month_usage = usage_repo.get_monthly_usage(
            p.id,
            date.today().year,
            date.today().month
        )

        providers_with_stats.append({
            'provider': p,
            'today_requests': today_usage['total_requests'],
            'today_cost': today_usage['total_cost'],
            'month_requests': month_usage['total_requests'],
            'month_cost': month_usage['total_cost'],
        })

    # 获取总体统计
    overall_stats = {
        'total_providers': AIProviderConfig.objects.count(),
        'active_providers': AIProviderConfig.objects.filter(is_active=True).count(),
        'total_requests_today': AIUsageLog.objects.filter(
            created_at__date=date.today()
        ).count(),
        'total_cost_today': float(
            AIUsageLog.objects.filter(
                created_at__date=date.today(),
                status='success'
            ).aggregate(
                total=Sum('estimated_cost')
            )['total'] or 0
        ),
    }

    # 获取提供商类型统计
    provider_types = AIProviderConfig.objects.values('provider_type').annotate(
        count=Count('id')
    ).order_by('provider_type')

    context = {
        'providers_with_stats': providers_with_stats,
        'overall_stats': overall_stats,
        'provider_types': list(provider_types),
    }

    return render(request, 'ai_provider/manage.html', context)


def ai_usage_logs_view(request):
    """
    AI调用日志页面

    显示API调用日志记录。
    """
    # 获取过滤参数
    provider_id = request.GET.get('provider')
    status = request.GET.get('status')
    limit = int(request.GET.get('limit', 100))

    usage_repo = AIUsageRepository()

    # 获取日志
    logs = usage_repo.get_recent_logs(
        provider_id=int(provider_id) if provider_id else None,
        limit=limit,
        status=status if status else None
    )

    # 获取所有提供商用于过滤
    providers = AIProviderConfig.objects.all().order_by('priority', 'name')

    # 状态选择
    status_choices = AIUsageLog.STATUS_CHOICES

    context = {
        'logs': logs,
        'providers': providers,
        'filter_provider': provider_id,
        'filter_status': status,
        'filter_limit': limit,
        'status_choices': status_choices,
    }

    return render(request, 'ai_provider/usage_logs.html', context)


def ai_provider_detail_view(request, provider_id):
    """
    AI提供商详情页面

    显示单个提供商的详细统计信息。
    """
    provider_repo = AIProviderRepository()
    usage_repo = AIUsageRepository()

    provider = provider_repo.get_by_id(provider_id)
    if not provider:
        # 返回404或重定向
        from django.http import Http404
        raise Http404(f"Provider {provider_id} not found")

    # 今日统计
    today_usage = usage_repo.get_daily_usage(provider.id, date.today())

    # 本月统计
    month_usage = usage_repo.get_monthly_usage(
        provider.id,
        date.today().year,
        date.today().month
    )

    # 最近日志
    recent_logs = usage_repo.get_recent_logs(provider_id=provider.id, limit=50)

    # 按日期的统计（最近30天）
    usage_by_date = usage_repo.get_usage_by_date(provider.id, days=30)

    # 按模型的统计
    model_stats = usage_repo.get_model_stats(provider.id, days=30)

    context = {
        'provider': provider,
        'today_usage': today_usage,
        'month_usage': month_usage,
        'recent_logs': recent_logs[:20],  # 只显示最近20条
        'usage_by_date': usage_by_date,
        'model_stats': model_stats,
    }

    return render(request, 'ai_provider/detail.html', context)
