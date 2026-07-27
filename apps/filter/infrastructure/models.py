"""
ORM Models for Filter Operations.

Django models for persisting filter results and Kalman states.
"""

from decimal import Decimal, InvalidOperation
from typing import Self

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.filter.domain.entities import (
    FilterType,
    HPFilterParams,
    KalmanFilterParams,
    KalmanFilterState,
)


def _finite_decimal(value: object) -> Decimal | None:
    """Narrow a dynamic model value to a finite non-boolean Decimal."""

    if isinstance(value, bool):
        return None
    try:
        narrowed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return narrowed if narrowed.is_finite() else None


class FilterResultModel(models.Model):
    """滤波结果 ORM 模型"""

    FILTER_TYPE_CHOICES = [
        (FilterType.HP.value, "HP Filter"),
        (FilterType.KALMAN.value, "Kalman Filter"),
    ]

    # 唯一标识
    id = models.BigAutoField(primary_key=True)

    # 关联的宏观数据
    indicator_code = models.CharField(
        max_length=50, db_index=True, help_text="指标代码 (e.g., PMI, CPI)"
    )
    date = models.DateField(db_index=True, help_text="数据日期")

    # 滤波器信息
    filter_type = models.CharField(
        max_length=20, choices=FILTER_TYPE_CHOICES, help_text="滤波器类型"
    )
    params = models.JSONField(default=dict, help_text="滤波参数")

    # 结果值
    original_value = models.DecimalField(max_digits=20, decimal_places=6, help_text="原始值")
    filtered_value = models.DecimalField(
        max_digits=20, decimal_places=6, help_text="滤波后值（趋势）"
    )
    cycle_value = models.DecimalField(
        max_digits=20, decimal_places=6, null=True, blank=True, help_text="周期分量（原始-趋势）"
    )

    # Kalman 特有字段
    trend_slope = models.DecimalField(
        max_digits=20, decimal_places=6, null=True, blank=True, help_text="趋势斜率（仅 Kalman）"
    )

    # 元数据
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "filter_result"
        unique_together = [["indicator_code", "date", "filter_type"]]
        ordering = ["-date", "indicator_code"]
        indexes = [
            models.Index(fields=["indicator_code", "-date"]),
            models.Index(fields=["filter_type"]),
            models.Index(fields=["-date"]),
        ]
        verbose_name = "滤波结果"
        verbose_name_plural = "滤波结果"

    def __str__(self) -> str:
        return f"{self.indicator_code}@{self.date} ({self.filter_type}) = {self.filtered_value}"


class KalmanStateModel(models.Model):
    """Kalman 滤波器状态持久化模型"""

    id = models.BigAutoField(primary_key=True)

    indicator_code = models.CharField(
        max_length=50, unique=True, db_index=True, help_text="指标代码"
    )

    # 滤波器状态
    level = models.DecimalField(max_digits=20, decimal_places=6, help_text="水平值")
    slope = models.DecimalField(max_digits=20, decimal_places=6, help_text="斜率值")
    level_variance = models.DecimalField(max_digits=20, decimal_places=10, help_text="水平方差")
    slope_variance = models.DecimalField(max_digits=20, decimal_places=10, help_text="斜率方差")
    level_slope_cov = models.DecimalField(
        max_digits=20, decimal_places=10, help_text="水平-斜率协方差"
    )

    # 元数据
    params = models.JSONField(default=dict, help_text="使用的滤波参数")
    last_observed_date = models.DateField(help_text="最后观测日期")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "kalman_filter_state"
        ordering = ["-updated_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(level_variance__gte=0),
                name="kalman_state_level_variance_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(slope_variance__gte=0),
                name="kalman_state_slope_variance_nonnegative",
            ),
        ]
        verbose_name = "Kalman 滤波器状态"
        verbose_name_plural = "Kalman 滤波器状态"

    def __str__(self) -> str:
        return f"KalmanState[{self.indicator_code}] level={self.level} slope={self.slope}"

    def clean(self) -> None:
        """Reject non-finite states and negative covariance variances."""

        super().clean()
        errors: dict[str, str] = {}
        finite_fields = (
            "level",
            "slope",
            "level_variance",
            "slope_variance",
            "level_slope_cov",
        )
        for field_name in finite_fields:
            value = _finite_decimal(getattr(self, field_name))
            if value is None:
                errors[field_name] = "必须为有限数"
        for field_name in ("level_variance", "slope_variance"):
            value = _finite_decimal(getattr(self, field_name))
            if value is not None and value < 0:
                errors[field_name] = "必须大于或等于 0"
        if errors:
            raise ValidationError(errors)

    def to_domain_state(self) -> KalmanFilterState:
        """转换为 Domain 层的 KalmanFilterState"""

        return KalmanFilterState(
            level=float(self.level),
            slope=float(self.slope),
            level_variance=float(self.level_variance),
            slope_variance=float(self.slope_variance),
            level_slope_cov=float(self.level_slope_cov),
            updated_at=self.last_observed_date,
        )

    @classmethod
    def from_domain_state(
        cls,
        domain_state: KalmanFilterState,
        indicator_code: str,
        params: dict[str, object],
    ) -> Self:
        """Build and validate an ORM state from its Domain representation."""

        instance = cls(
            indicator_code=indicator_code,
            level=Decimal(str(domain_state.level)),
            slope=Decimal(str(domain_state.slope)),
            level_variance=Decimal(str(domain_state.level_variance)),
            slope_variance=Decimal(str(domain_state.slope_variance)),
            level_slope_cov=Decimal(str(domain_state.level_slope_cov)),
            last_observed_date=domain_state.updated_at,
            params=dict(params),
        )
        instance.full_clean()
        return instance


