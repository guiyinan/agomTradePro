from apps.data_center.infrastructure.models import (
    IndicatorCatalogModel,
    IndicatorUnitRuleModel,
)


def _infer_dimension_key(unit: str) -> str:
    if unit in {"元", "万元", "亿元", "万亿元", "万美元", "百万美元", "亿美元", "十亿美元"}:
        return "currency"
    if unit in {"%", "BP", "bps"}:
        return "rate"
    if unit in {"指数", "点"}:
        return "index"
    if "/" in unit:
        return "price"
    return "other"


def seed_indicator_rule(
    *,
    code: str,
    original_unit: str,
    source_type: str = "test",
    storage_unit: str | None = None,
    display_unit: str | None = None,
    multiplier_to_storage: float = 1.0,
    default_period_type: str = "M",
    category: str = "test",
) -> None:
    resolved_storage_unit = storage_unit or original_unit
    resolved_display_unit = display_unit or original_unit
    IndicatorCatalogModel.objects.update_or_create(
        code=code,
        defaults={
            "name_cn": code,
            "name_en": code,
            "description": "",
            "category": category,
            "default_period_type": default_period_type,
            "default_unit": resolved_storage_unit,
            "is_active": True,
            "extra": {},
        },
    )
    IndicatorUnitRuleModel.objects.update_or_create(
        indicator_code=code,
        source_type=source_type,
        original_unit=original_unit,
        defaults={
            "dimension_key": _infer_dimension_key(original_unit or resolved_storage_unit),
            "storage_unit": resolved_storage_unit,
            "display_unit": resolved_display_unit,
            "multiplier_to_storage": multiplier_to_storage,
            "is_active": True,
            "priority": 10,
            "description": "integration test rule",
        },
    )
