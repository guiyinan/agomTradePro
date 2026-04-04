"""
Page Views for Macro Data Management.
Updated for collapsible category layout.
"""

import json
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Max, Min, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from apps.macro.infrastructure.models import DataSourceConfig, MacroIndicator
from apps.macro.interface.forms import DataSourceConfigForm
from shared.config.secrets import clear_secrets_cache


def safe_float(value):
    """Safely convert value to float, handling None, NaN, Infinity"""
    if value is None:
        return None
    try:
        f = float(value)
        # Check for NaN or Infinity
        if not (f == f):  # NaN check
            return None
        if abs(f) == float('inf'):  # Infinity check
            return None
        return f
    except (InvalidOperation, ValueError, TypeError):
        return None


def _mask_credential(value: str) -> str:
    """Mask sensitive credential values for management page display."""
    if not value:
        return "未配置"
    if len(value) <= 8:
        return f"{value[:2]}***{value[-2:]}"
    return f"{value[:4]}...{value[-4:]}"


def _format_extra_config(value: object) -> str:
    """Render JSON config in a readable single string for preview."""
    if not value:
        return "未配置"
    try:
        return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
    except TypeError:
        return str(value)


def _build_datasource_card(source: DataSourceConfig) -> dict[str, object]:
    """Build display-oriented metadata for datasource management cards."""
    endpoint = source.http_url or source.api_endpoint or "未配置"
    return {
        "source": source,
        "masked_api_key": _mask_credential(source.api_key),
        "masked_api_secret": _mask_credential(source.api_secret),
        "endpoint": endpoint,
        "extra_config_preview": _format_extra_config(source.extra_config),
        "has_sensitive_fields": bool(source.api_key or source.api_secret),
    }


# 分类定义：包含ID、图标、名称和关键词匹配规则
# 指标通过代码前缀或名称关键词自动归类
CATEGORY_DEFINITIONS = [
    {
        'id': 'growth',
        'icon': '📈',
        'name': '增长类',
        'keywords': ['PMI', 'GDP', '工业增加值', '零售', '投资', '利润'],
        'code_prefixes': ['CN_PMI', 'CN_VALUE_ADDED', 'CN_RETAIL_SALES',
                          'CN_FIXED_INVESTMENT', 'CN_GDP', 'CN_INDUSTRIAL_PROFIT']
    },
    {
        'id': 'inflation',
        'icon': '💹',
        'name': '通胀类',
        'keywords': ['CPI', 'PPI', 'PPirm', '价格', '消费价格', '生产者'],
        'code_prefixes': ['CN_CPI', 'CN_PPI', 'CN_PPIRM']
    },
    {
        'id': 'money',
        'icon': '💰',
        'name': '货币类',
        'keywords': ['M2', 'M1', 'M0', 'SHIBOR', 'LPR', '利率', '准备金', '逆回购', '存款', '贷款'],
        'code_prefixes': ['CN_M2', 'CN_M1', 'CN_M0', 'CN_SHIBOR', 'CN_LPR',
                          'CN_RRR', 'CN_RESERVE_RATIO', 'CN_REVERSE_REPO', 'CN_LOAN_RATE']
    },
    {
        'id': 'trade',
        'icon': '🚢',
        'name': '贸易类',
        'keywords': ['出口', '进口', '贸易', '外汇', '储备'],
        'code_prefixes': ['CN_EXPORT', 'CN_IMPORT', 'CN_TRADE', 'CN_FX_RESERVE']
    },
    {
        'id': 'financial',
        'icon': '🏦',
        'name': '金融类',
        'keywords': ['股票', '债券', '信贷', '融资', '市值'],
        'code_prefixes': ['CN_STOCK', 'CN_BOND', 'CN_NEW_CREDIT', 'CN_SOCIAL_FINANCING',
                          'CN_RMB_DEPOSIT', 'CN_RMB_LOAN']
    },
    {
        'id': 'other',
        'icon': '📊',
        'name': '其他',
        'keywords': [],
        'code_prefixes': []
    },
]


