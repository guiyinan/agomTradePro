"""
Django Management Command: Initialize Rotation Assets and Configurations

Initializes asset classes and rotation configurations.

Usage:
    python manage.py init_rotation
    python manage.py init_rotation --reset
"""

from django.core.management.base import BaseCommand
from apps.rotation.infrastructure.models import AssetClassModel, RotationConfigModel


class Command(BaseCommand):
    help = 'Initialize rotation assets and default configurations'

    def add_arguments(self, parser):
        parser.add_argument(
            '--reset',
            action='store_true',
            dest='reset',
            help='Reset all rotation data (delete existing and recreate)',
        )

    def handle(self, *args, **options):
        reset = options.get('reset', False)

        if reset:
            self.stdout.write(self.style.WARNING('Resetting rotation data...'))
            AssetClassModel.objects.all().delete()
            RotationConfigModel.objects.all().delete()

        # Initialize asset classes
        self.init_asset_classes()

        # Initialize rotation configurations
        self.init_rotation_configs()

        self.stdout.write(self.style.SUCCESS('Rotation initialization complete!'))

    def init_asset_classes(self):
        """Initialize asset classes (ETFs)"""
        assets = [
            # Equity ETFs
            {
                'code': '510300',
                'name': '沪深300ETF',
                'category': 'equity',
                'description': '跟踪沪深300指数，代表A股核心资产',
                'underlying_index': '000300.SH',
                'currency': 'CNY',
            },
            {
                'code': '510500',
                'name': '中证500ETF',
                'category': 'equity',
                'description': '跟踪中证500指数，代表中盘成长股',
                'underlying_index': '000905.SH',
                'currency': 'CNY',
            },
            {
                'code': '159915',
                'name': '创业板ETF',
                'category': 'equity',
                'description': '跟踪创业板指数，代表新兴成长股',
                'underlying_index': '399006.SZ',
                'currency': 'CNY',
            },
            {
                'code': '512100',
                'name': '中证1000ETF',
                'category': 'equity',
                'description': '跟踪中证1000指数，代表小盘股',
                'underlying_index': '000852.SH',
                'currency': 'CNY',
            },
            {
                'code': '588000',
                'name': '科创50ETF',
                'category': 'equity',
                'description': '跟踪科创50指数，代表科技创新企业',
                'underlying_index': '000688.SH',
                'currency': 'CNY',
            },
            {
                'code': '512690',
                'name': '白酒ETF',
                'category': 'equity',
                'description': '跟踪中证白酒指数',
                'underlying_index': '399997.SZ',
                'currency': 'CNY',
            },
            {
                'code': '515030',
                'name': '新能源ETF',
                'category': 'equity',
                'description': '跟踪中证新能源指数',
                'underlying_index': '931151.CSI',
                'currency': 'CNY',
            },
            {
                'code': '515180',
                'name': '红利ETF',
                'category': 'equity',
                'description': '跟踪上证红利指数',
                'underlying_index': '000022.SH',
                'currency': 'CNY',
            },

            # Bond ETFs
            {
                'code': '511260',
                'name': '十年国债ETF',
                'category': 'bond',
                'description': '跟踪10年期国债指数',
                'underlying_index': '净价10年国债',
                'currency': 'CNY',
            },
            {
                'code': '511010',
                'name': '国债ETF',
                'category': 'bond',
                'description': '跟踪国债指数',
                'underlying_index': '上证国债',
                'currency': 'CNY',
            },
            {
                'code': '511270',
                'name': '十年地方债ETF',
                'category': 'bond',
                'description': '跟踪10年期地方债指数',
                'currency': 'CNY',
            },
            {
                'code': '511280',
                'name': '可转债ETF',
                'category': 'bond',
                'description': '跟踪可转债指数',
                'underlying_index': '中信可转债',
                'currency': 'CNY',
            },

            # Commodity ETFs
            {
                'code': '159985',
                'name': '豆粕ETF',
                'category': 'commodity',
                'description': '跟踪大商所豆粕期货价格',
                'currency': 'CNY',
            },
            {
                'code': '159980',
                'name': '黄金ETF',
                'category': 'commodity',
                'description': '跟踪上海黄金现货价格',
                'underlying_index': 'Au99.99',
                'currency': 'CNY',
            },
            {
                'code': '159930',
                'name': '能源化工ETF',
                'category': 'commodity',
                'description': '跟踪能源化工期货指数',
                'currency': 'CNY',
            },

            # Currency/Money Market
            {
                'code': '511880',
                'name': '银华日利',
                'category': 'currency',
                'description': '货币市场基金，短期现金管理工具',
                'currency': 'CNY',
            },
            {
                'code': '511990',
                'name': '华宝添益',
                'category': 'currency',
                'description': '货币市场基金，短期现金管理工具',
                'currency': 'CNY',
            },
            {
                'code': '511660',
                'name': '建信添益',
                'category': 'currency',
                'description': '货币市场基金，短期现金管理工具',
                'currency': 'CNY',
            },
        ]

        for asset_data in assets:
            asset, created = AssetClassModel.objects.get_or_create(
                code=asset_data['code'],
                defaults=asset_data
            )
            if created:
                self.stdout.write(f'[创建] {asset.code} - {asset.name}')
            else:
                self.stdout.write(f'[存在] {asset.code} - {asset.name}')

        self.stdout.write(f'已初始化 {len(assets)} 个资产类别')

    def init_rotation_configs(self):
        """Initialize rotation configurations"""
        # Default asset universe (top 10 assets)
        default_universe = [
            '510300',  # 沪深300ETF
            '510500',  # 中证500ETF
            '159915',  # 创业板ETF
            '159985',  # 豆粕ETF
            '159980',  # 黄金ETF
            '511260',  # 十年国债ETF
            '511880',  # 银华日利
            '512100',  # 中证1000ETF
            '588000',  # 科创50ETF
            '515180',  # 红利ETF
        ]

        # Regime allocation matrix
        regime_allocations = {
            "Recovery": {
                "510300": 0.30,
                "510500": 0.20,
                "159985": 0.15,
                "511260": 0.20,
                "511880": 0.15,
            },
            "Overheat": {
                "510300": 0.20,
                "159985": 0.25,
                "159980": 0.15,
                "511260": 0.25,
                "511880": 0.15,
            },
            "Stagflation": {
                "159985": 0.20,
                "159980": 0.20,
                "511260": 0.35,
                "511880": 0.25,
            },
            "Deflation": {
                "511260": 0.50,
                "511880": 0.30,
                "159980": 0.10,
                "510300": 0.10,
            },
        }

        configs = [
            {
                'name': '动量轮动策略',
                'description': '基于价格动量的资产轮动策略，选择近期表现最好的3-5个资产等权配置',
                'strategy_type': 'momentum',
                'asset_universe': default_universe,
                'params': {
                    'momentum_periods': [20, 60, 120],
                    'weight_method': 'equal_weight',
                },
                'rebalance_frequency': 'monthly',
                'min_weight': 0.0,
                'max_weight': 1.0,
                'lookback_period': 120,
                'momentum_periods': [20, 60, 120],
                'top_n': 3,
            },
            {
                'name': '宏观象限轮动策略',
                'description': '根据宏观象限进行资产配置，复苏期配股票，滞胀期配债券和黄金',
                'strategy_type': 'regime_based',
                'asset_universe': default_universe,
                'params': {},
                'rebalance_frequency': 'monthly',
                'min_weight': 0.0,
                'max_weight': 0.5,
                'lookback_period': 60,
                'regime_allocations': regime_allocations,
                'top_n': 5,
            },
            {
                'name': '风险平价策略',
                'description': '基于风险平价的资产配置，按波动率倒数分配权重',
                'strategy_type': 'risk_parity',
                'asset_universe': [
                    '510300',  # 沪深300ETF
                    '510500',  # 中证500ETF
                    '511260',  # 十年国债ETF
                    '159980',  # 黄金ETF
                    '511880',  # 银华日利
                ],
                'params': {
                    'volatility_window': 60,
                },
                'rebalance_frequency': 'monthly',
                'min_weight': 0.1,
                'max_weight': 0.5,
                'lookback_period': 60,
                'top_n': 5,
            },
            {
                'name': '股债平衡轮动',
                'description': '股债动态平衡，根据股债相对强弱调整配置比例',
                'strategy_type': 'momentum',
                'asset_universe': [
                    '510300',  # 沪深300ETF
                    '511260',  # 十年国债ETF
                    '511880',  # 银华日利
                ],
                'params': {
                    'momentum_periods': [20, 60],
                    'min_stock_weight': 0.2,
                    'max_stock_weight': 0.8,
                },
                'rebalance_frequency': 'weekly',
                'min_weight': 0.0,
                'max_weight': 1.0,
                'lookback_period': 60,
                'momentum_periods': [20, 60],
                'top_n': 2,
            },
            {
                'name': '核心卫星策略',
                'description': '核心资产（沪深300）配置60%，卫星资产轮动配置40%',
                'strategy_type': 'custom',
                'asset_universe': [
                    '510300',  # 核心
                    '510500',  # 卫星
                    '159915',  # 卫星
                    '512100',  # 卫星
                ],
                'params': {
                    'core_asset': '510300',
                    'core_weight': 0.6,
                    'satellite_count': 2,
                },
                'rebalance_frequency': 'monthly',
                'min_weight': 0.1,
                'max_weight': 0.6,
                'lookback_period': 120,
                'momentum_periods': [60, 120],
                'top_n': 3,
            },
        ]

        for config_data in configs:
            config, created = RotationConfigModel.objects.get_or_create(
                name=config_data['name'],
                defaults=config_data
            )
            if created:
                self.stdout.write(f'[创建] {config.name}')
            else:
                self.stdout.write(f'[存在] {config.name}')

        self.stdout.write(f'已初始化 {len(configs)} 个轮动策略配置')
