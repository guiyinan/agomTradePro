# Persist valuation source observation time and replayable fetch time.

import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    """Persist source observation time without rewriting legacy valuation rows."""

    dependencies = [
        ("data_center", "0072_note_non_st_price_limit_scope"),
    ]

    operations = [
        migrations.AddField(
            model_name="valuationfactmodel",
            name="observed_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AlterField(
            model_name="valuationfactmodel",
            name="fetched_at",
            field=models.DateTimeField(default=django.utils.timezone.now),
        ),
    ]
