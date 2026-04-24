"""
Interface Views for Filter Dashboard.

Page views for filter operations.
"""

import json
from datetime import date
from typing import Dict, List

from django.shortcuts import render

from ..application.repository_provider import get_filter_repository
from ..application.use_cases import (
    ApplyFilterRequest,
    ApplyFilterUseCase,
    CompareFiltersUseCase,
    GetFilterDataRequest,
    GetFilterDataUseCase,
)
from ..domain.entities import FilterType


class DjangoFilterRepository:
    """Compatibility wrapper kept for legacy interface tests."""

    def __init__(self):
        self._repository = get_filter_repository()

    def get_filter_config(self, indicator_code: str):
        return self._repository.get_filter_config(indicator_code)

    def __getattr__(self, item):
        return getattr(self._repository, item)


def filter_dashboard_view(request):
    """趋势滤波器仪表板页面"""
    repository = DjangoFilterRepository()
    apply_use_case = ApplyFilterUseCase(repository)
    get_use_case = GetFilterDataUseCase(repository)

    # 获取可用指标列表
    available_indicators = _get_available_indicators(repository)

    # 获取查询参数（默认使用第一个可用指标的代码）
    default_indicator = available_indicators[0]['code'] if available_indicators else 'CN_PMI'
    indicator = request.GET.get('indicator', default_indicator)
    filter_type_str = request.GET.get('filter_type', 'hp')
    filter_type = FilterType.HP if filter_type_str == 'hp' else FilterType.KALMAN

    context = {
        'current_indicator': indicator,
        'current_filter_type': filter_type_str,
        'available_indicators': available_indicators,
        'error': None,
        'chart_data': None,
    }

    try:
        # 尝试获取已保存的滤波结果
        get_response = get_use_case.execute(GetFilterDataRequest(
            indicator_code=indicator,
            filter_type=filter_type,
        ))

        if get_response.success:
            context['chart_data'] = _prepare_chart_data(get_response)
        else:
            # 如果没有保存的结果，尝试计算
            apply_response = apply_use_case.execute(ApplyFilterRequest(
                indicator_code=indicator,
                filter_type=filter_type,
                save_results=True,
            ))

            if apply_response.success:
                # 重新获取数据
                get_response = get_use_case.execute(GetFilterDataRequest(
                    indicator_code=indicator,
                    filter_type=filter_type,
                ))
                if get_response.success:
                    context['chart_data'] = _prepare_chart_data(get_response)
                    context['warnings'] = apply_response.warnings
            else:
                context['error'] = apply_response.error

    except Exception as e:
        context['error'] = str(e)

    return render(request, 'filter/dashboard.html', context)


def _get_available_indicators(repository) -> list[str]:
    """获取可用的指标列表（从数据库动态获取）"""
    return repository.get_available_indicators()


def _prepare_chart_data(response) -> dict:
    """准备图表数据"""
    return {
        'dates': response.dates,
        'original_values': response.original_values,
        'filtered_values': response.filtered_values,
        'slopes': response.slopes,
        'dates_json': json.dumps(response.dates),
        'original_values_json': json.dumps(response.original_values),
        'filtered_values_json': json.dumps(response.filtered_values),
        'slopes_json': json.dumps(response.slopes) if response.slopes else '[]',
    }
