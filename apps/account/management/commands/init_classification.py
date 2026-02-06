"""
Initialize Asset Categories and Currencies.

初始化资产分类和币种数据。
"""

from django.core.management.base import BaseCommand
from apps.account.infrastructure.models import (
    AssetCategoryModel,
    CurrencyModel,
    ExchangeRateModel,
)
from decimal import Decimal
from datetime import date


class Command(BaseCommand):
    help = '初始化资产分类和币种数据'

    def handle(self, *args, **options):
        self.stdout.write('Starting initialization of asset categories and currencies...')

        # 1. 创建币种
        self.stdout.write('\n1. Creating currencies...')
        currencies = [
            ('CNY', '人民币', '¥', True, 2),
            ('USD', '美元', '$', False, 2),
            ('EUR', '欧元', '€', False, 2),
            ('HKD', '港币', 'HK$', False, 2),
            ('JPY', '日元', '¥', False, 0),
            ('GBP', '英镑', '£', False, 2),
        ]

        for code, name, symbol, is_base, precision in currencies:
            currency, created = CurrencyModel._default_manager.get_or_create(
                code=code,
                defaults={
                    'name': name,
                    'symbol': symbol,
                    'is_base': is_base,
                    'precision': precision,
                }
            )
            if created:
                self.stdout.write(f'  [OK] Create currency: {code} - {name}')
            else:
                self.stdout.write(f'  - Currency exists: {code} - {name}')

        # 2. 创建一级分类
        self.stdout.write('\n2. Creating top-level asset categories...')
        top_categories = [
            ('FUND', '基金', 1, '基金'),
            ('STOCK', '股票', 2, '股票'),
            ('BOND', '债券', 3, '债券'),
            ('WEALTH', '理财', 4, '理财'),
            ('DEPOSIT', '存款', 5, '存款'),
            ('COMMODITY', '商品', 6, '商品'),
            ('CASH', '现金', 7, '现金'),
            ('REAL_ESTATE', '房地产', 8, '房地产'),
            ('OTHER', '其他', 9, '其他'),
        ]

        for code, name, order, path in top_categories:
            category, created = AssetCategoryModel._default_manager.get_or_create(
                code=code,
                defaults={
                    'name': name,
                    'level': 1,
                    'path': path,
                    'sort_order': order,
                }
            )
            if created:
                self.stdout.write(f'  [OK] Create top-level category: {code} - {name}')
            else:
                self.stdout.write(f'  - Category exists: {code} - {name}')

        # 3. 创建二级分类（基金子类）
        self.stdout.write('\n3. Creating fund sub-categories...')
        fund_parent = AssetCategoryModel._default_manager.get(code='FUND')
        fund_subcategories = [
            ('STOCK_FUND', '股票基金', 1),
            ('BOND_FUND', '债券基金', 2),
            ('MIXED_FUND', '混合基金', 3),
            ('COMMODITY_FUND', '商品基金', 4),
            ('MONEY_FUND', '货币基金', 5),
            ('INDEX_FUND', '指数基金', 6),
            ('QDII_FUND', 'QDII基金', 7),
        ]

        for code, name, order in fund_subcategories:
            category, created = AssetCategoryModel._default_manager.get_or_create(
                code=code,
                defaults={
                    'name': name,
                    'parent': fund_parent,
                    'level': 2,
                    'path': f"{fund_parent.path} / {name}",
                    'sort_order': order,
                }
            )
            if created:
                self.stdout.write(f'  [OK] Create sub-category: {code} - {name}')
            else:
                self.stdout.write(f'  - Sub-category exists: {code} - {name}')

        # 4. 创建二级分类（存款子类）
        self.stdout.write('\n4. Creating deposit sub-categories...')
        deposit_parent = AssetCategoryModel._default_manager.get(code='DEPOSIT')
        deposit_subcategories = [
            ('DEMAND', '活期存款', 1),
            ('TIME', '定期存款', 2),
            ('LUMP_SUM', '大额存单', 3),
        ]

        for code, name, order in deposit_subcategories:
            category, created = AssetCategoryModel._default_manager.get_or_create(
                code=code,
                defaults={
                    'name': name,
                    'parent': deposit_parent,
                    'level': 2,
                    'path': f"{deposit_parent.path} / {name}",
                    'sort_order': order,
                }
            )
            if created:
                self.stdout.write(f'  [OK] Create sub-category: {code} - {name}')
            else:
                self.stdout.write(f'  - Sub-category exists: {code} - {name}')

        # 5. 创建二级分类（理财子类）
        self.stdout.write('\n5. Creating wealth sub-categories...')
        wealth_parent = AssetCategoryModel._default_manager.get(code='WEALTH')
        wealth_subcategories = [
            ('BANK_WEALTH', '银行理财', 1),
            ('TRUST', '信托', 2),
            ('INSURANCE', '保险理财', 3),
        ]

        for code, name, order in wealth_subcategories:
            category, created = AssetCategoryModel._default_manager.get_or_create(
                code=code,
                defaults={
                    'name': name,
                    'parent': wealth_parent,
                    'level': 2,
                    'path': f"{wealth_parent.path} / {name}",
                    'sort_order': order,
                }
            )
            if created:
                self.stdout.write(f'  [OK] Create sub-category: {code} - {name}')
            else:
                self.stdout.write(f'  - Sub-category exists: {code} - {name}')

        # 6. 创建初始汇率
        self.stdout.write('\n6. Creating initial exchange rates...')
        cny = CurrencyModel._default_manager.get(code='CNY')
        usd = CurrencyModel._default_manager.get(code='USD')

        initial_rates = [
            ('USD', 'CNY', Decimal('7.20')),  # 1 USD = 7.20 CNY
            ('CNY', 'USD', Decimal('0.1389')),  # 1 CNY = 0.1389 USD
        ]

        for from_code, to_code, rate in initial_rates:
            from_curr = CurrencyModel._default_manager.get(code=from_code)
            to_curr = CurrencyModel._default_manager.get(code=to_code)

            exchange_rate, created = ExchangeRateModel._default_manager.get_or_create(
                from_currency=from_curr,
                to_currency=to_curr,
                effective_date=date.today(),
                defaults={'rate': rate}
            )
            if created:
                self.stdout.write(f'  [OK] Create exchange rate: {from_code} -> {to_code} = {rate}')
            else:
                # 更新汇率
                exchange_rate.rate = rate
                exchange_rate.save()
                self.stdout.write(f'  ~ Update exchange rate: {from_code} -> {to_code} = {rate}')

        self.stdout.write('\n[OK] Initialization complete!')
        self.stdout.write(f'\nStatistics:')
        self.stdout.write(f'  - Currencies: {CurrencyModel._default_manager.count()}')
        self.stdout.write(f'  - Top-level categories: {AssetCategoryModel._default_manager.filter(level=1).count()}')
        self.stdout.write(f'  - Sub-categories: {AssetCategoryModel._default_manager.filter(level=2).count()}')
        self.stdout.write(f'  - Exchange rates: {ExchangeRateModel._default_manager.count()}')

