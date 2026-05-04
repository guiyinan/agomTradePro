from django.db import migrations


def enable_dr007_sync_supported(apps, schema_editor):
    IndicatorCatalog = apps.get_model("data_center", "IndicatorCatalogModel")
    indicator = IndicatorCatalog.objects.filter(code="CN_DR007").first()
    if indicator is None:
        return
    extra = dict(indicator.extra or {})
    extra["governance_scope"] = "macro_console"
    extra["governance_sync_supported"] = True
    indicator.extra = extra
    indicator.save(update_fields=["extra"])


def disable_dr007_sync_supported(apps, schema_editor):
    IndicatorCatalog = apps.get_model("data_center", "IndicatorCatalogModel")
    indicator = IndicatorCatalog.objects.filter(code="CN_DR007").first()
    if indicator is None:
        return
    extra = dict(indicator.extra or {})
    extra.pop("governance_scope", None)
    extra.pop("governance_sync_supported", None)
    indicator.extra = extra
    indicator.save(update_fields=["extra"])


class Migration(migrations.Migration):

    dependencies = [
        ("data_center", "0019_enable_additional_macro_sync_supported"),
    ]

    operations = [
        migrations.RunPython(
            enable_dr007_sync_supported,
            disable_dr007_sync_supported,
        ),
    ]
