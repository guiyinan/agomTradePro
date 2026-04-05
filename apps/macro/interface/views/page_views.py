"""
Page Views for Macro Data Management.
Updated for collapsible category layout.
"""

import json
from decimal import Decimal, InvalidOperation

from django.apps import apps as django_apps
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Max, Min, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from apps.macro.interface.forms import DataSourceConfigForm
from core.application.provider_inventory import (
    build_provider_dashboard,
    build_unified_provider_inventory,
    group_provider_inventory_by_access,
)
from shared.config.secrets import clear_secrets_cache

DataProviderSettings = django_apps.get_model("macro", "DataProviderSettings")
DataSourceConfig = django_apps.get_model("macro", "DataSourceConfig")
MacroIndicator = django_apps.get_model("macro", "MacroIndicator")


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


def _build_pending_provider_cards(
    providers: list[dict[str, object]],
    data_sources,
) -> list[dict[str, object]]:
    """Build left-panel cards for providers that are not yet editable configs."""
    existing_types = set(
        data_sources.values_list("source_type", flat=True)
    )
    configurable_types = {
        source_type for source_type, _ in DataSourceConfig.SOURCE_TYPE_CHOICES
    }
    suggestions = {
        "tushare": {"name": "Tushare Pro", "description": "补齐 Token / HTTP URL 后即可启用。"},
        "qmt": {"name": "QMT Local", "description": "补齐本地终端参数后即可接入。"},
        "fred": {"name": "FRED", "description": "补齐 API Key 后即可启用。"},
        "wind": {"name": "Wind", "description": "补齐授权参数后即可启用。"},
        "choice": {"name": "Choice", "description": "补齐授权参数后即可启用。"},
    }

    cards: list[dict[str, object]] = []
    for provider in providers:
        key = str(provider["key"])
        if key in existing_types:
            continue
        if key == "akshare":
            continue

        if key in configurable_types:
            suggestion = suggestions.get(
                key,
                {"name": str(provider["label"]), "description": "创建配置后即可启用。"},
            )
            cards.append(
                {
                    "name": suggestion["name"],
                    "badge_label": provider["access_category_label"],
                    "badge_type": key,
                    "status_label": provider["catalog_badge_label"],
                    "status_class": "status-off" if provider["macro_mode"] == "needs_config" else "status-on",
                    "endpoint": provider["config_surface_label"],
                    "description": suggestion["description"],
                    "detail": provider["macro_config_summary"],
                    "action_url": (
                        f"{reverse('macro:datasources')}"
                        f"?mode=create&source_type={key}&name={suggestion['name']}#datasource-workbench"
                    ),
                    "action_label": "新建配置",
                    "is_configurable": True,
                }
            )
            continue

        cards.append(
            {
                "name": str(provider["label"]),
                "badge_label": provider["access_category_label"],
                "badge_type": key,
                "status_label": provider["catalog_badge_label"],
                "status_class": "status-on" if provider["market_registered"] else "status-off",
                "endpoint": provider["config_surface_label"],
                "description": "当前不通过 DataSourceConfig 维护，直接在统一页查看运行状态。",
                "detail": provider["macro_list_presence_label"],
                "action_url": f"{reverse('macro:datasources')}#provider-status",
                "action_label": "查看运行状态",
                "is_configurable": False,
            }
        )
    return cards


def _build_macro_data_summary() -> dict[str, object]:
    """Build a lightweight summary of stored macro data for page diagnostics."""
    macro_queryset = MacroIndicator._default_manager.all()
    total_records = macro_queryset.count()
    latest_period = macro_queryset.aggregate(latest=Max("reporting_period"))["latest"]
    source_breakdown = list(
        macro_queryset.values("source")
        .annotate(count=Count("id"))
        .order_by("-count", "source")
    )
    return {
        "total_records": total_records,
        "indicator_count": macro_queryset.values("code").distinct().count(),
        "latest_period": latest_period,
        "sources": source_breakdown,
        "has_historical_data": total_records > 0,
    }


def _build_system_source_cards(provider_settings: DataProviderSettings) -> list[dict[str, object]]:
    """Build visible cards for built-in/public datasource capabilities."""
    default_source = provider_settings.default_data_source
    default_source_label = provider_settings.get_default_data_source_display()

    akshare_role = "默认抓取源"
    if default_source == "failover":
        akshare_role = "自动容错链路中的主源"
    elif default_source == "tushare":
        akshare_role = "系统内置备用公共源"

    cards = [
        {
            "name": "AKShare 公共接口",
            "badge_type": "akshare",
            "badge_label": "系统内置",
            "status_label": "启用",
            "status_class": "status-on",
            "endpoint": "系统内置 Python Adapter",
            "description": "无需 Token。宏观同步页面和默认抓取链路可直接调用该公共接口。",
            "config_rows": [
                {"label": "认证方式", "value": "无需 Token"},
                {"label": "当前角色", "value": akshare_role},
                {"label": "默认策略", "value": default_source_label},
            ],
            "action_url": reverse("macro:data_controller"),
            "action_label": "打开数据管理器",
        }
    ]

    cards.append(
        {
            "name": "默认抓取策略",
            "badge_type": "system",
            "badge_label": "全局设置",
            "status_label": "生效中",
            "status_class": "status-on",
            "endpoint": default_source_label,
            "description": "这不是单独的数据源，而是系统当前默认抓取模式。即使没有手工录入配置，这条策略也应对管理员可见。",
            "config_rows": [
                {"label": "default_data_source", "value": provider_settings.default_data_source},
                {
                    "label": "failover",
                    "value": "启用" if provider_settings.enable_failover else "关闭",
                },
                {
                    "label": "容差",
                    "value": f"{provider_settings.failover_tolerance * 100:.2f}%",
                },
            ],
            "action_url": f"{reverse('macro:datasources')}#provider-status",
            "action_label": "查看运行状态",
        }
    )
    return cards


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
    provider_settings = DataProviderSettings.load()
    data_sources = DataSourceConfig._default_manager.all().order_by('priority', 'name')
    macro_data_summary = _build_macro_data_summary()
    system_source_cards = _build_system_source_cards(provider_settings)
    unified_provider_inventory = build_unified_provider_inventory()
    provider_dashboard = build_provider_dashboard()
    provider_inventory_sections = group_provider_inventory_by_access(
        unified_provider_inventory
    )
    pending_provider_cards = _build_pending_provider_cards(
        unified_provider_inventory,
        data_sources,
    )
    selected_source = None
    create_mode = request.GET.get("mode") == "create" or not data_sources.exists()
    selected_id = request.GET.get("edit")
    requested_source_type = request.GET.get("source_type")
    requested_name = request.GET.get("name")
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
            valid_source_types = {
                source_type for source_type, _ in DataSourceConfig.SOURCE_TYPE_CHOICES
            }
            if requested_source_type in valid_source_types:
                initial["source_type"] = requested_source_type
            if requested_name:
                initial["name"] = requested_name
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
        'provider_settings': provider_settings,
        'system_source_cards': system_source_cards,
        'unified_provider_inventory': unified_provider_inventory,
        'provider_dashboard': provider_dashboard,
        'provider_inventory_sections': provider_inventory_sections,
        'pending_provider_cards': pending_provider_cards,
        'management_form': form,
        'management_mode': 'create' if create_mode else 'edit',
        'selected_source': selected_source,
        'selected_source_id': selected_source.id if selected_source else None,
        'selected_card': _build_datasource_card(selected_source) if selected_source else None,
        'macro_data_summary': macro_data_summary,
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

