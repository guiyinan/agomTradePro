"""Add nullable canonical vendor quote metric storage without rewriting history."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("data_center", "0103_calendar_publication_permissions"),
    ]

    operations = [
        migrations.AddField(
            model_name="quotesnapshotmodel",
            name="change_pct",
            field=models.DecimalField(
                blank=True,
                decimal_places=12,
                max_digits=38,
                null=True,
            ),
        ),
    ]
