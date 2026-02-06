"""
Initialize Confidence Configuration.

This command initializes the default confidence configuration for Regime calculation.

Usage:
    python manage.py init_confidence_config
    python manage.py init_confidence_config --refresh
"""

from django.core.management.base import BaseCommand
from apps.audit.infrastructure.models import ConfidenceConfigModel


class Command(BaseCommand):
    help = 'Initialize default confidence configuration'

    def add_arguments(self, parser):
        parser.add_argument(
            '--refresh',
            action='store_true',
            dest='refresh',
            help='Refresh existing configuration (update instead of skip)',
        )

    def handle(self, *args, **options):
        refresh = options.get('refresh', False)

        # 默认置信度配置
        default_config = {
            # 新鲜度系数
            'day_0_coefficient': 0.6,      # 发布当天
            'day_7_coefficient': 0.5,      # 发布1周后
            'day_14_coefficient': 0.4,     # 发布2周后
            'day_30_coefficient': 0.3,     # 发布1月后

            # 数据类型加成
            'daily_data_bonus': 0.2,       # 日度数据加成
            'weekly_data_bonus': 0.1,      # 周度数据加成
            'daily_consistency_bonus': 0.1,  # 日度一致性加成

            # 基础置信度
            'base_confidence': 0.5,

            # 信号冲突解决阈值
            'daily_persist_threshold': 10,  # 日度持续阈值
            'hybrid_weight_daily': 0.3,     # 混合日度权重
            'hybrid_weight_monthly': 0.7,   # 混合月度权重

            # 权重动态调整参数
            'decay_threshold': 0.2,         # F1 < 0.2 视为衰减
            'decay_penalty': 0.5,           # 衰减后权重减半
            'improvement_threshold': 0.1,   # F1 提升 0.1 给予奖励
            'improvement_bonus': 1.2,       # 提升权重 20%

            'description': '默认置信度配置，用于 Regime 概率计算',
        }

        try:
            existing = ConfidenceConfigModel._default_manager.get(is_active=True)

            if refresh:
                # 更新现有配置
                for key, value in default_config.items():
                    if key != 'description':
                        setattr(existing, key, value)
                existing.description = default_config['description']
                existing.save()

                self.stdout.write('\n' + '=' * 50)
                self.stdout.write(self.style.WARNING('Updated existing confidence configuration'))
                self._display_config(existing)
            else:
                self.stdout.write('\n' + '=' * 50)
                self.stdout.write(self.style.WARNING('Confidence configuration already exists (use --refresh to update)'))
                self._display_config(existing)

        except ConfidenceConfigModel.DoesNotExist:
            # 创建新配置
            ConfidenceConfigModel._default_manager.create(**default_config)

            self.stdout.write('\n' + '=' * 50)
            self.stdout.write(self.style.SUCCESS('Created confidence configuration'))
            self.stdout.write('=' * 50)
            self._display_config_dict(default_config)

        self.stdout.write('\n' + '=' * 50)
        self.stdout.write(self.style.SUCCESS('Confidence configuration initialized successfully.'))
        self.stdout.write('Run "python manage.py init_confidence_config --refresh" to update existing config.')
        self.stdout.write('=' * 50)

    def _display_config(self, config: ConfidenceConfigModel):
        """显示配置详情"""
        self.stdout.write('\n配置详情:')
        self.stdout.write(f'  新鲜度系数:')
        self.stdout.write(f'    发布当天: {config.day_0_coefficient}')
        self.stdout.write(f'    发布1周: {config.day_7_coefficient}')
        self.stdout.write(f'    发布2周: {config.day_14_coefficient}')
        self.stdout.write(f'    发布1月: {config.day_30_coefficient}')
        self.stdout.write(f'  数据加成:')
        self.stdout.write(f'    日度加成: {config.daily_data_bonus}')
        self.stdout.write(f'    周度加成: {config.weekly_data_bonus}')
        self.stdout.write(f'    一致性加成: {config.daily_consistency_bonus}')
        self.stdout.write(f'  基础置信度: {config.base_confidence}')
        self.stdout.write(f'  冲突解决:')
        self.stdout.write(f'    日度持续阈值: {config.daily_persist_threshold}天')
        self.stdout.write(f'    混合权重(日度/月度): {config.hybrid_weight_daily}/{config.hybrid_weight_monthly}')

    def _display_config_dict(self, config: dict):
        """显示配置字典"""
        self.stdout.write('\n配置详情:')
        self.stdout.write(f'  新鲜度系数:')
        self.stdout.write(f'    发布当天: {config["day_0_coefficient"]}')
        self.stdout.write(f'    发布1周: {config["day_7_coefficient"]}')
        self.stdout.write(f'    发布2周: {config["day_14_coefficient"]}')
        self.stdout.write(f'    发布1月: {config["day_30_coefficient"]}')
        self.stdout.write(f'  数据加成:')
        self.stdout.write(f'    日度加成: {config["daily_data_bonus"]}')
        self.stdout.write(f'    周度加成: {config["weekly_data_bonus"]}')
        self.stdout.write(f'    一致性加成: {config["daily_consistency_bonus"]}')
        self.stdout.write(f'  基础置信度: {config["base_confidence"]}')
        self.stdout.write(f'  冲突解决:')
        self.stdout.write(f'    日度持续阈值: {config["daily_persist_threshold"]}天')
        self.stdout.write(f'    混合权重(日度/月度): {config["hybrid_weight_daily"]}/{config["hybrid_weight_monthly"]}')

