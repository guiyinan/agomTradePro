"""Enrich GDP indicator metadata with display semantics."""

from django.db import migrations

GDP_METADATA = {
    "CN_GDP": {
        "name_cn": "GDP 国内生产总值累计值",
        "description": "季度累计值口径，反映经济总量，不是单季值，也不是同比增速。判断增长强弱时应配合 CN_GDP_YOY。",
        "extra": {
            "series_semantics": "cumulative_level",
            "paired_indicator_code": "CN_GDP_YOY",
            "display_priority": 20,
        },
    },
    "CN_GDP_YOY": {
        "name_cn": "GDP同比增速",
        "description": "季度同比增速口径，用于观察经济增长方向；与 CN_GDP 累计值口径配对使用。",
        "extra": {
            "series_semantics": "yoy_rate",
            "paired_indicator_code": "CN_GDP",
            "display_priority": 120,
        },
    },
}


def apply_gdp_semantics(apps, schema_editor):
    IndicatorCatalog = apps.get_model("data_center", "IndicatorCatalogModel")
    for code, payload in GDP_METADATA.items():
        indicator = IndicatorCatalog.objects.filter(code=code).first()
        if indicator is None:
            continue
        merged_extra = dict(indicator.extra or {})
        merged_extra.update(payload["extra"])
        indicator.name_cn = payload["name_cn"]
        indicator.description = payload["description"]
        indicator.extra = merged_extra
        indicator.save(update_fields=["name_cn", "description", "extra"])


def revert_gdp_semantics(apps, schema_editor):
    IndicatorCatalog = apps.get_model("data_center", "IndicatorCatalogModel")

    gdp = IndicatorCatalog.objects.filter(code="CN_GDP").first()
    if gdp is not None:
        reverted_extra = dict(gdp.extra or {})
        reverted_extra.pop("series_semantics", None)
        reverted_extra.pop("paired_indicator_code", None)
        reverted_extra.pop("display_priority", None)
        gdp.name_cn = "GDP 国内生产总值"
        gdp.description = ""
        gdp.extra = reverted_extra
        gdp.save(update_fields=["name_cn", "description", "extra"])

    gdp_yoy = IndicatorCatalog.objects.filter(code="CN_GDP_YOY").first()
    if gdp_yoy is not None:
        reverted_extra = dict(gdp_yoy.extra or {})
        reverted_extra.pop("series_semantics", None)
        reverted_extra.pop("paired_indicator_code", None)
        reverted_extra.pop("display_priority", None)
        gdp_yoy.name_cn = "GDP同比增速"
        gdp_yoy.description = ""
        gdp_yoy.extra = reverted_extra
        gdp_yoy.save(update_fields=["name_cn", "description", "extra"])


class Migration(migrations.Migration):

    dependencies = [
        ("data_center", "0009_rename_indicator_unit_rule_indexes"),
    ]

    operations = [
        migrations.RunPython(apply_gdp_semantics, revert_gdp_semantics),
    ]
