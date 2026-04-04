"""
Market Data 模块 - 页面视图

只做页面渲染，数据由前端 JS 通过 API 获取。
"""

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from apps.market_data.application.registry_factory import get_registry


def build_provider_dashboard() -> dict[str, object]:
    """构建市场数据 provider 页面摘要。

    返回按 provider 聚合的健康状态，供页面和配置中心复用。
    """
    statuses = [status.to_dict() for status in get_registry().get_all_statuses()]
    grouped: dict[str, list[dict[str, object]]] = {}
    for status in statuses:
        grouped.setdefault(str(status["provider_name"]), []).append(status)

    providers: list[dict[str, object]] = []
    for name, items in sorted(grouped.items()):
        healthy_count = sum(1 for item in items if item["is_healthy"])
        providers.append(
            {
                "name": name,
                "capability_count": len(items),
                "healthy": healthy_count == len(items) and len(items) > 0,
                "healthy_count": healthy_count,
                "unhealthy_count": len(items) - healthy_count,
            }
        )

    return {
        "provider_count": len(providers),
        "healthy_provider_count": sum(1 for provider in providers if provider["healthy"]),
        "unhealthy_provider_count": sum(
            1 for provider in providers if not provider["healthy"]
        ),
        "providers": providers,
    }


@login_required
@require_http_methods(["GET"])
def providers_page(request):
    """市场数据源状态页面。

    GET /market-data/providers/
    """
    return render(
        request,
        "market_data/providers.html",
        {"provider_dashboard": build_provider_dashboard()},
    )
