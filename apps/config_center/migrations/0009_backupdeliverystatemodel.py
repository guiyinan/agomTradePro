from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("config_center", "0008_decisionruntimestatemodel"),
    ]

    operations = [
        migrations.CreateModel(
            name="BackupDeliveryStateModel",
            fields=[
                (
                    "state_id",
                    models.PositiveSmallIntegerField(
                        default=1,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "last_sent_at",
                    models.DateTimeField(blank=True, db_index=True, null=True),
                ),
                ("download_token_digest", models.CharField(blank=True, default="", max_length=64)),
                (
                    "download_token_expires_at",
                    models.DateTimeField(blank=True, null=True),
                ),
                (
                    "download_token_consumed_at",
                    models.DateTimeField(blank=True, null=True),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"db_table": "config_center_backup_delivery_state"},
        ),
    ]
