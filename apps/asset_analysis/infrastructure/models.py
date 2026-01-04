"""
资产分析模块 - Infrastructure 层数据模型

本模块包含 Django ORM 模型定义。
"""

from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from datetime import datetime


class WeightConfigModel(models.Model):
    """
    多维度评分权重配置表

    存储不同资产类型、市场条件下的权重配置。
    """

    name = models.CharField(
        max_length=50,
        unique=True,
        verbose_name="配置名称",
        help_text="如: default, policy_crisis, sentiment_extreme"
    )

    description = models.TextField(
        blank=True,
        null=True,
        verbose_name="配置描述"
    )

    # 四大维度权重
    regime_weight = models.FloatField(
        default=0.40,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
        verbose_name="Regime 权重"
    )

    policy_weight = models.FloatField(
        default=0.25,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
        verbose_name="Policy 权重"
    )

    sentiment_weight = models.FloatField(
        default=0.20,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
        verbose_name="Sentiment 权重"
    )

    signal_weight = models.FloatField(
        default=0.15,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
        verbose_name="Signal 权重"
    )

    # 适用条件（可选）
    asset_type = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        verbose_name="资产类型",
        help_text="为空表示通用配置"
    )

    market_condition = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        verbose_name="市场状态",
        help_text="如: crisis, extreme_sentiment"
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name="是否激活"
    )

    priority = models.IntegerField(
        default=0,
        verbose_name="优先级",
        help_text="数字越大优先级越高"
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="创建时间"
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="更新时间"
    )

    class Meta:
        db_table = "asset_weight_config"
        verbose_name = "权重配置"
        verbose_name_plural = "权重配置"
        ordering = ["-priority", "-created_at"]

    def __str__(self):
        return f"{self.name} (R={self.regime_weight:.2f}, P={self.policy_weight:.2f})"

    def clean(self):
        """验证权重总和"""
        from django.core.exceptions import ValidationError

        total = (
            self.regime_weight +
            self.policy_weight +
            self.sentiment_weight +
            self.signal_weight
        )

        if abs(total - 1.0) > 0.01:
            raise ValidationError(f"权重总和必须为1.0，当前为 {total:.4f}")

    def save(self, *args, **kwargs):
        """保存前验证"""
        self.full_clean()
        super().save(*args, **kwargs)


class AssetScoreCache(models.Model):
    """
    资产评分缓存表

    缓存资产评分结果，避免重复计算。
    """

    asset_type = models.CharField(
        max_length=20,
        db_index=True,
        verbose_name="资产类型"
    )

    asset_code = models.CharField(
        max_length=20,
        db_index=True,
        verbose_name="资产代码"
    )

    asset_name = models.CharField(
        max_length=100,
        verbose_name="资产名称"
    )

    score_date = models.DateField(
        db_index=True,
        verbose_name="评分日期"
    )

    # 评分上下文
    regime = models.CharField(
        max_length=20,
        verbose_name="Regime"
    )

    policy_level = models.CharField(
        max_length=2,
        verbose_name="政策档位"
    )

    sentiment_index = models.FloatField(
        verbose_name="情绪指数"
    )

    # 各维度得分
    regime_score = models.FloatField(
        default=0.0,
        verbose_name="Regime 得分"
    )

    policy_score = models.FloatField(
        default=0.0,
        verbose_name="Policy 得分"
    )

    sentiment_score = models.FloatField(
        default=0.0,
        verbose_name="Sentiment 得分"
    )

    signal_score = models.FloatField(
        default=0.0,
        verbose_name="Signal 得分"
    )

    # 综合得分
    total_score = models.FloatField(
        default=0.0,
        db_index=True,
        verbose_name="综合得分"
    )

    rank = models.IntegerField(
        default=0,
        verbose_name="排名"
    )

    # 推荐信息
    allocation_percent = models.FloatField(
        default=0.0,
        verbose_name="推荐比例(%)"
    )

    risk_level = models.CharField(
        max_length=20,
        default="未知",
        verbose_name="风险等级"
    )

    # 自定义维度得分（JSON）
    custom_scores = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="自定义得分"
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="创建时间"
    )

    class Meta:
        db_table = "asset_score_cache"
        verbose_name = "资产评分缓存"
        verbose_name_plural = "资产评分缓存"
        unique_together = [("asset_type", "asset_code", "score_date")]
        ordering = ["-score_date", "-total_score"]
        indexes = [
            models.Index(fields=["score_date", "total_score"]),
        ]

    def __str__(self):
        return f"{self.asset_code} - {self.score_date} - {self.total_score:.1f}"


