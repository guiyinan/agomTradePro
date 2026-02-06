"""
Page Views for Macro Data Management.

Contains view functions for rendering HTML pages.
"""

from django.shortcuts import render
from django.db.models import Q, Count, Max, Min
from apps.macro.infrastructure.models import MacroIndicator, DataSourceConfig
from apps.macro.infrastructure.repositories import DjangoMacroRepository
from apps.macro.application.data_management import (
    GetDataManagementSummaryUseCase,
    ScheduleDataFetchUseCase,
)
from apps.macro.infrastructure.adapters import AKShareAdapter
from datetime import datetime, timedelta

from .helpers import get_repository


# 指标名称映射
INDICATOR_NAMES = {
    # 基础指标
    "CN_PMI": "PMI 制造业采购经理指数",
    "CN_NON_MAN_PMI": "非制造业PMI",
    "CN_CPI": "CPI 居民消费价格指数",
    "CN_CPI_NATIONAL_YOY": "全国CPI同比",
    "CN_CPI_NATIONAL_MOM": "全国CPI环比",
    "CN_CPI_URBAN_YOY": "城市CPI同比",
    "CN_CPI_URBAN_MOM": "城市CPI环比",
    "CN_CPI_RURAL_YOY": "农村CPI同比",
    "CN_CPI_RURAL_MOM": "农村CPI环比",
    "CN_PPI": "PPI 工业生产者出厂价格指数",
    "CN_PPI_YOY": "PPI同比",
    "CN_M2": "M2 广义货币供应量",
    "CN_VALUE_ADDED": "工业增加值",
    "CN_RETAIL_SALES": "社会消费品零售总额",
    "CN_GDP": "GDP 国内生产总值",

    # 贸易数据
    "CN_EXPORTS": "出口同比增长",
    "CN_IMPORTS": "进口同比增长",
    "CN_TRADE_BALANCE": "贸易差额",
    "CN_EXPORT": "出口额",
    "CN_IMPORT": "进口额",
    "CN_FX_RESERVE": "外汇储备",

    # 房产数据
    "CN_NEW_HOUSE_PRICE": "新房价格指数",

    # 价格数据
    "CN_OIL_PRICE": "成品油价格",

    # 就业数据
    "CN_UNEMPLOYMENT": "城镇调查失业率",

    # 金融数据
    "CN_LPR": "LPR 贷款市场报价利率",
    "CN_SHIBOR": "SHIBOR 上海银行间同业拆放利率",
    "CN_RRR": "存款准备金率",
    "CN_LOAN_RATE": "贷款利率",
    "CN_RESERVE_RATIO": "存款准备金率",
    "CN_REVERSE_REPO": "逆回购利率",
    "CN_M1": "M1 狭义货币供应量",
    "CN_M0": "M0 流通中现金",

    # 信贷数据
    "CN_NEW_CREDIT": "新增信贷",
    "CN_RMB_DEPOSIT": "人民币存款",
    "CN_RMB_LOAN": "人民币贷款",
    "CN_SOCIAL_FINANCING": "社会融资规模",
    "CN_BOND_ISSUANCE": "债券发行",
    "CN_STOCK_MARKET_CAP": "股票市值",

    # 其他
    "CN_FIXED_INVESTMENT": "固定资产投资",
    "CN_INDUSTRIAL_PROFIT": "工业企业利润",
    "CN_PPIRM": "PPIRM 生产资料价格指数",
    "CN_CPI_FOOD": "CPI 食品价格",
    "CN_CPI_CORE": "CPI 核心CPI",
}


