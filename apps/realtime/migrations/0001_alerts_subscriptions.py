"""Create durable realtime alerts and subscriptions."""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PriceAlertModel",
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
                ("asset_code", models.CharField(db_index=True, max_length=32)),
                (
                    "condition",
                    models.CharField(
                        choices=[
                            ("above", "above"),
                            ("below", "below"),
                            ("cross_up", "cross_up"),
                            ("cross_down", "cross_down"),
                        ],
                        max_length=16,
                    ),
                ),
                ("threshold", models.DecimalField(decimal_places=6, max_digits=20)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("active", "active"),
                            ("triggered", "triggered"),
                            ("inactive", "inactive"),
                        ],
                        db_index=True,
                        default="active",
                        max_length=16,
                    ),
                ),
                ("message", models.CharField(blank=True, default="", max_length=500)),
                (
                    "triggered_price",
                    models.DecimalField(
                        blank=True,
                        decimal_places=6,
                        max_digits=20,
                        null=True,
                    ),
                ),
                ("triggered_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "owner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="realtime_price_alerts",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "realtime_price_alert",
                "ordering": ["-created_at", "-id"],
                "indexes": [
                    models.Index(
                        fields=["owner", "status", "asset_code"],
                        name="rt_alert_owner_status_asset",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="PriceSubscriptionModel",
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
                ("asset_code", models.CharField(db_index=True, max_length=32)),
                ("is_active", models.BooleanField(db_index=True, default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "owner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="realtime_price_subscriptions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "realtime_price_subscription",
                "ordering": ["asset_code", "id"],
                "indexes": [
                    models.Index(
                        fields=["owner", "is_active"],
                        name="rt_sub_owner_active_idx",
                    ),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("owner", "asset_code"),
                        name="realtime_subscription_owner_asset_uniq",
                    ),
                ],
            },
        ),
    ]
