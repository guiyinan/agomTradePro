"""
Rollback Qlib Model Management Command

回滚 Qlib 模型的 Django 管理命令。
"""

import logging
from django.core.management.base import BaseCommand, CommandError


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """
    回滚 Qlib 模型命令

    用法:
        python manage.py rollback_model [options]

    选项:
        --to: 回滚到指定的 artifact hash
        --prev: 回滚到上一个版本
        --model-name: 模型名称（必需）
    """

    help = 'Rollback to a previous Qlib model version'

    def add_arguments(self, parser):
        parser.add_argument(
            '--to',
            type=str,
            dest='to_hash',
            help='Rollback to specific artifact hash',
        )
        parser.add_argument(
            '--prev',
            action='store_true',
            dest='prev',
            help='Rollback to previous version',
        )
        parser.add_argument(
            '--model-name',
            type=str,
            required=True,
            dest='model_name',
            help='Model name (required)',
        )

    def handle(self, *args, **options):
        """执行命令"""
        to_hash = options.get('to_hash')
        prev = options.get('prev', False)
        model_name = options.get('model_name')

        self.stdout.write(f'回滚模型: {model_name}')

        if to_hash:
            self._rollback_to_hash(model_name, to_hash)
        elif prev:
            self._rollback_to_prev(model_name)
        else:
            self.stdout.write(
                self.style.ERROR('  ✗ 请指定 --to 或 --prev')
            )

    def _rollback_to_hash(self, model_name: str, artifact_hash: str):
        """回滚到指定版本"""
        from apps.alpha.infrastructure.models import QlibModelRegistryModel

        self.stdout.write(f'  回滚到: {artifact_hash[:8]}...')

        try:
            # 查找目标模型
            target_model = QlibModelRegistryModel._default_manager.get(
                model_name=model_name,
                artifact_hash=artifact_hash
            )

            # 取消当前激活的模型
            current_active = QlibModelRegistryModel._default_manager.filter(
                model_name=model_name,
                is_active=True
            ).first()

            if current_active:
                current_active.deactivate()
                self.stdout.write(
                    self.style.WARNING(
                        f'  ⚠ 已取消激活: {current_active.artifact_hash[:8]}...'
                    )
                )

            # 激活目标模型
            target_model.activate(activated_by='rollback_command')

            self.stdout.write(
                self.style.SUCCESS(f'  ✓ 已回滚到: {artifact_hash[:8]}...')
            )

        except QlibModelRegistryModel.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(f'  ✗ 模型不存在: {artifact_hash}')
            )
            raise CommandError(f'模型不存在: {artifact_hash}')

    def _rollback_to_prev(self, model_name: str):
        """回滚到上一个版本"""
        from apps.alpha.infrastructure.models import QlibModelRegistryModel

        # 获取当前激活的模型
        current_active = QlibModelRegistryModel._default_manager.filter(
            model_name=model_name,
            is_active=True
        ).first()

        if not current_active:
            self.stdout.write(
                self.style.ERROR(f'  ✗ 没有激活的模型')
            )
            return

        # 查找上一个版本
        prev_model = QlibModelRegistryModel._default_manager.filter(
            model_name=model_name,
            created_at__lt=current_active.created_at
        ).order_by('-created_at').first()

        if not prev_model:
            self.stdout.write(
                self.style.ERROR(f'  ✗ 没有找到上一个版本')
            )
            return

        self.stdout.write(
            self.style.SUCCESS(f'  上一个版本: {prev_model.artifact_hash[:8]}...')
        )
        self.stdout.write(f'    创建时间: {prev_model.created_at}')

        # 执行回滚
        self._rollback_to_hash(model_name, prev_model.artifact_hash)

    def _list_versions(self, model_name: str):
        """列出所有版本"""
        from apps.alpha.infrastructure.models import QlibModelRegistryModel

        models = QlibModelRegistryModel._default_manager.filter(
            model_name=model_name
        ).order_by('-created_at')

        self.stdout.write(f'  版本列表:')
        for model in models:
            active_flag = ' [ACTIVE]' if model.is_active else ''
            self.stdout.write(
                f'    {model.artifact_hash[:8]}... - {model.created_at}{active_flag}'
            )

