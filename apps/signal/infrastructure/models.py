"""
ORM Models for Investment Signals.
"""

from django.db import models
from django.core.exceptions import ValidationError
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

    asset_code = models.CharField(max_length=20, db_index=True)
    asset_class = models.CharField(max_length=50)
    direction = models.CharField(max_length=10, choices=DIRECTION_CHOICES)
    logic_desc = models.TextField()

    # 文本描述（保留用于显示）
    invalidation_logic = models.TextField()
    invalidation_threshold = models.FloatField(null=True, blank=True)

    # 结构化证伪规则（新增）
    invalidation_rules = models.JSONField(default=dict, blank=True, null=True,
        help_text="结构化证伪规则，格式: {conditions: [...], logic: 'AND/OR'}")

    target_regime = models.CharField(max_length=20)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    rejection_reason = models.TextField(blank=True)

    # 证伪记录
    invalidated_at = models.DateTimeField(null=True, blank=True)
    invalidation_details = models.JSONField(null=True, blank=True,
        help_text="证伪时的详细数据")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'investment_signal'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.asset_code} {self.direction}: {self.status}"

    def clean(self):
        """验证证伪规则格式"""
        if self.invalidation_rules:
            try:
                self._validate_rules(self.invalidation_rules)
            except ValueError as e:
                raise ValidationError({'invalidation_rules': str(e)})

    def _validate_rules(self, rules):
        """验证规则结构"""
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

    def get_human_readable_rules(self):
        """生成人类可读的规则描述"""
        if not self.invalidation_rules:
            return self.invalidation_logic

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
        return f"证伪条件: {'当' + logic_text.join(conditions) + '时证伪'}"
