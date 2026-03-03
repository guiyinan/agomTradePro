"""
Decision Model Parameters Initialization Command

初始化推荐模型默认参数。

Usage:
    python manage.py init_decision_model_params [--env ENV] [--force]

Options:
    --env ENV     目标环境 (dev/test/prod)，默认 dev
    --force       强制覆盖已存在的参数
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.decision_rhythm.infrastructure.models import (
    DecisionModelParamConfigModel,
    DecisionModelParamAuditLogModel,
)


# 默认参数配置
DEFAULT_PARAMS = [
    # 模型权重
    {
        "param_key": "alpha_model_weight",
        "param_value": "0.40",
        "param_type": "float",
        "description": "Alpha 模型权重（综合分计算）",
    },
    {
        "param_key": "sentiment_weight",
        "param_value": "0.15",
        "param_type": "float",
        "description": "舆情分数权重（综合分计算）",
    },
    {
        "param_key": "flow_weight",
        "param_value": "0.15",
        "param_type": "float",
        "description": "资金流向权重（综合分计算）",
    },
    {
        "param_key": "technical_weight",
        "param_value": "0.15",
        "param_type": "float",
        "description": "技术面权重（综合分计算）",
    },
    {
        "param_key": "fundamental_weight",
        "param_value": "0.15",
        "param_type": "float",
        "description": "基本面权重（综合分计算）",
    },
    # Gate 惩罚
    {
        "param_key": "gate_penalty_cooldown",
        "param_value": "0.10",
        "param_type": "float",
        "description": "冷却期违反惩罚（综合分扣减）",
    },
    {
        "param_key": "gate_penalty_quota",
        "param_value": "0.10",
        "param_type": "float",
        "description": "配额紧张惩罚（综合分扣减）",
    },
    {
        "param_key": "gate_penalty_volatility",
        "param_value": "0.10",
        "param_type": "float",
        "description": "波动过高惩罚（综合分扣减）",
    },
    # 阈值
    {
        "param_key": "composite_score_threshold",
        "param_value": "0.60",
        "param_type": "float",
        "description": "综合分阈值（低于此值不生成推荐）",
    },
    {
        "param_key": "confidence_threshold",
        "param_value": "0.70",
        "param_type": "float",
        "description": "置信度阈值（低于此值需要人工审核）",
    },
    # 仓位控制
    {
        "param_key": "default_position_pct",
        "param_value": "5.0",
        "param_type": "float",
        "description": "默认仓位比例（%）",
    },
    {
        "param_key": "max_position_pct",
        "param_value": "10.0",
        "param_type": "float",
        "description": "最大仓位比例（%）",
    },
    {
        "param_key": "max_capital_per_trade",
        "param_value": "50000",
        "param_type": "float",
        "description": "单笔最大资金量（元）",
    },
]


class Command(BaseCommand):
    help = "初始化决策模型默认参数"

    def add_arguments(self, parser):
        parser.add_argument(
            "--env",
            type=str,
            default="dev",
            help="目标环境 (dev/test/prod)",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="强制覆盖已存在的参数",
        )

    def handle(self, *args, **options):
        env = options["env"]
        force = options["force"]

        if env not in ("dev", "test", "prod"):
            raise CommandError(f"无效的环境: {env}，必须是 dev/test/prod")

        self.stdout.write(f"开始初始化 {env} 环境的模型参数...")

        created_count = 0
        updated_count = 0
        skipped_count = 0

        with transaction.atomic():
            for param in DEFAULT_PARAMS:
                param_key = param["param_key"]
                param_value = param["param_value"]
                param_type = param["param_type"]
                description = param["description"]

                try:
                    existing = DecisionModelParamConfigModel.objects.get(
                        param_key=param_key,
                        env=env,
                    )

                    if force:
                        # 记录旧值用于审计
                        old_value = existing.param_value

                        # 更新参数
                        existing.param_value = param_value
                        existing.param_type = param_type
                        existing.description = description
                        existing.version += 1
                        existing.updated_by = "init_command"
                        existing.updated_reason = "初始化脚本强制更新"
                        existing.save()

                        # 创建审计日志
                        DecisionModelParamAuditLogModel.objects.create(
                            param_key=param_key,
                            old_value=old_value,
                            new_value=param_value,
                            env=env,
                            changed_by="init_command",
                            change_reason="初始化脚本强制更新",
                        )

                        updated_count += 1
                        self.stdout.write(
                            self.style.WARNING(f"  更新: {param_key} = {param_value}")
                        )
                    else:
                        skipped_count += 1
                        self.stdout.write(
                            self.style.HTTP_INFO(f"  跳过: {param_key}（已存在）")
                        )

                except DecisionModelParamConfigModel.DoesNotExist:
                    # 创建新参数
                    DecisionModelParamConfigModel.objects.create(
                        param_key=param_key,
                        param_value=param_value,
                        param_type=param_type,
                        env=env,
                        version=1,
                        is_active=True,
                        description=description,
                        updated_by="init_command",
                        updated_reason="初始化脚本创建",
                    )

                    # 创建审计日志
                    DecisionModelParamAuditLogModel.objects.create(
                        param_key=param_key,
                        old_value="",
                        new_value=param_value,
                        env=env,
                        changed_by="init_command",
                        change_reason="初始化脚本创建",
                    )

                    created_count += 1
                    self.stdout.write(
                        self.style.SUCCESS(f"  创建: {param_key} = {param_value}")
                    )

        # 输出汇总
        self.stdout.write("")
        self.stdout.write("=" * 50)
        self.stdout.write(f"环境: {env}")
        self.stdout.write(f"创建: {created_count} 个参数")
        self.stdout.write(f"更新: {updated_count} 个参数")
        self.stdout.write(f"跳过: {skipped_count} 个参数")
        self.stdout.write("=" * 50)

        if created_count + updated_count > 0:
            self.stdout.write(
                self.style.SUCCESS(f"成功初始化 {created_count + updated_count} 个参数")
            )
        else:
            self.stdout.write(
                self.style.WARNING("所有参数已存在，未做任何更改。使用 --force 强制更新。")
            )
