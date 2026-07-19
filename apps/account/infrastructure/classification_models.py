"""
资产分类体系与币种参考 ORM 模型

包含资产元数据、多级资产分类、币种与汇率。
"""

from decimal import Decimal
from typing import Any, cast

from django.db import models  # type: ignore[import-untyped]

__all__ = [
    "AssetCategoryModel",
    "AssetMetadataModel",
    "CurrencyModel",
    "ExchangeRateModel",
]


# 资产元数据模型


class AssetMetadataModel(models.Model):  # type: ignore[misc]
    """
    资产元数据表

    存储每个资产代码的完整分类信息。
    由管理员维护，用户查看。
    """

    # 基础信息
    asset_code = models.CharField(
        max_length=50, unique=True, db_index=True, verbose_name="资产代码"
    )
    name = models.CharField(max_length=200, verbose_name="资产名称")
    description = models.TextField(blank=True, verbose_name="描述")

    # 预定义分类（枚举）
    ASSET_CLASS_CHOICES = [
        ("equity", "股票"),
        ("fixed_income", "固定收益"),
        ("commodity", "商品"),
        ("currency", "外汇"),
        ("cash", "现金"),
        ("fund", "基金"),
        ("derivative", "衍生品"),
        ("other", "其他"),
    ]
    asset_class = models.CharField(
        max_length=20, choices=ASSET_CLASS_CHOICES, verbose_name="资产大类"
    )

    REGION_CHOICES = [
        ("CN", "中国境内"),
        ("US", "美国"),
        ("EU", "欧洲"),
        ("JP", "日本"),
        ("EM", "新兴市场"),
        ("GLOBAL", "全球"),
        ("OTHER", "其他"),
    ]
    region = models.CharField(max_length=10, choices=REGION_CHOICES, verbose_name="地区")

    CROSS_BORDER_CHOICES = [
        ("domestic", "境内资产"),
        ("qdii", "QDII基金"),
        ("direct_foreign", "直接境外投资"),
    ]
    cross_border = models.CharField(
        max_length=20, choices=CROSS_BORDER_CHOICES, default="domestic", verbose_name="跨境标识"
    )

    STYLE_CHOICES = [
        ("growth", "成长"),
        ("value", "价值"),
        ("blend", "混合"),
        ("cyclical", "周期"),
        ("defensive", "防御"),
        ("quality", "质量"),
        ("momentum", "动量"),
        ("unknown", "未知/不适用"),
    ]
    style = models.CharField(
        max_length=20, choices=STYLE_CHOICES, default="unknown", verbose_name="投资风格"
    )

    # 用户可自定义分类
    sector = models.CharField(max_length=50, blank=True, verbose_name="行业板块")
    sub_class = models.CharField(max_length=50, blank=True, verbose_name="子类")

    # 元数据
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "asset_metadata"
        verbose_name = "资产元数据"
        verbose_name_plural = "资产元数据"
        indexes = [
            models.Index(fields=["asset_code"]),
            models.Index(fields=["asset_class", "region"]),
        ]

    def __str__(self) -> str:
        return f"{self.asset_code} - {self.name}"


# 资产分类体系（多级分类）


class AssetCategoryModel(models.Model):  # type: ignore[misc]
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
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="children",
        verbose_name="父分类",
    )

    level = models.IntegerField(default=1, verbose_name="层级")  # 1=一级, 2=二级, etc.
    path = models.CharField(max_length=200, verbose_name="分类路径")  # 例如：基金/股票基金

    description = models.TextField(blank=True, verbose_name="描述")
    is_active = models.BooleanField(default=True, verbose_name="是否启用")
    sort_order = models.IntegerField(default=0, verbose_name="排序")

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = "asset_category"
        verbose_name = "资产分类"
        verbose_name_plural = "资产分类"
        ordering = ["path", "sort_order"]
        indexes = [
            models.Index(fields=["code"]),
            models.Index(fields=["parent"]),
            models.Index(fields=["level"]),
        ]

    def __str__(self) -> str:
        return f"{self.path} - {self.name}"

    def get_ancestors(self) -> list["AssetCategoryModel"]:
        """获取所有父级分类"""
        if self.parent:
            parent = cast("AssetCategoryModel", self.parent)
            return parent.get_ancestors() + [parent]
        return []

    def get_full_path(self) -> str:
        """获取完整分类路径"""
        ancestors = self.get_ancestors()
        path_parts = [a.name for a in ancestors]
        path_parts.append(self.name)
        return " / ".join(path_parts)