def macro_data_view(request):
    """宏观数据管理页面 - 完整版"""
    # 获取查询参数
    indicator_code = request.GET.get('code', '')
    source = request.GET.get('source', '')
    start_date = request.GET.get('start_date', '')  # 时间范围开始
    end_date = request.GET.get('end_date', '')  # 时间范围结束
    search_query = request.GET.get('search', '')  # 搜索关键词

    # 基础查询
    queryset = MacroIndicator._default_manager.all()

    # 应用搜索（搜索代码或名称）
    if search_query:
        queryset = queryset.filter(
            Q(code__icontains=search_query) |
            Q(code__in=[k for k, v in INDICATOR_NAMES.items() if search_query.lower() in v.lower()])
        )

    # 应用筛选
    if indicator_code:
        queryset = queryset.filter(code__icontains=indicator_code)
    if source:
        queryset = queryset.filter(source=source)

    # 解析日期范围
    start_date_obj = None
    end_date_obj = None
    if start_date:
        try:
            start_date_obj = datetime.strptime(start_date, '%Y-%m-%d').date()
        except:
            pass
    if end_date:
        try:
            end_date_obj = datetime.strptime(end_date, '%Y-%m-%d').date()
        except:
            pass

    # 按指标代码分组，获取所有指标
    indicator_codes = queryset.values('code').annotate(
        count=Count('id'),
        latest_period=Max('reporting_period')
    ).order_by('code')

    # 获取所有指标的完整数据（用于展示）
    all_indicators = []
    for ind in indicator_codes:
        code = ind['code']
        records_query = MacroIndicator._default_manager.filter(code=code).order_by('-reporting_period', '-revision_number')

        # 如果指定了日期范围，筛选范围内的数据
        if start_date_obj and end_date_obj:
            records_query = records_query.filter(reporting_period__gte=start_date_obj, reporting_period__lte=end_date_obj)
        elif start_date_obj:
            records_query = records_query.filter(reporting_period__gte=start_date_obj)
        elif end_date_obj:
            records_query = records_query.filter(reporting_period__lte=end_date_obj)

        records = list(records_query)

        if records:
            # 获取最新记录
            latest = records[0]

            # 获取指标名称
            indicator_name = INDICATOR_NAMES.get(code, code)

            all_indicators.append({
                'code': code,
                'name': indicator_name,
                'latest_value': float(latest.value),
                'latest_period': latest.reporting_period,
                'source': latest.source,
                'period_type': latest.period_type,
                'period_type_display': latest.get_period_type_display(),
                'total_records': len(records),
                'all_records': [
                    {
                        'period': r.reporting_period,
                        'value': float(r.value),
                        'source': r.source,
                        'published_at': r.published_at
                    }
                    for r in records[:100]  # 限制最多100条
                ]
            })

    # 按类别分组
    growth_indicators = [
        'CN_PMI', 'CN_VALUE_ADDED', 'CN_RETAIL_SALES', 'CN_FIXED_INVESTMENT',
        'CN_GDP', 'CN_INDUSTRIAL_PROFIT', 'CN_NON_MAN_PMI'
    ]
    inflation_indicators = [
        'CN_CPI', 'CN_PPI', 'CN_PPIRM', 'CN_CPI_FOOD', 'CN_CPI_CORE',
        'CN_CPI_NATIONAL_YOY', 'CN_CPI_NATIONAL_MOM'
    ]
    money_indicators = [
        'CN_M2', 'CN_M1', 'CN_M0', 'CN_SHIBOR', 'CN_LOAN_RATE',
        'CN_RESERVE_RATIO', 'CN_REVERSE_REPO', 'CN_LPR', 'CN_RRR'
    ]
    trade_indicators = [
        'CN_EXPORT', 'CN_IMPORT', 'CN_TRADE_BALANCE', 'CN_FX_RESERVE',
        'CN_EXPORTS', 'CN_IMPORTS'
    ]
    financial_indicators = [
        'CN_STOCK_MARKET_CAP', 'CN_BOND_ISSUATION', 'CN_SOCIAL_FINANCING',
        'CN_NEW_CREDIT', 'CN_RMB_DEPOSIT', 'CN_RMB_LOAN'
    ]

    def categorize_indicator(code):
        """判断指标类别"""
        if code in growth_indicators:
            return 'growth'
        elif code in inflation_indicators:
            return 'inflation'
        elif code in money_indicators:
            return 'money'
        elif code in trade_indicators:
            return 'trade'
        elif code in financial_indicators:
            return 'financial'
        else:
            return 'other'

    # 分组数据
    categorized_data = {
        'growth': [],
        'inflation': [],
        'money': [],
        'trade': [],
        'financial': [],
        'other': []
    }

    for ind in all_indicators:
        category = categorize_indicator(ind['code'])
        categorized_data[category].append(ind)

    # 统计信息
    stats = {
        'total_indicators': MacroIndicator._default_manager.values('code').distinct().count(),
        'total_records': MacroIndicator._default_manager.count(),
        'latest_date': MacroIndicator._default_manager.aggregate(
            latest=Max('reporting_period')
        )['latest'] or '-',
        'sources': list(MacroIndicator._default_manager.values('source').annotate(
            count=Count('id')
        ).order_by('-count'))
    }

    # 数据源列表
    data_sources = list(DataSourceConfig._default_manager.filter(is_active=True).order_by('priority'))

    # 获取时间范围（用于时间轴）
    date_range = MacroIndicator._default_manager.aggregate(
        min_date=Min('reporting_period'),
        max_date=Max('reporting_period')
    )
    min_date = date_range['min_date']
    max_date = date_range['max_date']

    context = {
        'categorized_data': categorized_data,
        'stats': stats,
        'data_sources': data_sources,
        'filter_code': indicator_code,
        'filter_source': source,
        'filter_start_date': start_date,
        'filter_end_date': end_date,
        'filter_search': search_query,
        'indicator_names': INDICATOR_NAMES,
        'min_date': min_date,
        'max_date': max_date,
    }

    return render(request, 'macro/data.html', context)


def datasource_config_view(request):
    """数据源配置页面"""
    data_sources = DataSourceConfig._default_manager.all().order_by('priority', 'name')

    # 统计信息
    stats = {
        'total': data_sources.count(),
        'active': data_sources.filter(is_active=True).count(),
        'by_type': {}
    }

    for source_type, _ in DataSourceConfig.SOURCE_TYPE_CHOICES:
        count = data_sources.filter(source_type=source_type).count()
        if count > 0:
            stats['by_type'][source_type] = count

    context = {
        'data_sources': data_sources,
        'stats': stats,
        'source_type_choices': DataSourceConfig.SOURCE_TYPE_CHOICES,
    }

    return render(request, 'datasource/config.html', context)


def data_controller_view(request):
    """
    统一数据管理器页面

    提供数据抓取、定时任务配置、数据删除等功能
    """
    repo = get_repository()
    summary_use_case = GetDataManagementSummaryUseCase(repo)
    schedule_use_case = ScheduleDataFetchUseCase(repo)

    # 获取概览信息
    summary = summary_use_case.execute()

    # 获取可调度的指标配置
    scheduled_indicators = schedule_use_case.get_scheduled_indicators()

    # 获取所有可用指标
    all_indicators = MacroIndicator._default_manager.values('code').annotate(
        count=Count('id'),
        latest=Max('reporting_period')
    ).order_by('code')

    # 获取所有数据源
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

