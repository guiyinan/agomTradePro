"""
ORM Models for Investment Signals.
"""

from django.db import models
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User
import json


class InvestmentSignalModel(models.Model):
    """投资信号 ORM 模型"""

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('invalidated', 'Invalidated'),
        ('expired', 'Expired'),
    ]

    DIRECTION_CHOICES = [
        ('LONG', 'Long'),
        ('SHORT', 'Short'),
        ('NEUTRAL', 'Neutral'),
    ]

    # 用户关联（允许为空，兼容现有数据）
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='signals',
        null=True,
        blank=True,
        verbose_name="创建用户",
        help_text="NULL表示系统模板信号"
    )

    asset_code = models.CharField(max_length=20, db_index=True)
    asset_class = models.CharField(max_length=50)
    direction = models.CharField(max_length=10, choices=DIRECTION_CHOICES)
    logic_desc = models.TextField()

    # ==================== 证伪规则字段重构 ====================
    # 新的证伪规则字段（使用 InvalidationRule.to_dict() 格式）
    invalidation_rule_json = models.JSONField(
        null=True, blank=True,
        help_text="结构化证伪规则 (InvalidationRule.to_dict())"
    )
    invalidation_description = models.TextField(
        blank=True,
        help_text="证伪逻辑的人类可读描述"
    )

    # 旧字段保留用于兼容性和迁移（标记为 deprecated）
    invalidation_logic = models.TextField(
        blank=True,
        help_text="[DEPRECATED] 请使用 invalidation_description"
    )
    invalidation_threshold = models.FloatField(
        null=True, blank=True,
        help_text="[DEPRECATED] 请使用 invalidation_rule_json"
    )
    invalidation_rules = models.JSONField(
        default=dict, blank=True, null=True,
        help_text="[DEPRECATED] 请使用 invalidation_rule_json"
    )
    # ==========================================================

    target_regime = models.CharField(max_length=20)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    rejection_reason = models.TextField(blank=True)

    # 证伪记录
    invalidated_at = models.DateTimeField(null=True, blank=True)
    invalidation_details = models.JSONField(null=True, blank=True,
        help_text="证伪时的详细数据")

    # 回测表现评分
    backtest_performance_score = models.FloatField(
        null=True,
        blank=True,
        verbose_name="回测表现评分",
        help_text="基于历史回测的信号表现评分 (0-100)"
    )
    backtest_count = models.IntegerField(
        default=0,
        verbose_name="回测次数",
        help_text="该信号参与回测的次数"
    )
    avg_backtest_return = models.FloatField(
        null=True,
        blank=True,
        verbose_name="平均回测收益率",
        help_text="该信号在所有回测中的平均收益率"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'investment_signal'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.asset_code} {self.direction}: {self.status}"

    def clean(self):
        """验证证伪规则格式"""
        # 优先验证新格式
        if self.invalidation_rule_json:
            try:
                self._validate_new_format(self.invalidation_rule_json)
            except ValueError as e:
                raise ValidationError({'invalidation_rule_json': str(e)})
        # 兼容旧格式
        elif self.invalidation_rules:
            try:
                self._validate_rules(self.invalidation_rules)
            except ValueError as e:
                raise ValidationError({'invalidation_rules': str(e)})

    def _validate_new_format(self, rule_dict):
        """验证新格式的规则结构"""
        if not isinstance(rule_dict, dict):
            raise ValueError("规则必须是字典格式")

        if 'conditions' not in rule_dict:
            raise ValueError("规则必须包含 conditions 字段")

        if not isinstance(rule_dict['conditions'], list) or len(rule_dict['conditions']) == 0:
            raise ValueError("conditions 必须是非空列表")

        for idx, condition in enumerate(rule_dict['conditions']):
            if not isinstance(condition, dict):
                raise ValueError(f"条件 {idx} 必须是字典")

            required_keys = {'indicator_code', 'indicator_type', 'operator', 'threshold'}
            if not required_keys.issubset(condition.keys()):
                raise ValueError(f"条件 {idx} 缺少必要字段: {required_keys}")

            if condition['operator'] not in ['lt', 'lte', 'gt', 'gte', 'eq']:
                raise ValueError(f"条件 {idx} 的 operator 必须是 lt/lte/gt/gte/eq 之一")

    def _validate_rules(self, rules):
        """验证旧格式的规则结构（兼容性）"""
        if not isinstance(rules, dict):
            raise ValueError("规则必须是字典格式")

        if 'conditions' not in rules:
            raise ValueError("规则必须包含 conditions 字段")

        if not isinstance(rules['conditions'], list) or len(rules['conditions']) == 0:
            raise ValueError("conditions 必须是非空列表")

        for idx, condition in enumerate(rules['conditions']):
            if not isinstance(condition, dict):
                raise ValueError(f"条件 {idx} 必须是字典")

            required_keys = {'indicator', 'condition', 'threshold'}
            if not required_keys.issubset(condition.keys()):
                raise ValueError(f"条件 {idx} 缺少必要字段: {required_keys}")

            if condition['condition'] not in ['lt', 'lte', 'gt', 'gte', 'eq']:
                raise ValueError(f"条件 {idx} 的 condition 必须是 lt/lte/gt/gte/eq 之一")

    def to_domain_entity(self):
        """转换为 Domain 实体"""
        from apps.signal.domain.entities import InvestmentSignal, SignalStatus
        from apps.signal.domain.invalidation import InvalidationRule

        invalidation_rule = None
        if self.invalidation_rule_json:
            try:
                invalidation_rule = InvalidationRule.from_dict(self.invalidation_rule_json)
            except (KeyError, ValueError):
                # 如果新格式解析失败，尝试旧格式
                pass

        return InvestmentSignal(
            id=str(self.id),
            asset_code=self.asset_code,
            asset_class=self.asset_class,
            direction=self.direction,
            logic_desc=self.logic_desc,
            invalidation_rule=invalidation_rule,
            invalidation_description=self.invalidation_description or self.invalidation_logic,
            target_regime=self.target_regime,
            created_at=self.created_at.date() if self.created_at else None,
            status=SignalStatus(self.status),
            rejection_reason=self.rejection_reason,
            backtest_performance_score=self.backtest_performance_score,
            avg_backtest_return=self.avg_backtest_return,
        )

    @classmethod
    def from_domain_entity(cls, signal):
        """从 Domain 实体创建 ORM 模型"""
        return cls(
            asset_code=signal.asset_code,
            asset_class=signal.asset_class,
            direction=signal.direction,
            logic_desc=signal.logic_desc,
            invalidation_rule_json=signal.invalidation_rule.to_dict() if signal.invalidation_rule else None,
            invalidation_description=signal.invalidation_description,
            target_regime=signal.target_regime,
            status=signal.status.value,
            rejection_reason=signal.rejection_reason,
            backtest_performance_score=signal.backtest_performance_score,
            avg_backtest_return=signal.avg_backtest_return,
        )

    def get_human_readable_rules(self):
        """生成人类可读的规则描述"""
        # 优先使用新格式
        if self.invalidation_rule_json:
            conditions = []
            for cond in self.invalidation_rule_json.get('conditions', []):
                indicator = cond.get('indicator_code', '')
                op = cond.get('operator', '')
                threshold = cond.get('threshold', '')

                op_map = {'lt': '<', 'lte': '≤', 'gt': '>', 'gte': '≥', 'eq': '='}
                cond_str = f"{indicator} {op_map.get(op, op)} {threshold}"

                if cond.get('duration'):
                    cond_str += f" 连续{cond['duration']}期"
                if cond.get('compare_with'):
                    cond_str += f" (较{cond['compare_with']})"

                conditions.append(cond_str)

            logic = self.invalidation_rule_json.get('logic', 'AND')
            logic_text = ' 且 ' if logic == 'AND' else ' 或 '
            return f"证伪条件: {logic_text.join(conditions)}"

        # 回退到旧格式
        elif self.invalidation_rules:
            conditions = []
            for cond in self.invalidation_rules.get('conditions', []):
                indicator = cond.get('indicator', '')
                op = cond.get('condition', '')
                threshold = cond.get('threshold', '')

                op_map = {'lt': '<', 'lte': '≤', 'gt': '>', 'gte': '≥', 'eq': '='}
                cond_str = f"{indicator} {op_map.get(op, op)} {threshold}"

                if cond.get('duration'):
                    cond_str += f" 连续{cond['duration']}期"
                if cond.get('compare_with'):
                    cond_str += f" (较{cond['compare_with']})"

                conditions.append(cond_str)

            logic = self.invalidation_rules.get('logic', 'AND')
            logic_text = ' 且 ' if logic == 'AND' else ' 或 '
            return f"证伪条件: {logic_text.join(conditions)}"

        # 最后使用描述文本
        return self.invalidation_description or self.invalidation_logic


