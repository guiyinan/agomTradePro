"""
Data migration: copy existing macro.DataSourceConfig and
macro.DataProviderSettings rows into data_center tables.

Safe to run multiple times — uses get_or_create so it will not duplicate
rows if already migrated.  The macro source rows are left in place until
Phase 6.

Dependencies:
  macro.0013 — last migration that touched DataSourceConfig/DataProviderSettings
               fields we need (http_url added in 0012, source_type choices in 0013,
               DataProviderSettings added in 0009).
"""

from django.db import migrations


def _copy_provider_configs(apps, schema_editor):
    """Copy macro DataSourceConfig → data_center ProviderConfigModel."""
    try:
        MacroDataSourceConfig = apps.get_model("macro", "DataSourceConfig")
    except LookupError:
        return  # macro not yet at the required migration state — skip

    ProviderConfigModel = apps.get_model("data_center", "ProviderConfigModel")

    for src in MacroDataSourceConfig.objects.all():
        ProviderConfigModel.objects.get_or_create(
            name=src.name,
            defaults={
                "source_type": src.source_type,
                "is_active": src.is_active,
                "priority": src.priority,
                "api_key": src.api_key or "",
                "api_secret": src.api_secret or "",
                "http_url": getattr(src, "http_url", "") or "",
                "api_endpoint": src.api_endpoint or "",
                "extra_config": src.extra_config or {},
                "description": src.description or "",
            },
        )


def _copy_provider_settings(apps, schema_editor):
    """Copy macro DataProviderSettings singleton → data_center DataProviderSettingsModel."""
    try:
        MacroProviderSettings = apps.get_model("macro", "DataProviderSettings")
    except LookupError:
        return  # DataProviderSettings added in macro.0009; not present on fresh setups

    DataProviderSettingsModel = apps.get_model("data_center", "DataProviderSettingsModel")

    try:
        src = MacroProviderSettings.objects.get(pk=1)
    except MacroProviderSettings.DoesNotExist:
        return  # singleton not yet created — nothing to migrate

    # macro uses `default_data_source`; data_center uses `default_source`
    DataProviderSettingsModel.objects.get_or_create(
        pk=1,
        defaults={
            "default_source": src.default_data_source,
            "enable_failover": src.enable_failover,
            "failover_tolerance": src.failover_tolerance,
            "description": getattr(src, "description", "") or "",
        },
    )


class Migration(migrations.Migration):

    dependencies = [
        ("data_center", "0001_initial"),
        # Depend on macro.0013 so all fields (http_url, current source_type choices,
        # DataProviderSettings) are present in the historical model state.
        ("macro", "0013_alter_datasourceconfig_source_type"),
    ]

    operations = [
        migrations.RunPython(
            _copy_provider_configs,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.RunPython(
            _copy_provider_settings,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
