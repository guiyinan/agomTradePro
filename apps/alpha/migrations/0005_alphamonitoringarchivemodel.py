from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("alpha", "0004_alphascorecachemodel_scope_hash_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="AlphaMonitoringArchiveModel",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("archive_key", models.CharField(db_index=True, max_length=120, unique=True)),
                (
                    "archive_type",
                    models.CharField(
                        db_index=True,
                        default="score_cache_cleanup",
                        max_length=50,
                    ),
                ),
                ("cutoff_date", models.DateField(db_index=True)),
                ("row_count", models.PositiveIntegerField(default=0)),
                ("payload", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Alpha 监控归档",
                "verbose_name_plural": "Alpha 监控归档",
                "db_table": "alpha_monitoring_archive",
                "ordering": ["-cutoff_date", "-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="alphamonitoringarchivemodel",
            index=models.Index(
                fields=["archive_type", "cutoff_date"],
                name="alpha_monit_archive_9a1b19_idx",
            ),
        ),
    ]
