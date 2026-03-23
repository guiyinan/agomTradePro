"""
ORM Models for Audit.
"""

import uuid

from django.core.serializers.json import DjangoJSONEncoder
from django.db import models

from apps.backtest.infrastructure.models import BacktestResultModel


class AuditReport(models.Model):
    """审计报告（已存在，保持不变）"""

    period_start = models.DateField()
    period_end = models.DateField()
    total_pnl = models.FloatField()
    regime_timing_pnl = models.FloatField()
    asset_selection_pnl = models.FloatField()
    interaction_pnl = models.FloatField()
    regime_predicted = models.CharField(max_length=20)
    regime_actual = models.CharField(max_length=20)
    lesson_learned = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'audit_report'
        ordering = ['-period_end']

    def __str__(self):
        return f"Audit {self.period_start} to {self.period_end}"


# ============ 新增 Models ============

class AttributionReport(models.Model):
    """归因分析报告（详细版本）"""

    ATTRIBUTION_METHOD_CHOICES = [
        ('heuristic', '启发式方法（30%/50%规则）'),
        ('brinson', '标准Brinson模型'),
    ]

    backtest = models.ForeignKey(
        BacktestResultModel,
        on_delete=models.CASCADE,
        related_name='attribution_reports',
        verbose_name='关联回测'
    )

    period_start = models.DateField(verbose_name='分析起始日期')
    period_end = models.DateField(verbose_name='分析结束日期')

    # 归因方法标识
    attribution_method = models.CharField(
        max_length=20,
        choices=ATTRIBUTION_METHOD_CHOICES,
        default='heuristic',
        verbose_name='归因方法',
        help_text='使用的归因分析方法'
    )

    # 归因分析结果
    regime_timing_pnl = models.FloatField(
        verbose_name='Regime 择时贡献',
        help_text='因 Regime 判断正确/错误产生的收益/损失'
    )
    asset_selection_pnl = models.FloatField(
        verbose_name='资产选择贡献',
        help_text='因资产选择正确/错误产生的收益/损失'
    )
    interaction_pnl = models.FloatField(
        verbose_name='交互效应',
        help_text='择时与选股的交互作用'
    )
    total_pnl = models.FloatField(verbose_name='总收益')

    # Regime 准确性
    regime_accuracy = models.FloatField(
        verbose_name='Regime 预测准确率',
        help_text='实际 Regime 与预测 Regime 的匹配度（0-1）'
    )
    regime_predicted = models.CharField(
        max_length=20,
        verbose_name='预测 Regime'
    )
    regime_actual = models.CharField(
        max_length=20,
        verbose_name='实际 Regime',
        null=True,
        blank=True
    )

    # 元数据
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'audit_attribution_report'
        ordering = ['-period_end']
        verbose_name = '归因分析报告'
        verbose_name_plural = '归因分析报告'

    def __str__(self):
        return f"Attribution {self.period_start} to {self.period_end}"


