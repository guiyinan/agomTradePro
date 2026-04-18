"""
Interface Views for Regime Calculation.

DRF Views and page views for regime calculation.

重构说明 (2026-03-11):
- 使用 MacroRepositoryAdapter 替代直接导入 DjangoMacroRepository
- 使用 DjangoDataSourceConfig 替代直接导入 macro 模块的 DataSourceConfig
- 保持 API 完全兼容
"""

from datetime import date
from types import SimpleNamespace

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from apps.regime.application.use_cases import CalculateRegimeV2Request, CalculateRegimeV2UseCase
from apps.regime.infrastructure.macro_data_provider import (
    MacroRepositoryAdapter,
)
from apps.regime.infrastructure.macro_source_config_gateway import (
    DjangoMacroSourceConfigGateway,
)

# API Cache layer
from core.cache_utils import cached_api


def _get_available_sources():
    """Return active data sources for template rendering."""
    gateway = DjangoMacroSourceConfigGateway()
    return gateway.list_active_sources()


def _build_regime_v2_response(use_case, as_of_date: date, data_source: str | None, skip_cache: bool):
    """Execute the V2 regime use case with a consistent request payload."""
    request_obj = CalculateRegimeV2Request(
        as_of_date=as_of_date,
        use_pit=True,
        growth_indicator="PMI",
        inflation_indicator="CPI",
        data_source=data_source,
        skip_cache=skip_cache,
    )
    return use_case.execute(request_obj)


def _append_source_option(
    available_sources: list,
    source_type: str | None,
) -> list:
    """Ensure the effective source is still visible in the selector."""
    if not source_type:
        return available_sources

    if any(getattr(source, "source_type", None) == source_type for source in available_sources):
        return available_sources

    fallback_names = {
        "akshare": "AKShare",
        "tushare": "Tushare Pro",
    }
    return [
        *available_sources,
        SimpleNamespace(source_type=source_type, name=fallback_names.get(source_type, source_type)),
    ]


def _resolve_dashboard_response(
    use_case,
    available_sources: list,
    requested_source: str | None,
    as_of_date: date,
    skip_cache: bool,
):
    """
    Resolve the effective source for dashboard rendering.

    If the user explicitly selected a source, keep that choice even when it has
    no data. If the source was implicit, automatically fall back to the first
    source that can actually produce a regime result.
    """
    candidate_sources: list[str | None] = []
    explicit_source = bool(requested_source)

    if explicit_source:
        candidate_sources.append(requested_source)
    else:
        candidate_sources.extend(
            getattr(source, "source_type", None)
            for source in available_sources
            if getattr(source, "source_type", None)
        )
        candidate_sources.extend(["akshare", "tushare", None])

    deduped_candidates: list[str | None] = []
    seen: set[str | None] = set()
    for candidate in candidate_sources:
        if candidate in seen:
            continue
        seen.add(candidate)
        deduped_candidates.append(candidate)

    last_response = None
    selected_source = requested_source
    warnings: list[str] = []
    primary_source = deduped_candidates[0] if deduped_candidates else None

    for candidate in deduped_candidates:
        response = _build_regime_v2_response(
            use_case=use_case,
            as_of_date=as_of_date,
            data_source=candidate,
            skip_cache=skip_cache,
        )
        last_response = response
        if response.success and response.result is not None:
            selected_source = candidate
            if (
                not explicit_source
                and primary_source
                and candidate != primary_source
            ):
                warnings.append(
                    f"默认数据源 {primary_source} 暂无 Regime 所需数据，已自动切换到 {candidate or 'all'}。"
                )
            return response, selected_source, warnings

    return last_response, selected_source, warnings


def regime_dashboard_view(request):
    """Regime 判定仪表板页面（统一使用 V2 水平法）"""
    import json

    available_sources = _get_available_sources()

    try:
        default_source = available_sources[0].source_type if available_sources else 'akshare'
        requested_source = request.GET.get('source')
        data_source = requested_source or default_source

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
        # 重构说明 (2026-03-11): 使用 MacroRepositoryAdapter 替代 DjangoMacroRepository
        repository = MacroRepositoryAdapter()
        use_case = CalculateRegimeV2UseCase(repository)
        response, effective_source, auto_warnings = _resolve_dashboard_response(
            use_case=use_case,
            available_sources=available_sources,
            requested_source=requested_source,
            as_of_date=as_of_date,
            skip_cache=skip_cache,
        )
        available_sources = _append_source_option(available_sources, effective_source)
        data_source = effective_source or data_source

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
                'confidence': round(float(result_v2.confidence), 4),
                'distribution': dict(result_v2.distribution or {}),
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
            'warnings': (response.warnings if response.success else []) + auto_warnings,
            'error': response.error if not response.success else None,
            'current_date': date.today(),
            'as_of_date': as_of_date,
            'raw_data': response.raw_data if response.success else None,
            'raw_data_json': raw_data_json,
            'current_source': data_source,
            'available_sources': available_sources,
        }

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
