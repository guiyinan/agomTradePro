# Generated migration for home workflow outsourcing spec
# Adds decision tracking fields to AlphaCandidateModel

from django.db import migrations, models


class Migration(migrations.Migration):
    """
    Alpha 候选模型扩展迁移

    新增字段用于首页主流程闭环改造：
    - last_decision_request_id: 最后决策请求 ID
    - last_execution_status: 最后执行状态

    数据回填规则：
    - 若候选已 EXECUTED 但无执行记录，标记 last_execution_status='UNKNOWN_LEGACY'
    """

    dependencies = [
        ("alpha_trigger", "0001_initial"),
    ]

    operations = [
        # 添加 last_decision_request_id 字段
        migrations.AddField(
            model_name="alphacandidatemodel",
            name="last_decision_request_id",
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text="最后决策请求 ID",
                max_length=64,
            ),
        ),
        # 添加 last_execution_status 字段
        migrations.AddField(
            model_name="alphacandidatemodel",
            name="last_execution_status",
            field=models.CharField(
                blank=True,
                choices=[
                    ("PENDING", "待执行"),
                    ("EXECUTED", "已执行"),
                    ("FAILED", "执行失败"),
                    ("CANCELLED", "已取消"),
                    ("UNKNOWN_LEGACY", "历史数据（未知状态）"),
                ],
                help_text="最后执行状态",
                max_length=16,
            ),
        ),
        # 添加索引
        migrations.AddIndex(
            model_name="alphacandidatemodel",
            index=models.Index(fields=["last_decision_request_id"], name="alpha_candi_last_de_857354_idx"),
        ),
        # 数据回填：已 EXECUTED 但无执行记录的候选标记为 UNKNOWN_LEGACY
        migrations.RunSQL(
            sql="UPDATE alpha_candidate SET last_decision_request_id = '', last_execution_status = 'UNKNOWN_LEGACY' WHERE status = 'EXECUTED' AND (last_execution_status IS NULL OR last_execution_status = '');",
            reverse_sql="",
        ),
        # 数据回填：非 EXECUTED 状态的候选设置默认值
        migrations.RunSQL(
            sql="UPDATE alpha_candidate SET last_decision_request_id = '', last_execution_status = '' WHERE status != 'EXECUTED' AND (last_decision_request_id IS NULL OR last_execution_status IS NULL);",
            reverse_sql="",
        ),
    ]
