"""
投资组合 ORM 模型

Infrastructure层:
- 使用Django ORM定义数据表
- 对应Domain层的实体
- 包含索引优化和约束

⭐ 统一的投资组合系统：
- 支持多个实仓（real）
- 支持多个模拟仓（simulated）
- 通过 user 外键关联用户
"""

from __future__ import annotations

from math import isfinite
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, router, transaction
from django.db.models import Q
from django.utils import timezone

# These model imports register their tables with Django's app registry.
from .simulated_account_raw_observation_models import (  # noqa: F401
    SimulatedAccountRawObservationModel,
)
from .simulated_account_row_source_models import SimulatedAccountRowSourceModel  # noqa: F401
from .simulated_account_row_source_v2_models import SimulatedAccountRowSourceV2Model  # noqa: F401


class SimulatedAccountModel(models.Model):
    """
    投资组合账户模型（统一）

    ⭐ 重构说明：
    - 统一管理实仓和模拟仓
    - 用户可以创建多个投资组合
    - 每个投资组合可以选择类型：real（实仓）或 simulated（模拟仓）
    - 替代老的 PortfolioModel 系统
    """

    # Data migration 0013 assigns a default user to existing null records.
    # Kept nullable until use cases and mappers pass user consistently.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="investment_accounts",
        verbose_name="用户",
        db_index=True,
        null=True,
        blank=True,
    )

    account_name = models.CharField("账户名称", max_length=100)  # ⭐ 删除 unique 约束
    account_type = models.CharField(
        "账户类型",
        max_length=20,
        choices=[
            ("real", "实仓"),
            ("simulated", "模拟仓"),
        ],
        default="simulated",
        db_index=True,
    )

    # 资金信息
    initial_capital = models.DecimalField("初始资金(元)", max_digits=15, decimal_places=2)
    current_cash = models.DecimalField("当前现金(元)", max_digits=15, decimal_places=2)
    current_market_value = models.DecimalField(
        "当前持仓市值(元)", max_digits=15, decimal_places=2, default=0
    )
    total_value = models.DecimalField("总资产(元)", max_digits=15, decimal_places=2)

    # 绩效指标
    total_return = models.FloatField("总收益率(%)", default=0.0)
    annual_return = models.FloatField("年化收益率(%)", default=0.0)
    max_drawdown = models.FloatField("最大回撤(%)", default=0.0)
    sharpe_ratio = models.FloatField("夏普比率", default=0.0)
    win_rate = models.FloatField("胜率(%)", default=0.0)

    # 交易统计
    total_trades = models.IntegerField("总交易次数", default=0)
    winning_trades = models.IntegerField("盈利交易次数", default=0)

    # 时间信息
    start_date = models.DateField("开始日期", auto_now_add=True)
    last_trade_date = models.DateField("最后交易日期", null=True, blank=True)
    is_active = models.BooleanField("是否激活", default=True, db_index=True)

    # 策略配置
    auto_trading_enabled = models.BooleanField("启用自动交易", default=True)
    max_position_pct = models.FloatField("单资产最大持仓比例(%)", default=20.0)
    max_total_position_pct = models.FloatField("总持仓比例上限(%)", default=95.0)
    stop_loss_pct = models.FloatField("止损比例(%)", null=True, blank=True)

    # 关联策略（可选）- 临时注释以修复 migration 问题
    # active_strategy = models.ForeignKey(
    #     'strategy.StrategyModel',
    #     on_delete=models.SET_NULL,
    #     null=True,
    #     blank=True,
    #     related_name='portfolios',
    #     verbose_name="激活策略",
    #     help_text="绑定策略后，自动交易将使用策略引擎执行",
    #     db_index=True
    # )

    # 费用配置
    commission_rate = models.FloatField("手续费率", default=0.0003)
    slippage_rate = models.FloatField("滑点率", default=0.001)

    # 元数据
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        db_table = "simulated_account"
        verbose_name = "投资组合账户"
        verbose_name_plural = "投资组合账户"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["user", "account_type"]),
            models.Index(fields=["user", "is_active"]),
            models.Index(fields=["is_active", "auto_trading_enabled"]),
            models.Index(fields=["-start_date"]),
            # models.Index(fields=["active_strategy", "is_active"]),  # 临时注释
        ]

    def __str__(self) -> str:
        type_label = "实仓" if self.account_type == "real" else "模拟仓"
        return f"{self.account_name} ({type_label})"


class PositionModel(models.Model):
    """持仓模型"""

    account = models.ForeignKey(
        SimulatedAccountModel,
        on_delete=models.CASCADE,
        related_name="positions",
        verbose_name="所属账户",
    )

    asset_code = models.CharField("资产代码", max_length=20, db_index=True)
    asset_name = models.CharField("资产名称", max_length=100)
    asset_type = models.CharField(
        "资产类型", max_length=20, choices=[("equity", "股票"), ("fund", "基金"), ("bond", "债券")]
    )

    # 持仓数量 (DecimalField 支持非整数股份，兼容旧账本浮点 shares)
    quantity = models.DecimalField("持仓数量", max_digits=20, decimal_places=6)
    available_quantity = models.DecimalField("可卖数量", max_digits=20, decimal_places=6)

    # 成本信息
    avg_cost = models.DecimalField("平均成本(元)", max_digits=10, decimal_places=4)
    total_cost = models.DecimalField("总成本(元)", max_digits=15, decimal_places=2)

    # 当前信息
    current_price = models.DecimalField("当前价格(元)", max_digits=10, decimal_places=4)
    market_value = models.DecimalField("市值(元)", max_digits=15, decimal_places=2)

    # 盈亏信息
    unrealized_pnl = models.DecimalField("浮动盈亏(元)", max_digits=15, decimal_places=2, default=0)
    unrealized_pnl_pct = models.FloatField("浮动盈亏率(%)", default=0.0)

    # 时间信息
    first_buy_date = models.DateField("首次买入日期")
    last_update_date = models.DateField("最后更新日期", auto_now=True)

    # 关联信号
    signal_id = models.IntegerField("关联信号ID", null=True, blank=True)
    entry_reason = models.CharField("入场原因", max_length=200, blank=True)

    # ==================== 证伪条件跟踪 ====================
    # 从信号继承的证伪条件（副本，即使信号被删除也不影响）
    invalidation_rule_json = models.JSONField(
        "证伪规则", null=True, blank=True, help_text="从信号继承的结构化证伪规则"
    )
    invalidation_description = models.TextField(
        "证伪描述", blank=True, help_text="人类可读的证伪条件描述"
    )

    # 证伪状态
    is_invalidated = models.BooleanField(
        "是否已证伪", default=False, db_index=True, help_text="证伪条件已满足，建议平仓"
    )
    invalidation_reason = models.TextField("证伪原因", blank=True, help_text="证伪原因说明")
    invalidation_checked_at = models.DateTimeField(
        "最后检查时间", null=True, blank=True, help_text="最后一次检查证伪条件的时间"
    )
    # =====================================================

    # 元数据
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        db_table = "simulated_position"
        verbose_name = "模拟持仓"
        verbose_name_plural = "模拟持仓"
        ordering = ["-market_value"]
        unique_together = [["account", "asset_code"]]
        indexes = [
            models.Index(fields=["account", "asset_code"]),
            models.Index(fields=["-market_value"]),
            models.Index(fields=["account", "is_invalidated"]),  # 证伪状态查询
            models.Index(fields=["is_invalidated", "invalidation_checked_at"]),  # 定期检查
        ]

    def __str__(self) -> str:
        return f"{self.asset_name} ({self.quantity})"


