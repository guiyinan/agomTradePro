"""
ORM Models for Backtest.
"""

from __future__ import annotations

import json
import math
from decimal import Decimal
from typing import cast

from django.contrib.auth.models import User
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models

from apps.backtest.domain.entities import BacktestCompletionPayload

_MAX_BACKTEST_JSON_BYTES = 8 * 1024 * 1024
_MAX_BACKTEST_WARNINGS = 1_000
_MAX_BACKTEST_WARNING_LENGTH = 2_000


def _finite_float(value: object, *, field_name: str) -> float:
    """Return one finite numeric value without accepting booleans."""

    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError(f"{field_name} must be finite")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError(f"{field_name} must be finite")
    return numeric


def _optional_finite_float(value: object, *, field_name: str) -> float | None:
    """Return an optional finite metric."""

    if value is None:
        return None
    return _finite_float(value, field_name=field_name)


def _detached_json_list(value: object, *, field_name: str) -> list[object]:
    """Validate, bound, and detach one JSON list before persistence."""

    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list")
    try:
        serialized = json.dumps(
            value,
            cls=DjangoJSONEncoder,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field_name} must contain finite JSON values") from exc
    if len(serialized.encode("utf-8")) > _MAX_BACKTEST_JSON_BYTES:
        raise ValueError(f"{field_name} exceeds the persistence limit")
    detached = json.loads(serialized)
    if not isinstance(detached, list):
        raise ValueError(f"{field_name} must be a list")
    return cast(list[object], detached)


def _validated_warnings(value: object) -> list[str]:
    """Validate and detach bounded warning strings."""

    if not isinstance(value, list) or len(value) > _MAX_BACKTEST_WARNINGS:
        raise ValueError("warnings must be a bounded list of strings")
    if any(not isinstance(item, str) or len(item) > _MAX_BACKTEST_WARNING_LENGTH for item in value):
        raise ValueError("warnings must be a bounded list of strings")
    return list(value)


