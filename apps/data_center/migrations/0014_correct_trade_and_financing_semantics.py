"""Correct trade semantics and clarify fixed-investment/social-financing governance."""

from django.db import migrations


CATALOG_UPDATES = {
    "CN_EXPORTS": {
        "name_cn": "当月出口额",
        "default_unit": "亿美元",
        "description": "月度当月出口金额口径，当前治理口径为绝对额；同比方向应查看 CN_EXPORT_YOY。",
        "extra": {
            "series_semantics": "monthly_level",
            "paired_indicator_code": "CN_EXPORT_YOY",
            "display_priority": 32,
        },
    },
    "CN_EXPORT_YOY": {
        "name_cn": "当月出口额同比增速",
        "default_unit": "%",
        "description": "月度当月出口额同比增速口径，用于观察出口变化方向；与 CN_EXPORTS 配对使用。",
        "extra": {
            "series_semantics": "yoy_rate",
            "paired_indicator_code": "CN_EXPORTS",
            "display_priority": 132,
        },
    },
    "CN_IMPORTS": {
        "name_cn": "当月进口额",
        "default_unit": "亿美元",
        "description": "月度当月进口金额口径，当前治理口径为绝对额；同比方向应查看 CN_IMPORT_YOY。",
        "extra": {
            "series_semantics": "monthly_level",
            "paired_indicator_code": "CN_IMPORT_YOY",
            "display_priority": 32,
        },
    },
    "CN_IMPORT_YOY": {
        "name_cn": "当月进口额同比增速",
        "default_unit": "%",
        "description": "月度当月进口额同比增速口径，用于观察进口变化方向；与 CN_IMPORTS 配对使用。",
        "extra": {
            "series_semantics": "yoy_rate",
            "paired_indicator_code": "CN_IMPORTS",
            "display_priority": 132,
        },
    },
    "CN_FIXED_INVESTMENT": {
        "name_cn": "固定资产投资累计值",
        "default_unit": "亿元",
        "description": "月度年初累计投资额口径，当前 canonical 值直接取累计额；同比方向由 CN_FAI_YOY 按同月累计值派生。",
        "extra": {
            "series_semantics": "cumulative_level",
            "paired_indicator_code": "CN_FAI_YOY",
            "display_priority": 24,
        },
    },
    "CN_FAI_YOY": {
        "name_cn": "固定资产投资累计同比增速",
        "default_unit": "%",
        "description": "月度累计同比增速口径，当前由固定资产投资累计值按同月累计额派生；与 CN_FIXED_INVESTMENT 配对使用。",
        "extra": {
            "series_semantics": "yoy_rate",
            "paired_indicator_code": "CN_FIXED_INVESTMENT",
            "display_priority": 124,
        },
    },
    "CN_SOCIAL_FINANCING": {
        "name_cn": "社会融资规模增量",
        "default_unit": "亿元",
        "description": "月度社会融资规模增量口径，当前 canonical 值为当月增量，不是存量余额；同比方向应查看 CN_SOCIAL_FINANCING_YOY。",
        "extra": {
            "series_semantics": "flow_level",
            "paired_indicator_code": "CN_SOCIAL_FINANCING_YOY",
            "display_priority": 28,
        },
    },
    "CN_SOCIAL_FINANCING_YOY": {
        "name_cn": "社会融资规模增量同比增速",
        "default_unit": "%",
        "description": "月度社会融资规模增量同比增速口径，当前按同月增量派生；与 CN_SOCIAL_FINANCING 配对使用。",
        "extra": {
            "series_semantics": "yoy_rate",
            "paired_indicator_code": "CN_SOCIAL_FINANCING",
            "display_priority": 128,
        },
    },
}