class SimulatedTradeModel(models.Model):
    """模拟交易记录模型"""

    account = models.ForeignKey(
        SimulatedAccountModel,
        on_delete=models.CASCADE,
        related_name="trades",
        verbose_name="所属账户",
    )

    # 资产信息
    asset_code = models.CharField("资产代码", max_length=20, db_index=True)
    asset_name = models.CharField("资产名称", max_length=100)
    asset_type = models.CharField("资产类型", max_length=20)

    # 交易信息
    action = models.CharField(
        "交易动作", max_length=10, choices=[("buy", "买入"), ("sell", "卖出")]
    )
    quantity = models.DecimalField("交易数量", max_digits=20, decimal_places=6)
    price = models.DecimalField("成交价格(元)", max_digits=10, decimal_places=4)
    amount = models.DecimalField("成交金额(元)", max_digits=15, decimal_places=2)

    # 费用
    commission = models.DecimalField("手续费(元)", max_digits=10, decimal_places=2, default=0)
    transfer_fee = models.DecimalField(
        "过户费(元)", max_digits=10, decimal_places=2, null=True, blank=True
    )
    stamp_duty = models.DecimalField(
        "印花税(元)", max_digits=10, decimal_places=2, null=True, blank=True
    )
    slippage = models.DecimalField("滑点损失(元)", max_digits=10, decimal_places=2, default=0)
    total_cost = models.DecimalField("总成本(元)", max_digits=15, decimal_places=2)

    # 盈亏(仅SELL时有)
    realized_pnl = models.DecimalField(
        "已实现盈亏(元)", max_digits=15, decimal_places=2, null=True, blank=True
    )
    realized_pnl_pct = models.FloatField("已实现盈亏率(%)", null=True, blank=True)

    # 交易原因
    reason = models.CharField("交易原因", max_length=200, blank=True)
    signal_id = models.IntegerField("关联信号ID", null=True, blank=True)

    # 时间信息
    order_date = models.DateField("订单日期", db_index=True)
    execution_date = models.DateField("执行日期")
    execution_time = models.DateTimeField("执行时间", auto_now_add=True)

    # 状态
    status = models.CharField(
        "订单状态",
        max_length=20,
        choices=[
            ("pending", "待执行"),
            ("executed", "已执行"),
            ("cancelled", "已取消"),
            ("failed", "执行失败"),
        ],
        default="pending",
    )

    # 元数据
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    # Exact metadata for the new settlement-bound normal-simulation UoW. Legacy
    # and imported facts leave these columns NULL and are never backfilled.
    idempotency_key = models.CharField(max_length=128, null=True, blank=True)
    request_payload_hash = models.CharField(max_length=64, null=True, blank=True)
    fee_config_id = models.PositiveBigIntegerField(null=True, blank=True)
    fee_schedule_hash = models.CharField(max_length=64, null=True, blank=True)
    fee_schedule_snapshot = models.JSONField(null=True, blank=True)
    fee_precision_basis = models.CharField(max_length=32, null=True, blank=True)
    fee_calculation_purpose = models.CharField(max_length=32, null=True, blank=True)
    fee_rounding_policy = models.CharField(max_length=48, null=True, blank=True)
    settlement_status = models.CharField(
        max_length=12,
        choices=[("pending", "待结算"), ("released", "已结算")],
        null=True,
        blank=True,
    )
    settlement_security_id = models.CharField(max_length=192, null=True, blank=True)
    settlement_market = models.CharField(max_length=32, null=True, blank=True)
    settlement_exchange = models.CharField(max_length=32, null=True, blank=True)
    settlement_board = models.CharField(max_length=32, null=True, blank=True)
    settlement_market_session = models.DateField(null=True, blank=True)
    settlement_lag_sessions = models.PositiveIntegerField(null=True, blank=True)
    settlement_plan_binding_version = models.PositiveSmallIntegerField(default=0)
    settlement_plan_binding_payload = models.JSONField(null=True, blank=True)
    settlement_plan_binding_hash = models.CharField(max_length=64, null=True, blank=True)
    settlement_bundle_id = models.CharField(max_length=192, null=True, blank=True)
    settlement_bundle_version = models.CharField(max_length=192, null=True, blank=True)
    settlement_bundle_hash = models.CharField(max_length=64, null=True, blank=True)
    settlement_policy_id = models.CharField(max_length=192, null=True, blank=True)
    settlement_policy_version = models.CharField(max_length=192, null=True, blank=True)
    settlement_policy_hash = models.CharField(max_length=64, null=True, blank=True)
    execution_rule_v2_hash = models.CharField(max_length=64, null=True, blank=True)
    settlement_release_date = models.DateField(null=True, blank=True)
    settlement_calendar_snapshot_id = models.CharField(max_length=36, null=True, blank=True)
    settlement_calendar_content_hash = models.CharField(max_length=71, null=True, blank=True)
    settlement_calendar_record_digest = models.CharField(max_length=71, null=True, blank=True)
    settlement_calendar_publication_id = models.CharField(max_length=192, null=True, blank=True)
    settlement_calendar_publication_hash = models.CharField(max_length=64, null=True, blank=True)
    settlement_calendar_policy_hash = models.CharField(max_length=64, null=True, blank=True)
    settlement_calendar_evidence_hash = models.CharField(max_length=64, null=True, blank=True)
    settlement_calendar_timezone = models.CharField(max_length=64, null=True, blank=True)
    settlement_released_at = models.DateTimeField(null=True, blank=True)
    settlement_release_session = models.DateField(null=True, blank=True)
    settlement_release_calendar_snapshot_id = models.CharField(max_length=36, null=True, blank=True)
    settlement_release_calendar_content_hash = models.CharField(
        max_length=71, null=True, blank=True
    )
    settlement_release_calendar_record_digest = models.CharField(
        max_length=71, null=True, blank=True
    )
    settlement_release_calendar_publication_id = models.CharField(
        max_length=192, null=True, blank=True
    )
    settlement_release_calendar_publication_hash = models.CharField(
        max_length=64, null=True, blank=True
    )
    settlement_release_calendar_policy_hash = models.CharField(max_length=64, null=True, blank=True)
    settlement_release_calendar_evidence_hash = models.CharField(
        max_length=64, null=True, blank=True
    )
    settlement_release_calendar_timezone = models.CharField(max_length=64, null=True, blank=True)

    class Meta:
        db_table = "simulated_trade"
        verbose_name = "模拟交易记录"
        verbose_name_plural = "模拟交易记录"
        ordering = ["-execution_date", "-execution_time"]
        indexes = [
            models.Index(fields=["account", "-execution_date"]),
            models.Index(fields=["asset_code", "-execution_date"]),
            models.Index(fields=["-execution_date"]),
            models.Index(
                fields=["account", "asset_code", "settlement_status", "settlement_market_session"],
                name="sim_trade_settle_due_ix",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("account", "idempotency_key"),
                condition=Q(idempotency_key__isnull=False),
                name="sim_trade_account_idemp_uq",
            ),
            models.CheckConstraint(
                condition=Q(idempotency_key__isnull=True, request_payload_hash__isnull=True)
                | Q(idempotency_key__isnull=False, request_payload_hash__isnull=False),
                name="sim_trade_idemp_pair_ck",
            ),
            models.CheckConstraint(
                condition=Q(
                    settlement_plan_binding_version=0,
                    settlement_plan_binding_payload__isnull=True,
                    settlement_plan_binding_hash__isnull=True,
                    settlement_exchange__isnull=True,
                )
                | Q(
                    settlement_plan_binding_version=1,
                    idempotency_key__isnull=False,
                    request_payload_hash__isnull=False,
                    settlement_plan_binding_payload__isnull=False,
                    settlement_plan_binding_hash__isnull=False,
                    settlement_exchange__isnull=True,
                )
                | Q(
                    settlement_plan_binding_version=2,
                    idempotency_key__isnull=False,
                    request_payload_hash__isnull=False,
                    settlement_plan_binding_payload__isnull=False,
                    settlement_plan_binding_hash__isnull=False,
                    settlement_exchange__isnull=False,
                ),
                name="sim_trade_plan_binding_pair_ck",
            ),
            models.CheckConstraint(
                condition=Q(
                    idempotency_key__isnull=True,
                    fee_config_id__isnull=True,
                    fee_schedule_hash__isnull=True,
                    fee_schedule_snapshot__isnull=True,
                    fee_precision_basis__isnull=True,
                    fee_calculation_purpose__isnull=True,
                    fee_rounding_policy__isnull=True,
                    settlement_market_session__isnull=True,
                    settlement_security_id__isnull=True,
                    settlement_market__isnull=True,
                    settlement_exchange__isnull=True,
                    settlement_board__isnull=True,
                    settlement_lag_sessions__isnull=True,
                    settlement_bundle_id__isnull=True,
                    settlement_bundle_version__isnull=True,
                    settlement_bundle_hash__isnull=True,
                    settlement_policy_id__isnull=True,
                    settlement_policy_version__isnull=True,
                    settlement_policy_hash__isnull=True,
                    execution_rule_v2_hash__isnull=True,
                    settlement_calendar_snapshot_id__isnull=True,
                    settlement_calendar_content_hash__isnull=True,
                    settlement_calendar_record_digest__isnull=True,
                    settlement_calendar_publication_id__isnull=True,
                    settlement_calendar_publication_hash__isnull=True,
                    settlement_calendar_policy_hash__isnull=True,
                    settlement_calendar_evidence_hash__isnull=True,
                    settlement_calendar_timezone__isnull=True,
                )
                | Q(
                    idempotency_key__isnull=False,
                    fee_config_id__isnull=False,
                    fee_schedule_hash__isnull=False,
                    fee_schedule_snapshot__isnull=False,
                    fee_precision_basis__isnull=False,
                    fee_calculation_purpose__isnull=False,
                    fee_rounding_policy__isnull=False,
                    settlement_market_session__isnull=False,
                    settlement_security_id__isnull=False,
                    settlement_market__isnull=False,
                    settlement_board__isnull=False,
                    settlement_lag_sessions__isnull=False,
                    settlement_bundle_id__isnull=False,
                    settlement_bundle_version__isnull=False,
                    settlement_bundle_hash__isnull=False,
                    settlement_policy_id__isnull=False,
                    settlement_policy_version__isnull=False,
                    settlement_policy_hash__isnull=False,
                    execution_rule_v2_hash__isnull=False,
                    settlement_calendar_snapshot_id__isnull=False,
                    settlement_calendar_content_hash__isnull=False,
                    settlement_calendar_record_digest__isnull=False,
                    settlement_calendar_publication_id__isnull=False,
                    settlement_calendar_publication_hash__isnull=False,
                    settlement_calendar_policy_hash__isnull=False,
                    settlement_calendar_evidence_hash__isnull=False,
                    settlement_calendar_timezone__isnull=False,
                ),
                name="sim_trade_uow_binding_ck",
            ),
            models.CheckConstraint(
                condition=Q(
                    idempotency_key__isnull=True,
                    settlement_status__isnull=True,
                    settlement_release_date__isnull=True,
                    settlement_released_at__isnull=True,
                    settlement_release_session__isnull=True,
                    settlement_release_calendar_snapshot_id__isnull=True,
                    settlement_release_calendar_content_hash__isnull=True,
                    settlement_release_calendar_record_digest__isnull=True,
                    settlement_release_calendar_publication_id__isnull=True,
                    settlement_release_calendar_publication_hash__isnull=True,
                    settlement_release_calendar_policy_hash__isnull=True,
                    settlement_release_calendar_evidence_hash__isnull=True,
                    settlement_release_calendar_timezone__isnull=True,
                )
                | Q(
                    action="sell",
                    idempotency_key__isnull=False,
                    settlement_status__isnull=True,
                    settlement_release_date__isnull=True,
                    settlement_released_at__isnull=True,
                    settlement_release_session__isnull=True,
                    settlement_release_calendar_snapshot_id__isnull=True,
                    settlement_release_calendar_content_hash__isnull=True,
                    settlement_release_calendar_record_digest__isnull=True,
                    settlement_release_calendar_publication_id__isnull=True,
                    settlement_release_calendar_publication_hash__isnull=True,
                    settlement_release_calendar_policy_hash__isnull=True,
                    settlement_release_calendar_evidence_hash__isnull=True,
                    settlement_release_calendar_timezone__isnull=True,
                )
                | Q(
                    action="buy",
                    settlement_status="pending",
                    settlement_release_date__isnull=False,
                    settlement_released_at__isnull=True,
                    settlement_release_session__isnull=True,
                    settlement_release_calendar_snapshot_id__isnull=True,
                    settlement_release_calendar_content_hash__isnull=True,
                    settlement_release_calendar_record_digest__isnull=True,
                    settlement_release_calendar_publication_id__isnull=True,
                    settlement_release_calendar_publication_hash__isnull=True,
                    settlement_release_calendar_policy_hash__isnull=True,
                    settlement_release_calendar_evidence_hash__isnull=True,
                    settlement_release_calendar_timezone__isnull=True,
                )
                | Q(
                    action="buy",
                    settlement_status="released",
                    settlement_release_date__isnull=False,
                    settlement_released_at__isnull=False,
                    settlement_release_session__isnull=False,
                    settlement_release_calendar_snapshot_id__isnull=False,
                    settlement_release_calendar_content_hash__isnull=False,
                    settlement_release_calendar_record_digest__isnull=False,
                    settlement_release_calendar_publication_id__isnull=False,
                    settlement_release_calendar_publication_hash__isnull=False,
                    settlement_release_calendar_policy_hash__isnull=False,
                    settlement_release_calendar_evidence_hash__isnull=False,
                    settlement_release_calendar_timezone__isnull=False,
                ),
                name="sim_trade_settlement_release_ck",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.get_action_display()} {self.asset_name} x{self.quantity} @ {self.execution_date}"


class FeeConfigQuerySet(models.QuerySet["FeeConfigModel"]):
    """Prevent ORM bulk writes from rewriting immutable V2 policy rows."""

    def update(self, **kwargs: Any) -> int:
        """Allow mutable legacy updates but reject changes to strict versions."""

        if self.filter(fee_policy_id__isnull=False).exists():
            raise ValidationError("版本化模拟费率策略不可通过 QuerySet.update 修改")
        if any(field_name.startswith("fee_policy_") for field_name in kwargs):
            raise ValidationError("版本化模拟费率元数据只能由版本创建流程写入")
        legacy_rows = self.filter(fee_policy_id__isnull=True)
        return models.QuerySet.update(legacy_rows, **kwargs)

    def delete(self) -> tuple[int, dict[str, int]]:
        """Prevent bulk deletion of immutable V2 policy versions."""

        if self.filter(fee_policy_id__isnull=False).exists():
            raise ValidationError("版本化模拟费率策略不可通过 QuerySet.delete 删除")
        legacy_rows = self.filter(fee_policy_id__isnull=True)
        return models.QuerySet.delete(legacy_rows)


FeeConfigManager = models.Manager.from_queryset(FeeConfigQuerySet)


class FeeConfigModel(models.Model):
    """
    交易费率配置模型

    支持按资产类型配置不同的费率，可创建多套费率方案(如VIP/普通/低佣)
    """

    config_name = models.CharField("配置名称", max_length=100, unique=True)
    asset_type = models.CharField(
        "资产类型",
        max_length=20,
        choices=[("all", "通用"), ("equity", "股票"), ("fund", "基金"), ("bond", "债券")],
        default="all",
    )

    # 手续费(双向)
    commission_rate_buy = models.FloatField("买入手续费率", default=0.0003, help_text="默认0.03%")
    commission_rate_sell = models.FloatField("卖出手续费率", default=0.0003, help_text="默认0.03%")
    min_commission = models.FloatField("最低手续费(元)", help_text="不足按此收取")

    # 印花税(仅卖出,A股特有)
    stamp_duty_rate = models.FloatField(
        "印花税率(卖出)", default=0.001, help_text="默认0.1%,仅股票"
    )

    # 过户费(双向,仅上海市场股票)
    transfer_fee_rate = models.FloatField("过户费率", default=0.00002, help_text="默认0.002%")
    min_transfer_fee = models.FloatField("最低过户费(元)", default=0.0)

    # 滑点(模拟市场冲击)
    slippage_rate = models.FloatField("滑点率", default=0.001, help_text="默认0.1%")

    # 其他配置
    is_default = models.BooleanField("是否为默认配置", default=False, db_index=True)
    is_active = models.BooleanField("是否启用", default=True, db_index=True)
    description = models.TextField("配置说明", blank=True)

    # Exact-case V2 policy metadata. Legacy FeeConfig rows remain NULL here and
    # are intentionally ineligible for the new settlement-bound execution path.
    fee_policy_id = models.CharField(max_length=192, null=True, blank=True)
    fee_policy_version = models.PositiveIntegerField(null=True, blank=True)
    fee_policy_account_scope = models.CharField(max_length=32, null=True, blank=True)
    fee_policy_effective_from = models.DateTimeField(null=True, blank=True)
    fee_policy_valid_until = models.DateTimeField(null=True, blank=True)
    fee_policy_transaction_cases = models.JSONField(null=True, blank=True)
    fee_policy_content_hash = models.CharField(max_length=64, null=True, blank=True)

    # 元数据
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    objects = FeeConfigManager()

    class Meta:
        db_table = "simulated_fee_config"
        verbose_name = "交易费率配置"
        verbose_name_plural = "交易费率配置"
        ordering = ["asset_type", "config_name"]
        indexes = [
            models.Index(fields=["asset_type", "is_active"]),
            models.Index(fields=["is_default", "is_active"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["asset_type"],
                condition=Q(is_default=True),
                name="uniq_default_fee_config_per_asset_type",
            ),
            models.UniqueConstraint(
                fields=["fee_policy_id", "fee_policy_version"],
                condition=Q(fee_policy_id__isnull=False),
                name="uniq_sim_fee_policy_identity_v2",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        fee_policy_id__isnull=True,
                        fee_policy_version__isnull=True,
                        fee_policy_account_scope__isnull=True,
                        fee_policy_effective_from__isnull=True,
                        fee_policy_valid_until__isnull=True,
                        fee_policy_transaction_cases__isnull=True,
                        fee_policy_content_hash__isnull=True,
                    )
                    | Q(
                        fee_policy_id__isnull=False,
                        fee_policy_version__isnull=False,
                        fee_policy_account_scope__isnull=False,
                        fee_policy_effective_from__isnull=False,
                        fee_policy_valid_until__isnull=False,
                        fee_policy_transaction_cases__isnull=False,
                        fee_policy_content_hash__isnull=False,
                    )
                ),
                name="sim_fee_policy_v2_complete_ck",
            ),
            models.CheckConstraint(
                condition=Q(fee_policy_id__isnull=True)
                | Q(fee_policy_effective_from__lt=models.F("fee_policy_valid_until")),
                name="sim_fee_policy_v2_window_ck",
            ),
            models.CheckConstraint(
                condition=Q(fee_policy_id__isnull=True)
                | Q(created_at__lt=models.F("fee_policy_valid_until")),
                name="sim_fee_policy_v2_known_window_ck",
            ),
        ]
        indexes += [
            models.Index(
                fields=["fee_policy_id", "fee_policy_effective_from", "fee_policy_valid_until"],
                name="sim_fee_policy_window_idx",
            )
        ]

    def __str__(self) -> str:
        return f"{self.config_name} ({self.get_asset_type_display()})"

    def clean(self) -> None:
        """Validate finite, non-negative transaction fee parameters."""

        super().clean()
        rate_fields = (
            "commission_rate_buy",
            "commission_rate_sell",
            "stamp_duty_rate",
            "transfer_fee_rate",
            "slippage_rate",
        )
        errors: dict[str, str] = {}
        for field_name in rate_fields:
            value = getattr(self, field_name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not isfinite(float(value))
                or not 0 <= float(value) <= 1
            ):
                errors[field_name] = "必须是 0 到 1 之间的有限数值"
        for field_name in ("min_commission", "min_transfer_fee"):
            value = getattr(self, field_name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not isfinite(float(value))
                or float(value) < 0
            ):
                errors[field_name] = "必须是非负有限数值"
        if errors:
            raise ValidationError(errors)

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Validate and atomically switch the default fee configuration."""

        # Preserve raw Python types so direct ORM writes cannot coerce bool to 1.0.
        using = kwargs.get("using")
        if using is None:
            using = router.db_for_write(type(self), instance=self)
        kwargs["using"] = using
        if self.pk is not None:
            current_policy_id = (
                FeeConfigModel._base_manager.using(using)
                .filter(pk=self.pk)
                .values_list("fee_policy_id", flat=True)
                .first()
            )
            if current_policy_id is not None:
                raise ValidationError("版本化模拟费率策略不可通过 Model.save 修改")
        self.clean()
        self.full_clean(validate_unique=False, validate_constraints=False)
        with transaction.atomic(using=using):
            if self.is_default:
                FeeConfigModel._default_manager.filter(
                    asset_type=self.asset_type,
                    is_default=True,
                ).using(using).exclude(id=self.id).update(is_default=False)
            super().save(*args, **kwargs)

    def delete(
        self,
        using: str | None = None,
        keep_parents: bool = False,
    ) -> tuple[int, dict[str, int]]:
        """Keep strict versions append-only while preserving legacy deletion."""

        if self.pk is None:
            raise ValueError("FeeConfigModel object cannot be deleted because its pk is None")
        database = using or self._state.db or router.db_for_write(type(self), instance=self)
        current_policy_id = (
            FeeConfigModel._base_manager.using(database)
            .filter(pk=self.pk)
            .values_list("fee_policy_id", flat=True)
            .first()
        )
        if current_policy_id is not None:
            raise ValidationError("版本化模拟费率策略不可删除")
        deleted, per_model = (
            FeeConfigModel._default_manager.using(database)
            .filter(pk=self.pk, fee_policy_id__isnull=True)
            .delete()
        )
        if deleted:
            self.pk = None
        return deleted, per_model


class DailyInspectionReportModel(models.Model):
    """日更巡检报告（账户维度）"""

    account = models.ForeignKey(
        SimulatedAccountModel,
        on_delete=models.CASCADE,
        related_name="inspection_reports",
        verbose_name="所属账户",
    )
    strategy = models.ForeignKey(
        "strategy.StrategyModel",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inspection_reports",
        verbose_name="关联策略",
    )
    position_rule = models.ForeignKey(
        "strategy.PositionManagementRuleModel",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inspection_reports",
        verbose_name="仓位规则",
    )
    inspection_date = models.DateField("巡检日期", db_index=True)
    status = models.CharField(
        "巡检状态",
        max_length=20,
        choices=[
            ("ok", "正常"),
            ("warning", "预警"),
            ("error", "异常"),
        ],
        default="ok",
        db_index=True,
    )
    macro_regime = models.CharField("宏观象限", max_length=32, blank=True, default="")
    policy_gear = models.CharField("政策档位", max_length=8, blank=True, default="")
    total_value = models.DecimalField("账户总资产", max_digits=15, decimal_places=2, default=0)
    current_cash = models.DecimalField("账户现金", max_digits=15, decimal_places=2, default=0)
    current_market_value = models.DecimalField(
        "持仓市值", max_digits=15, decimal_places=2, default=0
    )
    checks = models.JSONField("巡检明细", default=list, blank=True)
    summary = models.JSONField("巡检汇总", default=dict, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        db_table = "simulated_daily_inspection_report"
        verbose_name = "模拟盘日更巡检报告"
        verbose_name_plural = "模拟盘日更巡检报告"
        ordering = ["-inspection_date", "-updated_at"]
        unique_together = [["account", "inspection_date"]]
        indexes = [
            models.Index(fields=["account", "-inspection_date"]),
            models.Index(fields=["inspection_date", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.account.account_name} - {self.inspection_date} ({self.status})"


class DailyInspectionNotificationConfigModel(models.Model):
    """日更巡检邮件通知配置（账户维度）"""

    account = models.OneToOneField(
        SimulatedAccountModel,
        on_delete=models.CASCADE,
        related_name="inspection_notification_config",
        verbose_name="所属账户",
    )
    is_enabled = models.BooleanField("启用邮件通知", default=True)
    notify_on = models.CharField(
        "触发级别",
        max_length=20,
        choices=[
            ("warning_error", "仅预警/异常"),
            ("all", "所有状态"),
        ],
        default="warning_error",
    )
    include_owner_email = models.BooleanField("包含账户所有者邮箱", default=True)
    recipient_emails = models.JSONField("额外收件人", default=list, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        db_table = "simulated_daily_inspection_notify_config"
        verbose_name = "模拟盘巡检通知配置"
        verbose_name_plural = "模拟盘巡检通知配置"

    def __str__(self) -> str:
        return f"{self.account.account_name} notify={self.is_enabled}"


class DailyNetValueModel(models.Model):
    """
    每日净值记录模型

    用于记录账户每日的净值数据，支持绘制净值曲线和计算绩效指标。
    """

    account = models.ForeignKey(
        SimulatedAccountModel,
        on_delete=models.CASCADE,
        related_name="daily_net_values",
        verbose_name="所属账户",
        db_index=True,
    )

    record_date = models.DateField("记录日期", db_index=True)
    net_value = models.DecimalField(
        "净值", max_digits=15, decimal_places=4, help_text="账户总资产（元）"
    )
    cash = models.DecimalField("现金", max_digits=15, decimal_places=2, help_text="可用现金（元）")
    market_value = models.DecimalField(
        "持仓市值", max_digits=15, decimal_places=2, help_text="持仓市值（元）"
    )
    daily_return = models.FloatField("日收益率(%)", default=0.0, help_text="相对于前一日的收益率")
    cumulative_return = models.FloatField(
        "累计收益率(%)", default=0.0, help_text="相对于初始资金的收益率"
    )
    drawdown = models.FloatField("回撤(%)", default=0.0, help_text="相对于历史最高点的回撤")

    # 统计信息
    total_trades = models.IntegerField("当日交易次数", default=0)
    positions_count = models.IntegerField("持仓数量", default=0)

    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        db_table = "simulated_daily_net_value"
        verbose_name = "每日净值记录"
        verbose_name_plural = "每日净值记录"
        ordering = ["record_date"]
        unique_together = [["account", "record_date"]]
        indexes = [
            models.Index(fields=["account", "-record_date"]),
            models.Index(fields=["-record_date"]),
        ]

    def __str__(self) -> str:
        return f"{self.account.account_name} - {self.record_date} - 净值:{self.net_value}"


class RebalanceProposalModel(models.Model):
    """
    再平衡建议草案模型

    存储日更巡检生成的再平衡建议，支持追踪建议来源和执行状态。
    """

    # 建议来源类型
    SOURCE_DAILY_INSPECTION = "daily_inspection"
    SOURCE_SIGNAL = "signal"
    SOURCE_MANUAL = "manual"
    SOURCE_REGIME_CHANGE = "regime_change"
    SOURCE_POLICY_CHANGE = "policy_change"

    SOURCE_CHOICES = [
        (SOURCE_DAILY_INSPECTION, "日更巡检"),
        (SOURCE_SIGNAL, "投资信号"),
        (SOURCE_MANUAL, "手动创建"),
        (SOURCE_REGIME_CHANGE, "宏观象限变化"),
        (SOURCE_POLICY_CHANGE, "政策档位变化"),
    ]

    # 执行状态
    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_EXECUTING = "executing"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = [
        (STATUS_PENDING, "待审核"),
        (STATUS_APPROVED, "已批准"),
        (STATUS_REJECTED, "已拒绝"),
        (STATUS_EXECUTING, "执行中"),
        (STATUS_COMPLETED, "已完成"),
        (STATUS_FAILED, "执行失败"),
        (STATUS_CANCELLED, "已取消"),
    ]

    # 关联账户
    account = models.ForeignKey(
        SimulatedAccountModel,
        on_delete=models.CASCADE,
        related_name="rebalance_proposals",
        verbose_name="所属账户",
        db_index=True,
    )

    # 关联巡检报告（可选）
    inspection_report = models.ForeignKey(
        DailyInspectionReportModel,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rebalance_proposals",
        verbose_name="关联巡检报告",
    )

    # 关联策略（可选）
    strategy = models.ForeignKey(
        "strategy.StrategyModel",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rebalance_proposals",
        verbose_name="关联策略",
    )

    # 建议来源
    source = models.CharField(
        "建议来源",
        max_length=50,
        choices=SOURCE_CHOICES,
        default=SOURCE_DAILY_INSPECTION,
        db_index=True,
    )

    source_description = models.TextField(
        "来源描述",
        blank=True,
        help_text="建议生成的原因说明",
    )

    # 状态
    status = models.CharField(
        "执行状态",
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
    )

    # 优先级
    priority = models.CharField(
        "优先级",
        max_length=20,
        choices=[
            ("low", "低"),
            ("normal", "普通"),
            ("high", "高"),
            ("urgent", "紧急"),
        ],
        default="normal",
        db_index=True,
    )

    # 建议详情（JSON）
    proposals = models.JSONField(
        "再平衡建议",
        default=list,
        help_text="""再平衡建议列表:
        [
            {
                "asset_code": "512880.SH",
                "asset_name": "证券ETF",
                "action": "buy" | "sell" | "hold",
                "current_quantity": 1000,
                "current_weight": 0.25,
                "target_weight": 0.30,
                "suggested_quantity": 200,
                "reason": "仓位偏离目标",
                "estimated_amount": 5000.00
            }
        ]
        """,
    )

    # 汇总信息（JSON）
    summary = models.JSONField(
        "汇总信息",
        default=dict,
        help_text="""汇总信息:
        {
            "total_value": 100000.00,
            "current_cash": 5000.00,
            "rebalance_assets": ["512880.SH", "515050.SH"],
            "buy_count": 2,
            "sell_count": 1,
            "estimated_trade_amount": 15000.00
        }
        """,
    )

    # 审计字段
    proposed_by = models.CharField(
        "建议人",
        max_length=100,
        default="system",
        help_text="谁创建了这个建议",
    )

    proposed_at = models.DateTimeField(
        "建议时间",
        auto_now_add=True,
        db_index=True,
    )

    # 审核字段
    reviewed_by = models.CharField(
        "审核人",
        max_length=100,
        blank=True,
    )

    reviewed_at = models.DateTimeField(
        "审核时间",
        null=True,
        blank=True,
    )

    review_comment = models.TextField(
        "审核意见",
        blank=True,
    )

    # 执行字段
    executed_by = models.CharField(
        "执行人",
        max_length=100,
        blank=True,
    )

    executed_at = models.DateTimeField(
        "执行时间",
        null=True,
        blank=True,
    )

    execution_result = models.JSONField(
        "执行结果",
        null=True,
        blank=True,
        help_text="实际执行的交易结果",
    )

    # 元数据
    metadata = models.JSONField(
        "元数据",
        default=dict,
        blank=True,
        help_text="额外的上下文信息",
    )

    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        db_table = "simulated_rebalance_proposal"
        verbose_name = "再平衡建议草案"
        verbose_name_plural = "再平衡建议草案"
        ordering = ["-proposed_at"]
        indexes = [
            models.Index(fields=["account", "-proposed_at"]),
            models.Index(fields=["status", "-proposed_at"]),
            models.Index(fields=["source", "-proposed_at"]),
            models.Index(fields=["priority", "-proposed_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.account.account_name} - {self.get_source_display()} - {self.get_status_display()}"

    def approve(self, reviewed_by: str, comment: str = "") -> None:
        """批准建议"""
        self.status = self.STATUS_APPROVED
        self.reviewed_by = reviewed_by
        self.reviewed_at = timezone.now()
        self.review_comment = comment
        self.save()

    def reject(self, reviewed_by: str, comment: str) -> None:
        """拒绝建议"""
        self.status = self.STATUS_REJECTED
        self.reviewed_by = reviewed_by
        self.reviewed_at = timezone.now()
        self.review_comment = comment
        self.save()

    def start_execution(self, executed_by: str) -> None:
        """开始执行"""
        self.status = self.STATUS_EXECUTING
        self.executed_by = executed_by
        self.save()

    def complete_execution(self, result: dict[str, Any]) -> None:
        """完成执行"""
        self.status = self.STATUS_COMPLETED
        self.executed_at = timezone.now()
        self.execution_result = result
        self.save()

    def fail_execution(self, error: str) -> None:
        """执行失败"""
        self.status = self.STATUS_FAILED
        self.executed_at = timezone.now()
        self.execution_result = {"error": error}
        self.save()

    def cancel(self) -> None:
        """取消建议"""
        self.status = self.STATUS_CANCELLED
        self.save()

    def get_rebalance_actions(self) -> dict[str, Any]:
        """获取再平衡操作汇总"""
        buy_actions = [p for p in self.proposals if p.get("action") == "buy"]
        sell_actions = [p for p in self.proposals if p.get("action") == "sell"]

        return {
            "buy_count": len(buy_actions),
            "sell_count": len(sell_actions),
            "buy_assets": [p["asset_code"] for p in buy_actions],
            "sell_assets": [p["asset_code"] for p in sell_actions],
            "total_buy_amount": sum(p.get("estimated_amount", 0) for p in buy_actions),
            "total_sell_amount": sum(p.get("estimated_amount", 0) for p in sell_actions),
        }


class NotificationHistoryModel(models.Model):
    """
    通知历史记录模型

    记录所有发送的通知，用于追踪和审计。
    """

    # 通知通道类型
    CHANNEL_EMAIL = "email"
    CHANNEL_IN_APP = "in_app"
    CHANNEL_ALERT = "alert"
    CHANNEL_SMS = "sms"
    CHANNEL_WEBHOOK = "webhook"

    CHANNEL_CHOICES = [
        (CHANNEL_EMAIL, "邮件"),
        (CHANNEL_IN_APP, "站内"),
        (CHANNEL_ALERT, "告警"),
        (CHANNEL_SMS, "短信"),
        (CHANNEL_WEBHOOK, "Webhook"),
    ]

    # 通知状态
    STATUS_PENDING = "pending"
    STATUS_SENDING = "sending"
    STATUS_SENT = "sent"
    STATUS_FAILED = "failed"
    STATUS_RETRYING = "retrying"

    STATUS_CHOICES = [
        (STATUS_PENDING, "待发送"),
        (STATUS_SENDING, "发送中"),
        (STATUS_SENT, "已发送"),
        (STATUS_FAILED, "发送失败"),
        (STATUS_RETRYING, "重试中"),
    ]

    # 关联账户（可选）
    account = models.ForeignKey(
        SimulatedAccountModel,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notifications",
        verbose_name="关联账户",
        db_index=True,
    )

    # 关联再平衡建议（可选）
    rebalance_proposal = models.ForeignKey(
        RebalanceProposalModel,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notifications",
        verbose_name="关联再平衡建议",
    )

    # 通知类型
    notification_type = models.CharField(
        "通知类型",
        max_length=50,
        help_text="如: daily_inspection, rebalance_proposal, position_invalidated",
        db_index=True,
    )

    # 通道
    channel = models.CharField(
        "通知通道",
        max_length=20,
        choices=CHANNEL_CHOICES,
        db_index=True,
    )

    # 接收者
    recipient_user_id = models.IntegerField(
        "接收者用户ID",
        null=True,
        blank=True,
        db_index=True,
    )

    recipient_email = models.EmailField(
        "接收者邮箱",
        null=True,
        blank=True,
    )

    # 通知内容
    subject = models.CharField(
        "通知主题",
        max_length=500,
    )

    body = models.TextField(
        "通知内容",
    )

    # 状态
    status = models.CharField(
        "发送状态",
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
    )

    # 错误信息
    error_message = models.TextField(
        "错误信息",
        blank=True,
    )

    # 重试信息
    retry_count = models.IntegerField(
        "重试次数",
        default=0,
    )

    # 时间
    created_at = models.DateTimeField(
        "创建时间",
        auto_now_add=True,
        db_index=True,
    )

    sent_at = models.DateTimeField(
        "发送时间",
        null=True,
        blank=True,
    )

    # 元数据
    metadata = models.JSONField(
        "元数据",
        default=dict,
        blank=True,
    )

    class Meta:
        db_table = "simulated_notification_history"
        verbose_name = "通知历史记录"
        verbose_name_plural = "通知历史记录"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["account", "-created_at"]),
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["channel", "-created_at"]),
            models.Index(fields=["notification_type", "-created_at"]),
            models.Index(fields=["recipient_user_id", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.notification_type} - {self.recipient_email or self.recipient_user_id} - {self.status}"

    def mark_sent(self) -> None:
        """标记为已发送"""
        self.status = self.STATUS_SENT
        self.sent_at = timezone.now()
        self.save()

    def mark_failed(self, error: str) -> None:
        """标记为失败"""
        self.status = self.STATUS_FAILED
        self.error_message = error
        self.save()

    def increment_retry(self) -> None:
        """增加重试计数"""
        self.retry_count += 1
        self.status = self.STATUS_RETRYING
        self.save()


# Backward compatibility alias for legacy imports
SimulatedPositionModel = PositionModel


class LedgerMigrationMapModel(models.Model):
    """
    账本迁移映射表

    跟踪 apps/account 旧模型记录迁移到 simulated_trading 统一账本的 ID 对应关系。
    用于幂等重跑和迁移校验。

    Phase-3 产物，迁移完成后可废弃但建议保留以便审计。
    """

    SOURCE_APP_CHOICES = [
        ("account", "account app"),
    ]
    SOURCE_TABLE_CHOICES = [
        ("portfolio", "PortfolioModel"),
        ("position", "PositionModel (account)"),
        ("transaction", "TransactionModel"),
    ]
    TARGET_TABLE_CHOICES = [
        ("simulated_account", "SimulatedAccountModel"),
        ("simulated_position", "PositionModel (simulated_trading)"),
        ("simulated_trade", "SimulatedTradeModel"),
    ]

    source_app = models.CharField(
        "来源应用", max_length=50, choices=SOURCE_APP_CHOICES, default="account"
    )
    source_table = models.CharField("来源表", max_length=50, choices=SOURCE_TABLE_CHOICES)
    source_id = models.IntegerField("来源ID")
    target_table = models.CharField("目标表", max_length=50, choices=TARGET_TABLE_CHOICES)
    target_id = models.IntegerField("目标ID")
    migrated_at = models.DateTimeField("迁移时间", auto_now_add=True)
    notes = models.CharField("备注", max_length=500, blank=True)

    class Meta:
        db_table = "ledger_migration_map"
        verbose_name = "账本迁移映射"
        verbose_name_plural = "账本迁移映射"
        unique_together = [["source_app", "source_table", "source_id"]]
        indexes = [
            models.Index(fields=["source_app", "source_table", "source_id"]),
            models.Index(fields=["target_table", "target_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.source_table}:{self.source_id} → {self.target_table}:{self.target_id}"


# ============================================================================
# 统一账户业绩域 ORM 模型
# ============================================================================


class AccountBenchmarkComponentModel(models.Model):
    """
    账户基准成分配置

    一个账户可配置多个基准成分，构成加权组合基准。
    应用层写入时强制归一化权重，总和必须大于 0。
    """

    account = models.ForeignKey(
        SimulatedAccountModel,
        on_delete=models.CASCADE,
        related_name="benchmark_components",
        verbose_name="所属账户",
        db_index=True,
    )
    benchmark_code = models.CharField("基准代码", max_length=30, help_text="如 000300.SH")
    weight = models.FloatField("权重（归一化后）", help_text="归一化后总和为 1.0")
    display_name = models.CharField("显示名称", max_length=100, blank=True, help_text="如 沪深300")
    sort_order = models.IntegerField("排序", default=0)
    is_active = models.BooleanField("是否启用", default=True, db_index=True)

    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        db_table = "account_benchmark_component"
        verbose_name = "账户基准成分"
        verbose_name_plural = "账户基准成分"
        ordering = ["account", "sort_order"]
        indexes = [
            models.Index(fields=["account", "is_active"]),
            models.Index(fields=["account", "sort_order"]),
        ]

    def __str__(self) -> str:
        return f"{self.account.account_name} / {self.benchmark_code} ({self.weight:.0%})"


class UnifiedAccountCashFlowModel(models.Model):
    """
    统一账户外部现金流

    统一存储所有账户的外部现金流：
    - 真实盘：从 CapitalFlowModel 回填并持续镜像
    - 模拟盘：默认写入一笔 initial_capital 初始入金
    """

    FLOW_TYPE_CHOICES = [
        ("initial_capital", "初始入金"),
        ("deposit", "追加入金"),
        ("withdrawal", "取款出金"),
        ("dividend", "股息/分红"),
        ("interest", "利息"),
        ("adjustment", "手工调整"),
    ]

    account = models.ForeignKey(
        SimulatedAccountModel,
        on_delete=models.CASCADE,
        related_name="cash_flows",
        verbose_name="所属账户",
        db_index=True,
    )
    flow_type = models.CharField(
        "现金流类型", max_length=20, choices=FLOW_TYPE_CHOICES, db_index=True
    )
    amount = models.DecimalField(
        "金额（元）", max_digits=15, decimal_places=2, help_text="正数=入金，负数=出金"
    )
    flow_date = models.DateField("发生日期", db_index=True)
    source_app = models.CharField(
        "来源应用", max_length=50, help_text="account 或 simulated_trading"
    )
    source_id = models.CharField("来源记录ID", max_length=50, blank=True, default="")
    notes = models.CharField("备注", max_length=500, blank=True, default="")

    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        db_table = "unified_account_cash_flow"
        verbose_name = "统一账户现金流"
        verbose_name_plural = "统一账户现金流"
        ordering = ["account", "flow_date"]
        indexes = [
            models.Index(fields=["account", "flow_date"]),
            models.Index(fields=["account", "flow_type"]),
            models.Index(fields=["source_app", "source_id"]),
        ]

    def __str__(self) -> str:
        sign = "+" if float(self.amount) >= 0 else ""
        return f"{self.account.account_name} / {self.flow_date} / {sign}{self.amount}"


class AccountPositionValuationSnapshotModel(models.Model):
    """
    账户持仓时点估值快照

    每日快照记录，用于历史持仓估值表查询和未来稳定查询。
    通过 TransactionModel / SimulatedTradeModel 回放 + 历史收盘价填充。
    """

    account = models.ForeignKey(
        SimulatedAccountModel,
        on_delete=models.CASCADE,
        related_name="position_valuation_snapshots",
        verbose_name="所属账户",
        db_index=True,
    )
    record_date = models.DateField("记录日期", db_index=True)
    asset_code = models.CharField("资产代码", max_length=20)
    asset_name = models.CharField("资产名称", max_length=100, blank=True, default="")
    asset_type = models.CharField(
        "资产类型",
        max_length=20,
        choices=[
            ("equity", "股票"),
            ("fund", "基金"),
            ("bond", "债券"),
            ("cash", "现金"),
            ("other", "其他"),
        ],
    )
    quantity = models.DecimalField("持仓数量", max_digits=20, decimal_places=6)
    avg_cost = models.DecimalField("平均成本（元）", max_digits=10, decimal_places=4, default=0)
    close_price = models.DecimalField("收盘价（元）", max_digits=10, decimal_places=4, default=0)
    market_value = models.DecimalField("市值（元）", max_digits=15, decimal_places=2)
    weight = models.FloatField("仓位占比（市值/总市值）", default=0.0)
    unrealized_pnl = models.DecimalField(
        "浮动盈亏（元）", max_digits=15, decimal_places=2, default=0
    )
    unrealized_pnl_pct = models.FloatField("浮动盈亏率（%）", default=0.0)

    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        db_table = "account_position_valuation_snapshot"
        verbose_name = "持仓时点估值快照"
        verbose_name_plural = "持仓时点估值快照"
        ordering = ["account", "-record_date", "asset_code"]
        unique_together = [["account", "record_date", "asset_code"]]
        indexes = [
            models.Index(fields=["account", "-record_date"]),
            models.Index(fields=["account", "record_date", "asset_code"]),
            models.Index(fields=["asset_code", "-record_date"]),
        ]

    def __str__(self) -> str:
        return f"{self.account.account_name} / {self.record_date} / {self.asset_code}"
