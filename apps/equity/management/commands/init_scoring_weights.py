"""
Django management command to initialize default scoring weight configuration.

Usage:
    python manage.py init_scoring_weights
"""

from django.core.management.base import BaseCommand

from apps.equity.infrastructure.models import ScoringWeightConfigModel


class Command(BaseCommand):
    help = '初始化默认股票评分权重配置'

    def handle(self, *args, **options):
        """Execute the command"""
        # 检查是否已存在配置
        existing_count = ScoringWeightConfigModel._default_manager.count()
        if existing_count > 0:
            self.stdout.write(
                self.style.WARNING(f'数据库中已存在 {existing_count} 个评分权重配置')
            )
            if not self.confirm('是否仍要创建默认配置？'):
                self.stdout.write(self.style.ERROR('操作已取消'))
                return

        # 创建默认配置
        default_configs = [
            {
                'name': '默认配置',
                'description': '系统默认评分权重配置：成长性40%、盈利能力40%、估值20%',
                'is_active': True,
                'growth_weight': 0.4,
                'profitability_weight': 0.4,
                'valuation_weight': 0.2,
                'revenue_growth_weight': 0.5,
                'profit_growth_weight': 0.5,
            },
            {
                'name': '成长型配置',
                'description': '偏向成长性的配置：成长性50%、盈利能力35%、估值15%',
                'is_active': False,
                'growth_weight': 0.5,
                'profitability_weight': 0.35,
                'valuation_weight': 0.15,
                'revenue_growth_weight': 0.6,
                'profit_growth_weight': 0.4,
            },
            {
                'name': '价值型配置',
                'description': '偏向价值的配置：成长性30%、盈利能力35%、估值35%',
                'is_active': False,
                'growth_weight': 0.3,
                'profitability_weight': 0.35,
                'valuation_weight': 0.35,
                'revenue_growth_weight': 0.4,
                'profit_growth_weight': 0.6,
            },
        ]

        created_count = 0
        for config_data in default_configs:
            name = config_data['name']
            # 检查是否已存在同名配置
            if ScoringWeightConfigModel._default_manager.filter(name=name).exists():
                self.stdout.write(
                    self.style.WARNING(f'配置 "{name}" 已存在，跳过创建')
                )
                continue

            try:
                ScoringWeightConfigModel._default_manager.create(**config_data)
                created_count += 1
                self.stdout.write(
                    self.style.SUCCESS(f'成功创建配置: {name}')
                )
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f'创建配置 "{name}" 失败: {e}')
                )

        if created_count > 0:
            self.stdout.write(
                self.style.SUCCESS(f'\n成功创建 {created_count} 个评分权重配置')
            )
            self.stdout.write('您现在可以通过 Django Admin 管理这些配置：')
            self.stdout.write('  路径: /admin/equity/scoringweightconfigmodel/')
        else:
            self.stdout.write(
                self.style.WARNING('没有创建新配置')
            )

    def confirm(self, message):
        """Ask for user confirmation"""
        try:
            return input(f'{message} (y/N): ').lower() == 'y'
        except (EOFError, KeyboardInterrupt):
            # Non-interactive mode, return False
            return False
