"""Keep published quote, bar, valuation and financial rows across refreshes."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("data_center", "0084_normalize_tushare_valuation_market_cap_units")]

    operations = [
        migrations.AlterUniqueTogether(
            name="financialfactmodel",
            unique_together={
                (
                    "asset_code",
                    "period_end",
                    "period_type",
                    "metric_code",
                    "source",
                    "revision_number",
                )
            },
        ),
        migrations.AlterUniqueTogether(
            name="pricebarmodel",
            unique_together={
                ("asset_code", "bar_date", "freq", "adjustment", "source", "revision_number")
            },
        ),
        migrations.AlterUniqueTogether(
            name="quotesnapshotmodel",
            unique_together={("asset_code", "snapshot_at", "source", "revision_number")},
        ),
        migrations.AlterUniqueTogether(
            name="valuationfactmodel",
            unique_together={("asset_code", "val_date", "source", "revision_number")},
        ),
        migrations.AddIndex(
            model_name="publicationmembermodel",
            index=models.Index(fields=["fact_table", "fact_pk"], name="dc_pub_member_fact_idx"),
        ),
    ]
