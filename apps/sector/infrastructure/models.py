"""板块分析模块 - ORM 模型定义.

遵循项目架构约束：
- 使用 Django ORM 定义数据表结构
- 包含板块基本信息、板块指数、板块成分股等表
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.base import ModelBase

_REGIMES = frozenset({"Recovery", "Overheat", "Stagflation", "Deflation"})


def _bounded_text(value: object, *, field_name: str, maximum: int) -> str:
    """Normalize one required bounded identifier."""

    if not isinstance(value, str):
        raise ValidationError({field_name: f"{field_name} must be a string"})
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > maximum
        or any(character in normalized for character in "\r\n\x00")
    ):
        raise ValidationError({field_name: f"{field_name} is invalid"})
    return normalized


def _finite_decimal(
    value: object,
    *,
    field_name: str,
    positive: bool,
) -> Decimal:
    """Normalize one finite decimal observation."""

    if isinstance(value, bool):
        raise ValidationError({field_name: f"{field_name} must be a finite number"})
    try:
        normalized = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError({field_name: f"{field_name} must be a finite number"}) from exc
    if not normalized.is_finite() or (normalized <= 0 if positive else normalized < 0):
        qualifier = "positive" if positive else "non-negative"
        raise ValidationError({field_name: f"{field_name} must be finite and {qualifier}"})
    return normalized


def _finite_float(
    value: object,
    *,
    field_name: str,
    nonnegative: bool = False,
) -> float:
    """Normalize one finite floating-point observation."""

    if isinstance(value, bool) or not isinstance(value, int | float | Decimal):
        raise ValidationError({field_name: f"{field_name} must be a finite number"})
    normalized = float(value)
    if not math.isfinite(normalized) or (nonnegative and normalized < 0):
        qualifier = " finite and non-negative" if nonnegative else " finite"
        raise ValidationError({field_name: f"{field_name} must be{qualifier}"})
    return normalized


class ValidatedSectorModel(models.Model):
    """Run model contracts for every ordinary ORM write."""

    class Meta:
        abstract = True

    def _validate_raw_values(self) -> None:
        """Reject raw values Django fields would otherwise coerce unsafely."""

    def save(
        self,
        *,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Validate raw and normalized values before persistence."""

        self._validate_raw_values()
        # Let database uniqueness remain the race-safe source of truth.
        self.full_clean(validate_unique=False, validate_constraints=False)
        super().save(
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=update_fields,
        )


class SectorInfoModel(ValidatedSectorModel):
    """板块基本信息表

    存储申万行业分类信息（一级、二级、三级）
    """

    sector_code = models.CharField(
        max_length=10, unique=True, db_index=True, verbose_name="板块代码"
    )
    sector_name = models.CharField(max_length=50, verbose_name="板块名称")
    level = models.CharField(
        max_length=10,
        choices=[
            ("SW1", "申万一级"),
            ("SW2", "申万二级"),
            ("SW3", "申万三级"),
        ],
        db_index=True,
        verbose_name="板块级别",
    )
    parent_code = models.CharField(
        max_length=10, null=True, blank=True, verbose_name="父级板块代码"
    )

    # 元数据
    is_active = models.BooleanField(default=True, verbose_name="是否活跃")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "sector_info"
        verbose_name = "板块基本信息"
        verbose_name_plural = "板块基本信息"
        indexes = [
            models.Index(fields=["sector_code"]),
            models.Index(fields=["level"]),
            models.Index(fields=["parent_code"]),
        ]
        ordering = ["level", "sector_code"]

    def clean(self) -> None:
        """Validate sector identity and hierarchy invariants."""

        super().clean()
        self.sector_code = _bounded_text(self.sector_code, field_name="sector_code", maximum=10)
        self.sector_name = _bounded_text(self.sector_name, field_name="sector_name", maximum=50)
        self.parent_code = self.parent_code.strip() if self.parent_code else None
        if self.level == "SW1" and self.parent_code is not None:
            raise ValidationError({"parent_code": "SW1 sectors cannot have a parent"})
        if self.level in {"SW2", "SW3"}:
            if self.parent_code is None:
                raise ValidationError({"parent_code": f"{self.level} sectors require a parent"})
            self.parent_code = _bounded_text(self.parent_code, field_name="parent_code", maximum=10)
            if self.parent_code == self.sector_code:
                raise ValidationError({"parent_code": "a sector cannot be its own parent"})

    def __str__(self) -> str:
        return f"{self.sector_code} - {self.sector_name} ({self.get_level_display()})"