class AssetScoringLog(models.Model):
    """
    资产评分日志表

    记录每次资产评分的详细信息，用于追溯和调试。
    """

    # 请求信息
    asset_type = models.CharField(
        max_length=20,
        db_index=True,
        verbose_name="资产类型"
    )

    request_source = models.CharField(
        max_length=50,
        verbose_name="请求来源",
        help_text="如: fund_dashboard, equity_screen, api_call"
    )

    user_id = models.IntegerField(
        null=True,
        blank=True,
        verbose_name="用户ID"
    )

    # 评分上下文
    regime = models.CharField(
        max_length=20,
        verbose_name="Regime"
    )

    policy_level = models.CharField(
        max_length=2,
        verbose_name="政策档位"
    )

    sentiment_index = models.FloatField(
        verbose_name="情绪指数"
    )

    active_signals_count = models.IntegerField(
        default=0,
        verbose_name="激活信号数"
    )

    # 权重配置
    weight_config_name = models.CharField(
        max_length=50,
        verbose_name="权重配置名称"
    )

    regime_weight = models.FloatField(
        verbose_name="Regime 权重"
    )

    policy_weight = models.FloatField(
        verbose_name="Policy 权重"
    )

    sentiment_weight = models.FloatField(
        verbose_name="Sentiment 权重"
    )

    signal_weight = models.FloatField(
        verbose_name="Signal 权重"
    )

    # 筛选条件（JSON）
    filters = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="筛选条件"
    )

    # 结果统计
    total_assets = models.IntegerField(
        default=0,
        verbose_name="总资产数"
    )

    scored_assets = models.IntegerField(
        default=0,
        verbose_name="已评分资产数"
    )

    filtered_assets = models.IntegerField(
        default=0,
        verbose_name="筛选后资产数"
    )

    # 性能指标
    execution_time_ms = models.IntegerField(
        null=True,
        blank=True,
        verbose_name="执行时间(毫秒)"
    )

    cache_hit = models.BooleanField(
        default=False,
        verbose_name="是否命中缓存"
    )

    # 状态
    status = models.CharField(
        max_length=20,
        choices=[
            ('success', '成功'),
            ('partial_success', '部分成功'),
            ('failed', '失败'),
        ],
        default='success',
        verbose_name="状态"
    )

    error_message = models.TextField(
        blank=True,
        null=True,
        verbose_name="错误信息"
    )

    # 元信息
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        verbose_name="创建时间"
    )

    class Meta:
        db_table = "asset_scoring_log"
        verbose_name = "资产评分日志"
        verbose_name_plural = "资产评分日志"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["-created_at"]),
            models.Index(fields=["asset_type"]),
            models.Index(fields=["status"]),
            models.Index(fields=["request_source"]),
        ]

    def __str__(self):
        return f"{self.asset_type} - {self.created_at} - {self.status}"


