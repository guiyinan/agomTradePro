from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("config_center", "0001_initial"),
        ("account", "0027_remove_systemsettingsmodel_macro_index_catalog"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(name="SystemSettingsModel"),
            ],
            database_operations=[],
        ),
    ]

