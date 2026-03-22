"""
Django Management Command: Initialize Rotation Assets and Configurations

Initializes asset classes and rotation configurations.

Usage:
    python manage.py init_rotation
    python manage.py init_rotation --reset
"""

from django.core.management.base import BaseCommand
from apps.rotation.infrastructure.models import AssetClassModel, RotationConfigModel, RotationTemplateModel
from apps.rotation.infrastructure.default_assets import DEFAULT_ROTATION_ASSETS


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
            AssetClassModel._default_manager.all().delete()
            RotationConfigModel._default_manager.all().delete()
            RotationTemplateModel._default_manager.all().delete()

        # Initialize asset classes
        self.init_asset_classes()

        # Initialize rotation configurations
        self.init_rotation_configs()

        # Initialize risk preset templates (from DB assets, no hardcoded weights)
        self.init_risk_templates()

        self.stdout.write(self.style.SUCCESS('Rotation initialization complete!'))

    def init_asset_classes(self):
        """Initialize asset classes (ETFs)"""
        assets = DEFAULT_ROTATION_ASSETS

        for asset_data in assets:
            asset, created = AssetClassModel._default_manager.get_or_create(
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
            config, created = RotationConfigModel._default_manager.get_or_create(
                name=config_data['name'],
                defaults=config_data
            )
            if created:
                self.stdout.write(f'[创建] {config.name}')
            else:
                self.stdout.write(f'[存在] {config.name}')

        self.stdout.write(f'已初始化 {len(configs)} 个轮动策略配置')

    def init_risk_templates(self):
        """
        初始化预设风险模板。

        权重从已存在的 AssetClassModel 动态查询，按资产类别分配比例。
        不在代码中硬编码任何具体资产代码或权重，避免硬编码违规。

        如果数据库中无对应资产，该类别跳过，权重按剩余类别归一化。
        """

        def get_codes(category: str, limit: int = None) -> list:
            qs = AssetClassModel._default_manager.filter(
                category=category, is_active=True
            ).order_by('code').values_list('code', flat=True)
            return list(qs[:limit] if limit else qs)

        def build_quadrant(weights_by_category: dict) -> dict:
            """
            按类别权重构建象限配置。

            weights_by_category: {category: total_weight}
            每个类别内部等权分配到该类别下所有资产。
            返回 {asset_code: weight} 并归一化确保总和为 1.0。
            """
            result = {}
            for category, total_weight in weights_by_category.items():
                codes = get_codes(category)
                if not codes:
                    continue
                per_asset = round(total_weight / len(codes), 4)
                for code in codes:
                    result[code] = per_asset

            # 归一化（消除浮点误差）
            total = sum(result.values())
            if total > 0 and abs(total - 1.0) > 0.001:
                factor = 1.0 / total
                result = {k: round(v * factor, 4) for k, v in result.items()}

            return result

        # 三种风险偏好的各象限目标类别权重
        # 权重比例代表该风险偏好下对各资产类别的倾向，不绑定具体资产代码
        templates_spec = [
            {
                'key': 'conservative',
                'name': '保守型',
                'description': '重点配置债券和货币类资产，低波动，适合风险厌恶型投资者',
                'display_order': 1,
                'quadrants': {
                    'Recovery':    {'equity': 0.15, 'bond': 0.45, 'currency': 0.30, 'commodity': 0.10},
                    'Overheat':    {'bond': 0.50, 'currency': 0.30, 'commodity': 0.15, 'equity': 0.05},
                    'Stagflation': {'bond': 0.55, 'currency': 0.30, 'commodity': 0.15},
                    'Deflation':   {'bond': 0.60, 'currency': 0.30, 'commodity': 0.10},
                },
            },
            {
                'key': 'moderate',
                'name': '稳健型',
                'description': '股债平衡配置，兼顾收益和风险，适合大多数投资者',
                'display_order': 2,
                'quadrants': {
                    'Recovery':    {'equity': 0.50, 'bond': 0.25, 'currency': 0.15, 'commodity': 0.10},
                    'Overheat':    {'equity': 0.30, 'commodity': 0.25, 'bond': 0.30, 'currency': 0.15},
                    'Stagflation': {'commodity': 0.25, 'bond': 0.45, 'currency': 0.30},
                    'Deflation':   {'bond': 0.50, 'currency': 0.20, 'equity': 0.20, 'commodity': 0.10},
                },
            },
            {
                'key': 'aggressive',
                'name': '激进型',
                'description': '以权益和商品为主，追求高收益，适合高风险承受能力投资者',
                'display_order': 3,
                'quadrants': {
                    'Recovery':    {'equity': 0.70, 'commodity': 0.15, 'bond': 0.10, 'currency': 0.05},
                    'Overheat':    {'equity': 0.45, 'commodity': 0.35, 'bond': 0.15, 'currency': 0.05},
                    'Stagflation': {'commodity': 0.40, 'bond': 0.35, 'equity': 0.15, 'currency': 0.10},
                    'Deflation':   {'equity': 0.35, 'bond': 0.35, 'commodity': 0.15, 'currency': 0.15},
                },
            },
        ]

        for spec in templates_spec:
            regime_allocations = {
                regime: build_quadrant(weights_by_cat)
                for regime, weights_by_cat in spec['quadrants'].items()
            }

            template, created = RotationTemplateModel._default_manager.update_or_create(
                key=spec['key'],
                defaults={
                    'name': spec['name'],
                    'description': spec['description'],
                    'display_order': spec['display_order'],
                    'regime_allocations': regime_allocations,
                    'is_active': True,
                },
            )
            action_label = '创建' if created else '更新'
            self.stdout.write(f'[{action_label}] 模板: {template.name}')

        self.stdout.write(f'已初始化 {len(templates_spec)} 个风险偏好模板')
