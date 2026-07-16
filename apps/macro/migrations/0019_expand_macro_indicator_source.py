from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("macro", "0018_drop_indicator_unit_config"),
    ]

    operations = [
        migrations.AlterField(
            model_name="macroindicator",
            name="source",
            field=models.CharField(help_text="数据源", max_length=50),
        ),
    ]