def apply_updates(apps, schema_editor):
    IndicatorCatalog = apps.get_model("data_center", "IndicatorCatalogModel")
    IndicatorUnitRule = apps.get_model("data_center", "IndicatorUnitRuleModel")

    for code, payload in CATALOG_UPDATES.items():
        indicator = IndicatorCatalog.objects.filter(code=code).first()
        if indicator is None:
            continue
        extra = dict(indicator.extra or {})
        extra.update(payload["extra"])
        indicator.name_cn = payload["name_cn"]
        indicator.default_unit = payload["default_unit"]
        indicator.description = payload["description"]
        indicator.extra = extra
        indicator.save(update_fields=["name_cn", "default_unit", "description", "extra"])

    export_rule = IndicatorUnitRule.objects.filter(indicator_code="CN_EXPORTS", original_unit="%").first()
    if export_rule is not None:
        export_rule.original_unit = "亿美元"
        export_rule.storage_unit = "元"
        export_rule.display_unit = "亿美元"
        export_rule.multiplier_to_storage = 100000000
        export_rule.description = "当月出口额按亿美元展示，canonical 存储沿用元层级。"
        export_rule.save(
            update_fields=[
                "original_unit",
                "storage_unit",
                "display_unit",
                "multiplier_to_storage",
                "description",
            ]
        )

    import_rule = IndicatorUnitRule.objects.filter(indicator_code="CN_IMPORTS", original_unit="%").first()
    if import_rule is not None:
        import_rule.original_unit = "亿美元"
        import_rule.storage_unit = "元"
        import_rule.display_unit = "亿美元"
        import_rule.multiplier_to_storage = 100000000
        import_rule.description = "当月进口额按亿美元展示，canonical 存储沿用元层级。"
        import_rule.save(
            update_fields=[
                "original_unit",
                "storage_unit",
                "display_unit",
                "multiplier_to_storage",
                "description",
            ]
        )


def revert_updates(apps, schema_editor):
    IndicatorCatalog = apps.get_model("data_center", "IndicatorCatalogModel")
    IndicatorUnitRule = apps.get_model("data_center", "IndicatorUnitRuleModel")

    for code in ["CN_EXPORTS", "CN_IMPORTS"]:
        indicator = IndicatorCatalog.objects.filter(code=code).first()
        if indicator is None:
            continue
        indicator.default_unit = "%"
        indicator.description = "月度同比增速口径，反映变化方向。"
        extra = dict(indicator.extra or {})
        extra["series_semantics"] = "yoy_rate"
        extra["paired_indicator_code"] = ""
        indicator.extra = extra
        indicator.save(update_fields=["default_unit", "description", "extra"])

    for code in ["CN_EXPORT_YOY", "CN_IMPORT_YOY"]:
        indicator = IndicatorCatalog.objects.filter(code=code).first()
        if indicator is None:
            continue
        extra = dict(indicator.extra or {})
        extra["series_semantics"] = "yoy_rate"
        extra["paired_indicator_code"] = ""
        indicator.extra = extra
        indicator.description = "月度同比增速口径。"
        indicator.save(update_fields=["description", "extra"])

    export_rule = IndicatorUnitRule.objects.filter(indicator_code="CN_EXPORTS", original_unit="亿美元").first()
    if export_rule is not None:
        export_rule.original_unit = "%"
        export_rule.storage_unit = "%"
        export_rule.display_unit = "%"
        export_rule.multiplier_to_storage = 1
        export_rule.description = ""
        export_rule.save(
            update_fields=[
                "original_unit",
                "storage_unit",
                "display_unit",
                "multiplier_to_storage",
                "description",
            ]
        )

    import_rule = IndicatorUnitRule.objects.filter(indicator_code="CN_IMPORTS", original_unit="亿美元").first()
    if import_rule is not None:
        import_rule.original_unit = "%"
        import_rule.storage_unit = "%"
        import_rule.display_unit = "%"
        import_rule.multiplier_to_storage = 1
        import_rule.description = ""
        import_rule.save(
            update_fields=[
                "original_unit",
                "storage_unit",
                "display_unit",
                "multiplier_to_storage",
                "description",
            ]
        )


class Migration(migrations.Migration):

    dependencies = [
        ("data_center", "0013_revert_trade_alias_flags"),
    ]

    operations = [
        migrations.RunPython(apply_updates, revert_updates),
    ]
