"""Canonical persistence model for portfolio order drafts and execution intents."""

from django.db import models
from django.utils import timezone


class OrderIntentModel(models.Model):
    """Compatibility table now owned by the portfolio bounded context."""

    intent_id = models.CharField("意图ID", max_length=64, unique=True, db_index=True)
    idempotency_key = models.CharField("幂等键", max_length=128, unique=True, db_index=True)
    strategy = models.ForeignKey(
        "strategy.StrategyModel",
        on_delete=models.CASCADE,
        related_name="order_intents",
        verbose_name="策略",
    )
    portfolio = models.ForeignKey(
        "simulated_trading.SimulatedAccountModel",
        on_delete=models.CASCADE,
        related_name="strategy_order_intents",
        verbose_name="投资组合",
    )
    symbol = models.CharField("资产代码", max_length=32, db_index=True)
    side = models.CharField(
        "方向", max_length=8, choices=[("buy", "买入"), ("sell", "卖出")]
    )
    qty = models.PositiveIntegerField("数量")
    limit_price = models.FloatField("限价", null=True, blank=True)
    time_in_force = models.CharField(
        "订单时效",
        max_length=8,
        default="day",
        choices=[("day", "DAY"), ("gtc", "GTC"), ("ioc", "IOC"), ("fok", "FOK")],
    )
    reason = models.TextField("原因", blank=True)
    status = models.CharField(
        "状态",
        max_length=32,
        default="draft",
        db_index=True,
        choices=[
            ("draft", "草稿"),
            ("pending_approval", "待审批"),
            ("approved", "已批准"),
            ("rejected", "已拒绝"),
            ("sent", "已发送"),
            ("partial_filled", "部分成交"),
            ("filled", "已成交"),
            ("canceled", "已取消"),
            ("failed", "失败"),
        ],
    )
    decision_json = models.JSONField("决策快照", default=dict)
    sizing_json = models.JSONField("仓位快照", default=dict)
    risk_snapshot_json = models.JSONField("风控快照", default=dict)
    created_at = models.DateTimeField("创建时间", default=timezone.now, db_index=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        app_label = "portfolio"
        db_table = "order_intent"
        verbose_name = "订单意图"
        verbose_name_plural = "订单意图"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["portfolio", "status"], name="order_inten_portfol_c5915a_idx"
            ),
            models.Index(
                fields=["strategy", "-created_at"], name="order_inten_strateg_ba47e5_idx"
            ),
            models.Index(
                fields=["symbol", "-created_at"], name="order_inten_symbol_1cccbc_idx"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.intent_id} {self.symbol} {self.side} {self.qty} ({self.status})"