class AssetAnalysisAlert(models.Model):
    """
    资产分析告警表

    存储资产分析系统产生的异常告警。
    """

    # 告警级别
    SEVERITY_LEVELS = [
        ('info', '信息'),
        ('warning', '警告'),
        ('error', '错误'),
        ('critical', '严重'),
    ]

    # 告警类型
    ALERT_TYPES = [
        ('scoring_error', '评分错误'),
        ('weight_config_error', '权重配置错误'),
        ('data_quality_issue', '数据质量问题'),
        ('performance_issue', '性能问题'),
        ('api_failure', 'API 调用失败'),
        ('validation_error', '验证错误'),
    ]

    severity = models.CharField(
        max_length=20,
        choices=SEVERITY_LEVELS,
        db_index=True,
        verbose_name="严重程度"
    )

    alert_type = models.CharField(
        max_length=50,
        choices=ALERT_TYPES,
        db_index=True,
        verbose_name="告警类型"
    )

    title = models.CharField(
        max_length=200,
        verbose_name="告警标题"
    )

    message = models.TextField(
        verbose_name="告警消息"
    )

    # 关联信息
    asset_type = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        verbose_name="相关资产类型"
    )

    asset_code = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        verbose_name="相关资产代码"
    )

    # 上下文信息（JSON）
    context = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="上下文信息",
        help_text="存储额外的调试信息"
    )

    # 堆栈跟踪
    stack_trace = models.TextField(
        blank=True,
        null=True,
        verbose_name="堆栈跟踪"
    )

    # 状态
    is_resolved = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name="是否已解决"
    )

    resolved_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name="解决时间"
    )

    resolved_by = models.IntegerField(
        blank=True,
        null=True,
        verbose_name="解决人ID"
    )

    resolution_notes = models.TextField(
        blank=True,
        null=True,
        verbose_name="解决备注"
    )

    # 元信息
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        verbose_name="创建时间"
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="更新时间"
    )

    class Meta:
        db_table = "asset_analysis_alert"
        verbose_name = "资产分析告警"
        verbose_name_plural = "资产分析告警"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["-created_at"]),
            models.Index(fields=["severity", "is_resolved"]),
            models.Index(fields=["alert_type"]),
        ]

    def __str__(self):
        return f"[{self.severity.upper()}] {self.title}"


class AssetPoolEntry(models.Model):
    """
    资产池条目表

    存储资产在各个资产池中的状态。
    """

    # 资产池类型
    POOL_TYPE_CHOICES = [
        ('investable', '可投池'),
        ('prohibited', '禁投池'),
        ('watch', '观察池'),
        ('candidate', '候选池'),
    ]

    # 资产类别
    ASSET_CATEGORY_CHOICES = [
        ('equity', '股票'),
        ('fund', '基金'),
        ('bond', '债券'),
        ('wealth', '理财'),
        ('commodity', '商品'),
        ('index', '指数'),
    ]

    # 资产标识
    asset_category = models.CharField(
        max_length=20,
        choices=ASSET_CATEGORY_CHOICES,
        db_index=True,
        verbose_name="资产类别"
    )

    asset_code = models.CharField(
        max_length=20,
        db_index=True,
        verbose_name="资产代码"
    )

    asset_name = models.CharField(
        max_length=100,
        verbose_name="资产名称"
    )

    pool_type = models.CharField(
        max_length=20,
        choices=POOL_TYPE_CHOICES,
        db_index=True,
        verbose_name="资产池类型"
    )

    # 评分信息
    total_score = models.FloatField(
        verbose_name="综合评分"
    )

    regime_score = models.FloatField(
        verbose_name="Regime评分"
    )

    policy_score = models.FloatField(
        verbose_name="Policy评分"
    )

    sentiment_score = models.FloatField(
        verbose_name="Sentiment评分"
    )

    signal_score = models.FloatField(
        verbose_name="Signal评分"
    )

    # 入池/出池信息
    entry_date = models.DateField(
        db_index=True,
        verbose_name="入池日期"
    )

    entry_reason = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        verbose_name="入池原因"
    )

    exit_date = models.DateField(
        blank=True,
        null=True,
        verbose_name="出池日期"
    )

    exit_reason = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        verbose_name="出池原因"
    )

    is_active = models.BooleanField(
        default=True,
        db_index=True,
        verbose_name="是否活跃"
    )

    # 风险指标
    risk_level = models.CharField(
        max_length=20,
        default="未知",
        verbose_name="风险等级"
    )

    volatility = models.FloatField(
        blank=True,
        null=True,
        verbose_name="波动率"
    )

    max_drawdown = models.FloatField(
        blank=True,
        null=True,
        verbose_name="最大回撤"
    )

    # 额外属性
    sector = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        verbose_name="行业"
    )

    market_cap = models.FloatField(
        blank=True,
        null=True,
        verbose_name="市值（元）"
    )

    pe_ratio = models.FloatField(
        blank=True,
        null=True,
        verbose_name="PE倍数"
    )

    pb_ratio = models.FloatField(
        blank=True,
        null=True,
        verbose_name="PB倍数"
    )

    # 上下文信息（JSON）
    context = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="上下文信息"
    )

    # 元信息
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="创建时间"
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="更新时间"
    )

    class Meta:
        db_table = "asset_pool_entry"
        verbose_name = "资产池条目"
        verbose_name_plural = "资产池条目"
        unique_together = [("asset_category", "asset_code", "pool_type", "entry_date")]
        ordering = ["-entry_date", "-total_score"]
        indexes = [
            models.Index(fields=["-entry_date"]),
            models.Index(fields=["pool_type", "is_active"]),
            models.Index(fields=["asset_category"]),
            models.Index(fields=["total_score"]),
        ]

    def __str__(self):
        return f"{self.asset_code} - {self.get_pool_type_display()}"


