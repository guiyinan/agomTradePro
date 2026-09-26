from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("data_center", "0085_published_market_fact_revisions")]

    operations = [
        migrations.AddField(
            model_name="canonicalpublicationmodel",
            name="scope_blocks",
            field=models.JSONField(default=list, db_default=[]),
        ),
    ]
