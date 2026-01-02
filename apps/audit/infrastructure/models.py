"""
ORM Models for Audit.
"""

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

    backtest = models.ForeignKey(
        BacktestResultModel,
        on_delete=models.CASCADE,
        related_name='attribution_reports',
        verbose_name='关联回测'
    )

    period_start = models.DateField(verbose_name='分析起始日期')
    period_end = models.DateField(verbose_name='分析结束日期')

    # Brinson 归因分析结果
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
