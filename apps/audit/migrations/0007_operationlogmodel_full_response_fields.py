from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("audit", "0006_add_operation_log_model"),
    ]

    operations = [
        migrations.AddField(
            model_name="operationlogmodel",
            name="exception_traceback",
            field=models.TextField(blank=True, verbose_name="异常堆栈"),
        ),
        migrations.AddField(
            model_name="operationlogmodel",
            name="response_payload",
            field=models.JSONField(blank=True, null=True, verbose_name="响应载荷", help_text="结构化响应内容，已脱敏"),
        ),
        migrations.AddField(
            model_name="operationlogmodel",
            name="response_text",
            field=models.TextField(blank=True, verbose_name="响应文本快照", help_text="完整或截断后的文本响应"),
        ),
    ]