class LossAnalysis(models.Model):
    """损失归因分析"""

    LOSS_SOURCE_CHOICES = [
        ('REGIME_ERROR', 'Regime 判断错误'),
        ('TIMING_ERROR', '择时错误'),
        ('ASSET_SELECTION_ERROR', '资产选择错误'),
        ('EXECUTION_ERROR', '执行误差'),
        ('TRANSACTION_COST', '交易成本'),
        ('POLICY_MISJUDGMENT', 'Policy 误判'),
        ('EXTERNAL_SHOCK', '外部冲击'),
    ]

    report = models.ForeignKey(
        AttributionReport,
        on_delete=models.CASCADE,
        related_name='loss_analyses',
        verbose_name='归因报告'
    )

    loss_source = models.CharField(
        max_length=50,
        choices=LOSS_SOURCE_CHOICES,
        verbose_name='损失来源'
    )

    impact = models.FloatField(
        verbose_name='影响金额',
        help_text='该因素造成的收益/损失'
    )

    impact_percentage = models.FloatField(
        verbose_name='影响占比',
        help_text='占总损失的百分比'
    )

    description = models.TextField(
        verbose_name='详细描述',
        help_text='损失产生的具体原因和情境'
    )

    # 可改进措施
    improvement_suggestion = models.TextField(
        verbose_name='改进建议',
        blank=True
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'audit_loss_analysis'
        ordering = ['-impact']
        verbose_name = '损失归因分析'
        verbose_name_plural = '损失归因分析'

    def __str__(self):
        return f"{self.get_loss_source_display()}: {self.impact}"


class ExperienceSummary(models.Model):
    """经验总结"""

    PRIORITY_CHOICES = [
        ('HIGH', '高优先级'),
        ('MEDIUM', '中优先级'),
        ('LOW', '低优先级'),
    ]

    report = models.ForeignKey(
        AttributionReport,
        on_delete=models.CASCADE,
        related_name='experience_summaries',
        verbose_name='归因报告'
    )

    lesson = models.TextField(
        verbose_name='经验教训',
        help_text='从本次回测中学到的教训'
    )

    recommendation = models.TextField(
        verbose_name='改进建议',
        help_text='针对性的改进措施'
    )

    priority = models.CharField(
        max_length=20,
        choices=PRIORITY_CHOICES,
        default='MEDIUM',
        verbose_name='优先级'
    )

    # 是否已应用
    is_applied = models.BooleanField(
        default=False,
        verbose_name='是否已应用'
    )
    applied_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='应用时间'
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'audit_experience_summary'
        ordering = ['-priority', '-created_at']
        verbose_name = '经验总结'
        verbose_name_plural = '经验总结'

    def __str__(self):
        return f"{self.get_priority_display()}: {self.lesson[:50]}"


# ============ 指标表现评估相关 Models ============

class IndicatorPerformanceModel(models.Model):
    """指标表现历史记录

    存储指标的历史表现评估结果。
    """

    indicator_code = models.CharField(
        max_length=50,
        db_index=True,
        verbose_name='指标代码'
    )
    evaluation_period_start = models.DateField(verbose_name='评估起始日期')
    evaluation_period_end = models.DateField(verbose_name='评估结束日期')

    # 混淆矩阵
    true_positive_count = models.IntegerField(default=0, verbose_name='真阳性数')
    false_positive_count = models.IntegerField(default=0, verbose_name='假阳性数')
    true_negative_count = models.IntegerField(default=0, verbose_name='真阴性数')
    false_negative_count = models.IntegerField(default=0, verbose_name='假阴性数')

    # 统计指标
    precision = models.FloatField(null=True, verbose_name='精确率')
    recall = models.FloatField(null=True, verbose_name='召回率')
    f1_score = models.FloatField(null=True, verbose_name='F1 分数')
    accuracy = models.FloatField(null=True, verbose_name='准确率')

    # 领先时间
    lead_time_mean = models.FloatField(default=0.0, verbose_name='平均领先时间(月)')
    lead_time_std = models.FloatField(default=0.0, verbose_name='领先时间标准差')

    # 稳定性
    pre_2015_correlation = models.FloatField(null=True, verbose_name='2015年前相关性')
    post_2015_correlation = models.FloatField(null=True, verbose_name='2015年后相关性')
    stability_score = models.FloatField(default=0.0, verbose_name='稳定性分数')

    # 信号特征
    decay_rate = models.FloatField(default=0.0, verbose_name='信号衰减率')
    signal_strength = models.FloatField(default=0.0, verbose_name='信号强度')

    # 建议
    recommended_action = models.CharField(
        max_length=20,
        null=True,
        verbose_name='建议操作'
    )
    recommended_weight = models.FloatField(default=0.0, verbose_name='建议权重')
    confidence_level = models.FloatField(default=0.0, verbose_name='置信度')

    # 元数据
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'audit_indicator_performance'
        ordering = ['-evaluation_period_end', '-f1_score']
        verbose_name = '指标表现记录'
        verbose_name_plural = '指标表现记录'
        indexes = [
            models.Index(fields=['indicator_code', '-evaluation_period_end']),
        ]

    def __str__(self):
        return f"{self.indicator_code}: F1={self.f1_score:.3f}"


class IndicatorThresholdConfigModel(models.Model):
    """指标阈值配置（所有阈值从数据库读取，不硬编码）

    存储各指标的阈值配置、权重配置和验证参数。
    """

    indicator_code = models.CharField(
        max_length=50,
        unique=True,
        verbose_name='指标代码'
    )
    indicator_name = models.CharField(
        max_length=100,
        verbose_name='指标名称'
    )

    # 阈值定义
    level_low = models.FloatField(
        null=True,
        blank=True,
        verbose_name='低水平阈值',
        help_text='低水平阈值（如 PMI < 50 为收缩）'
    )
    level_high = models.FloatField(
        null=True,
        blank=True,
        verbose_name='高水平阈值',
        help_text='高水平阈值（如 PMI > 50 为扩张）'
    )

    # 权重配置
    base_weight = models.FloatField(
        default=1.0,
        verbose_name='基础权重',
        help_text='指标的基础权重（0-1）'
    )
    min_weight = models.FloatField(
        default=0.0,
        verbose_name='最小权重'
    )
    max_weight = models.FloatField(
        default=1.0,
        verbose_name='最大权重'
    )

    # 验证阈值（可调整）
    decay_threshold = models.FloatField(
        default=0.2,
        verbose_name='衰减阈值',
        help_text='F1 分数低于此值视为衰减'
    )
    decay_penalty = models.FloatField(
        default=0.5,
        verbose_name='衰减惩罚系数'
    )
    improvement_threshold = models.FloatField(
        default=0.1,
        verbose_name='改进阈值'
    )
    improvement_bonus = models.FloatField(
        default=1.2,
        verbose_name='改进奖励系数'
    )

    # 行为阈值
    action_thresholds = models.JSONField(
        default=dict,
        verbose_name='行为阈值配置',
        help_text='{"keep_min_f1": 0.6, "reduce_min_f1": 0.4, "remove_max_f1": 0.3}'
    )

    # 分段验证配置
    validation_periods = models.JSONField(
        default=list,
        verbose_name='分段验证配置',
        help_text='[{"name": "刚兑时期", "start": "2005-01-01", "end": "2017-12-31"}]'
    )

    # 指标类别
    category = models.CharField(
        max_length=50,
        blank=True,
        verbose_name='指标类别',
        help_text='如 growth, inflation, sentiment'
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name='是否启用'
    )

    # 元数据
    description = models.TextField(
        blank=True,
        verbose_name='说明'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'audit_indicator_threshold_config'
        ordering = ['category', 'indicator_code']
        verbose_name = '指标阈值配置'
        verbose_name_plural = '指标阈值配置'

    def __str__(self):
        return f"{self.indicator_code}: low={self.level_low}, high={self.level_high}, weight={self.base_weight}"


class ValidationSummaryModel(models.Model):
    """验证摘要

    记录每次验证运行的总体结果。
    """

    validation_run_id = models.CharField(
        max_length=100,
        unique=True,
        verbose_name='验证运行ID'
    )
    run_date = models.DateTimeField(auto_now_add=True, verbose_name='运行日期')

    evaluation_period_start = models.DateField(verbose_name='评估起始日期')
    evaluation_period_end = models.DateField(verbose_name='评估结束日期')

    total_indicators = models.IntegerField(default=0, verbose_name='总指标数')
    approved_indicators = models.IntegerField(default=0, verbose_name='通过指标数')
    rejected_indicators = models.IntegerField(default=0, verbose_name='拒绝指标数')
    pending_indicators = models.IntegerField(default=0, verbose_name='待定指标数')

    # 总体统计
    avg_f1_score = models.FloatField(null=True, verbose_name='平均F1分数')
    avg_stability_score = models.FloatField(null=True, verbose_name='平均稳定性分数')

    # 总体建议
    overall_recommendation = models.TextField(
        blank=True,
        verbose_name='总体建议'
    )

    # 验证状态
    STATUS_CHOICES = [
        ('pending', '待验证'),
        ('in_progress', '验证中'),
        ('completed', '已完成'),
        ('failed', '失败'),
    ]
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        verbose_name='状态'
    )

    # 影子模式标记
    is_shadow_mode = models.BooleanField(
        default=False,
        verbose_name='是否为影子模式'
    )

    # 错误信息
    error_message = models.TextField(
        blank=True,
        verbose_name='错误信息'
    )

    class Meta:
        db_table = 'audit_validation_summary'
        ordering = ['-run_date']
        verbose_name = '验证摘要'
        verbose_name_plural = '验证摘要'

    def __str__(self):
        return f"Validation {self.validation_run_id}: {self.approved_indicators}/{self.total_indicators} passed"


# ============ Phase 4: Confidence Configuration Models ============

class ConfidenceConfigModel(models.Model):
    """置信度配置（Phase 4）

    存储置信度计算的所有可配置参数。
    所有阈值从数据库读取，不硬编码。
    """

    # 新鲜度系数
    day_0_coefficient = models.FloatField(
        default=0.6,
        verbose_name='发布当天系数',
        help_text='数据发布当天的置信度系数'
    )
    day_7_coefficient = models.FloatField(
        default=0.5,
        verbose_name='发布1周后系数',
        help_text='数据发布1周后的置信度系数'
    )
    day_14_coefficient = models.FloatField(
        default=0.4,
        verbose_name='发布2周后系数',
        help_text='数据发布2周后的置信度系数'
    )
    day_30_coefficient = models.FloatField(
        default=0.3,
        verbose_name='发布1月后系数',
        help_text='数据发布1个月后的置信度系数'
    )

    # 数据类型加成
    daily_data_bonus = models.FloatField(
        default=0.2,
        verbose_name='日度数据加成',
        help_text='有日度数据支持时的置信度加成'
    )
    weekly_data_bonus = models.FloatField(
        default=0.1,
        verbose_name='周度数据加成',
        help_text='有周度数据支持时的置信度加成'
    )
    daily_consistency_bonus = models.FloatField(
        default=0.1,
        verbose_name='日度一致性加成',
        help_text='日度数据与月度数据一致时的加成'
    )

    # 基础置信度
    base_confidence = models.FloatField(
        default=0.5,
        verbose_name='基础置信度',
        help_text='默认的基础置信度'
    )

    # 信号冲突解决阈值
    daily_persist_threshold = models.IntegerField(
        default=10,
        verbose_name='日度持续阈值',
        help_text='日度信号持续多少天后采用日度信号'
    )
    hybrid_weight_daily = models.FloatField(
        default=0.3,
        verbose_name='混合日度权重',
        help_text='混合模式中日度信号的权重'
    )
    hybrid_weight_monthly = models.FloatField(
        default=0.7,
        verbose_name='混合月度权重',
        help_text='混合模式中月度信号的权重'
    )

    # 权重动态调整参数
    decay_threshold = models.FloatField(
        default=0.2,
        verbose_name='衰减阈值',
        help_text='F1分数低于此值视为衰减'
    )
    decay_penalty = models.FloatField(
        default=0.5,
        verbose_name='衰减惩罚系数',
        help_text='衰减后权重乘以该系数'
    )
    improvement_threshold = models.FloatField(
        default=0.1,
        verbose_name='改进阈值',
        help_text='F1提升超过此值给予奖励'
    )
    improvement_bonus = models.FloatField(
        default=1.2,
        verbose_name='改进奖励系数',
        help_text='改进后权重乘以该系数'
    )

    # 元数据
    description = models.TextField(
        blank=True,
        verbose_name='说明'
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name='是否启用'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'audit_confidence_config'
        verbose_name = '置信度配置'
        verbose_name_plural = '置信度配置'

    def __str__(self):
        return f"ConfidenceConfig: base={self.base_confidence}, active={self.is_active}"

    def to_domain_config(self):
        """转换为 Domain 层的 ConfidenceConfig 实体"""
        from apps.regime.domain.entities import ConfidenceConfig
        return ConfidenceConfig(
            day_0_coefficient=self.day_0_coefficient,
            day_7_coefficient=self.day_7_coefficient,
            day_14_coefficient=self.day_14_coefficient,
            day_30_coefficient=self.day_30_coefficient,
            daily_data_bonus=self.daily_data_bonus,
            weekly_data_bonus=self.weekly_data_bonus,
            daily_consistency_bonus=self.daily_consistency_bonus,
            base_confidence=self.base_confidence,
        )


# ============ MCP/SDK 操作审计日志 Models ============

class OperationLogModel(models.Model):
    """MCP/SDK 操作审计日志

    记录所有通过 MCP 和 SDK 进行的工具调用，用于审计追踪。
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        verbose_name='日志ID'
    )
    request_id = models.CharField(
        max_length=64,
        db_index=True,
        verbose_name='链路追踪ID',
        help_text='用于关联请求链路'
    )

    # 操作者身份
    user_id = models.IntegerField(
        null=True,
        db_index=True,
        verbose_name='用户ID'
    )
    username = models.CharField(
        max_length=150,
        default='anonymous',
        verbose_name='用户名'
    )
    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        verbose_name='IP地址'
    )
    user_agent = models.CharField(
        max_length=500,
        blank=True,
        verbose_name='User Agent'
    )

    # 来源与租户
    source = models.CharField(
        max_length=20,
        default='MCP',
        db_index=True,
        verbose_name='来源',
        help_text='MCP/SDK/API'
    )
    client_id = models.CharField(
        max_length=100,
        blank=True,
        db_index=True,
        verbose_name='客户端ID'
    )

    # 操作描述
    operation_type = models.CharField(
        max_length=50,
        db_index=True,
        verbose_name='操作类型',
        help_text='MCP_CALL/API_ACCESS/DATA_MODIFY'
    )
    module = models.CharField(
        max_length=50,
        db_index=True,
        verbose_name='模块',
        help_text='signal/policy/backtest/...'
    )
    action = models.CharField(
        max_length=50,
        verbose_name='动作',
        help_text='CREATE/READ/UPDATE/DELETE/EXECUTE'
    )
    resource_type = models.CharField(
        max_length=50,
        blank=True,
        verbose_name='资源类型'
    )
    resource_id = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        db_index=True,
        verbose_name='资源ID'
    )

    # MCP 特定字段
    mcp_tool_name = models.CharField(
        max_length=120,
        null=True,
        blank=True,
        db_index=True,
        verbose_name='MCP工具名'
    )
    mcp_client_id = models.CharField(
        max_length=100,
        blank=True,
        verbose_name='MCP客户端ID'
    )
    mcp_role = models.CharField(
        max_length=30,
        blank=True,
        verbose_name='MCP角色'
    )
    sdk_version = models.CharField(
        max_length=50,
        blank=True,
        verbose_name='SDK版本'
    )

    # 请求详情（params 为脱敏后）
    request_method = models.CharField(
        max_length=10,
        default='MCP',
        verbose_name='请求方法'
    )
    request_path = models.CharField(
        max_length=500,
        blank=True,
        verbose_name='请求路径'
    )
    request_params = models.JSONField(
        default=dict,
        encoder=DjangoJSONEncoder,
        verbose_name='请求参数',
        help_text='已脱敏'
    )
    response_payload = models.JSONField(
        null=True,
        blank=True,
        encoder=DjangoJSONEncoder,
        verbose_name='响应载荷',
        help_text='结构化响应内容，已脱敏'
    )
    response_text = models.TextField(
        blank=True,
        verbose_name='响应文本快照',
        help_text='完整或截断后的文本响应'
    )
    response_status = models.IntegerField(
        default=200,
        db_index=True,
        verbose_name='响应状态码'
    )
    response_message = models.TextField(
        blank=True,
        verbose_name='响应消息'
    )
    error_code = models.CharField(
        max_length=50,
        blank=True,
        verbose_name='错误代码'
    )
    exception_traceback = models.TextField(
        blank=True,
        verbose_name='异常堆栈'
    )

    # 时间与性能
    timestamp = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        verbose_name='时间戳'
    )
    duration_ms = models.IntegerField(
        null=True,
        blank=True,
        verbose_name='耗时(ms)'
    )

    # 完整性校验
    checksum = models.CharField(
        max_length=64,
        blank=True,
        verbose_name='校验和',
        help_text='SHA-256'
    )

    class Meta:
        db_table = 'audit_operation_log'
        ordering = ['-timestamp']
        verbose_name = '操作审计日志'
        verbose_name_plural = '操作审计日志'
        indexes = [
            models.Index(fields=['user_id', '-timestamp'], name='idx_audit_user_ts'),
            models.Index(fields=['operation_type', 'module'], name='idx_audit_type_module'),
            models.Index(fields=['mcp_tool_name', '-timestamp'], name='idx_audit_tool_ts'),
            models.Index(fields=['response_status', '-timestamp'], name='idx_audit_status_ts'),
            models.Index(fields=['source', '-timestamp'], name='idx_audit_source_ts'),
        ]

    def __str__(self):
        return f"{self.timestamp} | {self.username} | {self.mcp_tool_name or self.operation_type} | {self.response_status}"