class SectorIndexModel(ValidatedSectorModel):
    """板块指数日线数据表

    存储申万行业指数的日线行情数据
    """

    sector_code = models.CharField(max_length=10, db_index=True, verbose_name="板块代码")
    trade_date = models.DateField(db_index=True, verbose_name="交易日期")

    # 价格数据
    open_price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="开盘点位")
    high = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="最高点位")
    low = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="最低点位")
    close = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="收盘点位")

    # 成交数据
    volume = models.BigIntegerField(verbose_name="成交量（手）")
    amount = models.DecimalField(max_digits=20, decimal_places=2, verbose_name="成交额（元）")
    turnover_rate = models.FloatField(null=True, blank=True, verbose_name="换手率（%）")

    # 涨跌幅
    change_pct = models.FloatField(verbose_name="涨跌幅（%）")

    # 元数据
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "sector_index_daily"
        verbose_name = "板块指数日线"
        verbose_name_plural = "板块指数日线"
        unique_together = [["sector_code", "trade_date"]]
        indexes = [
            models.Index(fields=["sector_code", "trade_date"]),
            models.Index(fields=["trade_date"]),
        ]
        ordering = ["-trade_date"]

    def _validate_raw_values(self) -> None:
        """Reject booleans before numeric model fields coerce them."""

        for field_name in (
            "open_price",
            "high",
            "low",
            "close",
            "volume",
            "amount",
            "turnover_rate",
            "change_pct",
        ):
            if isinstance(getattr(self, field_name), bool):
                raise ValidationError({field_name: f"{field_name} cannot be a boolean"})

    def clean(self) -> None:
        """Validate one finite and internally consistent daily index bar."""

        super().clean()
        self.sector_code = _bounded_text(self.sector_code, field_name="sector_code", maximum=10)
        self.open_price = _finite_decimal(self.open_price, field_name="open_price", positive=True)
        self.high = _finite_decimal(self.high, field_name="high", positive=True)
        self.low = _finite_decimal(self.low, field_name="low", positive=True)
        self.close = _finite_decimal(self.close, field_name="close", positive=True)
        if self.low > min(self.open_price, self.close) or self.high < max(
            self.open_price, self.close
        ):
            raise ValidationError("OHLC prices are internally inconsistent")
        if isinstance(self.volume, bool) or not isinstance(self.volume, int) or self.volume < 0:
            raise ValidationError({"volume": "volume must be a non-negative integer"})
        self.amount = _finite_decimal(self.amount, field_name="amount", positive=False)
        self.change_pct = _finite_float(self.change_pct, field_name="change_pct")
        if self.turnover_rate is not None:
            self.turnover_rate = _finite_float(
                self.turnover_rate,
                field_name="turnover_rate",
                nonnegative=True,
            )

    def __str__(self) -> str:
        return f"{self.sector_code} - {self.trade_date}"


class SectorConstituentModel(ValidatedSectorModel):
    """板块成分股关系表

    存储板块与股票的从属关系
    """

    sector_code = models.CharField(max_length=10, db_index=True, verbose_name="板块代码")
    stock_code = models.CharField(max_length=10, db_index=True, verbose_name="股票代码")
    enter_date = models.DateField(verbose_name="纳入日期")
    exit_date = models.DateField(null=True, blank=True, verbose_name="剔除日期")

    # 元数据
    is_current = models.BooleanField(default=True, verbose_name="是否当前成分股")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "sector_constituent"
        verbose_name = "板块成分股"
        verbose_name_plural = "板块成分股"
        indexes = [
            models.Index(fields=["sector_code", "is_current"]),
            models.Index(fields=["stock_code", "is_current"]),
        ]
        ordering = ["sector_code", "-enter_date"]

    def clean(self) -> None:
        """Validate constituent identity and membership interval."""

        super().clean()
        self.sector_code = _bounded_text(self.sector_code, field_name="sector_code", maximum=10)
        self.stock_code = _bounded_text(self.stock_code, field_name="stock_code", maximum=10)
        if self.exit_date is not None and self.exit_date < self.enter_date:
            raise ValidationError({"exit_date": "exit_date cannot precede enter_date"})
        if self.is_current != (self.exit_date is None):
            raise ValidationError({"is_current": "current membership must not have an exit date"})

    def __str__(self) -> str:
        return f"{self.sector_code} - {self.stock_code}"


