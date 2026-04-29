from django.db import migrations


UNIT_FIXES = {
    "CN_PMI": "指数",
    "CN_NON_MAN_PMI": "指数",
    "CN_CPI": "指数",
    "CN_PPI": "指数",
    "CN_M2": "万亿元",
}


def apply_unit_fixes(apps, schema_editor):
    IndicatorCatalog = apps.get_model("data_center", "IndicatorCatalogModel")
    for code, unit in UNIT_FIXES.items():
        IndicatorCatalog.objects.filter(code=code).update(default_unit=unit)


def revert_unit_fixes(apps, schema_editor):
    IndicatorCatalog = apps.get_model("data_center", "IndicatorCatalogModel")
    legacy_units = {
        "CN_PMI": "%",
        "CN_NON_MAN_PMI": "%",
        "CN_CPI": "%",
        "CN_PPI": "%",
        "CN_M2": "亿元",
    }
    for code, unit in legacy_units.items():
        IndicatorCatalog.objects.filter(code=code).update(default_unit=unit)


class Migration(migrations.Migration):

    dependencies = [
        ("data_center", "0004_seed_indicator_catalog"),
    ]

    operations = [
        migrations.RunPython(apply_unit_fixes, revert_unit_fixes),
    ]
