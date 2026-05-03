"""Mark duplicate macro catalog codes as compatibility aliases."""

from django.db import migrations


ALIAS_UPDATES = {
    "CN_CPI_YOY": {
        "description": "兼容别名代码，canonical 指标为 CN_CPI_NATIONAL_YOY；不再单独维护独立时序。",
        "extra": {
            "alias_of_indicator_code": "CN_CPI_NATIONAL_YOY",
            "governance_status": "alias_only",
        },
    },
    "CN_EXPORT_YOY": {
        "description": "兼容别名代码，canonical 指标为 CN_EXPORTS；不再单独维护独立时序。",
        "extra": {
            "alias_of_indicator_code": "CN_EXPORTS",
            "governance_status": "alias_only",
        },
    },
    "CN_IMPORT_YOY": {
        "description": "兼容别名代码，canonical 指标为 CN_IMPORTS；不再单独维护独立时序。",
        "extra": {
            "alias_of_indicator_code": "CN_IMPORTS",
            "governance_status": "alias_only",
        },
    },
}


def apply_alias_metadata(apps, schema_editor):
    IndicatorCatalog = apps.get_model("data_center", "IndicatorCatalogModel")
    for code, payload in ALIAS_UPDATES.items():
        indicator = IndicatorCatalog.objects.filter(code=code).first()
        if indicator is None:
            continue
        merged_extra = dict(indicator.extra or {})
        merged_extra.update(payload["extra"])
        indicator.description = payload["description"]
        indicator.extra = merged_extra
        indicator.save(update_fields=["description", "extra"])


def revert_alias_metadata(apps, schema_editor):
    IndicatorCatalog = apps.get_model("data_center", "IndicatorCatalogModel")
    for code, payload in ALIAS_UPDATES.items():
        indicator = IndicatorCatalog.objects.filter(code=code).first()
        if indicator is None:
            continue
        reverted_extra = dict(indicator.extra or {})
        for key in payload["extra"]:
            reverted_extra.pop(key, None)
        indicator.description = ""
        indicator.extra = reverted_extra
        indicator.save(update_fields=["description", "extra"])


class Migration(migrations.Migration):

    dependencies = [
        ("data_center", "0011_enrich_core_macro_semantics"),
    ]

    operations = [
        migrations.RunPython(apply_alias_metadata, revert_alias_metadata),
    ]
