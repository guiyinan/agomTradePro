"""
基金分析模块 - ORM 模型定义

遵循项目架构约束：
- 使用 Django ORM 定义数据表结构
- 包含基金基本信息、净值、持仓、业绩等表
"""

import math
import re
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.db import models

from .model_constraints import (
    FUND_HOLDING_CONSTRAINTS,
    FUND_INFO_CONSTRAINTS,
    FUND_MANAGER_CONSTRAINTS,
    FUND_NAV_CONSTRAINTS,
    FUND_PERFORMANCE_CONSTRAINTS,
    FUND_SECTOR_CONSTRAINTS,
)

_FUND_CODE_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9._-]{1,9}$")


def _validate_code(value: str, *, field_name: str) -> None:
    """Require one canonical bounded fund or security code."""

    if not _FUND_CODE_PATTERN.fullmatch(value):
        raise ValidationError({field_name: "代码必须为 2 至 10 位大写 ASCII 标识"})


def _validate_optional_finite(value: float | None, *, field_name: str) -> None:
    """Reject NaN and infinities from optional model metrics."""

    if value is not None and not math.isfinite(value):
        raise ValidationError({field_name: "指标必须为有限数"})


def _quantize_decimal(value: object, *, places: int, field_name: str) -> Decimal:
    """Normalize finite DecimalField input to declared storage precision."""

    try:
        parsed = value if isinstance(value, Decimal) else Decimal(str(value))
    except (ArithmeticError, TypeError, ValueError) as exc:
        raise ValidationError({field_name: "数值格式无效"}) from exc
    if not parsed.is_finite():
        return parsed
    return parsed.quantize(Decimal(1).scaleb(-places))


