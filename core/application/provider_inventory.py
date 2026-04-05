"""Unified provider inventory for macro and market-data pages."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from apps.market_data.application.registry_factory import get_registry
from apps.macro.infrastructure.models import DataProviderSettings, DataSourceConfig

_PROVIDER_ORDER = [
    "akshare",
    "eastmoney",
    "tushare",
    "qmt",
    "fred",
    "wind",
    "choice",
]

_PROVIDER_LABELS = {
    "akshare": "AKShare",
    "eastmoney": "EastMoney / 东方财富",
    "tushare": "Tushare",
    "qmt": "QMT / XtQuant",
    "fred": "FRED",
    "wind": "Wind",
    "choice": "Choice",
}

_CAPABILITY_LABELS = {
    "realtime_quote": "实时行情",
    "capital_flow": "资金流向",
    "stock_news": "新闻",
    "technical_factors": "技术指标",
    "historical_price": "历史价格",
}

_MACRO_MODE_LABELS = {
    "custom": "自定义配置",
    "builtin": "系统内置",
    "needs_config": "待配置",
    "none": "未接入",
}

_ACCESS_CATEGORY_DEFINITIONS = {
    "public": {
        "label": "公开数据",
        "description": "免账号或系统可直接使用的公开数据源。",
        "empty_message": "当前没有公开数据 Provider。",
    },
    "licensed": {
        "label": "授权数据",
        "description": "需要 Token、账号或额度授权的数据源。",
        "empty_message": "当前没有授权数据 Provider。",
    },
    "local_terminal": {
        "label": "本地终端",
        "description": "依赖本地终端或本机环境接入的数据源。",
        "empty_message": "当前没有本地终端 Provider。",
    },
}

_ACCESS_CATEGORY_ORDER = ["public", "licensed", "local_terminal"]


def _normalize_provider_key(name: str) -> str:
    normalized = (name or "").strip().lower()
    if normalized.startswith("qmt"):
        return "qmt"
    if normalized == "akshare_general":
        return "akshare"
    return normalized


def _resolve_access_category(provider_key: str) -> str:
    """Classify providers by user-facing access model."""
    if provider_key in {"akshare", "eastmoney", "fred"}:
        return "public"
    if provider_key == "qmt":
        return "local_terminal"
    return "licensed"


def _resolve_macro_mode(
    *,
    provider_key: str,
    provider_settings: DataProviderSettings,
    custom_items: list[dict[str, Any]],
) -> str:
    """Resolve how a provider should be presented on macro-facing pages."""
    if custom_items:
        return "custom"
    if provider_key == "akshare":
        return "builtin"
    if (
        provider_key == "tushare"
        and provider_settings.default_data_source in {"tushare", "failover"}
    ):
        return "needs_config"
    return "none"


def _get_macro_config_summary(macro_mode: str, custom_active_count: int, custom_total: int) -> str:
    """Return a compact, human-readable macro configuration summary."""
    if macro_mode == "custom":
        return f"{custom_active_count}/{custom_total} 条已启用"
    if macro_mode == "builtin":
        return "系统内置，无需单独建配置"
    if macro_mode == "needs_config":
        return "策略已引用，但本页还未创建配置记录"
    return "未接入"


def _get_config_surface_label(macro_mode: str, market_registered: bool) -> str:
    """Return the primary surface where the provider should be understood/configured."""
    if macro_mode in {"custom", "needs_config"}:
        return "统一数据源中心"
    if macro_mode == "builtin":
        return "系统内置 / 无需配置"
    if market_registered:
        return "统一数据源中心（只读 / 运行状态）"
    return "当前未暴露配置入口"


def _get_catalog_badge_label(macro_mode: str, market_registered: bool) -> str:
    """Return a cross-page badge label for unified provider cards."""
    if macro_mode == "needs_config":
        return "待配置"
    if market_registered and macro_mode != "none":
        return "跨域 Provider"
    if market_registered:
        return "运行时已注册"
    if macro_mode == "builtin":
        return "系统内置"
    if macro_mode == "custom":
        return "自定义配置"
    return "未接入"


def _get_catalog_badge_tone(macro_mode: str, market_registered: bool) -> str:
    """Return a semantic tone for provider catalog badges."""
    if macro_mode == "needs_config":
        return "warning"
    if market_registered and macro_mode != "none":
        return "neutral"
    if market_registered:
        return "neutral"
    if macro_mode == "builtin":
        return "muted"
    if macro_mode == "custom":
        return "info"
    return "muted"


def _get_macro_list_presence_label(macro_mode: str, market_registered: bool) -> str:
    """Explain whether the provider appears in macro datasource management lists."""
    if macro_mode == "custom":
        return "会显示在左侧可编辑列表"
    if macro_mode == "builtin":
        return "会显示为左侧系统内置卡片"
    if macro_mode == "needs_config":
        return "会显示在左侧待补配置列表"
    if market_registered:
        return "会显示在左侧只读列表"
    return "当前页不显示"


def build_unified_provider_inventory() -> list[dict[str, Any]]:
    """Build a unified provider catalog across macro and market-data domains."""
    provider_settings = DataProviderSettings.load()
    custom_rows = list(
        DataSourceConfig._default_manager.all().values(
            "name",
            "source_type",
            "is_active",
            "priority",
        )
    )
    custom_by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in custom_rows:
        custom_by_type[str(row["source_type"])].append(row)

    market_by_provider: dict[str, dict[str, Any]] = {}
    for status in get_registry().get_all_statuses():
        raw = status.to_dict()
        key = _normalize_provider_key(str(raw["provider_name"]))
        item = market_by_provider.setdefault(
            key,
            {
                "registered": False,
                "healthy": True,
                "capabilities": set(),
                "registered_names": set(),
            },
        )
        item["registered"] = True
        item["healthy"] = item["healthy"] and bool(raw["is_healthy"])
        item["capabilities"].add(str(raw["capability"]))
        item["registered_names"].add(str(raw["provider_name"]))

    known_keys = set(_PROVIDER_ORDER) | set(custom_by_type.keys()) | set(market_by_provider.keys())

    inventory: list[dict[str, Any]] = []
    for key in sorted(known_keys, key=lambda item: (_PROVIDER_ORDER.index(item) if item in _PROVIDER_ORDER else 999, item)):
        custom_items = sorted(
            custom_by_type.get(key, []),
            key=lambda row: (row["priority"], row["name"]),
        )
        market_item = market_by_provider.get(key, {})
        custom_active_count = sum(1 for row in custom_items if row["is_active"])
        macro_mode = _resolve_macro_mode(
            provider_key=key,
            provider_settings=provider_settings,
            custom_items=custom_items,
        )
        domains: list[str] = []
        if macro_mode != "none":
            domains.append("宏观")
        if market_item.get("registered"):
            domains.append("市场数据")

        if not domains:
            continue

        access_category = _resolve_access_category(key)

        inventory.append(
            {
                "key": key,
                "label": _PROVIDER_LABELS.get(key, key.upper()),
                "access_category": access_category,
                "access_category_label": _ACCESS_CATEGORY_DEFINITIONS[access_category]["label"],
                "access_category_description": _ACCESS_CATEGORY_DEFINITIONS[access_category]["description"],
                "domains": domains,
                "macro_mode": macro_mode,
                "macro_mode_label": _MACRO_MODE_LABELS[macro_mode],
                "catalog_badge_label": _get_catalog_badge_label(
                    macro_mode,
                    bool(market_item.get("registered")),
                ),
                "catalog_badge_tone": _get_catalog_badge_tone(
                    macro_mode,
                    bool(market_item.get("registered")),
                ),
                "macro_config_summary": _get_macro_config_summary(
                    macro_mode,
                    custom_active_count,
                    len(custom_items),
                ),
                "macro_list_presence_label": _get_macro_list_presence_label(
                    macro_mode,
                    bool(market_item.get("registered")),
                ),
                "config_surface_label": _get_config_surface_label(
                    macro_mode,
                    bool(market_item.get("registered")),
                ),
                "custom_total": len(custom_items),
                "custom_active_count": custom_active_count,
                "default_macro_source": provider_settings.default_data_source == key,
                "macro_referenced_by_strategy": (
                    key == "tushare"
                    and provider_settings.default_data_source in {"tushare", "failover"}
                ),
                "shows_in_macro_page": macro_mode != "none",
                "market_registered": bool(market_item.get("registered")),
                "market_healthy": bool(market_item.get("healthy", False)),
                "market_capabilities": [
                    _CAPABILITY_LABELS.get(capability, capability)
                    for capability in sorted(market_item.get("capabilities", set()))
                ],
                "registered_names": sorted(market_item.get("registered_names", set())),
            }
        )

    return inventory


def group_provider_inventory_by_access(
    inventory: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Group provider cards into public / licensed / local-terminal sections."""
    grouped_items: dict[str, list[dict[str, Any]]] = {
        key: [] for key in _ACCESS_CATEGORY_ORDER
    }
    for item in inventory:
        grouped_items.setdefault(item["access_category"], []).append(item)

    sections: list[dict[str, Any]] = []
    for key in _ACCESS_CATEGORY_ORDER:
        items = grouped_items.get(key, [])
        sections.append(
            {
                "key": key,
                "label": _ACCESS_CATEGORY_DEFINITIONS[key]["label"],
                "description": _ACCESS_CATEGORY_DEFINITIONS[key]["description"],
                "empty_message": _ACCESS_CATEGORY_DEFINITIONS[key]["empty_message"],
                "items": items,
            }
        )
    return sections


def build_provider_dashboard() -> dict[str, object]:
    """Build a market-provider runtime summary for the unified datasource page."""
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
        "healthy_provider_count": sum(
            1 for provider in providers if provider["healthy"]
        ),
        "unhealthy_provider_count": sum(
            1 for provider in providers if not provider["healthy"]
        ),
        "providers": providers,
    }
