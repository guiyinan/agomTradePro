"""
Management Command: Initialize Regime Threshold Configuration

初始化 Regime 判定阈值配置

用法:
    python manage.py init_regime_thresholds
    python manage.py init_regime_thresholds --reset
"""

from django.core.management.base import BaseCommand

from apps.regime.infrastructure.models import (
    RegimeIndicatorThreshold,
    RegimeThresholdConfig,
    RegimeTrendIndicator,
)


class Command(BaseCommand):
    help = '初始化 Regime 阈值配置'

    def add_arguments(self, parser):
        parser.add_argument(
            '--reset',
            action='store_true',
            dest='reset',
            help='重置为默认配置（先删除现有配置）',
        )

    def handle(self, *args, **options):
        reset = options.get('reset', False)

        if reset:
            self.stdout.write(self.style.WARNING('重置现有配置...'))
            RegimeThresholdConfig._default_manager.all().delete()

        # 检查是否已有配置
        if RegimeThresholdConfig._default_manager.filter(is_active=True).exists():
            self.stdout.write(self.style.WARNING('已存在激活配置，使用 --reset 重置'))
            return

        # 创建默认配置
        config = RegimeThresholdConfig._default_manager.create(
            name="默认配置 (2026-01)",
            is_active=True
        )

        # PMI 阈值
        RegimeIndicatorThreshold._default_manager.create(
            config=config,
            indicator_code="PMI",
            indicator_name="制造业PMI",
            level_low=50.0,
            level_high=50.0,
            description="PMI > 50 为扩张，< 50 为收缩"
        )

        # CPI 阈值
        RegimeIndicatorThreshold._default_manager.create(
            config=config,
            indicator_code="CPI",
            indicator_name="全国CPI同比",
            level_low=1.0,
            level_high=2.0,
            description="CPI > 2% 为高通胀，< 1% 为低通胀，< 0 为通缩"
        )

        # PPI 阈值
        RegimeIndicatorThreshold._default_manager.create(
            config=config,
            indicator_code="PPI",
            indicator_name="PPI同比",
            level_low=0.0,
            level_high=2.0,
            description="PPI > 2% 为高通胀，< 0 为通缩"
        )

        # PMI 趋动指标
        RegimeTrendIndicator._default_manager.create(
            config=config,
            indicator_code="PMI",
            momentum_period=3,
            trend_weight=0.3
        )

        # CPI 趋势指标
        RegimeTrendIndicator._default_manager.create(
            config=config,
            indicator_code="CPI",
            momentum_period=3,
            trend_weight=0.3
        )

        self.stdout.write(self.style.SUCCESS(f'\n成功创建配置: {config.name}'))
        self.stdout.write(self.style.SUCCESS('阈值配置:'))
        self.stdout.write('  PMI: 扩张阈值 50.0')
        self.stdout.write('  CPI: 高通胀 > 2.0%, 低通胀 < 1.0%, 通缩 < 0%')
        self.stdout.write(self.style.SUCCESS('趋势指标:'))
        self.stdout.write('  PMI: 周期 3 个月, 权重 0.3')
        self.stdout.write('  CPI: 周期 3 个月, 权重 0.3')

