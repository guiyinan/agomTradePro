"""
ORM Models for Filter Operations.

Django models for persisting filter results and Kalman states.
"""

from django.db import models

from apps.filter.domain.entities import FilterType


class FilterResultModel(models.Model):
    """滤波结果 ORM 模型"""

    FILTER_TYPE_CHOICES = [
        (FilterType.HP.value, 'HP Filter'),
        (FilterType.KALMAN.value, 'Kalman Filter'),
    ]

    # 唯一标识
    id = models.BigAutoField(primary_key=True)

    # 关联的宏观数据
    indicator_code = models.CharField(
        max_length=50,
        db_index=True,
        help_text="指标代码 (e.g., PMI, CPI)"
    )
    date = models.DateField(db_index=True, help_text="数据日期")

    # 滤波器信息
    filter_type = models.CharField(
        max_length=20,
        choices=FILTER_TYPE_CHOICES,
        help_text="滤波器类型"
    )
    params = models.JSONField(default=dict, help_text="滤波参数")

    # 结果值
    original_value = models.DecimalField(
        max_digits=20,
        decimal_places=6,
        help_text="原始值"
    )
    filtered_value = models.DecimalField(
        max_digits=20,
        decimal_places=6,
        help_text="滤波后值（趋势）"
    )
    cycle_value = models.DecimalField(
        max_digits=20,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="周期分量（原始-趋势）"
    )

    # Kalman 特有字段
    trend_slope = models.DecimalField(
        max_digits=20,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="趋势斜率（仅 Kalman）"
    )

    # 元数据
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'filter_result'
        unique_together = [
            ['indicator_code', 'date', 'filter_type']
        ]
        ordering = ['-date', 'indicator_code']
        indexes = [
            models.Index(fields=['indicator_code', '-date']),
            models.Index(fields=['filter_type']),
            models.Index(fields=['-date']),
        ]
        verbose_name = "滤波结果"
        verbose_name_plural = "滤波结果"

    def __str__(self):
        return f"{self.indicator_code}@{self.date} ({self.filter_type}) = {self.filtered_value}"


class KalmanStateModel(models.Model):
    """Kalman 滤波器状态持久化模型"""

    id = models.BigAutoField(primary_key=True)

    indicator_code = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        help_text="指标代码"
    )

    # 滤波器状态
    level = models.DecimalField(max_digits=20, decimal_places=6, help_text="水平值")
    slope = models.DecimalField(max_digits=20, decimal_places=6, help_text="斜率值")
    level_variance = models.DecimalField(
        max_digits=20,
        decimal_places=10,
        help_text="水平方差"
    )
    slope_variance = models.DecimalField(
        max_digits=20,
        decimal_places=10,
        help_text="斜率方差"
    )
    level_slope_cov = models.DecimalField(
        max_digits=20,
        decimal_places=10,
        help_text="水平-斜率协方差"
    )

    # 元数据
    params = models.JSONField(default=dict, help_text="使用的滤波参数")
    last_observed_date = models.DateField(help_text="最后观测日期")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'kalman_filter_state'
        ordering = ['-updated_at']
        verbose_name = "Kalman 滤波器状态"
        verbose_name_plural = "Kalman 滤波器状态"

    def __str__(self):
        return f"KalmanState[{self.indicator_code}] level={self.level} slope={self.slope}"

    def to_domain_state(self):
        """转换为 Domain 层的 KalmanFilterState"""
        from apps.filter.domain.entities import KalmanFilterState
        return KalmanFilterState(
            level=float(self.level),
            slope=float(self.slope),
            level_variance=float(self.level_variance),
            slope_variance=float(self.slope_variance),
            level_slope_cov=float(self.level_slope_cov),
            updated_at=self.last_observed_date,
        )

    @classmethod
    def from_domain_state(cls, domain_state, indicator_code: str, params: dict):
        """从 Domain 层状态创建 ORM 模型"""
        return cls(
            indicator_code=indicator_code,
            level=domain_state.level,
            slope=domain_state.slope,
            level_variance=domain_state.level_variance,
            slope_variance=domain_state.slope_variance,
            level_slope_cov=domain_state.level_slope_cov,
            last_observed_date=domain_state.updated_at,
            params=params,
        )


class FilterConfig(models.Model):
    """滤波器配置模型"""

    id = models.BigAutoField(primary_key=True)

    indicator_code = models.CharField(
        max_length=50,
        unique=True,
        help_text="指标代码"
    )

    # HP 滤波配置
    hp_enabled = models.BooleanField(default=True, help_text="是否启用 HP 滤波")
    hp_lambda = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=129600,
        help_text="HP 滤波 lambda 参数"
    )

    # Kalman 滤波配置
    kalman_enabled = models.BooleanField(default=True, help_text="是否启用 Kalman 滤波")
    kalman_level_variance = models.DecimalField(
        max_digits=20,
        decimal_places=6,
        default=0.05,
        help_text="Kalman 水平方差"
    )
    kalman_slope_variance = models.DecimalField(
        max_digits=20,
        decimal_places=6,
        default=0.005,
        help_text="Kalman 斜率方差"
    )
    kalman_observation_variance = models.DecimalField(
        max_digits=20,
        decimal_places=6,
        default=0.5,
        help_text="Kalman 观测方差"
    )

    # 元数据
    description = models.TextField(blank=True, help_text="描述")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'filter_config'
        verbose_name = "滤波器配置"
        verbose_name_plural = "滤波器配置"

    def __str__(self):
        return f"FilterConfig[{self.indicator_code}]"

# Shared configuration models repatriated from shared.infrastructure.models

class FilterParameterConfigModel(models.Model):
    """滤波参数配置表"""

    FILTER_TYPE_CHOICES = [
        ('hp', 'HP 滤波'),
        ('kalman', 'Kalman 滤波'),
        ('ma', '移动平均'),
        ('other', '其他'),
    ]

    key = models.CharField(
        max_length=100,
        unique=True,
        verbose_name="参数键",
        help_text="如 hp_monthly, kalman_macro 等"
    )
    name = models.CharField(max_length=100, verbose_name="参数名称")
    filter_type = models.CharField(
        max_length=20,
        choices=FILTER_TYPE_CHOICES,
        verbose_name="滤波类型"
    )

    # 滤波参数
    parameters = models.JSONField(
        verbose_name="滤波参数",
        help_text="如 {'lambda': 129600} 或 {'level_variance': 0.05}"
    )

    # 适用场景
    data_frequency = models.CharField(
        max_length=10,
        blank=True,
        verbose_name="数据频率",
        help_text="D/W/M/Q/Y，留空表示不限"
    )
    indicator_category = models.CharField(
        max_length=20,
        blank=True,
        verbose_name="适用指标分类",
        help_text="growth/inflation/等"
    )

    is_active = models.BooleanField(default=True, verbose_name="是否启用")
    description = models.TextField(blank=True, verbose_name="描述")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = 'filter_parameter_config'
        verbose_name = "滤波参数配置"
        verbose_name_plural = "滤波参数配置"

    def __str__(self):
        return f"{self.name} ({self.filter_type})"