class BacktestResultModel(models.Model):
    """回测结果模型"""

    # 状态枚举
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("running", "Running"),
        ("completed", "Completed"),
        ("failed", "Failed"),
    ]

    # 用户关联（允许为空，兼容现有数据）
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="backtests",
        null=True,
        blank=True,
        verbose_name="创建用户",
        help_text="NULL表示系统/测试数据",
    )

    # 基本配置
    name = models.CharField(max_length=200)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    error_message = models.TextField(blank=True, null=True)

    # 回测配置
    start_date = models.DateField()
    end_date = models.DateField()
    initial_capital = models.DecimalField(max_digits=20, decimal_places=2)
    rebalance_frequency = models.CharField(max_length=20)  # monthly, quarterly, yearly
    use_pit_data = models.BooleanField(default=False)
    transaction_cost_bps = models.FloatField(default=10.0)
    data_manifest_id = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    pit_coverage = models.JSONField(default=dict, blank=True)
    trust_status = models.CharField(
        max_length=24,
        choices=[
            ("legacy_unverified", "Legacy unverified"),
            ("exploratory", "Exploratory"),
            ("pit_verified", "PIT verified"),
        ],
        default="legacy_unverified",
        db_index=True,
    )
    config_hash = models.CharField(max_length=64, blank=True)
    code_commit = models.CharField(max_length=64, blank=True)
    engine_version = models.CharField(max_length=64, blank=True)
    research_trial_id = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    decision_snapshot_id = models.CharField(max_length=64, null=True, blank=True, db_index=True)

    # 回测结果
    final_capital = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    total_return = models.FloatField(null=True, blank=True)
    annualized_return = models.FloatField(null=True, blank=True)
    max_drawdown = models.FloatField(null=True, blank=True)
    sharpe_ratio = models.FloatField(null=True, blank=True)

    # 详细数据（JSON 存储）
    equity_curve = models.JSONField(
        default=list, blank=True
    )  # [{"date": "2024-01-01", "value": 100000}, ...]
    regime_history = models.JSONField(
        default=list, blank=True
    )  # [{"date": "...", "regime": "...", ...}, ...]
    trades = models.JSONField(
        default=list, blank=True
    )  # [{"trade_date": "...", "asset_class": "...", ...}, ...]
    warnings = models.JSONField(default=list, blank=True)  # ["warning 1", "warning 2", ...]

    # 元数据
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    # Signal 反向链接
    used_signals = models.ManyToManyField(
        "signal.InvestmentSignalModel",
        related_name="backtests",
        blank=True,
        verbose_name="使用的信号",
        help_text="记录回测使用了哪些投资信号",
    )

    # 关联的信号配置（JSON 存储，用于追踪信号参数）
    signal_configs = models.JSONField(
        default=list,
        blank=True,
        verbose_name="信号配置",
        help_text="记录每个信号的配置参数，如权重、准入条件等",
    )

    class Meta:
        db_table = "backtest_result"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["-created_at"]),
            models.Index(fields=["status"]),
            models.Index(fields=["start_date", "end_date"]),
            models.Index(fields=["trust_status", "-created_at"]),
        ]

    def __str__(self) -> str:
        return (
            f"{self.name}: {self.total_return:.2%}"
            if self.total_return is not None
            else f"{self.name}: {self.status}"
        )

    def mark_completed(
        self,
        final_capital: float,
        result_data: BacktestCompletionPayload,
    ) -> None:
        """Persist a validated and detached completed-backtest snapshot."""

        from django.utils import timezone

        normalized_final_capital = Decimal(
            str(_finite_float(final_capital, field_name="final_capital"))
        )
        normalized_total_return = _finite_float(
            result_data.get("total_return"), field_name="total_return"
        )
        normalized_annualized_return = _finite_float(
            result_data.get("annualized_return"), field_name="annualized_return"
        )
        normalized_max_drawdown = _finite_float(
            result_data.get("max_drawdown"), field_name="max_drawdown"
        )
        normalized_sharpe_ratio = _optional_finite_float(
            result_data.get("sharpe_ratio"), field_name="sharpe_ratio"
        )
        normalized_equity_curve = _detached_json_list(
            result_data.get("equity_curve"), field_name="equity_curve"
        )
        normalized_regime_history = _detached_json_list(
            result_data.get("regime_history"), field_name="regime_history"
        )
        normalized_trades = _detached_json_list(result_data.get("trades"), field_name="trades")
        normalized_warnings = _validated_warnings(result_data.get("warnings"))

        self.status = "completed"
        self.final_capital = normalized_final_capital
        self.total_return = normalized_total_return
        self.annualized_return = normalized_annualized_return
        self.max_drawdown = normalized_max_drawdown
        self.sharpe_ratio = normalized_sharpe_ratio
        self.equity_curve = normalized_equity_curve
        self.regime_history = normalized_regime_history
        self.trades = normalized_trades
        self.warnings = normalized_warnings
        self.completed_at = timezone.now()
        self.save()

    def mark_failed(self, error_message: str) -> None:
        """标记回测为失败"""
        from django.utils import timezone

        self.status = "failed"
        self.error_message = error_message
        self.completed_at = timezone.now()
        self.save()


class BacktestTradeModel(models.Model):
    """回测交易记录模型（可选，用于更详细的交易分析）"""

    ACTION_CHOICES = [
        ("buy", "Buy"),
        ("sell", "Sell"),
    ]

    # 关联回测结果
    backtest = models.ForeignKey(
        BacktestResultModel, on_delete=models.CASCADE, related_name="trade_records"
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
        db_table = "backtest_trade"
        ordering = ["trade_date", "asset_class"]
        indexes = [
            models.Index(fields=["backtest", "trade_date"]),
            models.Index(fields=["asset_class"]),
        ]

    def __str__(self) -> str:
        return f"{self.trade_date} {self.action} {self.asset_class}: {self.shares} @ {self.price}"


__all__ = [
    "BacktestResultModel",
    "BacktestTradeModel",
]
