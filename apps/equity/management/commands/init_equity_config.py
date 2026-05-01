"""
Django Management Command: 初始化个股/板块/基金配置

运行方式：
    python manage.py init_equity_config
"""

from decimal import Decimal

from django.core.management.base import BaseCommand

from apps.equity.infrastructure.repositories import EquityBootstrapConfigRepository


class Command(BaseCommand):
    help = '初始化个股/板块/基金配置'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.bootstrap_repository = EquityBootstrapConfigRepository()

    def handle(self, *args, **options):
        """执行初始化"""
        self.stdout.write("开始初始化个股/板块/基金配置...")
        self.init_stock_screening_rules()
        self.init_sector_preferences()
        self.init_fund_type_preferences()
        self.stdout.write(self.style.SUCCESS("配置初始化完成！"))

    def init_stock_screening_rules(self):
        """初始化个股筛选规则"""
        rules = [
            {
                "regime": "Recovery",
                "rule_name": "复苏期成长股",
                "min_roe": 15.0,
                "min_revenue_growth": 20.0,
                "min_profit_growth": 15.0,
                "max_pe": 35.0,
                "max_pb": 5.0,
                "min_market_cap": Decimal('5000000000'),  # 50 亿
                "sector_preference": ["证券", "建筑材料", "化工", "汽车", "电子"],
                "max_count": 30,
                "priority": 1
            },
            {
                "regime": "Overheat",
                "rule_name": "过热期商品股",
                "min_roe": 12.0,
                "min_revenue_growth": 15.0,
                "max_pe": 25.0,
                "max_pb": 3.0,
                "min_market_cap": Decimal('10000000000'),  # 100 亿
                "sector_preference": ["煤炭", "有色金属", "石油石化", "钢铁"],
                "max_count": 30,
                "priority": 1
            },
            {
                "regime": "Stagflation",
                "rule_name": "滞胀期防御股",
                "min_roe": 10.0,
                "min_revenue_growth": 5.0,
                "max_pe": 20.0,
                "max_pb": 2.5,
                "min_market_cap": Decimal('10000000000'),  # 100 亿
                "sector_preference": ["医药生物", "食品饮料", "公用事业", "农林牧渔"],
                "max_count": 30,
                "priority": 1
            },
            {
                "regime": "Deflation",
                "rule_name": "通缩期价值股",
                "min_roe": 8.0,
                "max_debt_ratio": 60.0,
                "max_pe": 15.0,
                "max_pb": 2.0,
                "min_market_cap": Decimal('20000000000'),  # 200 亿
                "sector_preference": ["银行", "保险", "房地产"],
                "max_count": 30,
                "priority": 1
            },
        ]

        for rule_data in rules:
            self.bootstrap_repository.upsert_stock_screening_rule(rule_data)

        self.stdout.write(f"已初始化 {len(rules)} 条个股筛选规则")

    def init_sector_preferences(self):
        """初始化板块偏好"""
        preferences = [
            # Recovery
            {"regime": "Recovery", "sector_name": "证券", "weight": 1.0},
            {"regime": "Recovery", "sector_name": "建筑材料", "weight": 0.9},
            {"regime": "Recovery", "sector_name": "化工", "weight": 0.9},
            {"regime": "Recovery", "sector_name": "汽车", "weight": 0.8},
            {"regime": "Recovery", "sector_name": "电子", "weight": 0.8},

            # Overheat
            {"regime": "Overheat", "sector_name": "煤炭", "weight": 1.0},
            {"regime": "Overheat", "sector_name": "有色金属", "weight": 0.9},
            {"regime": "Overheat", "sector_name": "石油石化", "weight": 0.9},

            # Stagflation
            {"regime": "Stagflation", "sector_name": "医药生物", "weight": 1.0},
            {"regime": "Stagflation", "sector_name": "食品饮料", "weight": 0.9},
            {"regime": "Stagflation", "sector_name": "公用事业", "weight": 0.8},

            # Deflation
            {"regime": "Deflation", "sector_name": "银行", "weight": 1.0},
            {"regime": "Deflation", "sector_name": "保险", "weight": 0.9},
        ]

        for pref in preferences:
            self.bootstrap_repository.upsert_sector_preference(pref)

        self.stdout.write(f"已初始化 {len(preferences)} 条板块偏好配置")

    def init_fund_type_preferences(self):
        """初始化基金类型偏好"""
        preferences = [
            # Recovery
            {"regime": "Recovery", "fund_type": "股票型", "style": "成长", "priority": 2},
            {"regime": "Recovery", "fund_type": "混合型", "style": "平衡", "priority": 1},

            # Overheat
            {"regime": "Overheat", "fund_type": "商品型", "style": "商品", "priority": 2},
            {"regime": "Overheat", "fund_type": "QDII", "style": "商品", "priority": 1},

            # Stagflation
            {"regime": "Stagflation", "fund_type": "货币型", "style": "稳健", "priority": 2},
            {"regime": "Stagflation", "fund_type": "短债型", "style": "稳健", "priority": 1},

            # Deflation
            {"regime": "Deflation", "fund_type": "债券型", "style": "纯债", "priority": 1},
        ]

        for pref in preferences:
            self.bootstrap_repository.upsert_fund_type_preference(pref)

        self.stdout.write(f"已初始化 {len(preferences)} 条基金类型偏好配置")

