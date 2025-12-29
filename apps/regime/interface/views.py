"""
Interface Views for Regime Calculation.

DRF Views and page views for regime calculation.
"""

from django.shortcuts import render
from datetime import date
from apps.regime.application.use_cases import CalculateRegimeUseCase, CalculateRegimeRequest
from apps.macro.infrastructure.repositories import DjangoMacroRepository
from apps.macro.infrastructure.models import DataSourceConfig


def regime_dashboard_view(request):
    """Regime 判定仪表板页面"""
    import json

    try:
        # 获取可用的数据源列表
        available_sources = DataSourceConfig.objects.filter(is_active=True).order_by('priority')

        # 获取查询参数，默认使用优先级最高的数据源
        default_source = available_sources.first().source_type if available_sources.exists() else 'akshare'
        data_source = request.GET.get('source', default_source)

        repository = DjangoMacroRepository()
        use_case = CalculateRegimeUseCase(repository)

        # 获取今天的日期
        today = date.today()

        # 计算当前 Regime
        request_obj = CalculateRegimeRequest(
            as_of_date=today,
            use_pit=False,
            growth_indicator="PMI",
            inflation_indicator="CPI",
            data_source=data_source
        )

        response = use_case.execute(request_obj)

        # 准备图表数据
        raw_data_json = json.dumps(response.raw_data) if response.raw_data else None
        intermediate_data_json = json.dumps(response.intermediate_data) if response.intermediate_data else None

        context = {
            'snapshot': response.snapshot if response.success else None,
            'warnings': response.warnings if response.success else [],
            'error': response.error if not response.success else None,
            'current_date': today,
            'raw_data': response.raw_data if response.success else None,
            'intermediate_data': response.intermediate_data if response.success else None,
            'raw_data_json': raw_data_json,
            'intermediate_data_json': intermediate_data_json,
            'current_source': data_source,
            'available_sources': available_sources,
        }

    except Exception as e:
        available_sources = DataSourceConfig.objects.filter(is_active=True).order_by('priority')
        default_source = available_sources.first().source_type if available_sources.exists() else 'akshare'
        data_source = request.GET.get('source', default_source)

        context = {
            'snapshot': None,
            'warnings': [],
            'error': str(e),
            'current_date': date.today(),
            'raw_data': None,
            'intermediate_data': None,
            'raw_data_json': None,
            'intermediate_data_json': None,
            'current_source': data_source,
            'available_sources': available_sources,
        }

    return render(request, 'regime/dashboard.html', context)
