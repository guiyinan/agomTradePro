# Generated manually - Add data_sufficient field to SentimentIndexModel

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("sentiment", "0003_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="sentimentindexmodel",
            name="data_sufficient",
            field=models.BooleanField(
                default=False,
                db_index=True,
                verbose_name="数据充足性",
                help_text="True 表示数据充足，False 表示无数据或数据不足"
            ),
        ),
    ]