# 指标名称映射（用于显示更友好的名称）
INDICATOR_NAME_ALIASES = {
    "CN_PMI": "PMI 制造业采购经理指数",
    "CN_NON_MAN_PMI": "非制造业PMI",
    "CN_CPI": "CPI 居民消费价格指数",
    "CN_CPI_NATIONAL_YOY": "全国CPI同比",
    "CN_CPI_NATIONAL_MOM": "全国CPI环比",
    "CN_PPI": "PPI 工业生产者出厂价格指数",
    "CN_PPI_YOY": "PPI同比",
    "CN_M2": "M2 广义货币供应量",
    "CN_VALUE_ADDED": "工业增加值",
    "CN_RETAIL_SALES": "社会消费品零售总额",
    "CN_GDP": "GDP 国内生产总值",
    "CN_EXPORTS": "出口同比增长",
    "CN_IMPORTS": "进口同比增长",
    "CN_TRADE_BALANCE": "贸易差额",
    "CN_EXPORT": "出口额",
    "CN_IMPORT": "进口额",
    "CN_FX_RESERVE": "外汇储备",
    "CN_LPR": "LPR 贷款市场报价利率",
    "CN_SHIBOR": "SHIBOR 上海银行间同业拆放利率",
    "CN_RRR": "存款准备金率",
    "CN_M1": "M1 狭义货币供应量",
    "CN_M0": "M0 流通中现金",
    "CN_NEW_CREDIT": "新增信贷",
    "CN_RMB_DEPOSIT": "人民币存款",
    "CN_RMB_LOAN": "人民币贷款",
    "CN_SOCIAL_FINANCING": "社会融资规模",
    "CN_STOCK_MARKET_CAP": "股票市值",
    "CN_FIXED_INVESTMENT": "固定资产投资",
    "CN_INDUSTRIAL_PROFIT": "工业企业利润",
    "CN_PPIRM": "PPIRM 生产资料价格指数",
    "CN_CPI_FOOD": "CPI 食品价格",
    "CN_CPI_CORE": "CPI 核心CPI",
    "CN_RESERVE_RATIO": "存款准备金率",
    "CN_REVERSE_REPO": "逆回购利率",
    "CN_LOAN_RATE": "贷款利率",
    "CN_BOND_ISSUANCE": "债券发行",
    "CN_NEW_HOUSE_PRICE": "新房价格指数",
    "CN_OIL_PRICE": "成品油价格",
    "CN_UNEMPLOYMENT": "城镇调查失业率",
}


def _get_indicator_display_name(code: str) -> str:
    """获取指标的显示名称"""
    return INDICATOR_NAME_ALIASES.get(code, code)


def _classify_indicator(code: str) -> str:
    """根据代码和关键词自动分类指标"""
    code_upper = code.upper()

    # 先检查代码前缀匹配
    for category_def in CATEGORY_DEFINITIONS:
        if category_def['id'] == 'other':
            continue
        for prefix in category_def['code_prefixes']:
            if code_upper.startswith(prefix):
                return category_def['id']

    # 再检查关键词匹配
    display_name = _get_indicator_display_name(code)
    for category_def in CATEGORY_DEFINITIONS:
        if category_def['id'] == 'other':
            continue
        for keyword in category_def['keywords']:
            if keyword in display_name or keyword in code_upper:
                return category_def['id']

    # 默认归入其他类
    return 'other'


def macro_data_view(request):
    """宏观数据管理页面 - 折叠分类布局"""
    # 获取查询参数
    selected_indicator = request.GET.get('indicator', '')
    search_query = request.GET.get('search', '')

    # 获取数据库中所有唯一指标代码
    all_indicator_codes = list(
        MacroIndicator._default_manager.values('code')
        .distinct()
        .order_by('code')
        .values_list('code', flat=True)
    )

    # 按分类组织指标
    indicator_categories = []
    all_indicators_map = {}  # 用于快速查找

    for category_def in CATEGORY_DEFINITIONS:
        # 找出属于此分类的指标
        category_indicators = []
        for code in all_indicator_codes:
            if _classify_indicator(code) == category_def['id']:
                # 获取最新数据
                latest_record = MacroIndicator._default_manager.filter(code=code).order_by('-reporting_period').first()
                if latest_record:
                    ind_info = {
                        'code': code,
                        'name': _get_indicator_display_name(code),
                        'latest_value': safe_float(latest_record.value),
                        'latest_period': latest_record.reporting_period.strftime('%Y-%m'),
                        'unit': latest_record.original_unit or latest_record.unit or '-',
                    }
                    category_indicators.append(ind_info)
                    all_indicators_map[code] = ind_info

        # 按代码排序
        category_indicators.sort(key=lambda x: x['code'])

        # 只有当该分类有指标时才添加
        if category_indicators:
            indicator_categories.append({
                'id': category_def['id'],
                'icon': category_def['icon'],
                'name': category_def['name'],
                'indicators': category_indicators,
            })

    # 默认选择第一个指标（如果没有指定）
    if not selected_indicator and all_indicators_map:
        selected_indicator = list(all_indicators_map.keys())[0]

    # 获取选中指标的详细数据
    selected_indicator_data = None
    chart_dates = []
    chart_values = []

    if selected_indicator and selected_indicator in all_indicators_map:
        selected_indicator_data = all_indicators_map[selected_indicator]

        # 获取历史数据用于图表
        historical_data = MacroIndicator._default_manager.filter(
            code=selected_indicator
        ).order_by('reporting_period')

        chart_dates = [d.reporting_period.strftime('%Y-%m') for d in historical_data]
        chart_values = [safe_float(d.value) for d in historical_data]

    # 统计信息
    stats = {
        'total_indicators': len(all_indicator_codes),
        'total_records': MacroIndicator._default_manager.count(),
        'latest_date': MacroIndicator._default_manager.aggregate(latest=Max('reporting_period'))['latest'],
    }

    # 时间范围
    date_range = MacroIndicator._default_manager.aggregate(
        min_date=Min('reporting_period'),
        max_date=Max('reporting_period')
    )

    context = {
        'indicator_categories': indicator_categories,
        'selected_indicator': selected_indicator,
        'selected_indicator_data': selected_indicator_data,
        'chart_dates': chart_dates,
        'chart_values': chart_values,
        'filter_search': search_query,
        'stats': stats,
        'min_date': date_range['min_date'],
        'max_date': date_range['max_date'],
    }

    return render(request, 'macro/data.html', context)


