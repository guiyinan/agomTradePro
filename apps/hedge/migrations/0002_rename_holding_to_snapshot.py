"""
Rename HedgePortfolioHoldingModel to HedgePortfolioSnapshotModel.

Preserves existing data by renaming the model and table.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("hedge", "0001_initial"),
    ]

    operations = [
        # 1. Rename the model (Django internal state)
        migrations.RenameModel(
            old_name="HedgePortfolioHoldingModel",
            new_name="HedgePortfolioSnapshotModel",
        ),
        # 2. Rename the database table
        migrations.AlterModelTable(
            name="HedgePortfolioSnapshotModel",
            table="hedge_portfolio_snapshots",
        ),
        # 3. Update verbose names
        migrations.AlterModelOptions(
            name="HedgePortfolioSnapshotModel",
            options={
                "verbose_name": "对冲组合快照",
                "verbose_name_plural": "对冲组合快照",
                "ordering": ["-trade_date"],
            },
        ),
    ]
