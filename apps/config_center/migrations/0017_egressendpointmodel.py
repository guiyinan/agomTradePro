"""Store operator-managed egress metadata; credentials remain in secret store."""

from django.db import migrations, models


class Migration(migrations.Migration):
    """Create the Config Center egress endpoint table."""

    dependencies = [("config_center", "0016_merge_runtime_materialization_and_secret_cutover")]

    operations = [
        migrations.CreateModel(
            name="EgressEndpointModel",
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
                ("name", models.CharField(max_length=120)),
                ("region", models.CharField(db_index=True, max_length=40)),
                (
                    "protocol",
                    models.CharField(
                        choices=[
                            ("http", "HTTP proxy"),
                            ("https", "HTTPS proxy"),
                        ],
                        default="http",
                        max_length=12,
                    ),
                ),
                ("host", models.CharField(max_length=255)),
                ("port", models.PositiveIntegerField()),
                ("username_secret_ref", models.CharField(blank=True, default="", max_length=300)),
                ("password_secret_ref", models.CharField(blank=True, default="", max_length=300)),
                ("enabled", models.BooleanField(db_index=True, default=False)),
                ("concurrency_limit", models.PositiveIntegerField(default=4)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"db_table": "config_center_egress_endpoint", "ordering": ("name", "id")},
        ),
    ]
