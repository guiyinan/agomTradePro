"""
Interface Views for Regime Calculation.

DRF Views and page views for regime calculation.
"""

from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from datetime import date
from apps.regime.application.use_cases import CalculateRegimeV2UseCase, CalculateRegimeV2Request
from apps.macro.infrastructure.repositories import DjangoMacroRepository
from apps.macro.infrastructure.models import DataSourceConfig


def regime_dashboard_view(request):
    """Regime 判定仪表板页面（统一使用 V2 水平法）"""
    import json

    try:
        # 获取可用的数据源列表
        available_sources = DataSourceConfig._default_manager.filter(is_active=True).order_by('priority')

        # 获取查询参数
        default_source = available_sources.first().source_type if available_sources.exists() else 'akshare'
        data_source = request.GET.get('source', default_source)

        # 获取分析时点参数
        as_of_date_str = request.GET.get('as_of_date')
        if as_of_date_str:
            from datetime import datetime
            as_of_date = datetime.strptime(as_of_date_str, '%Y-%m-%d').date()
        else:
            as_of_date = date.today()

        # 是否跳过缓存（force_refresh 参数）
        skip_cache = request.GET.get('force_refresh') == '1'

        # 统一使用 V2 算法（水平判定法）
        repository = DjangoMacroRepository()
        use_case = CalculateRegimeV2UseCase(repository)
        request_obj = CalculateRegimeV2Request(
            as_of_date=as_of_date,
            use_pit=True,
            growth_indicator="PMI",
            inflation_indicator="CPI",
            data_source=data_source,
            skip_cache=skip_cache
        )
        response = use_case.execute(request_obj)

        # V2 结果格式
        result_v2 = response.result if response.success else None
        raw_data_json = json.dumps(response.raw_data) if response.raw_data else None
        regime_result = None

        if result_v2:
            growth_series = (response.raw_data or {}).get('growth', []) or []
            inflation_series = (response.raw_data or {}).get('inflation', []) or []

            growth_tail = growth_series[-12:]
            inflation_tail = inflation_series[-12:]

            def _safe_float(value, default=0.0):
                if value in (None, ""):
                    return default
                try:
                    return float(value)
                except (TypeError, ValueError):
                    return default

            growth_values = [_safe_float(item.get('value')) for item in growth_tail]
            inflation_values = [_safe_float(item.get('value')) for item in inflation_tail]

            def _trend(values):
                if len(values) < 2:
                    return "flat"
                if values[-1] > values[-2]:
                    return "up"
                if values[-1] < values[-2]:
                    return "down"
                return "flat"

            regime_result = {
                # 模板兼容字段（历史模板使用 regime_result）
                'quadrant': result_v2.regime.value,
                'pmi_value': round(float(result_v2.growth_level), 2),
                'cpi_value': round(float(result_v2.inflation_level), 2),
                'pmi_trend': _trend(growth_values),
                'cpi_trend': _trend(inflation_values),
                'growth_dates': json.dumps([item.get('date') for item in growth_tail], ensure_ascii=False),
                'growth_values': json.dumps(growth_values, ensure_ascii=False),
                'inflation_dates': json.dumps([item.get('date') for item in inflation_tail], ensure_ascii=False),
                'inflation_values': json.dumps(inflation_values, ensure_ascii=False),
            }

        context = {
            'result_v2': result_v2,
            'regime_result': regime_result,
            'warnings': response.warnings if response.success else [],
            'error': response.error if not response.success else None,
            'current_date': date.today(),
            'as_of_date': as_of_date,
            'raw_data': response.raw_data if response.success else None,
            'raw_data_json': raw_data_json,
            'current_source': data_source,
            'available_sources': available_sources,
        }

    except Exception as e:
        available_sources = DataSourceConfig._default_manager.filter(is_active=True).order_by('priority')
        default_source = available_sources.first().source_type if available_sources.exists() else 'akshare'
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
def clear_regime_cache(request):
    """清除 Regime 缓存的 API 接口"""
    try:
        from django.core.cache import cache
        cache.clear()

        from shared.infrastructure.cache_service import CacheService
        CacheService.invalidate_regime()

        return JsonResponse({
            'status': 'success',
            'message': 'Regime 缓存已清除，请刷新页面查看最新数据'
        })
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': f'清除缓存失败: {str(e)}'
        }, status=500)

