"""
Django Management Command: Initialize Hedge Pairs

Initializes hedge pair configurations.

Usage:
    python manage.py init_hedge
    python manage.py init_hedge --reset
"""

from django.core.management.base import BaseCommand
from apps.hedge.infrastructure.models import HedgePairModel


class Command(BaseCommand):
    help = 'Initialize hedge pair configurations'

    def add_arguments(self, parser):
        parser.add_argument(
            '--reset',
            action='store_true',
            dest='reset',
            help='Reset all hedge data (delete existing and recreate)',
        )

    def handle(self, *args, **options):
        reset = options.get('reset', False)

        if reset:
            self.stdout.write(self.style.WARNING('Resetting hedge data...'))
            HedgePairModel._default_manager.all().delete()

        # Initialize hedge pairs
        self.init_hedge_pairs()

        self.stdout.write(self.style.SUCCESS('Hedge initialization complete!'))

    def init_hedge_pairs(self):
        """Initialize hedge pair configurations"""
        hedge_pairs = [
            {
                'name': '股债对冲',
                'long_asset': '510300',      # 沪深300ETF
                'hedge_asset': '511260',     # 10年国债ETF
                'hedge_method': 'beta',
                'target_long_weight': 0.7,
                'target_hedge_weight': 0.3,
                'min_correlation': -0.8,
                'max_correlation': -0.2,
                'correlation_window': 60,
            },
            {
                'name': '成长价值对冲',
                'long_asset': '159915',      # 创业板ETF
                'hedge_asset': '512100',     # 红利ETF
                'hedge_method': 'equal_risk',
                'target_long_weight': 0.6,
                'target_hedge_weight': 0.4,
                'min_correlation': -0.7,
                'max_correlation': -0.2,
                'correlation_window': 60,
            },
            {
                'name': '大小盘对冲',
                'long_asset': '512100',      # 中证1000ETF (小盘)
                'hedge_asset': '510300',     # 沪深300ETF (大盘)
                'hedge_method': 'min_variance',
                'target_long_weight': 0.5,
                'target_hedge_weight': 0.5,
                'min_correlation': -0.9,
                'max_correlation': -0.3,
                'correlation_window': 60,
            },
            {
                'name': '股票黄金对冲',
                'long_asset': '510300',      # 沪深300ETF
                'hedge_asset': '159980',     # 黄金ETF
                'hedge_method': 'dollar_neutral',
                'target_long_weight': 0.8,
                'target_hedge_weight': 0.2,
                'min_correlation': -0.5,
                'max_correlation': 0.3,
                'correlation_window': 60,
            },
            {
                'name': '股票商品对冲',
                'long_asset': '510300',      # 沪深300ETF
                'hedge_asset': '159985',     # 豆粕ETF
                'hedge_method': 'fixed_ratio',
                'target_long_weight': 0.75,
                'target_hedge_weight': 0.25,
                'min_correlation': -0.6,
                'max_correlation': -0.1,
                'correlation_window': 60,
            },
            {
                'name': 'A股黄金对冲',
                'long_asset': '510500',      # 中证500ETF
                'hedge_asset': '159980',     # 黄金ETF
                'hedge_method': 'beta',
                'target_long_weight': 0.7,
                'target_hedge_weight': 0.3,
                'beta_target': 0.3,
                'min_correlation': -0.5,
                'max_correlation': 0.2,
                'correlation_window': 60,
            },
            {
                'name': '高波低波对冲',
                'long_asset': '159915',      # 创业板ETF (高波动)
                'hedge_asset': '511260',     # 10年国债ETF (低波动)
                'hedge_method': 'min_variance',
                'target_long_weight': 0.6,
                'target_hedge_weight': 0.4,
                'min_correlation': -0.7,
                'max_correlation': -0.2,
                'correlation_window': 60,
            },
            {
                'name': '中盘国债对冲',
                'long_asset': '510500',      # 中证500ETF
                'hedge_asset': '511260',     # 10年国债ETF
                'hedge_method': 'beta',
                'target_long_weight': 0.75,
                'target_hedge_weight': 0.25,
                'min_correlation': -0.8,
                'max_correlation': -0.2,
                'correlation_window': 60,
            },
            {
                'name': '核心卫星对冲',
                'long_asset': '512100',      # 中证1000ETF (卫星)
                'hedge_asset': '510300',     # 沪深300ETF (核心)
                'hedge_method': 'equal_risk',
                'target_long_weight': 0.4,
                'target_hedge_weight': 0.6,
                'min_correlation': -0.9,
                'max_correlation': -0.3,
                'correlation_window': 60,
            },
            {
                'name': '可转债对冲',
                'long_asset': '510300',      # 沪深300ETF
                'hedge_asset': '511280',     # 可转债ETF
                'hedge_method': 'beta',
                'target_long_weight': 0.7,
                'target_hedge_weight': 0.3,
                'min_correlation': -0.6,
                'max_correlation': -0.1,
                'correlation_window': 60,
            },
        ]

        for pair_data in hedge_pairs:
            pair, created = HedgePairModel._default_manager.get_or_create(
                name=pair_data['name'],
                defaults=pair_data
            )
            if created:
                self.stdout.write(f'[创建] {pair.name} - {pair.long_asset} / {pair.hedge_asset}')
            else:
                self.stdout.write(f'[存在] {pair.name} - {pair.long_asset} / {pair.hedge_asset}')

        self.stdout.write(f'已初始化 {len(hedge_pairs)} 个对冲对配置')

