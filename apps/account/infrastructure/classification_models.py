"""
资产分类体系与币种参考 ORM 模型

包含资产元数据、多级资产分类、币种与汇率。
"""

import re
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models

from .classification_constraints import (
    ASSET_CATEGORY_CONSTRAINTS,
    CURRENCY_CONSTRAINTS,
    EXCHANGE_RATE_CONSTRAINTS,
)

__all__ = [
    "AssetCategoryModel",
    "AssetMetadataModel",
    "CurrencyModel",
    "ExchangeRateModel",
]


# 资产元数据模型


_CURRENCY_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9]{1,9}$")


class AssetMetadataModel(models.Model):
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
        constraints = ASSET_CATEGORY_CONSTRAINTS

    def __str__(self) -> str:
        return f"{self.path} - {self.name}"

    def get_ancestors(self) -> list["AssetCategoryModel"]:
        """Return root-first ancestors while failing closed on corrupt cycles."""

        ancestors: list[AssetCategoryModel] = []
        seen_ids: set[int] = set()
        if self.pk is not None:
            seen_ids.add(self.pk)
        current = self.parent
        while current is not None:
            if current.pk is None or current.pk in seen_ids:
                raise ValueError("资产分类层级存在循环引用")
            seen_ids.add(current.pk)
            ancestors.append(current)
            current = current.parent
        ancestors.reverse()
        return ancestors

    def clean(self) -> None:
        """Validate materialized tree invariants before repository or Admin writes."""

        super().clean()
        errors: dict[str, str] = {}
        if self.level < 1:
            errors["level"] = "分类层级必须大于等于 1"
        if self.parent_id is None:
            if self.level != 1:
                errors["level"] = "根分类层级必须为 1"
        else:
            if self.pk is not None and self.parent_id == self.pk:
                errors["parent"] = "分类不能以自身作为父分类"
            try:
                parent = self.parent
                if parent is None:
                    errors["parent"] = "父分类不存在"
                else:
                    if self.level != parent.level + 1:
                        errors["level"] = "子分类层级必须等于父分类层级加 1"
                    if not self.path.startswith(f"{parent.path}/"):
                        errors["path"] = "子分类路径必须位于父分类路径下"
                self.get_ancestors()
            except ValueError as exc:
                errors["parent"] = str(exc)
        if errors:
            raise ValidationError(errors)

    def get_full_path(self) -> str:
        """获取完整分类路径"""
        ancestors = self.get_ancestors()
        path_parts = [a.name for a in ancestors]
        path_parts.append(self.name)
        return " / ".join(path_parts)


# 币种模型


class CurrencyModel(models.Model):
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
        constraints = CURRENCY_CONSTRAINTS

    def __str__(self) -> str:
        return f"{self.code} - {self.name} ({self.symbol})"

    def clean(self) -> None:
        """Validate canonical currency identity and precision."""

        super().clean()
        errors: dict[str, str] = {}
        if not _CURRENCY_CODE_PATTERN.fullmatch(self.code):
            errors["code"] = "币种代码必须为 2 至 10 位大写 ASCII 字母或数字"
        if not 0 <= self.precision <= 8:
            errors["precision"] = "币种精度必须在 0 至 8 之间"
        if self.is_base and not self.is_active:
            errors["is_active"] = "基准货币必须启用"
        if errors:
            raise ValidationError(errors)

    @classmethod
    def get_base_currency(cls) -> "CurrencyModel | None":
        """获取基准货币"""
        return cls._default_manager.filter(is_base=True, is_active=True).first() or (
            cls._default_manager.filter(code="CNY", is_active=True).first()
        )


# 汇率模型


class ExchangeRateModel(models.Model):
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
        constraints = EXCHANGE_RATE_CONSTRAINTS

    def __str__(self) -> str:
        return f"{self.from_currency.code} -> {self.to_currency.code}: {self.rate} ({self.effective_date})"

    def clean(self) -> None:
        """Validate one governed exchange-rate observation."""

        super().clean()
        errors: dict[str, str] = {}
        if not self.rate.is_finite() or self.rate <= 0:
            errors["rate"] = "汇率必须为正有限数"
        if self.from_currency_id == self.to_currency_id:
            errors["to_currency"] = "源币种和目标币种不能相同"
        if self.from_currency_id and not self.from_currency.is_active:
            errors["from_currency"] = "源币种必须处于启用状态"
        if self.to_currency_id and not self.to_currency.is_active:
            errors["to_currency"] = "目标币种必须处于启用状态"
        if errors:
            raise ValidationError(errors)

    def convert(self, amount: Decimal) -> Decimal:
        """将金额从源币种转换为目标币种"""
        if not isinstance(amount, Decimal) or not amount.is_finite():
            raise ValueError("转换金额必须为有限 Decimal")
        rate = Decimal(self.rate)
        if not rate.is_finite() or rate <= 0:
            raise ValueError("汇率必须为正有限数")
        return amount * rate

    @classmethod
    def get_latest_rate(cls, from_code: str, to_code: str) -> "ExchangeRateModel | None":
        """获取最新汇率"""
        normalized_from = cls._normalize_currency_code(from_code)
        normalized_to = cls._normalize_currency_code(to_code)
        return (
            cls._default_manager.filter(
                from_currency__code=normalized_from,
                from_currency__is_active=True,
                to_currency__code=normalized_to,
                to_currency__is_active=True,
            )
            .order_by("-effective_date")
            .first()
        )

    @classmethod
    def convert_amount(
        cls,
        amount: Decimal,
        from_code: str,
        to_code: str,
        date: date | None = None,
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
        normalized_from = cls._normalize_currency_code(from_code)
        normalized_to = cls._normalize_currency_code(to_code)
        if not isinstance(amount, Decimal) or not amount.is_finite():
            raise ValueError("转换金额必须为有限 Decimal")
        if normalized_from == normalized_to:
            return amount

        queryset = cls._default_manager.filter(
            from_currency__code=normalized_from,
            from_currency__is_active=True,
            to_currency__code=normalized_to,
            to_currency__is_active=True,
        )

        if date:
            queryset = queryset.filter(effective_date__lte=date).order_by("-effective_date")
        else:
            queryset = queryset.order_by("-effective_date")

        rate = queryset.first()
        if not rate:
            raise ValueError(f"No exchange rate found for {normalized_from} -> {normalized_to}")

        return rate.convert(amount)

    @staticmethod
    def _normalize_currency_code(value: object) -> str:
        """Return one canonical governed currency code."""

        if not isinstance(value, str):
            raise ValueError("币种代码格式无效")
        normalized = value.strip().upper()
        if not _CURRENCY_CODE_PATTERN.fullmatch(normalized):
            raise ValueError("币种代码格式无效")
        return normalized
