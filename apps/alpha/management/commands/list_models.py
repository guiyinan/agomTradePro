"""
List Qlib Models Management Command

列出所有 Qlib 模型的 Django 管理命令。
"""

import logging
from django.core.management.base import BaseCommand


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """
    列出 Qlib 模型命令

    用法:
        python manage.py list_models [options]

    选项:
        --model-name: 按模型名称过滤
        --universe: 按股票池过滤
        --active: 只显示激活的模型
    """

    help = 'List all Qlib models'

    def add_arguments(self, parser):
        parser.add_argument(
            '--model-name',
            type=str,
            dest='model_name',
            help='Filter by model name',
        )
        parser.add_argument(
            '--universe',
            type=str,
            dest='universe',
            help='Filter by universe',
        )
        parser.add_argument(
            '--active',
            action='store_true',
            dest='active_only',
            help='Show only active models',
        )

    def handle(self, *args, **options):
        """执行命令"""
        from apps.alpha.infrastructure.models import QlibModelRegistryModel

        model_name = options.get('model_name')
        universe = options.get('universe')
        active_only = options.get('active_only', False)

        # 构建查询
        queryset = QlibModelRegistryModel._default_manager.all()

        if model_name:
            queryset = queryset.filter(model_name__icontains=model_name)

        if universe:
            queryset = queryset.filter(universe=universe)

        if active_only:
            queryset = queryset.filter(is_active=True)

        # 按创建时间排序
        queryset = queryset.order_by('-created_at')

        # 显示结果
        models = list(queryset)

        if not models:
            self.stdout.write(self.style.WARNING('  没有找到模型'))
            return

        self.stdout.write(self.style.SUCCESS(f'  找到 {len(models)} 个模型'))
        self.stdout.write('')

        for model in models:
            active_flag = ' [ACTIVE]' if model.is_active else ''
            self.stdout.write(
                f'  {model.model_name}{active_flag}'
            )
            self.stdout.write(f'    Hash: {model.artifact_hash[:12]}...')
            self.stdout.write(f'    类型: {model.model_type}')
            self.stdout.write(f'    股票池: {model.universe}')
            self.stdout.write(f'    创建: {model.created_at.strftime("%Y-%m-%d %H:%M")}')
            if model.is_active:
                activated = model.activated_at.strftime("%Y-%m-%d %H:%M") if model.activated_at else "N/A"
                self.stdout.write(f'    激活: {activated} by {model.activated_by or "N/A"}')
            self.stdout.write(f'    IC: {model.ic if model.ic else "N/A"}')
            self.stdout.write(f'    ICIR: {model.icir if model.icir else "N/A"}')
            self.stdout.write(f'    路径: {model.model_path}')
            self.stdout.write('')

        # 按模型名称汇总
        self.stdout.write(self.style.SUCCESS('  按模型名称汇总:'))
        summary = {}
        for model in models:
            if model.model_name not in summary:
                summary[model.model_name] = {'total': 0, 'active': 0}
            summary[model.model_name]['total'] += 1
            if model.is_active:
                summary[model.model_name]['active'] += 1

        for name, stats in summary.items():
            self.stdout.write(
                f'    {name}: {stats["total"]} 个版本, '
                f'{stats["active"]} 个激活'
            )