class SectorRelativeStrengthModel(ValidatedSectorModel):
    """板块相对强弱指标表

    存储板块相对于大盘的相对强弱指标
    """

    sector_code = models.CharField(max_length=10, db_index=True, verbose_name="板块代码")
    trade_date = models.DateField(db_index=True, verbose_name="交易日期")

    # 相对强弱指标
    relative_strength = models.FloatField(verbose_name="相对强弱（板块收益率 - 大盘收益率）")
    momentum = models.FloatField(verbose_name="动量（N日累计收益率，%）")
    momentum_window = models.IntegerField(default=20, verbose_name="动量计算窗口")
    beta = models.FloatField(null=True, blank=True, verbose_name="贝塔系数")

    # 元数据
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "sector_relative_strength"
        verbose_name = "板块相对强弱"
        verbose_name_plural = "板块相对强弱"
        unique_together = [["sector_code", "trade_date"]]
        indexes = [
            models.Index(fields=["sector_code", "-trade_date"]),
            models.Index(fields=["trade_date"]),
        ]
        ordering = ["-trade_date"]

    def _validate_raw_values(self) -> None:
        """Reject booleans before numeric model fields coerce them."""

        for field_name in ("relative_strength", "momentum", "momentum_window", "beta"):
            if isinstance(getattr(self, field_name), bool):
                raise ValidationError({field_name: f"{field_name} cannot be a boolean"})

    def clean(self) -> None:
        """Validate finite relative-strength evidence."""

        super().clean()
        self.sector_code = _bounded_text(self.sector_code, field_name="sector_code", maximum=10)
        self.relative_strength = _finite_float(
            self.relative_strength, field_name="relative_strength"
        )
        self.momentum = _finite_float(self.momentum, field_name="momentum")
        if (
            isinstance(self.momentum_window, bool)
            or not isinstance(self.momentum_window, int)
            or not 1 <= self.momentum_window <= 10_000
        ):
            raise ValidationError(
                {"momentum_window": "momentum_window must be between 1 and 10000"}
            )
        if self.beta is not None:
            self.beta = _finite_float(self.beta, field_name="beta")

    def __str__(self) -> str:
        return f"{self.sector_code} - {self.trade_date}"


# Shared configuration models repatriated from shared.infrastructure.models


class SectorPreferenceConfigModel(ValidatedSectorModel):
    """板块偏好配置表"""

    regime = models.CharField(
        max_length=20,
        db_index=True,
        verbose_name="Regime",
        help_text="Recovery/Overheat/Stagflation/Deflation",
    )
    sector_name = models.CharField(max_length=50, verbose_name="板块名称")
    weight = models.FloatField(
        default=0.5, verbose_name="权重（0.0-1.0）", help_text="1.0 表示最强偏好，0.0 表示无偏好"
    )

    # 元数据
    is_active = models.BooleanField(default=True, verbose_name="是否启用")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "config_sector_preference"
        verbose_name = "板块偏好配置"
        verbose_name_plural = "板块偏好配置"
        unique_together = [["regime", "sector_name"]]
        indexes = [
            models.Index(fields=["regime", "is_active"]),
        ]

    def _validate_raw_values(self) -> None:
        """Reject boolean weights before FloatField coercion."""

        if isinstance(self.weight, bool):
            raise ValidationError({"weight": "weight cannot be a boolean"})

    def clean(self) -> None:
        """Validate one governed regime-sector preference."""

        super().clean()
        self.regime = _bounded_text(self.regime, field_name="regime", maximum=20)
        if self.regime not in _REGIMES:
            raise ValidationError({"regime": "regime is unsupported"})
        self.sector_name = _bounded_text(self.sector_name, field_name="sector_name", maximum=50)
        self.weight = _finite_float(self.weight, field_name="weight", nonnegative=True)
        if self.weight > 1:
            raise ValidationError({"weight": "weight must be between 0 and 1"})

    def __str__(self) -> str:
        return f"{self.regime} - {self.sector_name} (权重: {self.weight})"