class FilterConfig(models.Model):
    """滤波器配置模型"""

    id = models.BigAutoField(primary_key=True)

    indicator_code = models.CharField(max_length=50, unique=True, help_text="指标代码")

    # HP 滤波配置
    hp_enabled = models.BooleanField(default=True, help_text="是否启用 HP 滤波")
    hp_lambda = models.DecimalField(
        max_digits=20, decimal_places=2, default=Decimal("129600"), help_text="HP 滤波 lambda 参数"
    )

    # Kalman 滤波配置
    kalman_enabled = models.BooleanField(default=True, help_text="是否启用 Kalman 滤波")
    kalman_level_variance = models.DecimalField(
        max_digits=20, decimal_places=6, default=Decimal("0.05"), help_text="Kalman 水平方差"
    )
    kalman_slope_variance = models.DecimalField(
        max_digits=20, decimal_places=6, default=Decimal("0.005"), help_text="Kalman 斜率方差"
    )
    kalman_observation_variance = models.DecimalField(
        max_digits=20, decimal_places=6, default=Decimal("0.5"), help_text="Kalman 观测方差"
    )

    # 元数据
    description = models.TextField(blank=True, help_text="描述")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "filter_config"
        constraints = [
            models.CheckConstraint(
                condition=Q(hp_lambda__gte=0),
                name="filter_config_hp_lambda_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(kalman_level_variance__gte=0),
                name="filter_config_level_variance_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(kalman_slope_variance__gte=0),
                name="filter_config_slope_variance_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(kalman_observation_variance__gt=0),
                name="filter_config_observation_variance_positive",
            ),
        ]
        verbose_name = "滤波器配置"
        verbose_name_plural = "滤波器配置"

    def __str__(self) -> str:
        return f"FilterConfig[{self.indicator_code}]"

    def clean(self) -> None:
        """Apply Domain-equivalent validation to persisted filter parameters."""

        super().clean()
        errors: dict[str, str] = {}
        hp_lambda = _finite_decimal(self.hp_lambda)
        level_variance = _finite_decimal(self.kalman_level_variance)
        slope_variance = _finite_decimal(self.kalman_slope_variance)
        observation_variance = _finite_decimal(self.kalman_observation_variance)

        if hp_lambda is None or hp_lambda < 0:
            errors["hp_lambda"] = "必须为大于或等于 0 的有限数"
        if level_variance is None or level_variance < 0:
            errors["kalman_level_variance"] = "必须为大于或等于 0 的有限数"
        if slope_variance is None or slope_variance < 0:
            errors["kalman_slope_variance"] = "必须为大于或等于 0 的有限数"
        if observation_variance is None or observation_variance <= 0:
            errors["kalman_observation_variance"] = "必须为正有限数"

        if not errors:
            assert hp_lambda is not None
            assert level_variance is not None
            assert slope_variance is not None
            assert observation_variance is not None
            HPFilterParams(lamb=float(hp_lambda))
            KalmanFilterParams(
                level_variance=float(level_variance),
                slope_variance=float(slope_variance),
                observation_variance=float(observation_variance),
            )
        if errors:
            raise ValidationError(errors)


# Shared configuration models repatriated from shared.infrastructure.models


class FilterParameterConfigModel(models.Model):
    """滤波参数配置表"""

    FILTER_TYPE_CHOICES = [
        ("hp", "HP 滤波"),
        ("kalman", "Kalman 滤波"),
        ("ma", "移动平均"),
        ("other", "其他"),
    ]

    key = models.CharField(
        max_length=100,
        unique=True,
        verbose_name="参数键",
        help_text="如 hp_monthly, kalman_macro 等",
    )
    name = models.CharField(max_length=100, verbose_name="参数名称")
    filter_type = models.CharField(
        max_length=20, choices=FILTER_TYPE_CHOICES, verbose_name="滤波类型"
    )

    # 滤波参数
    parameters = models.JSONField(
        verbose_name="滤波参数", help_text="如 {'lambda': 129600} 或 {'level_variance': 0.05}"
    )

    # 适用场景
    data_frequency = models.CharField(
        max_length=10, blank=True, verbose_name="数据频率", help_text="D/W/M/Q/Y，留空表示不限"
    )
    indicator_category = models.CharField(
        max_length=20, blank=True, verbose_name="适用指标分类", help_text="growth/inflation/等"
    )

    is_active = models.BooleanField(default=True, verbose_name="是否启用")
    description = models.TextField(blank=True, verbose_name="描述")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = "filter_parameter_config"
        verbose_name = "滤波参数配置"
        verbose_name_plural = "滤波参数配置"

    def __str__(self) -> str:
        return f"{self.name} ({self.filter_type})"
