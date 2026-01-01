"""
ORM Models for Backtest.
"""

from django.db import models
from django.contrib.auth.models import User
import json


class BacktestResultModel(models.Model):
    """回测结果模型"""

    # 状态枚举
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('running', 'Running'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]

    # 用户关联（允许为空，兼容现有数据）
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='backtests',
        null=True,
        blank=True,
        verbose_name="创建用户",
        help_text="NULL表示系统/测试数据"
    )

    # 基本配置
    name = models.CharField(max_length=200)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    error_message = models.TextField(blank=True, null=True)

    # 回测配置
    start_date = models.DateField()
    end_date = models.DateField()
    initial_capital = models.DecimalField(max_digits=20, decimal_places=2)
    rebalance_frequency = models.CharField(max_length=20)  # monthly, quarterly, yearly
    use_pit_data = models.BooleanField(default=False)
    transaction_cost_bps = models.FloatField(default=10.0)

    # 回测结果
    final_capital = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    total_return = models.FloatField(null=True, blank=True)
    annualized_return = models.FloatField(null=True, blank=True)
    max_drawdown = models.FloatField(null=True, blank=True)
    sharpe_ratio = models.FloatField(null=True, blank=True)

    # 详细数据（JSON 存储）
    equity_curve = models.JSONField(default=list, blank=True)  # [{"date": "2024-01-01", "value": 100000}, ...]
    regime_history = models.JSONField(default=list, blank=True)  # [{"date": "...", "regime": "...", ...}, ...]
    trades = models.JSONField(default=list, blank=True)  # [{"trade_date": "...", "asset_class": "...", ...}, ...]
    warnings = models.JSONField(default=list, blank=True)  # ["warning 1", "warning 2", ...]

    # 元数据
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'backtest_result'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['status']),
            models.Index(fields=['start_date', 'end_date']),
        ]

    def __str__(self):
        return f"{self.name}: {self.total_return:.2%}" if self.total_return is not None else f"{self.name}: {self.status}"

    def mark_completed(self, final_capital: float, result_data: dict) -> None:
        """标记回测为完成"""
        from django.utils import timezone
        self.status = 'completed'
        self.final_capital = final_capital
        self.total_return = result_data.get('total_return')
        self.annualized_return = result_data.get('annualized_return')
        self.max_drawdown = result_data.get('max_drawdown')
        self.sharpe_ratio = result_data.get('sharpe_ratio')
        self.equity_curve = result_data.get('equity_curve', [])
        self.regime_history = result_data.get('regime_history', [])
        self.trades = result_data.get('trades', [])
        self.warnings = result_data.get('warnings', [])
        self.completed_at = timezone.now()
        self.save()

    def mark_failed(self, error_message: str) -> None:
        """标记回测为失败"""
        from django.utils import timezone
        self.status = 'failed'
        self.error_message = error_message
        self.completed_at = timezone.now()
        self.save()


class BacktestTradeModel(models.Model):
    """回测交易记录模型（可选，用于更详细的交易分析）"""

    ACTION_CHOICES = [
        ('buy', 'Buy'),
        ('sell', 'Sell'),
    ]

    # 关联回测结果
    backtest = models.ForeignKey(
        BacktestResultModel,
        on_delete=models.CASCADE,
        related_name='trade_records'
    )

    # 交易信息
    trade_date = models.DateField()
    asset_class = models.CharField(max_length=50)
    action = models.CharField(max_length=10, choices=ACTION_CHOICES)
    shares = models.FloatField()
    price = models.DecimalField(max_digits=20, decimal_places=4)
    notional = models.DecimalField(max_digits=20, decimal_places=2)
    cost = models.DecimalField(max_digits=20, decimal_places=2)

    # 元数据
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'backtest_trade'
        ordering = ['trade_date', 'asset_class']
        indexes = [
            models.Index(fields=['backtest', 'trade_date']),
            models.Index(fields=['asset_class']),
        ]

    def __str__(self):
        return f"{self.trade_date} {self.action} {self.asset_class}: {self.shares} @ {self.price}"
