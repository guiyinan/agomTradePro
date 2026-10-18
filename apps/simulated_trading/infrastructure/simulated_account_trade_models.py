"""Account, position, and trade ORM models for simulated trading."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


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
    cash_known = models.BooleanField("现金余额是否有依据", default=False)
    cash_reconciliation_status = models.CharField(
        "现金核对状态",
        max_length=24,
        choices=[
            ("simulated_ledger", "模拟账本"),
            ("unverified", "未核实"),
            ("quantity_only", "仅同步持仓数量"),
        ],
        default="unverified",
    )
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
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(
                        account_type="simulated",
                        cash_known=True,
                        cash_reconciliation_status="simulated_ledger",
                    )
                    | Q(
                        account_type="real",
                        cash_known=False,
                        cash_reconciliation_status__in=("unverified", "quantity_only"),
                    )
                ),
                name="sim_account_cash_knowledge_ck",
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Derive cash knowledge from the owning ledger before persisting an account."""

        if self.account_type == "simulated":
            self.cash_known = True
            self.cash_reconciliation_status = "simulated_ledger"
        elif self.account_type == "real":
            self.cash_known = False
            if self.cash_reconciliation_status == "simulated_ledger":
                self.cash_reconciliation_status = "unverified"

        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = tuple(
                dict.fromkeys((*update_fields, "cash_known", "cash_reconciliation_status"))
            )
        super().save(*args, **kwargs)

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
    available_quantity_known = models.BooleanField("可卖数量是否已知", default=True)

    # 成本信息
    avg_cost = models.DecimalField("平均成本(元)", max_digits=10, decimal_places=4)
    total_cost = models.DecimalField("总成本(元)", max_digits=15, decimal_places=2)
    cost_basis_known = models.BooleanField("成本基数是否已知", null=True, blank=True, default=None)

    # 当前信息
    current_price = models.DecimalField("当前价格(元)", max_digits=10, decimal_places=4)
    market_value = models.DecimalField("市值(元)", max_digits=15, decimal_places=2)
    valuation_known = models.BooleanField("持仓估值是否已知", default=True)

    # 盈亏信息
    unrealized_pnl = models.DecimalField("浮动盈亏(元)", max_digits=15, decimal_places=2, default=0)
    unrealized_pnl_pct = models.FloatField("浮动盈亏率(%)", default=0.0)

    # 时间信息
    first_buy_date = models.DateField("首次买入日期")
    first_buy_date_known = models.BooleanField("首次买入日期是否已知", default=True)
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
    fee_amounts_known = models.BooleanField(
        "费用金额是否完整已知", null=True, blank=True, default=None
    )
    cost_basis_known = models.BooleanField("成本基数是否已知", null=True, blank=True, default=None)

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
    execution_time = models.DateTimeField(
        "执行时间", default=timezone.now, editable=False, blank=True
    )

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
                )
                | Q(
                    settlement_plan_binding_version=3,
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
