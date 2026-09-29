from django.db import migrations, models


class Migration(migrations.Migration):
    """Store the execution identity used by duplicate delivery guards."""

    dependencies = [
        (
            "task_monitor",
            "0002_rename_task_monit_level__trig_idx_task_monito_level_af3646_idx_and_more",
        ),
    ]

    operations = [
        migrations.AddField(
            model_name="taskexecutionmodel",
            name="attempt_id",
            field=models.CharField(
                blank=True,
                db_index=True,
                max_length=64,
                null=True,
                verbose_name="执行尝试ID",
            ),
        ),
    ]
