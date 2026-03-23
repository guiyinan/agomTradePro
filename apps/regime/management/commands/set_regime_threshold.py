"""
Django Management Command: 快速设置 Regime 阈值

用法:
    python manage.py set_regime_threshold --pmi 50 --cpi-high 2 --cpi-low 1
    python manage.py set_regime_threshold --activate
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.regime.infrastructure.models import RegimeIndicatorThreshold, RegimeThresholdConfig


class Command(BaseCommand):
    help = '快速设置 Regime 阈值配置'

    def add_arguments(self, parser):
        parser.add_argument(
            '--pmi',
            type=float,
            default=None,
            help='PMI 阈值（扩张/收缩分界线）'
        )
        parser.add_argument(
            '--cpi-high',
            type=float,
            default=None,
            help='CPI 高通胀阈值'
        )
        parser.add_argument(
            '--cpi-low',
            type=float,
            default=None,
            help='CPI 低通胀阈值'
        )
        parser.add_argument(
            '--ppi-high',
            type=float,
            default=None,
            help='PPI 高通胀阈值'
        )
        parser.add_argument(
            '--activate',
            action='store_true',
            help='激活当前或最新配置'
        )

    def handle(self, *args, **options):
        pmi = options.get('pmi')
        cpi_high = options.get('cpi_high')
        cpi_low = options.get('cpi_low')
        ppi_high = options.get('ppi_high')
        activate = options.get('activate')

        # 获取或创建默认配置
        config = RegimeThresholdConfig._default_manager.filter(is_active=True).first()
        if not config:
            config = RegimeThresholdConfig._default_manager.create(
                name='默认配置',
                is_active=True
            )
            self.stdout.write(self.style.SUCCESS(f'✓ 创建默认配置: {config.name}'))

        # 更新阈值
        updates = []
        with transaction.atomic():
            if pmi is not None:
                threshold, _ = RegimeIndicatorThreshold._default_manager.get_or_create(
                    config=config,
                    indicator_code='PMI',
                    defaults={
                        'indicator_name': '采购经理人指数',
                        'description': 'PMI ≥ 50 为扩张'
                    }
                )
                threshold.level_low = pmi
                threshold.level_high = pmi
                threshold.save()
                updates.append(f'PMI 阈值: {pmi}')

            if cpi_high is not None or cpi_low is not None:
                threshold, _ = RegimeIndicatorThreshold._default_manager.get_or_create(
                    config=config,
                    indicator_code='CPI',
                    defaults={
                        'indicator_name': '消费者物价指数',
                        'description': 'CPI > 2% 为高通胀'
                    }
                )
                if cpi_high is not None:
                    threshold.level_high = cpi_high
                if cpi_low is not None:
                    threshold.level_low = cpi_low
                threshold.save()
                updates.append(f'CPI 阈值: {cpi_low} ~ {cpi_high}%')

            if ppi_high is not None:
                threshold, _ = RegimeIndicatorThreshold._default_manager.get_or_create(
                    config=config,
                    indicator_code='PPI',
                    defaults={
                        'indicator_name': '生产者物价指数',
                        'description': 'PPI > 2% 为高通胀'
                    }
                )
                threshold.level_high = ppi_high
                threshold.save()
                updates.append(f'PPI 阈值: {ppi_high}%')

        # 显示更新结果
        if updates:
            self.stdout.write(self.style.SUCCESS('✓ 阈值已更新:'))
            for update in updates:
                self.stdout.write(f'  - {update}')

        # 激活配置
        if activate:
            RegimeThresholdConfig._default_manager.exclude(pk=config.pk).update(is_active=False)
            config.is_active = True
            config.save()

            # 清除缓存
            try:
                from shared.infrastructure.cache_service import CacheService
                CacheService.invalidate_regime()
            except ImportError:
                pass

            self.stdout.write(self.style.SUCCESS(f'\n✓ 已激活配置: {config.name}'))

            # 显示当前所有阈值
            self.stdout.write('\n当前阈值配置:')
            for t in config.thresholds.all().order_by('indicator_code'):
                range_str = f'{t.level_low} ~ {t.level_high}'
                if t.level_low == t.level_high:
                    range_str = f'≥ {t.level_high}'
                self.stdout.write(f'  {t.indicator_code:10s} ({t.indicator_name}): {range_str}')
        else:
            self.stdout.write('\n提示: 使用 --activate 参数激活此配置')

