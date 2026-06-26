from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("policy", "0008_add_in_app_notification"),
    ]

    operations = [
        migrations.AlterField(
            model_name="rsssourceconfigmodel",
            name="rsshub_route_path",
            field=models.CharField(
                blank=True,
                help_text=(
                    "如 /gov/csrc/news/c100028/common_xq_list.shtml，"
                    "完整 URL 将自动构建为: 基址 + 路由 + key"
                ),
                max_length=500,
                verbose_name="RSSHub 路由路径",
            ),
        ),
    ]
