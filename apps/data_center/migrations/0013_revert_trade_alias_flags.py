"""Revert over-aggressive alias flags for trade indicators."""

from django.db import migrations

TRADE_CODES = {
    "CN_EXPORT_YOY": {
        "description": "月度同比增速口径，反映出口变化方向；当前仍需与绝对值口径分离治理。",
    },
    "CN_IMPORT_YOY": {
        "description": "月度同比增速口径，反映进口变化方向；当前仍需与绝对值口径分离治理。",
    },
}


def apply_trade_reset(apps, schema_editor):
    IndicatorCatalog = apps.get_model("data_center", "IndicatorCatalogModel")
    for code, payload in TRADE_CODES.items():
        indicator = IndicatorCatalog.objects.filter(code=code).first()
        if indicator is None:
            continue
        extra = dict(indicator.extra or {})
        extra.pop("alias_of_indicator_code", None)
        extra.pop("governance_status", None)
        indicator.description = payload["description"]
        indicator.extra = extra
        indicator.save(update_fields=["description", "extra"])


def revert_trade_reset(apps, schema_editor):
    IndicatorCatalog = apps.get_model("data_center", "IndicatorCatalogModel")
    for code in TRADE_CODES:
        indicator = IndicatorCatalog.objects.filter(code=code).first()
        if indicator is None:
            continue
        extra = dict(indicator.extra or {})
        target = "CN_EXPORTS" if code == "CN_EXPORT_YOY" else "CN_IMPORTS"
        extra["alias_of_indicator_code"] = target
        extra["governance_status"] = "alias_only"
        indicator.description = (
            f"兼容别名代码，canonical 指标为 {target}；不再单独维护独立时序。"
        )
        indicator.extra = extra
        indicator.save(update_fields=["description", "extra"])


class Migration(migrations.Migration):

    dependencies = [
        ("data_center", "0012_mark_macro_alias_indicators"),
    ]

    operations = [
        migrations.RunPython(apply_trade_reset, revert_trade_reset),
    ]
