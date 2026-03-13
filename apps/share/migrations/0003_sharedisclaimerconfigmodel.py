from django.db import migrations, models


def seed_default_disclaimer(apps, schema_editor):
    ShareDisclaimerConfigModel = apps.get_model("share", "ShareDisclaimerConfigModel")
    ShareDisclaimerConfigModel.objects.get_or_create(
        singleton_key="default",
        defaults={
            "is_enabled": True,
            "modal_enabled": True,
            "modal_title": "风险提示",
            "modal_confirm_text": "我已知悉",
            "lines": [
                "本页面内容主要用于账户分享、策略复盘和公开交流，不构成投资建议。",
                "页面观点和持仓展示仅代表分享账户当时状态，不代表系统作者观点。",
                "历史业绩不代表未来表现，投资有风险，入市需谨慎。",
                "数据可能存在延迟或缺口，请以实际交易和行情数据为准。",
            ],
        },
    )


class Migration(migrations.Migration):

    dependencies = [
        ("share", "0002_sharelink_theme"),
    ]

    operations = [
        migrations.CreateModel(
            name="ShareDisclaimerConfigModel",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("singleton_key", models.CharField(default="default", editable=False, max_length=32, unique=True, verbose_name="单例键")),
                ("is_enabled", models.BooleanField(default=True, verbose_name="显示底部风险提示")),
                ("modal_enabled", models.BooleanField(default=True, verbose_name="启用风险提示弹窗")),
                ("modal_title", models.CharField(default="风险提示", max_length=120, verbose_name="弹窗标题")),
                ("modal_confirm_text", models.CharField(default="我已知悉", max_length=40, verbose_name="弹窗确认按钮文案")),
                ("lines", models.JSONField(blank=True, default=list, help_text="按顺序展示的风险提示条目", verbose_name="风险提示内容")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="创建时间")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="更新时间")),
            ],
            options={
                "db_table": "share_disclaimer_config",
                "verbose_name": "分享页风险提示配置",
                "verbose_name_plural": "分享页风险提示配置",
            },
        ),
        migrations.RunPython(seed_default_disclaimer, migrations.RunPython.noop),
    ]
