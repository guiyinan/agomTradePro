"""
ORM Models for Policy Events.
"""

from django.db import models


class PolicyLog(models.Model):
    """政策事件日志"""

    POLICY_LEVELS = [
        ('P0', 'P0 - 常态'),
        ('P1', 'P1 - 预警'),
        ('P2', 'P2 - 干预'),
        ('P3', 'P3 - 危机'),
    ]

    event_date = models.DateField(db_index=True)
    level = models.CharField(max_length=2, choices=POLICY_LEVELS)
    title = models.CharField(max_length=200)
    description = models.TextField()
    evidence_url = models.URLField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'policy_log'
        ordering = ['-event_date']

    def __str__(self):
        return f"{self.event_date}: {self.level} - {self.title}"
