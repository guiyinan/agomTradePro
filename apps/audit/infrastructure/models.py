"""
ORM Models for Audit.
"""

from django.db import models


class AuditReport(models.Model):
    """审计报告"""

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