@login_required(login_url="/account/login/")
def datasource_config_view(request):
    """数据源配置页面"""
    data_sources = DataSourceConfig._default_manager.all().order_by('priority', 'name')
    selected_source = None
    create_mode = request.GET.get("mode") == "create" or not data_sources.exists()
    selected_id = request.GET.get("edit")
    if selected_id:
        selected_source = get_object_or_404(DataSourceConfig, id=selected_id)
        create_mode = False
    elif not create_mode:
        selected_source = data_sources.first()

    if request.method == "POST":
        form = DataSourceConfigForm(request.POST, instance=selected_source)
        if form.is_valid():
            saved = form.save()
            clear_secrets_cache()
            messages.success(
                request,
                "数据源配置已更新" if selected_source else "数据源配置已创建",
            )
            return redirect(f"{reverse('macro:datasources')}?edit={saved.id}")
    else:
        initial = {}
        if create_mode:
            initial["priority"] = data_sources.count() + 1
        form = DataSourceConfigForm(instance=selected_source, initial=initial)

    stats = {
        'total': data_sources.count(),
        'active': data_sources.filter(is_active=True).count(),
        'inactive': data_sources.filter(is_active=False).count(),
        'by_type': {}
    }
    for source_type, _ in DataSourceConfig.SOURCE_TYPE_CHOICES:
        count = data_sources.filter(source_type=source_type).count()
        if count > 0:
            stats['by_type'][source_type] = count

    datasource_cards = [_build_datasource_card(source) for source in data_sources]
    context = {
        'data_sources': data_sources,
        'datasource_cards': datasource_cards,
        'stats': stats,
        'source_type_choices': DataSourceConfig.SOURCE_TYPE_CHOICES,
        'management_form': form,
        'management_mode': 'create' if create_mode else 'edit',
        'selected_source': selected_source,
        'selected_source_id': selected_source.id if selected_source else None,
        'selected_card': _build_datasource_card(selected_source) if selected_source else None,
    }
    return render(request, 'datasource/config.html', context)


@login_required(login_url="/account/login/")
def datasource_create_view(request):
    """Create data source config without Django admin."""
    if request.method == "POST":
        form = DataSourceConfigForm(request.POST)
        if form.is_valid():
            form.save()
            clear_secrets_cache()
            messages.success(request, "数据源配置已创建")
            return redirect("macro:datasources")
    else:
        form = DataSourceConfigForm()

    return render(
        request,
        "datasource/form.html",
        {"form": form, "page_title": "新增数据源配置", "submit_label": "创建"},
    )


@login_required(login_url="/account/login/")
def datasource_edit_view(request, source_id: int):
    """Edit data source config without Django admin."""
    source = get_object_or_404(DataSourceConfig, id=source_id)
    if request.method == "POST":
        form = DataSourceConfigForm(request.POST, instance=source)
        if form.is_valid():
            form.save()
            clear_secrets_cache()
            messages.success(request, "数据源配置已更新")
            return redirect("macro:datasources")
    else:
        form = DataSourceConfigForm(instance=source)

    return render(
        request,
        "datasource/form.html",
        {"form": form, "page_title": "编辑数据源配置", "submit_label": "保存"},
    )


def data_controller_view(request):
    """统一数据管理器页面"""
    from apps.macro.application.data_management import (
        GetDataManagementSummaryUseCase,
        ScheduleDataFetchUseCase,
    )
    from apps.macro.infrastructure.repositories import DjangoMacroRepository

    from .helpers import get_repository

    repo = get_repository()
    summary_use_case = GetDataManagementSummaryUseCase(repo)
    schedule_use_case = ScheduleDataFetchUseCase(repo)

    summary = summary_use_case.execute()
    scheduled_indicators = schedule_use_case.get_scheduled_indicators()

    all_indicators = MacroIndicator._default_manager.values('code').annotate(
        count=Count('id'),
        latest=Max('reporting_period')
    ).order_by('code')

    sources = MacroIndicator._default_manager.values('source').annotate(
        count=Count('id')
    ).order_by('-count')

    context = {
        'summary': summary,
        'scheduled_indicators': scheduled_indicators,
        'all_indicators': list(all_indicators),
        'sources': list(sources),
    }

    return render(request, 'macro/data_controller.html', context)