class UnifiedSignalModel(models.Model):
    """
    统一信号表（汇总各模块信号）

    聚合来自 Regime、Factor、Rotation、Hedge 等所有模块的信号，
    提供统一的信号管理和查询接口。
    """

    SIGNAL_SOURCE_CHOICES = [
        ('regime', '宏观象限'),
        ('factor', '因子选股'),
        ('rotation', '资产轮动'),
        ('hedge', '对冲组合'),
        ('alpha', 'AI选股'),
        ('manual', '手动'),
    ]

    SIGNAL_TYPE_CHOICES = [
        ('buy', '买入'),
        ('sell', '卖出'),
        ('rebalance', '调仓'),
        ('alert', '告警'),
        ('info', '信息'),
    ]

    PRIORITY_CHOICES = [
        (1, '最低'),
        (2, '低'),
        (3, '中低'),
        (4, '中等'),
        (5, '中高'),
        (6, '高'),
        (7, '很高'),
        (8, '极高'),
        (9, '紧急'),
        (10, '最高'),
    ]

    # 信号基本信息
    signal_date = models.DateField(db_index=True, verbose_name="信号日期")
    signal_source = models.CharField(
        max_length=20,
        choices=SIGNAL_SOURCE_CHOICES,
        db_index=True,
        verbose_name="信号来源"
    )
    signal_type = models.CharField(
        max_length=20,
        choices=SIGNAL_TYPE_CHOICES,
        db_index=True,
        verbose_name="信号类型"
    )

    # 资产信息
    asset_code = models.CharField(
        max_length=20,
        db_index=True,
        verbose_name="资产代码",
        help_text="如 ASSET_CODE、ETF_CODE 等"
    )
    asset_name = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="资产名称"
    )

    # 目标权重（用于配置信号）
    target_weight = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        null=True,
        blank=True,
        verbose_name="目标权重",
        help_text="建议配置权重 (0-1)"
    )
    current_weight = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        null=True,
        blank=True,
        verbose_name="当前权重",
        help_text="当前配置权重"
    )

    # 优先级和状态
    priority = models.IntegerField(
        default=5,
        choices=PRIORITY_CHOICES,
        verbose_name="优先级",
        help_text="1-10，数字越大越重要"
    )
    is_executed = models.BooleanField(
        default=False,
        verbose_name="是否已执行"
    )
    executed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="执行时间"
    )

    # 信号详情
    reason = models.TextField(verbose_name="信号原因", help_text="信号生成的详细原因")
    action_required = models.CharField(
        max_length=200,
        blank=True,
        verbose_name="所需操作",
        help_text="建议采取的操作"
    )

    # 额外数据（JSON格式，用于存储特定模块的额外信息）
    extra_data = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="额外数据",
        help_text="特定模块的额外信息"
    )

    # 关联到原始信号ID（如果有）
    related_signal_id = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="关联信号ID",
        help_text="原始模块中的信号ID"
    )

    # 时间戳
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = 'unified_signal'
        verbose_name = '统一信号'
        verbose_name_plural = '统一信号'
        ordering = ['-signal_date', '-priority']
        indexes = [
            models.Index(fields=['signal_date', '-priority']),
            models.Index(fields=['signal_date', 'signal_source']),
            models.Index(fields=['asset_code', 'signal_date']),
            models.Index(fields=['is_executed', 'signal_date']),
        ]

    def __str__(self):
        return f"{self.signal_date} {self.signal_source} {self.signal_type}: {self.asset_code}"

    def mark_executed(self):
        """标记信号为已执行"""
        from django.utils import timezone
        self.is_executed = True
        self.executed_at = timezone.now()
        self.save()
