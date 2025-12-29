"""
ORM Models for Investment Signals.
"""

from django.db import models


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
    invalidation_logic = models.TextField()
    invalidation_threshold = models.FloatField(null=True, blank=True)
    target_regime = models.CharField(max_length=20)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    rejection_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'investment_signal'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.asset_code} {self.direction}: {self.status}"
