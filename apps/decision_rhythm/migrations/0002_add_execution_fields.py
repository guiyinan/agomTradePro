# Generated migration for home workflow outsourcing spec
# Adds execution tracking fields to DecisionRequestModel

from django.db import migrations, models


class Migration(migrations.Migration):
    """
    决策请求模型扩展迁移

    新增字段用于首页主流程闭环改造：
    - candidate_id: 关联的候选 ID
    - execution_target: 执行目标（NONE/SIMULATED/ACCOUNT）
    - execution_status: 执行状态（PENDING/EXECUTED/FAILED/CANCELLED）
    - executed_at: 执行时间
    - execution_ref: 执行引用

    约束：
    - execution_status='EXECUTED' 时 executed_at 必填
    - execution_target='NONE' 时 execution_ref 应为空
    """

    dependencies = [
        ("decision_rhythm", "0001_initial"),
    ]

    operations = [
        # 添加 candidate_id 字段
        migrations.AddField(
            model_name="decisionrequestmodel",
            name="candidate_id",
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text="关联的候选 ID",
                max_length=64,
            ),
        ),
        # 添加 execution_target 字段
        migrations.AddField(
            model_name="decisionrequestmodel",
            name="execution_target",
            field=models.CharField(
                choices=[
                    ("NONE", "无执行"),
                    ("SIMULATED", "模拟盘执行"),
                    ("ACCOUNT", "实盘执行"),
                ],
                default="NONE",
                help_text="执行目标",
                max_length=16,
            ),
        ),
        # 添加 execution_status 字段
        migrations.AddField(
            model_name="decisionrequestmodel",
            name="execution_status",
            field=models.CharField(
                choices=[
                    ("PENDING", "待执行"),
                    ("EXECUTED", "已执行"),
                    ("FAILED", "执行失败"),
                    ("CANCELLED", "已取消"),
                ],
                db_index=True,
                default="PENDING",
                help_text="执行状态",
                max_length=16,
            ),
        ),
        # 添加 executed_at 字段
        migrations.AddField(
            model_name="decisionrequestmodel",
            name="executed_at",
            field=models.DateTimeField(
                blank=True,
                help_text="执行时间",
                null=True,
            ),
        ),
        # 添加 execution_ref 字段
        migrations.AddField(
            model_name="decisionrequestmodel",
            name="execution_ref",
            field=models.JSONField(
                blank=True,
                help_text="执行引用（如 trade_id, position_id 等）",
                null=True,
            ),
        ),
        # 添加索引
        migrations.AddIndex(
            model_name="decisionrequestmodel",
            index=models.Index(fields=["candidate_id"], name="decision_re_candida_75e212_idx"),
        ),
        migrations.AddIndex(
            model_name="decisionrequestmodel",
            index=models.Index(fields=["execution_status"], name="decision_re_executi_0ef27a_idx"),
        ),
        # 数据回填：旧请求统一设 execution_target='NONE'
        migrations.RunSQL(
            sql="UPDATE decision_request SET candidate_id = '', execution_target = 'NONE', execution_status = 'PENDING' WHERE execution_target IS NULL OR execution_target = '';",
            reverse_sql="",
        ),
    ]
