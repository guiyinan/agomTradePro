"""
Interface Views for Regime Calculation.

DRF Views and page views for regime calculation.

重构说明 (2026-03-11):
- 使用 MacroRepositoryAdapter 替代直接导入 DjangoMacroRepository
- 使用 DjangoDataSourceConfig 替代直接导入 macro 模块的 DataSourceConfig
- 保持 API 完全兼容
"""

from datetime import date

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from apps.regime.application.interface_services import (
    clear_regime_cache_payload,
    get_available_regime_sources,
    get_regime_dashboard_payload,
)

# API Cache layer
from core.cache_utils import cached_api


def regime_dashboard_view(request):
    """Regime 判定仪表板页面（统一使用 V2 水平法）"""
    available_sources = get_available_regime_sources()

    try:
        default_source = available_sources[0].source_type if available_sources else 'akshare'
        requested_source = request.GET.get('source')

        # 获取分析时点参数
        as_of_date_str = request.GET.get('as_of_date')
        if as_of_date_str:
            from datetime import datetime
            as_of_date = datetime.strptime(as_of_date_str, '%Y-%m-%d').date()
        else:
            as_of_date = date.today()

        # 是否跳过缓存（force_refresh 参数）
        skip_cache = request.GET.get('force_refresh') == '1'

        context = get_regime_dashboard_payload(
            requested_source=requested_source,
            as_of_date=as_of_date,
            skip_cache=skip_cache,
        )

    except Exception as e:
        default_source = available_sources[0].source_type if available_sources else 'akshare'
        data_source = request.GET.get('source', default_source)
        as_of_date_str = request.GET.get('as_of_date')
        if as_of_date_str:
            from datetime import datetime
            as_of_date = datetime.strptime(as_of_date_str, '%Y-%m-%d').date()
        else:
            as_of_date = date.today()

        context = {
            'result_v2': None,
            'regime_result': None,
            'warnings': [],
            'error': str(e),
            'current_date': date.today(),
            'as_of_date': as_of_date,
            'raw_data': None,
            'raw_data_json': None,
            'current_source': data_source,
            'available_sources': available_sources,
        }

    return render(request, 'regime/dashboard.html', context)


@require_http_methods(["POST"])
@cached_api(key_prefix='regime_clear_cache', ttl_seconds=0, method='POST')
def clear_regime_cache(request):
    """清除 Regime 缓存的 API 接口"""
    try:
        return JsonResponse(clear_regime_cache_payload())
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': f'清除缓存失败: {str(e)}'
        }, status=500)
