"""
Django Management Command: Initialize Factor Definitions

Initializes factor definitions for the factor stock selection module.

Usage:
    python manage.py init_factors
    python manage.py init_factors --reset
"""

from django.core.management.base import BaseCommand

from apps.factor.infrastructure.models import FactorDefinitionModel, FactorPortfolioConfigModel


class Command(BaseCommand):
    help = 'Initialize factor definitions and default portfolio configurations'

    def add_arguments(self, parser):
        parser.add_argument(
            '--reset',
            action='store_true',
            dest='reset',
            help='Reset all factor data (delete existing and recreate)',
        )

    def handle(self, *args, **options):
        reset = options.get('reset', False)

        if reset:
            self.stdout.write(self.style.WARNING('Resetting factor data...'))
            FactorDefinitionModel._default_manager.all().delete()
            FactorPortfolioConfigModel._default_manager.all().delete()

        # Initialize factor definitions
        self.init_factor_definitions()

        # Initialize default portfolio configurations
        self.init_portfolio_configs()

        self.stdout.write(self.style.SUCCESS('Factor initialization complete!'))

    def init_factor_definitions(self):
        """Initialize factor definitions"""
        initial_factors = [
            # Value factors
            {
                'code': 'pe_ttm',
                'name': 'PE(TTM)',
                'category': 'value',
                'description': '滚动市盈率，越低越便宜',
                'data_source': 'tushare',
                'data_field': 'pe_ttm',
                'direction': 'negative',
                'update_frequency': 'daily',
                'min_data_points': 5,
            },
            {
                'code': 'pb',
                'name': '市净率',
                'category': 'value',
                'description': '市净率，越低越便宜',
                'data_source': 'tushare',
                'data_field': 'pb',
                'direction': 'negative',
                'update_frequency': 'daily',
                'min_data_points': 5,
            },
            {
                'code': 'ps',
                'name': '市销率',
                'category': 'value',
                'description': '市销率，越低越便宜',
                'data_source': 'tushare',
                'data_field': 'ps',
                'direction': 'negative',
                'update_frequency': 'daily',
                'min_data_points': 5,
            },
            {
                'code': 'dividend_yield',
                'name': '股息率',
                'category': 'value',
                'description': '股息率，越高越好',
                'data_source': 'tushare',
                'data_field': 'dv_ratio',
                'direction': 'positive',
                'update_frequency': 'daily',
                'min_data_points': 5,
            },

            # Quality factors
            {
                'code': 'roe',
                'name': '净资产收益率',
                'category': 'quality',
                'description': '净资产收益率(ROE)，越高代表盈利能力越强',
                'data_source': 'tushare',
                'data_field': 'roe',
                'direction': 'positive',
                'update_frequency': 'quarterly',
                'min_data_points': 4,
            },
            {
                'code': 'roa',
                'name': '总资产收益率',
                'category': 'quality',
                'description': '总资产收益率(ROA)，越高代表资产使用效率越高',
                'data_source': 'tushare',
                'data_field': 'roa',
                'direction': 'positive',
                'update_frequency': 'quarterly',
                'min_data_points': 4,
            },
            {
                'code': 'debt_ratio',
                'name': '资产负债率',
                'category': 'quality',
                'description': '资产负债率，越低代表财务越稳健',
                'data_source': 'tushare',
                'data_field': 'debt_to_assets',
                'direction': 'negative',
                'update_frequency': 'quarterly',
                'min_data_points': 4,
            },
            {
                'code': 'current_ratio',
                'name': '流动比率',
                'category': 'quality',
                'description': '流动比率，越高代表短期偿债能力越强',
                'data_source': 'tushare',
                'data_field': 'current_ratio',
                'direction': 'positive',
                'update_frequency': 'quarterly',
                'min_data_points': 4,
            },
            {
                'code': 'gross_margin',
                'name': '毛利率',
                'category': 'quality',
                'description': '销售毛利率，越高代表盈利质量越好',
                'data_source': 'tushare',
                'data_field': 'gross_profit_margin',
                'direction': 'positive',
                'update_frequency': 'quarterly',
                'min_data_points': 4,
            },

            # Growth factors
            {
                'code': 'revenue_growth',
                'name': '营收增长率',
                'category': 'growth',
                'description': '营业收入同比增长率',
                'data_source': 'tushare',
                'data_field': 'or_yoy',
                'direction': 'positive',
                'update_frequency': 'quarterly',
                'min_data_points': 4,
            },
            {
                'code': 'profit_growth',
                'name': '利润增长率',
                'category': 'growth',
                'description': '净利润同比增长率',
                'data_source': 'tushare',
                'data_field': 'netprofit_yoy',
                'direction': 'positive',
                'update_frequency': 'quarterly',
                'min_data_points': 4,
            },
            {
                'code': 'revenue_growth_3y',
                'name': '营收3年复合增长率',
                'category': 'growth',
                'description': '营业收入3年复合增长率(CAGR)',
                'data_source': 'calculated',
                'data_field': 'revenue_cagr_3y',
                'direction': 'positive',
                'update_frequency': 'quarterly',
                'min_data_points': 12,
            },

            # Momentum factors
            {
                'code': 'momentum_1m',
                'name': '1月动量',
                'category': 'momentum',
                'description': '过去1个月价格动量（收益率）',
                'data_source': 'calculated',
                'data_field': 'momentum_20d',
                'direction': 'positive',
                'update_frequency': 'daily',
                'min_data_points': 20,
            },
            {
                'code': 'momentum_3m',
                'name': '3月动量',
                'category': 'momentum',
                'description': '过去3个月价格动量（收益率）',
                'data_source': 'calculated',
                'data_field': 'momentum_60d',
                'direction': 'positive',
                'update_frequency': 'daily',
                'min_data_points': 60,
            },
            {
                'code': 'momentum_6m',
                'name': '6月动量',
                'category': 'momentum',
                'description': '过去6个月价格动量（收益率）',
                'data_source': 'calculated',
                'data_field': 'momentum_120d',
                'direction': 'positive',
                'update_frequency': 'daily',
                'min_data_points': 120,
            },
            {
                'code': 'price_52w_high',
                'name': '52周新高距离',
                'category': 'momentum',
                'description': '当前价格距离52周高点的百分比',
                'data_source': 'calculated',
                'data_field': 'pct_52w_high',
                'direction': 'negative',
                'update_frequency': 'daily',
                'min_data_points': 252,
            },

            # Volatility factors
            {
                'code': 'volatility_20d',
                'name': '20日波动率',
                'category': 'volatility',
                'description': '过去20日收益率标准差',
                'data_source': 'calculated',
                'data_field': 'volatility_20d',
                'direction': 'negative',
                'update_frequency': 'daily',
                'min_data_points': 20,
            },
            {
                'code': 'volatility_60d',
                'name': '60日波动率',
                'category': 'volatility',
                'description': '过去60日收益率标准差',
                'data_source': 'calculated',
                'data_field': 'volatility_60d',
                'direction': 'negative',
                'update_frequency': 'daily',
                'min_data_points': 60,
            },
            {
                'code': 'beta',
                'name': 'Beta',
                'category': 'volatility',
                'description': '相对于沪深300的Beta系数',
                'data_source': 'calculated',
                'data_field': 'beta',
                'direction': 'negative',
                'update_frequency': 'daily',
                'min_data_points': 60,
            },
            {
                'code': 'downside_capture',
                'name': '下行捕获率',
                'category': 'volatility',
                'description': '市场下跌时的平均跌幅相对市场的比例',
                'data_source': 'calculated',
                'data_field': 'downside_capture',
                'direction': 'negative',
                'update_frequency': 'daily',
                'min_data_points': 252,
            },

            # Liquidity factors
            {
                'code': 'turnover_20d',
                'name': '20日换手率',
                'category': 'liquidity',
                'description': '过去20日平均日换手率',
                'data_source': 'calculated',
                'data_field': 'avg_turnover_20d',
                'direction': 'positive',
                'update_frequency': 'daily',
                'min_data_points': 20,
            },
            {
                'code': 'turnover_60d',
                'name': '60日换手率',
                'category': 'liquidity',
                'description': '过去60日平均日换手率',
                'data_source': 'calculated',
                'data_field': 'avg_turnover_60d',
                'direction': 'positive',
                'update_frequency': 'daily',
                'min_data_points': 60,
            },
            {
                'code': 'amplitude_20d',
                'name': '20日振幅',
                'category': 'liquidity',
                'description': '过去20日平均日振幅（(最高-最低)/昨收）',
                'data_source': 'calculated',
                'data_field': 'avg_amplitude_20d',
                'direction': 'negative',
                'update_frequency': 'daily',
                'min_data_points': 20,
            },
            {
                'code': 'volume_ratio',
                'name': '量比',
                'category': 'liquidity',
                'description': '当日成交量/过去N日平均成交量',
                'data_source': 'calculated',
                'data_field': 'volume_ratio',
                'direction': 'positive',
                'update_frequency': 'daily',
                'min_data_points': 20,
            },

            # Technical factors
            {
                'code': 'rsi',
                'name': 'RSI',
                'category': 'technical',
                'description': '相对强弱指数(RSI)，14日',
                'data_source': 'calculated',
                'data_field': 'rsi_14',
                'direction': 'neutral',
                'update_frequency': 'daily',
                'min_data_points': 14,
            },
            {
                'code': 'macd',
                'name': 'MACD',
                'category': 'technical',
                'description': 'MACD指标',
                'data_source': 'calculated',
                'data_field': 'macd',
                'direction': 'positive',
                'update_frequency': 'daily',
                'min_data_points': 26,
            },
            {
                'code': 'ma_cross',
                'name': '均线交叉',
                'category': 'technical',
                'description': '短期均线相对长期均线的位置',
                'data_source': 'calculated',
                'data_field': 'ma_cross_signal',
                'direction': 'positive',
                'update_frequency': 'daily',
                'min_data_points': 60,
            },
        ]

        for factor_data in initial_factors:
            factor, created = FactorDefinitionModel._default_manager.get_or_create(
                code=factor_data['code'],
                defaults=factor_data
            )
            if created:
                self.stdout.write(f'[创建] {factor.code} - {factor.name}')
            else:
                self.stdout.write(f'[存在] {factor.code} - {factor.name}')

        self.stdout.write(f'已初始化 {len(initial_factors)} 个因子定义')

    def init_portfolio_configs(self):
        """Initialize default portfolio configurations"""
        configs = [
            {
                'name': '价值成长平衡组合',
                'description': '平衡价值和成长因子的配置，适合稳健投资者',
                'factor_weights': {
                    'pe_ttm': 0.15,
                    'pb': 0.10,
                    'roe': 0.20,
                    'revenue_growth': 0.20,
                    'profit_growth': 0.15,
                    'momentum_3m': 0.10,
                    'volatility_20d': 0.10,
                },
                'universe': 'zz500',
                'top_n': 30,
                'rebalance_frequency': 'monthly',
                'weight_method': 'equal_weight',
            },
            {
                'name': '深度价值组合',
                'description': '专注于低估值股票，适合价值投资',
                'factor_weights': {
                    'pe_ttm': 0.30,
                    'pb': 0.25,
                    'dividend_yield': 0.20,
                    'debt_ratio': 0.10,
                    'roe': 0.15,
                },
                'universe': 'all_a',
                'min_market_cap': 50,
                'max_pe': 15,
                'top_n': 30,
                'rebalance_frequency': 'monthly',
                'weight_method': 'equal_weight',
            },
            {
                'name': '高成长组合',
                'description': '专注于高成长股票，适合成长投资',
                'factor_weights': {
                    'revenue_growth': 0.30,
                    'profit_growth': 0.30,
                    'roe': 0.15,
                    'momentum_3m': 0.15,
                    'momentum_6m': 0.10,
                },
                'universe': 'zz500',
                'min_market_cap': 20,
                'top_n': 30,
                'rebalance_frequency': 'monthly',
                'weight_method': 'equal_weight',
            },
            {
                'name': '质量优选组合',
                'description': '专注于高质量公司，稳健盈利',
                'factor_weights': {
                    'roe': 0.25,
                    'roa': 0.15,
                    'gross_margin': 0.15,
                    'debt_ratio': 0.15,
                    'current_ratio': 0.10,
                    'profit_growth': 0.10,
                    'volatility_20d': 0.10,
                },
                'universe': 'hs300',
                'top_n': 30,
                'rebalance_frequency': 'monthly',
                'weight_method': 'equal_weight',
            },
            {
                'name': '动量精选组合',
                'description': '基于价格动量的选股策略',
                'factor_weights': {
                    'momentum_1m': 0.15,
                    'momentum_3m': 0.30,
                    'momentum_6m': 0.25,
                    'volatility_20d': 0.15,
                    'volume_ratio': 0.15,
                },
                'universe': 'zz500',
                'top_n': 30,
                'rebalance_frequency': 'monthly',
                'weight_method': 'equal_weight',
            },
            {
                'name': '小盘价值组合',
                'description': '专注小盘价值股',
                'factor_weights': {
                    'pe_ttm': 0.25,
                    'pb': 0.25,
                    'roe': 0.15,
                    'revenue_growth': 0.15,
                    'turnover_20d': 0.10,
                    'momentum_3m': 0.10,
                },
                'universe': 'all_a',
                'max_market_cap': 200,
                'min_market_cap': 20,
                'top_n': 50,
                'rebalance_frequency': 'monthly',
                'weight_method': 'equal_weight',
            },
        ]

        for config_data in configs:
            config, created = FactorPortfolioConfigModel._default_manager.get_or_create(
                name=config_data['name'],
                defaults=config_data
            )
            if created:
                self.stdout.write(f'[创建] {config.name}')
            else:
                self.stdout.write(f'[存在] {config.name}')

        self.stdout.write(f'已初始化 {len(configs)} 个因子组合配置')

