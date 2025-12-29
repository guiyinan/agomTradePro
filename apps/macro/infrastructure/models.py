"""
ORM Models for Macro Data.

Django models for persisting macro indicator data.
"""

from django.db import models


class MacroIndicator(models.Model):
    """宏观指标 ORM 模型"""

    code = models.CharField(max_length=50, db_index=True, help_text="指标代码")
    value = models.DecimalField(max_digits=20, decimal_places=6, help_text="指标值")
    observed_at = models.DateField(db_index=True, help_text="指标所属期间")
    published_at = models.DateField(null=True, blank=True, help_text="实际发布时间")
    publication_lag_days = models.IntegerField(default=0, help_text="发布延迟天数")
    source = models.CharField(max_length=20, help_text="数据源")
    revision_number = models.IntegerField(default=1, help_text="修订版本号")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'macro_indicator'
        unique_together = [['code', 'observed_at', 'revision_number']]
        ordering = ['-observed_at', '-revision_number']
        indexes = [
            models.Index(fields=['code', '-observed_at']),
        ]

    def __str__(self):
        return f"{self.code}@{self.observed_at}={self.value}"
