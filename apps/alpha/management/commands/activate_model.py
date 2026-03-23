"""
Activate Qlib Model Management Command

激活已训练的 Qlib 模型的 Django 管理命令。
"""

import logging

from django.core.management.base import BaseCommand, CommandError

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """
    激活 Qlib 模型命令

    用法:
        python manage.py activate_model <artifact_hash> [options]

    参数:
        artifact_hash: 模型 artifact hash（必需）

    选项:
        --force: 强制激活（即使当前有激活的模型）
    """

    help = 'Activate a trained Qlib model'

    def add_arguments(self, parser):
        parser.add_argument(
            'artifact_hash',
            type=str,
            help='Model artifact hash',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            dest='force',
            help='Force activation',
        )

    def handle(self, *args, **options):
        """执行命令"""
        artifact_hash = options.get('artifact_hash')
        force = options.get('force', False)

        self.stdout.write(f'激活模型: {artifact_hash[:8]}...')

        from apps.alpha.infrastructure.models import QlibModelRegistryModel

        # 查找模型
        try:
            model = QlibModelRegistryModel._default_manager.get(
                artifact_hash=artifact_hash
            )
        except QlibModelRegistryModel.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(f'  ✗ 模型不存在: {artifact_hash}')
            )
            return

        # 检查当前激活状态
        if model.is_active:
            self.stdout.write(
                self.style.WARNING('  ⚠ 模型已经是激活状态')
            )
            return

        # 检查是否有其他激活的模型
        current_active = QlibModelRegistryModel._default_manager.filter(
            model_name=model.model_name,
            is_active=True
        ).first()

        if current_active and not force:
            self.stdout.write(
                self.style.WARNING(
                    f'  ⚠ 当前有激活的模型: {current_active.artifact_hash[:8]}...'
                )
            )
            self.stdout.write('  使用 --force 强制激活')
            return

        # 激活模型
        try:
            model.activate(activated_by='command_line')

            self.stdout.write(
                self.style.SUCCESS('  ✓ 模型已激活')
            )
            self.stdout.write(f'    模型名称: {model.model_name}')
            self.stdout.write(f'    模型类型: {model.model_type}')
            self.stdout.write(f'    股票池: {model.universe}')
            self.stdout.write(f'    IC: {model.ic}')
            self.stdout.write(f'    ICIR: {model.icir}')

            if current_active:
                self.stdout.write(
                    self.style.WARNING(
                        f'  ⚠ 之前的模型已取消激活: {current_active.artifact_hash[:8]}...'
                    )
                )

        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'  ✗ 激活失败: {e}')
            )
            raise CommandError(f'激活失败: {e}')

