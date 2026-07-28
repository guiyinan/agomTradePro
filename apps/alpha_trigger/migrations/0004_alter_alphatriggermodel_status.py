from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("alpha_trigger", "0003_alter_alphatriggermodel_trigger_type"),
    ]

    operations = [
        migrations.AlterField(
            model_name="alphatriggermodel",
            name="status",
            field=models.CharField(
                choices=[
                    ("ACTIVE", "活跃"),
                    ("TRIGGERED", "已触发"),
                    ("INVALIDATED", "已证伪"),
                    ("EXPIRED", "已过期"),
                    ("CANCELLED", "已取消"),
                    ("PAUSED", "已暂停"),
                ],
                db_index=True,
                default="ACTIVE",
                help_text="状态",
                max_length=16,
            ),
        ),
    ]
