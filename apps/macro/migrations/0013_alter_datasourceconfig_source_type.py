from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("macro", "0012_datasourceconfig_http_url"),
    ]

    operations = [
        migrations.AlterField(
            model_name="datasourceconfig",
            name="source_type",
            field=models.CharField(
                choices=[
                    ("tushare", "Tushare Pro"),
                    ("akshare", "AKShare"),
                    ("qmt", "QMT (XtQuant)"),
                    ("fred", "FRED"),
                    ("wind", "Wind"),
                    ("choice", "Choice"),
                ],
                help_text="数据源类型",
                max_length=20,
            ),
        ),
    ]
