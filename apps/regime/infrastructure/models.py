"""
ORM Models for Regime Data.
"""

from django.db import models


class RegimeLog(models.Model):
    """Regime 判定日志"""

    observed_at = models.DateField(unique=True, db_index=True)
    growth_momentum_z = models.FloatField()
    inflation_momentum_z = models.FloatField()
    distribution = models.JSONField()
    dominant_regime = models.CharField(max_length=20)
    confidence = models.FloatField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'regime_log'
        ordering = ['-observed_at']

    def __str__(self):
        return f"{self.observed_at}: {self.dominant_regime}"
