from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("macro", "0009_dataprovidersettings"),
    ]

    operations = [
        migrations.CreateModel(
            name="ExchangeRateModel",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "from_currency",
                    models.CharField(max_length=10, verbose_name="源货币"),
                ),
                (
                    "to_currency",
                    models.CharField(max_length=10, verbose_name="目标货币"),
                ),
                (
                    "rate",
                    models.DecimalField(
                        decimal_places=6, max_digits=16, verbose_name="汇率"
                    ),
                ),
                (
                    "effective_date",
                    models.DateField(db_index=True, verbose_name="生效日期"),
                ),
                (
                    "source",
                    models.CharField(
                        default="akshare",
                        max_length=30,
                        verbose_name="数据来源",
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        auto_now_add=True, verbose_name="创建时间"
                    ),
                ),
            ],
            options={
                "verbose_name": "汇率记录",
                "verbose_name_plural": "汇率记录",
                "db_table": "macro_exchange_rate",
                "ordering": ["-effective_date"],
                "unique_together": {
                    ("from_currency", "to_currency", "effective_date")
                },
            },
        ),
        migrations.AddIndex(
            model_name="exchangeratemodel",
            index=models.Index(
                fields=["from_currency", "to_currency", "-effective_date"],
                name="exchange_rate_lookup_idx",
            ),
        ),
    ]