class ValidatedFundModel(models.Model):
    """Run model and database-constraint validation on every ORM save path."""

    class Meta:
        abstract = True

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Validate before persisting provider or Admin data."""

        self._normalize_for_save()
        self.full_clean(validate_unique=False, validate_constraints=False)
        super().save(*args, **kwargs)

    def _normalize_for_save(self) -> None:
        """Normalize storage precision before field validation."""


class FundInfoModel(ValidatedFundModel):
    """基金基本信息表

    存公募基金的基本信息
    """

    fund_code = models.CharField(max_length=10, unique=True, db_index=True, verbose_name="基金代码")
    fund_name = models.CharField(max_length=100, verbose_name="基金名称")
    fund_type = models.CharField(
        max_length=20,
        db_index=True,
        verbose_name="基金类型",
        help_text="股票型/债券型/混合型/指数型/货币型/QDII/商品型",
    )
    investment_style = models.CharField(
        max_length=20,
        null=True,
        blank=True,
        db_index=True,
        verbose_name="投资风格",
        help_text="成长/价值/平衡/商品/稳健",
    )
    setup_date = models.DateField(null=True, blank=True, verbose_name="成立日期")
    management_company = models.CharField(
        max_length=100, null=True, blank=True, verbose_name="管理人"
    )
    custodian = models.CharField(max_length=100, null=True, blank=True, verbose_name="托管人")
    fund_scale = models.DecimalField(
        max_digits=20, decimal_places=2, null=True, blank=True, verbose_name="基金规模（元）"
    )

    # 元数据
    is_active = models.BooleanField(default=True, verbose_name="是否活跃")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "fund_info"
        verbose_name = "基金基本信息"
        verbose_name_plural = "基金基本信息"
        indexes = [
            models.Index(fields=["fund_code"]),
            models.Index(fields=["fund_type", "is_active"]),
            models.Index(fields=["investment_style"]),
        ]
        ordering = ["fund_code"]
        constraints = FUND_INFO_CONSTRAINTS

    def __str__(self) -> str:
        return f"{self.fund_code} - {self.fund_name}"

    def clean(self) -> None:
        """Validate master-data identity and scale."""

        super().clean()
        _validate_code(self.fund_code, field_name="fund_code")
        if self.fund_scale is not None and (not self.fund_scale.is_finite() or self.fund_scale < 0):
            raise ValidationError({"fund_scale": "基金规模必须为非负有限数"})

    def _normalize_for_save(self) -> None:
        if self.fund_scale is not None:
            self.fund_scale = _quantize_decimal(
                self.fund_scale,
                places=2,
                field_name="fund_scale",
            )


class FundManagerModel(ValidatedFundModel):
    """基金经理表

    存储基金经理的任职信息
    """

    fund_code = models.CharField(max_length=10, db_index=True, verbose_name="基金代码")
    manager_name = models.CharField(max_length=50, verbose_name="经理姓名")
    tenure_start = models.DateField(verbose_name="任职开始日期")
    tenure_end = models.DateField(null=True, blank=True, verbose_name="任职结束日期")
    total_tenure_days = models.IntegerField(null=True, blank=True, verbose_name="任期天数")
    fund_return = models.FloatField(null=True, blank=True, verbose_name="任期期间基金收益率（%）")

    # 元数据
    is_current = models.BooleanField(default=True, verbose_name="是否在任")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "fund_manager"
        verbose_name = "基金经理"
        verbose_name_plural = "基金经理"
        indexes = [
            models.Index(fields=["fund_code", "is_current"]),
            models.Index(fields=["manager_name"]),
        ]
        ordering = ["fund_code", "-tenure_start"]
        constraints = FUND_MANAGER_CONSTRAINTS

    def __str__(self) -> str:
        return f"{self.fund_code} - {self.manager_name}"

    def clean(self) -> None:
        """Validate manager tenure dates and provider metrics."""

        super().clean()
        _validate_code(self.fund_code, field_name="fund_code")
        _validate_optional_finite(self.fund_return, field_name="fund_return")
        if self.tenure_end is not None and self.tenure_end < self.tenure_start:
            raise ValidationError({"tenure_end": "任职结束日期不能早于开始日期"})
        if self.total_tenure_days is not None and self.total_tenure_days < 0:
            raise ValidationError({"total_tenure_days": "任期天数不能为负数"})


class FundNetValueModel(ValidatedFundModel):
    """基金净值数据表

    存储基金的日净值数据
    """

    fund_code = models.CharField(max_length=10, db_index=True, verbose_name="基金代码")
    nav_date = models.DateField(db_index=True, verbose_name="净值日期")
    unit_nav = models.DecimalField(max_digits=10, decimal_places=4, verbose_name="单位净值")
    accum_nav = models.DecimalField(max_digits=10, decimal_places=4, verbose_name="累计净值")
    daily_return = models.FloatField(null=True, blank=True, verbose_name="日收益率（%）")

    # 元数据
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "fund_net_value"
        verbose_name = "基金净值"
        verbose_name_plural = "基金净值"
        unique_together = [["fund_code", "nav_date"]]
        indexes = [
            models.Index(fields=["fund_code", "-nav_date"]),
            models.Index(fields=["nav_date"]),
        ]
        ordering = ["-nav_date"]
        constraints = FUND_NAV_CONSTRAINTS

    def __str__(self) -> str:
        return f"{self.fund_code} - {self.nav_date}"

    def clean(self) -> None:
        """Validate positive NAV facts and finite daily return."""

        super().clean()
        _validate_code(self.fund_code, field_name="fund_code")
        if not self.unit_nav.is_finite() or self.unit_nav <= 0:
            raise ValidationError({"unit_nav": "单位净值必须为正有限数"})
        if not self.accum_nav.is_finite() or self.accum_nav <= 0:
            raise ValidationError({"accum_nav": "累计净值必须为正有限数"})
        _validate_optional_finite(self.daily_return, field_name="daily_return")

    def _normalize_for_save(self) -> None:
        self.unit_nav = _quantize_decimal(
            self.unit_nav,
            places=4,
            field_name="unit_nav",
        )
        self.accum_nav = _quantize_decimal(
            self.accum_nav,
            places=4,
            field_name="accum_nav",
        )


class FundHoldingModel(ValidatedFundModel):
    """基金持仓表

    存储基金持仓股票信息
    """

    fund_code = models.CharField(max_length=10, db_index=True, verbose_name="基金代码")
    report_date = models.DateField(db_index=True, verbose_name="报告期")
    stock_code = models.CharField(max_length=10, db_index=True, verbose_name="股票代码")
    stock_name = models.CharField(max_length=100, verbose_name="股票名称")
    holding_amount = models.BigIntegerField(null=True, blank=True, verbose_name="持有数量（股）")
    holding_value = models.DecimalField(
        max_digits=20, decimal_places=2, null=True, blank=True, verbose_name="持有市值（元）"
    )
    holding_ratio = models.FloatField(null=True, blank=True, verbose_name="占净值比例（%）")

    # 元数据
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "fund_holding"
        verbose_name = "基金持仓"
        verbose_name_plural = "基金持仓"
        unique_together = [["fund_code", "report_date", "stock_code"]]
        indexes = [
            models.Index(fields=["fund_code", "-report_date"]),
            models.Index(fields=["stock_code", "-report_date"]),
        ]
        ordering = ["-report_date", "-holding_ratio"]
        constraints = FUND_HOLDING_CONSTRAINTS

    def __str__(self) -> str:
        return f"{self.fund_code} - {self.stock_code} - {self.report_date}"

    def clean(self) -> None:
        """Validate nonnegative holdings and bounded portfolio weight."""

        super().clean()
        _validate_code(self.fund_code, field_name="fund_code")
        _validate_code(self.stock_code, field_name="stock_code")
        if self.holding_value is not None and (
            not self.holding_value.is_finite() or self.holding_value < 0
        ):
            raise ValidationError({"holding_value": "持仓市值必须为非负有限数"})
        if self.holding_amount is not None and self.holding_amount < 0:
            raise ValidationError({"holding_amount": "持有数量不能为负数"})
        _validate_optional_finite(self.holding_ratio, field_name="holding_ratio")
        if self.holding_ratio is not None and not 0 <= self.holding_ratio <= 100:
            raise ValidationError({"holding_ratio": "持仓比例必须在 0 至 100 之间"})

    def _normalize_for_save(self) -> None:
        if self.holding_value is not None:
            self.holding_value = _quantize_decimal(
                self.holding_value,
                places=2,
                field_name="holding_value",
            )


class FundSectorAllocationModel(ValidatedFundModel):
    """基金行业配置表

    存储基金的行业配置比例
    """

    fund_code = models.CharField(max_length=10, db_index=True, verbose_name="基金代码")
    report_date = models.DateField(db_index=True, verbose_name="报告期")
    sector_name = models.CharField(max_length=50, verbose_name="行业名称")
    allocation_ratio = models.FloatField(verbose_name="配置比例（%）")

    # 元数据
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "fund_sector_allocation"
        verbose_name = "基金行业配置"
        verbose_name_plural = "基金行业配置"
        unique_together = [["fund_code", "report_date", "sector_name"]]
        indexes = [
            models.Index(fields=["fund_code", "-report_date"]),
            models.Index(fields=["report_date"]),
        ]
        ordering = ["-report_date", "-allocation_ratio"]
        constraints = FUND_SECTOR_CONSTRAINTS

    def __str__(self) -> str:
        return f"{self.fund_code} - {self.sector_name} - {self.report_date}"

    def clean(self) -> None:
        """Validate bounded finite sector allocation."""

        super().clean()
        _validate_code(self.fund_code, field_name="fund_code")
        if not math.isfinite(self.allocation_ratio):
            raise ValidationError({"allocation_ratio": "配置比例必须为有限数"})
        if not 0 <= self.allocation_ratio <= 100:
            raise ValidationError({"allocation_ratio": "配置比例必须在 0 至 100 之间"})


class FundPerformanceModel(ValidatedFundModel):
    """基金业绩指标表

    存储基金的历史业绩指标
    """

    fund_code = models.CharField(max_length=10, db_index=True, verbose_name="基金代码")
    start_date = models.DateField(verbose_name="计算起始日期")
    end_date = models.DateField(db_index=True, verbose_name="计算结束日期")

    # 收益指标
    total_return = models.FloatField(verbose_name="区间收益率（%）")
    annualized_return = models.FloatField(null=True, blank=True, verbose_name="年化收益率（%）")

    # 风险指标
    volatility = models.FloatField(null=True, blank=True, verbose_name="波动率（%）")
    max_drawdown = models.FloatField(null=True, blank=True, verbose_name="最大回撤（%）")

    # 风险调整收益指标
    sharpe_ratio = models.FloatField(null=True, blank=True, verbose_name="夏普比率")
    beta = models.FloatField(null=True, blank=True, verbose_name="贝塔系数")
    alpha = models.FloatField(null=True, blank=True, verbose_name="阿尔法（%）")

    # 元数据
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "fund_performance"
        verbose_name = "基金业绩指标"
        verbose_name_plural = "基金业绩指标"
        unique_together = [["fund_code", "start_date", "end_date"]]
        indexes = [
            models.Index(fields=["fund_code", "-end_date"]),
            models.Index(fields=["end_date"]),
        ]
        ordering = ["-end_date"]
        constraints = FUND_PERFORMANCE_CONSTRAINTS

    def __str__(self) -> str:
        return f"{self.fund_code} - {self.start_date} ~ {self.end_date}"

    def clean(self) -> None:
        """Validate performance window and every floating-point metric."""

        super().clean()
        _validate_code(self.fund_code, field_name="fund_code")
        if self.end_date < self.start_date:
            raise ValidationError({"end_date": "计算结束日期不能早于开始日期"})
        if not math.isfinite(self.total_return):
            raise ValidationError({"total_return": "区间收益率必须为有限数"})
        for field_name in (
            "annualized_return",
            "volatility",
            "max_drawdown",
            "sharpe_ratio",
            "beta",
            "alpha",
        ):
            _validate_optional_finite(getattr(self, field_name), field_name=field_name)
        if self.volatility is not None and self.volatility < 0:
            raise ValidationError({"volatility": "波动率不能为负数"})


# Shared configuration models repatriated from shared.infrastructure.models


class FundTypePreferenceConfigModel(ValidatedFundModel):
    """基金类型偏好配置表"""

    regime = models.CharField(
        max_length=20,
        db_index=True,
        verbose_name="Regime",
        help_text="Recovery/Overheat/Stagflation/Deflation",
    )
    fund_type = models.CharField(max_length=50, verbose_name="基金类型")
    style = models.CharField(
        max_length=50, blank=True, verbose_name="基金风格", help_text="如：成长、价值、平衡、商品等"
    )

    # 元数据
    is_active = models.BooleanField(default=True, verbose_name="是否启用")
    priority = models.IntegerField(default=0, verbose_name="优先级")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "config_fund_type_preference"
        verbose_name = "基金类型偏好配置"
        verbose_name_plural = "基金类型偏好配置"
        unique_together = [["regime", "fund_type", "style"]]
        indexes = [
            models.Index(fields=["regime", "is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.regime} - {self.fund_type} ({self.style})"
