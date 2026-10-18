"""Preserve source execution timestamps on newly imported simulated trades."""

import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    """Use the supplied execution timestamp when one is available."""

    dependencies = [
        ("simulated_trading", "0027_separate_settlement_exchange_identity"),
    ]

    operations = [
        migrations.AlterField(
            model_name="simulatedtrademodel",
            name="execution_time",
            field=models.DateTimeField(
                blank=True,
                default=django.utils.timezone.now,
                editable=False,
                verbose_name="执行时间",
            ),
        ),
    ]
