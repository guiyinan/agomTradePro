"""Add nullable fetch identity/hash columns without backfilling history."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("data_center", "0069_macro_factor_research_source"),
    ]

    operations = [
        migrations.AddField(
            model_name="rawauditmodel",
            name="run_id",
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="rawauditmodel",
            name="content_hash",
            field=models.CharField(blank=True, db_index=True, max_length=64, null=True),
        ),
    ]
