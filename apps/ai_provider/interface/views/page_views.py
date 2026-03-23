"""
Page Views for AI Provider Management.

页面视图，用于渲染HTML页面。
遵循项目架构约束：Interface 层调用 Application 层，不直接访问 Infrastructure 层。
"""

from django.contrib import messages
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render

from ...application.use_cases import (
    GetOverallStatsUseCase,
    GetProviderStatsUseCase,
    ListProvidersUseCase,
    ListUsageLogsUseCase,
    UpdateProviderUseCase,
)
from ...infrastructure.models import AIProviderConfig
from ..forms import AIProviderConfigForm


def ai_manage_view(request):
    """
    AI接口管理页面

    显示所有AI提供商配置及其使用统计。
    通过 Application 层获取数据。
    """
    # 使用 Application 层获取提供商列表（含统计数据）
    list_use_case = ListProvidersUseCase()
    providers_dto = list_use_case.execute(include_inactive=False)

    # 转换为模板所需格式
    providers_with_stats = []
    for dto in providers_dto:
        # 获取原始 ORM 对象（用于模板中访问所有字段）
        provider = AIProviderConfig._default_manager.get(id=dto.id)
        providers_with_stats.append({
            'provider': provider,
            'today_requests': dto.today_requests,
            'today_cost': dto.today_cost,
            'month_requests': dto.month_requests,
            'month_cost': dto.month_cost,
        })

    # 使用 Application 层获取总体统计
    stats_use_case = GetOverallStatsUseCase()
    overall_dto = stats_use_case.execute()

    overall_stats = {
        'total_providers': overall_dto.total_providers,
        'active_providers': overall_dto.active_providers,
        'total_requests_today': overall_dto.total_requests_today,
        'total_cost_today': overall_dto.total_cost_today,
    }

    # 提供商类型统计（仅用于展示，保留 ORM 查询）
    provider_types = AIProviderConfig._default_manager.values('provider_type').annotate(
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
    通过 Application 层获取数据。
    """
    # 获取过滤参数
    provider_id = request.GET.get('provider')
    status_filter = request.GET.get('status')
    limit = int(request.GET.get('limit', 100))

    # 使用 Application 层获取日志
    list_logs_use_case = ListUsageLogsUseCase()
    logs_dto = list_logs_use_case.execute(
        provider_id=int(provider_id) if provider_id else None,
        status=status_filter if status_filter else None,
        limit=limit,
    )

    # 获取所有提供商用于过滤下拉框
    providers = AIProviderConfig._default_manager.all().order_by('priority', 'name')

    # 状态选择（保留从模型获取）
    from ...infrastructure.models import AIUsageLog
    status_choices = AIUsageLog.STATUS_CHOICES

    context = {
        'logs': logs_dto,
        'providers': providers,
        'filter_provider': provider_id,
        'filter_status': status_filter,
        'filter_limit': limit,
        'status_choices': status_choices,
    }

    return render(request, 'ai_provider/usage_logs.html', context)


def ai_provider_detail_view(request, provider_id):
    """
    AI提供商详情页面

    显示单个提供商的详细统计信息。
    通过 Application 层获取数据。
    """
    # 使用 Application 层获取提供商统计
    stats_use_case = GetProviderStatsUseCase()

    try:
        stats_dto = stats_use_case.execute(pk=provider_id, days=30)
    except ValueError:
        from django.http import Http404
        raise Http404(f"Provider {provider_id} not found")

    # 获取原始提供商对象（用于模板访问所有字段）
    provider = get_object_or_404(AIProviderConfig, id=provider_id)

    # 使用 Application 层获取最近日志
    list_logs_use_case = ListUsageLogsUseCase()
    recent_logs_dto = list_logs_use_case.execute(
        provider_id=provider_id,
        limit=50,
    )

    context = {
        'provider': provider,
        'today_usage': {
            'total_requests': stats_dto.today_requests,
            'total_cost': stats_dto.today_cost,
        },
        'month_usage': {
            'total_requests': stats_dto.month_requests,
            'total_cost': stats_dto.month_cost,
        },
        'recent_logs': recent_logs_dto[:20],  # 只显示最近20条
        'usage_by_date': stats_dto.usage_by_date,
        'model_stats': stats_dto.model_stats,
    }

    return render(request, 'ai_provider/detail.html', context)


def ai_provider_edit_view(request, provider_id):
    """
    AI 提供商编辑页面（非 Admin）。

    通过 Application 层更新数据。
    """
    provider = get_object_or_404(AIProviderConfig, id=provider_id)

    if request.method == "POST":
        form = AIProviderConfigForm(request.POST, instance=provider)
        if form.is_valid():
            # 使用 Application 层更新提供商
            # 注意：form.cleaned_data 中有 extra_config_text，需要转换为 extra_config
            update_data = {
                "name": form.cleaned_data.get("name"),
                "provider_type": form.cleaned_data.get("provider_type"),
                "is_active": form.cleaned_data.get("is_active", False),
                "priority": form.cleaned_data.get("priority"),
                "base_url": form.cleaned_data.get("base_url"),
                "default_model": form.cleaned_data.get("default_model"),
                "api_mode": form.cleaned_data.get("api_mode"),
                "fallback_enabled": form.cleaned_data.get("fallback_enabled", True),
                "daily_budget_limit": form.cleaned_data.get("daily_budget_limit"),
                "monthly_budget_limit": form.cleaned_data.get("monthly_budget_limit"),
                "description": form.cleaned_data.get("description", ""),
                "extra_config": form.cleaned_data.get("extra_config_text", {}),
            }
            # 只有当 api_key 有值时才更新（留空表示不修改）
            if form.cleaned_data.get("api_key"):
                update_data["api_key"] = form.cleaned_data["api_key"]

            update_use_case = UpdateProviderUseCase()
            try:
                update_use_case.execute(pk=provider_id, **update_data)
                messages.success(request, "AI 提供商配置已更新")
                return redirect("ai_provider:detail", provider_id=provider_id)
            except ValueError as e:
                messages.error(request, str(e))
    else:
        form = AIProviderConfigForm(instance=provider)

    context = {
        "form": form,
        "provider": provider,
        "page_title": f"编辑 AI 提供商：{provider.name}",
    }
    return render(request, "ai_provider/form.html", context)
