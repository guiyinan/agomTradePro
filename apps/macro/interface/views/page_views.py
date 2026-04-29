"""Page views for macro data management."""

from decimal import InvalidOperation
from typing import Any

from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from apps.macro.application.interface_services import (
    get_macro_data_page_snapshot,
)


def safe_float(value: Any) -> float | None:
    """Safely convert a value to float, handling invalid numeric inputs."""

    if value is None:
        return None
    try:
        converted = float(value)
        if not (converted == converted):
            return None
        if abs(converted) == float("inf"):
            return None
        return converted
    except (InvalidOperation, ValueError, TypeError):
        return None


CATEGORY_DEFINITIONS = [
    {
        "id": "growth",
        "icon": "📈",
        "name": "增长类",
        "keywords": ["PMI", "GDP", "工业增加值", "零售", "投资", "利润"],
        "code_prefixes": [
            "CN_PMI",
            "CN_VALUE_ADDED",
            "CN_RETAIL_SALES",
            "CN_FIXED_INVESTMENT",
            "CN_GDP",
            "CN_INDUSTRIAL_PROFIT",
        ],
    },
    {
        "id": "inflation",
        "icon": "💹",
        "name": "通胀类",
        "keywords": ["CPI", "PPI", "PPirm", "价格", "消费价格", "生产者"],
        "code_prefixes": ["CN_CPI", "CN_PPI", "CN_PPIRM"],
    },
    {
        "id": "money",
        "icon": "💰",
        "name": "货币类",
        "keywords": ["M2", "M1", "M0", "SHIBOR", "LPR", "利率", "准备金", "逆回购", "存款", "贷款"],
        "code_prefixes": [
            "CN_M2",
            "CN_M1",
            "CN_M0",
            "CN_SHIBOR",
            "CN_LPR",
            "CN_RRR",
            "CN_RESERVE_RATIO",
            "CN_REVERSE_REPO",
            "CN_LOAN_RATE",
        ],
    },
    {
        "id": "trade",
        "icon": "🚢",
        "name": "贸易类",
        "keywords": ["出口", "进口", "贸易", "外汇", "储备"],
        "code_prefixes": ["CN_EXPORT", "CN_IMPORT", "CN_TRADE", "CN_FX_RESERVE"],
    },
    {
        "id": "financial",
        "icon": "🏦",
        "name": "金融类",
        "keywords": ["股票", "债券", "信贷", "融资", "市值"],
        "code_prefixes": [
            "CN_STOCK",
            "CN_BOND",
            "CN_NEW_CREDIT",
            "CN_SOCIAL_FINANCING",
            "CN_RMB_DEPOSIT",
            "CN_RMB_LOAN",
        ],
    },
    {
        "id": "other",
        "icon": "📊",
        "name": "其他",
        "keywords": [],
        "code_prefixes": [],
    },
]


def _get_indicator_display_name(code: str) -> str:
    """Return a display label for the indicator code."""

    return code


def _classify_indicator(code: str) -> str:
    """Classify an indicator code into the UI categories."""

    code_upper = code.upper()
    for category_definition in CATEGORY_DEFINITIONS:
        if category_definition["id"] == "other":
            continue
        for prefix in category_definition["code_prefixes"]:
            if code_upper.startswith(prefix):
                return category_definition["id"]

    display_name = _get_indicator_display_name(code)
    for category_definition in CATEGORY_DEFINITIONS:
        if category_definition["id"] == "other":
            continue
        for keyword in category_definition["keywords"]:
            if keyword in display_name or keyword in code_upper:
                return category_definition["id"]

    return "other"


def macro_data_view(request: HttpRequest) -> HttpResponse:
    """Render the macro data management page."""

    selected_indicator = request.GET.get("indicator", "")
    search_query = request.GET.get("search", "")
    snapshot = get_macro_data_page_snapshot(selected_indicator=selected_indicator)

    indicator_map = snapshot["indicator_map"]
    resolved_selected_indicator = snapshot["selected_indicator"]
    indicator_categories = []
    for category_definition in CATEGORY_DEFINITIONS:
        category_indicators = [
            indicator
            for code, indicator in indicator_map.items()
            if _classify_indicator(code) == category_definition["id"]
        ]
        category_indicators.sort(key=lambda item: item["code"])
        if category_indicators:
            indicator_categories.append(
                {
                    "id": category_definition["id"],
                    "icon": category_definition["icon"],
                    "name": category_definition["name"],
                    "is_selected_category": any(
                        indicator["code"] == resolved_selected_indicator
                        for indicator in category_indicators
                    ),
                    "indicators": category_indicators,
                }
            )

    selected_indicator_data = indicator_map.get(resolved_selected_indicator)
    chart_dates = [row["reporting_period"][:7] for row in snapshot["history"]]
    chart_values = [safe_float(row["value"]) for row in snapshot["history"]]

    context = {
        "indicator_categories": indicator_categories,
        "selected_indicator": resolved_selected_indicator,
        "selected_indicator_data": selected_indicator_data,
        "chart_dates": chart_dates,
        "chart_values": chart_values,
        "filter_search": search_query,
        "stats": snapshot["stats"],
        "min_date": snapshot["min_date"],
        "max_date": snapshot["max_date"],
    }
    return render(request, "macro/data.html", context)


def data_controller_view(request: HttpRequest) -> HttpResponse:
    """Redirect legacy macro controller traffic to the data-center governance console."""

    return redirect("/data-center/providers/")
