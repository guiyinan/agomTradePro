"""Drop legacy DataSourceConfig and DataProviderSettings tables.

These models have been superseded by apps.data_center.ProviderConfigModel and
apps.data_center.DataProviderSettingsModel respectively.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("macro", "0013_alter_datasourceconfig_source_type"),
    ]

    operations = [
        migrations.DeleteModel(
            name="DataSourceConfig",
        ),
        migrations.DeleteModel(
            name="DataProviderSettings",
        ),
    ]