# 币种模型


class CurrencyModel(models.Model):  # type: ignore[misc]
    """
    币种模型

    支持多币种，包括人民币、美元、欧元、港币等。
    """

    code = models.CharField(
        max_length=10, unique=True, verbose_name="币种代码"
    )  # CNY, USD, EUR, HKD
    name = models.CharField(max_length=50, verbose_name="币种名称")  # 人民币, 美元, 欧元, 港币
    symbol = models.CharField(max_length=10, verbose_name="货币符号")  # ¥, $, €, HK$

    is_base = models.BooleanField(default=False, verbose_name="是否基准货币")
    is_active = models.BooleanField(default=True, verbose_name="是否启用")

    # 精度设置
    precision = models.IntegerField(default=2, verbose_name="小数位数")  # CNY通常2位，JPY可能0位

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = "currency"
        verbose_name = "币种"
        verbose_name_plural = "币种"
        ordering = ["-is_base", "code"]

    def __str__(self) -> str:
        return f"{self.code} - {self.name} ({self.symbol})"

    @classmethod
    def get_base_currency(cls) -> "CurrencyModel | None":
        """获取基准货币"""
        result = cls.objects.filter(is_base=True).first() or cls.objects.filter(code="CNY").first()
        return cast("CurrencyModel | None", result)


# 汇率模型


class ExchangeRateModel(models.Model):  # type: ignore[misc]
    """
    汇率模型

    存储历史汇率数据，支持汇率换算。
    """

    from_currency = models.ForeignKey(
        CurrencyModel, on_delete=models.CASCADE, related_name="rates_from", verbose_name="源币种"
    )
    to_currency = models.ForeignKey(
        CurrencyModel, on_delete=models.CASCADE, related_name="rates_to", verbose_name="目标币种"
    )

    rate = models.DecimalField(max_digits=20, decimal_places=6, verbose_name="汇率")
    effective_date = models.DateField(db_index=True, verbose_name="生效日期")

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        db_table = "exchange_rate"
        verbose_name = "汇率"
        verbose_name_plural = "汇率"
        ordering = ["-effective_date"]
        unique_together = [["from_currency", "to_currency", "effective_date"]]
        indexes = [
            models.Index(fields=["from_currency", "to_currency", "effective_date"]),
        ]

    def __str__(self) -> str:
        return f"{self.from_currency.code} -> {self.to_currency.code}: {self.rate} ({self.effective_date})"

    def convert(self, amount: Decimal) -> Decimal:
        """将金额从源币种转换为目标币种"""
        return amount * Decimal(str(self.rate))

    @classmethod
    def get_latest_rate(cls, from_code: str, to_code: str) -> "ExchangeRateModel | None":
        """获取最新汇率"""
        result = (
            cls.objects.filter(from_currency__code=from_code, to_currency__code=to_code)
            .order_by("-effective_date")
            .first()
        )
        return cast("ExchangeRateModel | None", result)

    @classmethod
    def convert_amount(
        cls,
        amount: Decimal,
        from_code: str,
        to_code: str,
        date: Any = None,
    ) -> Decimal:
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

        queryset = cls.objects.filter(from_currency__code=from_code, to_currency__code=to_code)

        if date:
            queryset = queryset.filter(effective_date__lte=date).order_by("-effective_date")
        else:
            queryset = queryset.order_by("-effective_date")

        rate = cast("ExchangeRateModel | None", queryset.first())
        if not rate:
            raise ValueError(f"No exchange rate found for {from_code} -> {to_code}")

        return rate.convert(amount)