class AssetPoolConfig(models.Model):
    """
    资产池配置表

    存储不同资产池的配置参数。
    """

    # 资产池类型
    POOL_TYPE_CHOICES = [
        ('investable', '可投池'),
        ('prohibited', '禁投池'),
        ('watch', '观察池'),
        ('candidate', '候选池'),
    ]

    # 资产类别
    ASSET_CATEGORY_CHOICES = [
        ('equity', '股票'),
        ('fund', '基金'),
        ('bond', '债券'),
        ('wealth', '理财'),
        ('commodity', '商品'),
        ('index', '指数'),
    ]

    name = models.CharField(
        max_length=100,
        unique=True,
        verbose_name="配置名称"
    )

    description = models.TextField(
        blank=True,
        null=True,
        verbose_name="配置描述"
    )

    pool_type = models.CharField(
        max_length=20,
        choices=POOL_TYPE_CHOICES,
        verbose_name="资产池类型"
    )

    asset_category = models.CharField(
        max_length=20,
        choices=ASSET_CATEGORY_CHOICES,
        verbose_name="资产类别"
    )

    # 准入阈值
    min_total_score = models.FloatField(
        default=60.0,
        verbose_name="最低综合评分"
    )

    min_regime_score = models.FloatField(
        default=50.0,
        verbose_name="最低Regime评分"
    )

    min_policy_score = models.FloatField(
        default=50.0,
        verbose_name="最低Policy评分"
    )

    # 禁投阈值
    max_total_score = models.FloatField(
        default=30.0,
        verbose_name="最高综合评分（禁投）"
    )

    max_regime_score = models.FloatField(
        default=40.0,
        verbose_name="最高Regime评分（禁投）"
    )

    max_policy_score = models.FloatField(
        default=40.0,
        verbose_name="最高Policy评分（禁投）"
    )

    # 观察池阈值
    watch_min_score = models.FloatField(
        default=30.0,
        verbose_name="观察池最低分"
    )

    watch_max_score = models.FloatField(
        default=60.0,
        verbose_name="观察池最高分"
    )

    # 风险控制
    max_volatility = models.FloatField(
        blank=True,
        null=True,
        verbose_name="最大波动率"
    )

    max_drawdown = models.FloatField(
        blank=True,
        null=True,
        verbose_name="最大回撤"
    )

    # 其他限制
    min_market_cap = models.FloatField(
        blank=True,
        null=True,
        verbose_name="最小市值（元）"
    )

    max_pe_ratio = models.FloatField(
        blank=True,
        null=True,
        verbose_name="最大PE"
    )

    max_pb_ratio = models.FloatField(
        blank=True,
        null=True,
        verbose_name="最大PB"
    )

    # 状态
    is_active = models.BooleanField(
        default=True,
        verbose_name="是否启用"
    )

    # 元信息
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="创建时间"
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="更新时间"
    )

    class Meta:
        db_table = "asset_pool_config"
        verbose_name = "资产池配置"
        verbose_name_plural = "资产池配置"
        ordering = ["asset_category", "pool_type"]
        indexes = [
            models.Index(fields=["asset_category", "pool_type"]),
        ]

    def __str__(self):
        return f"{self.asset_category} - {self.get_pool_type_display()}"

