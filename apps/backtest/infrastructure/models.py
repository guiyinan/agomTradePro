"""
ORM Models for Backtest.
"""

from django.db import models


class BacktestResult(models.Model):
    """回测结果"""

    name = models.CharField(max_length=200)
    start_date = models.DateField()
    end_date = models.DateField()
    initial_capital = models.DecimalField(max_digits=20, decimal_places=2)
    final_capital = models.DecimalField(max_digits=20, decimal_places=2)
    total_return = models.FloatField()
    annualized_return = models.FloatField()
    max_drawdown = models.FloatField()
    sharpe_ratio = models.FloatField()
    regime_accuracy = models.FloatField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'backtest_result'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name}: {self.total_return:.2%}"
