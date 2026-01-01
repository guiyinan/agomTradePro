"""
Asset Classification and Multi-Currency Models.

资产分类体系和多币种支持模型。
"""

from django.db import models
from decimal import Decimal


# ============================================================
# 资产分类模型
# ============================================================

class AssetCategoryModel(models.Model):
    """
    资产分类模型

    支持树形结构的分类体系，例如：
    - 基金
      - 债券基金
      - 股票基金
      - 混合基金
      - 商品基金
    - 理财
    - 存款
    """

    code = models.CharField(max_length=50, unique=True, db_index=True, verbose_name="分类代码")
    name = models.CharField(max_length=100, verbose_name="分类名称")

    # 树形结构
    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='children',
        verbose_name="父分类"
    )

    level = models.IntegerField(default=1, verbose_name="层级")  # 1=一级, 2=二级, etc.
    path = models.CharField(max_length=200, verbose_name="分类路径")  # 例如：基金/股票基金

    description = models.TextField(blank=True, verbose_name="描述")
    is_active = models.BooleanField(default=True, verbose_name="是否启用")
    sort_order = models.IntegerField(default=0, verbose_name="排序")

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = 'asset_category'
        verbose_name = '资产分类'
        verbose_name_plural = '资产分类'
        ordering = ['path', 'sort_order']
        indexes = [
            models.Index(fields=['code']),
            models.Index(fields=['parent']),
            models.Index(fields=['level']),
        ]

    def __str__(self):
        return f"{self.path} - {self.name}"

    def get_ancestors(self):
        """获取所有父级分类"""
        if self.parent:
            return self.parent.get_ancestors() + [self.parent]
        return []

    def get_full_path(self):
        """获取完整分类路径"""
        ancestors = self.get_ancestors()
        path_parts = [a.name for a in ancestors]
        path_parts.append(self.name)
        return " / ".join(path_parts)


# ============================================================
# 币种模型
# ============================================================

class CurrencyModel(models.Model):
    """
    币种模型

    支持多币种，包括人民币、美元、欧元、港币等。
    """

    code = models.CharField(max_length=10, unique=True, verbose_name="币种代码")  # CNY, USD, EUR, HKD
    name = models.CharField(max_length=50, verbose_name="币种名称")  # 人民币, 美元, 欧元, 港币
    symbol = models.CharField(max_length=10, verbose_name="货币符号")  # ¥, $, €, HK$

    is_base = models.BooleanField(default=False, verbose_name="是否基准货币")
    is_active = models.BooleanField(default=True, verbose_name="是否启用")

    # 精度设置
    precision = models.IntegerField(default=2, verbose_name="小数位数")  # CNY通常2位，JPY可能0位

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = 'currency'
        verbose_name = '币种'
        verbose_name_plural = '币种'
        ordering = ['-is_base', 'code']

    def __str__(self):
        return f"{self.code} - {self.name} ({self.symbol})"

    @classmethod
    def get_base_currency(cls):
        """获取基准货币"""
        return cls.objects.filter(is_base=True).first() or cls.objects.filter(code='CNY').first()


# ============================================================
# 汇率模型
# ============================================================

class ExchangeRateModel(models.Model):
    """
    汇率模型

    存储历史汇率数据，支持汇率换算。
    """

    from_currency = models.ForeignKey(
        CurrencyModel,
        on_delete=models.CASCADE,
        related_name='rates_from',
        verbose_name="源币种"
    )
    to_currency = models.ForeignKey(
        CurrencyModel,
        on_delete=models.CASCADE,
        related_name='rates_to',
        verbose_name="目标币种"
    )

    rate = models.DecimalField(max_digits=20, decimal_places=6, verbose_name="汇率")
    effective_date = models.DateField(db_index=True, verbose_name="生效日期")

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        db_table = 'exchange_rate'
        verbose_name = '汇率'
        verbose_name_plural = '汇率'
        ordering = ['-effective_date']
        unique_together = [['from_currency', 'to_currency', 'effective_date']]
        indexes = [
            models.Index(fields=['from_currency', 'to_currency', 'effective_date']),
        ]

    def __str__(self):
        return f"{self.from_currency.code} -> {self.to_currency.code}: {self.rate} ({self.effective_date})"

    def convert(self, amount: Decimal) -> Decimal:
        """将金额从源币种转换为目标币种"""
        return amount * self.rate

    @classmethod
    def get_latest_rate(cls, from_code: str, to_code: str) -> 'ExchangeRateModel':
        """获取最新汇率"""
        return cls.objects.filter(
            from_currency__code=from_code,
            to_currency__code=to_code
        ).order_by('-effective_date').first()

    @classmethod
    def convert_amount(cls, amount: Decimal, from_code: str, to_code: str, date=None) -> Decimal:
        """
        转换金额

        Args:
            amount: 金额
            from_code: 源币种代码
            to_code: 目标币种代码
            date: 指定日期（可选）

        Returns:
            转换后的金额
        """
        if from_code == to_code:
            return amount

        queryset = cls.objects.filter(
            from_currency__code=from_code,
            to_currency__code=to_code
        )

        if date:
            queryset = queryset.filter(effective_date__lte=date).order_by('-effective_date')
        else:
            queryset = queryset.order_by('-effective_date')

        rate = queryset.first()
        if not rate:
            raise ValueError(f"No exchange rate found for {from_code} -> {to_code}")

        return rate.convert(amount)


# ============================================================
# 初始数据
# ============================================================

def init_currencies_and_categories():
    """初始化币种和资产分类数据"""

    # 创建币种
    currencies = [
        ('CNY', '人民币', '¥', True, 2),
        ('USD', '美元', '$', False, 2),
        ('EUR', '欧元', '€', False, 2),
        ('HKD', '港币', 'HK$', False, 2),
        ('JPY', '日元', '¥', False, 0),
        ('GBP', '英镑', '£', False, 2),
    ]

    for code, name, symbol, is_base, precision in currencies:
        CurrencyModel.objects.get_or_create(
            code=code,
            defaults={
                'name': name,
                'symbol': symbol,
                'is_base': is_base,
                'precision': precision,
            }
        )

    # 创建一级分类
    top_categories = [
        ('FUND', '基金', 1),
        ('STOCK', '股票', 2),
        ('BOND', '债券', 3),
        ('WEALTH', '理财', 4),
        ('DEPOSIT', '存款', 5),
        ('COMMODITY', '商品', 6),
        ('CASH', '现金', 7),
        ('REAL_ESTATE', '房地产', 8),
        ('OTHER', '其他', 9),
    ]

    for code, name, order in top_categories:
        parent, _ = AssetCategoryModel.objects.get_or_create(
            code=code,
            defaults={
                'name': name,
                'level': 1,
                'path': name,
                'sort_order': order,
            }
        )
        parent.path = parent.name
        parent.save()

    # 创建二级分类（基金子类）
    fund_parent = AssetCategoryModel.objects.get(code='FUND')
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
        AssetCategoryModel.objects.get_or_create(
            code=code,
            defaults={
                'name': name,
                'parent': fund_parent,
                'level': 2,
                'path': f"{fund_parent.name} / {name}",
                'sort_order': order,
            }
        )

    # 创建二级分类（存款子类）
    deposit_parent = AssetCategoryModel.objects.get(code='DEPOSIT')
    deposit_subcategories = [
        ('DEMAND', '活期存款', 1),
        ('TIME', '定期存款', 2),
        ('LUMP_SUM', '大额存单', 3),
    ]

    for code, name, order in deposit_subcategories:
        AssetCategoryModel.objects.get_or_create(
            code=code,
            defaults={
                'name': name,
                'parent': deposit_parent,
                'level': 2,
                'path': f"{deposit_parent.name} / {name}",
                'sort_order': order,
            }
        )

    # 创建二级分类（理财子类）
    wealth_parent = AssetCategoryModel.objects.get(code='WEALTH')
    wealth_subcategories = [
        ('BANK_WEALTH', '银行理财', 1),
        ('TRUST', '信托', 2),
        ('INSURANCE', '保险理财', 3),
    ]

    for code, name, order in wealth_subcategories:
        AssetCategoryModel.objects.get_or_create(
            code=code,
            defaults={
                'name': name,
                'parent': wealth_parent,
                'level': 2,
                'path': f"{wealth_parent.name} / {name}",
                'sort_order': order,
            }
        )
