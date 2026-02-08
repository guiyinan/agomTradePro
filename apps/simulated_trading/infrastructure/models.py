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
from django.db import models
from django.conf import settings


class SimulatedAccountModel(models.Model):
    """
    投资组合账户模型（统一）

    ⭐ 重构说明：
    - 统一管理实仓和模拟仓
    - 用户可以创建多个投资组合
    - 每个投资组合可以选择类型：real（实仓）或 simulated（模拟仓）
    - 替代老的 PortfolioModel 系统
    """

    # ⭐ 新增：用户外键
    # TODO: 创建迁移后需要数据迁移为现有数据分配用户，然后改为 null=False
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='investment_accounts',
        verbose_name="用户",
        db_index=True,
        null=True,
        blank=True
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
        db_index=True
    )

    # 资金信息
    initial_capital = models.DecimalField("初始资金(元)", max_digits=15, decimal_places=2)
    current_cash = models.DecimalField("当前现金(元)", max_digits=15, decimal_places=2)
    current_market_value = models.DecimalField("当前持仓市值(元)", max_digits=15, decimal_places=2, default=0)
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

    def __str__(self):
        type_label = "实仓" if self.account_type == "real" else "模拟仓"
        return f"{self.account_name} ({type_label})"


class PositionModel(models.Model):
    """持仓模型"""

    account = models.ForeignKey(
        SimulatedAccountModel,
        on_delete=models.CASCADE,
        related_name="positions",
        verbose_name="所属账户"
    )

    asset_code = models.CharField("资产代码", max_length=20, db_index=True)
    asset_name = models.CharField("资产名称", max_length=100)
    asset_type = models.CharField(
        "资产类型",
        max_length=20,
        choices=[
            ("equity", "股票"),
            ("fund", "基金"),
            ("bond", "债券")
        ]
    )

    # 持仓数量
    quantity = models.IntegerField("持仓数量")
    available_quantity = models.IntegerField("可卖数量")

    # 成本信息
    avg_cost = models.DecimalField("平均成本(元)", max_digits=10, decimal_places=4)
    total_cost = models.DecimalField("总成本(元)", max_digits=15, decimal_places=2)

    # 当前信息
    current_price = models.DecimalField("当前价格(元)", max_digits=10, decimal_places=4)
    market_value = models.DecimalField("市值(元)", max_digits=15, decimal_places=2)

    # 盈亏信息
    unrealized_pnl = models.DecimalField("浮动盈亏(元)", max_digits=15, decimal_places=2)
    unrealized_pnl_pct = models.FloatField("浮动盈亏率(%)")

    # 时间信息
    first_buy_date = models.DateField("首次买入日期")
    last_update_date = models.DateField("最后更新日期", auto_now=True)

    # 关联信号
    signal_id = models.IntegerField("关联信号ID", null=True, blank=True)
    entry_reason = models.CharField("入场原因", max_length=200, blank=True)

    # ==================== 证伪条件跟踪 ====================
    # 从信号继承的证伪条件（副本，即使信号被删除也不影响）
    invalidation_rule_json = models.JSONField(
        "证伪规则",
        null=True,
        blank=True,
        help_text="从信号继承的结构化证伪规则"
    )
    invalidation_description = models.TextField(
        "证伪描述",
        blank=True,
        help_text="人类可读的证伪条件描述"
    )

    # 证伪状态
    is_invalidated = models.BooleanField(
        "是否已证伪",
        default=False,
        db_index=True,
        help_text="证伪条件已满足，建议平仓"
    )
    invalidation_reason = models.TextField(
        "证伪原因",
        blank=True,
        help_text="证伪原因说明"
    )
    invalidation_checked_at = models.DateTimeField(
        "最后检查时间",
        null=True,
        blank=True,
        help_text="最后一次检查证伪条件的时间"
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

    def __str__(self):
        return f"{self.asset_name} ({self.quantity})"


class SimulatedTradeModel(models.Model):
    """模拟交易记录模型"""

    account = models.ForeignKey(
        SimulatedAccountModel,
        on_delete=models.CASCADE,
        related_name="trades",
        verbose_name="所属账户"
    )

    # 资产信息
    asset_code = models.CharField("资产代码", max_length=20, db_index=True)
    asset_name = models.CharField("资产名称", max_length=100)
    asset_type = models.CharField("资产类型", max_length=20)

    # 交易信息
    action = models.CharField(
        "交易动作",
        max_length=10,
        choices=[("buy", "买入"), ("sell", "卖出")]
    )
    quantity = models.IntegerField("交易数量")
    price = models.DecimalField("成交价格(元)", max_digits=10, decimal_places=4)
    amount = models.DecimalField("成交金额(元)", max_digits=15, decimal_places=2)

    # 费用
    commission = models.DecimalField("手续费(元)", max_digits=10, decimal_places=2, default=0)
    slippage = models.DecimalField("滑点损失(元)", max_digits=10, decimal_places=2, default=0)
    total_cost = models.DecimalField("总成本(元)", max_digits=15, decimal_places=2)

    # 盈亏(仅SELL时有)
    realized_pnl = models.DecimalField("已实现盈亏(元)", max_digits=15, decimal_places=2, null=True, blank=True)
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
            ("failed", "执行失败")
        ],
        default="pending"
    )

    # 元数据
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        db_table = "simulated_trade"
        verbose_name = "模拟交易记录"
        verbose_name_plural = "模拟交易记录"
        ordering = ["-execution_date", "-execution_time"]
        indexes = [
            models.Index(fields=["account", "-execution_date"]),
            models.Index(fields=["asset_code", "-execution_date"]),
            models.Index(fields=["-execution_date"]),
        ]

    def __str__(self):
        return f"{self.get_action_display()} {self.asset_name} x{self.quantity} @ {self.execution_date}"


class FeeConfigModel(models.Model):
    """
    交易费率配置模型

    支持按资产类型配置不同的费率，可创建多套费率方案(如VIP/普通/低佣)
    """

    config_name = models.CharField("配置名称", max_length=100, unique=True)
    asset_type = models.CharField(
        "资产类型",
        max_length=20,
        choices=[
            ("all", "通用"),
            ("equity", "股票"),
            ("fund", "基金"),
            ("bond", "债券")
        ],
        default="all"
    )

    # 手续费(双向)
    commission_rate_buy = models.FloatField("买入手续费率", default=0.0003, help_text="默认0.03%")
    commission_rate_sell = models.FloatField("卖出手续费率", default=0.0003, help_text="默认0.03%")
    min_commission = models.FloatField("最低手续费(元)", default=5.0, help_text="不足按此收取")

    # 印花税(仅卖出,A股特有)
    stamp_duty_rate = models.FloatField("印花税率(卖出)", default=0.001, help_text="默认0.1%,仅股票")

    # 过户费(双向,仅上海市场股票)
    transfer_fee_rate = models.FloatField("过户费率", default=0.00002, help_text="默认0.002%")
    min_transfer_fee = models.FloatField("最低过户费(元)", default=0.0)

    # 滑点(模拟市场冲击)
    slippage_rate = models.FloatField("滑点率", default=0.001, help_text="默认0.1%")

    # 其他配置
    is_default = models.BooleanField("是否为默认配置", default=False, db_index=True)
    is_active = models.BooleanField("是否启用", default=True, db_index=True)
    description = models.TextField("配置说明", blank=True)

    # 元数据
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        db_table = "simulated_fee_config"
        verbose_name = "交易费率配置"
        verbose_name_plural = "交易费率配置"
        ordering = ["asset_type", "config_name"]
        indexes = [
            models.Index(fields=["asset_type", "is_active"]),
            models.Index(fields=["is_default", "is_active"]),
        ]

    def __str__(self):
        return f"{self.config_name} ({self.get_asset_type_display()})"

    def save(self, *args, **kwargs):
        """保存时确保只有一个默认配置"""
        if self.is_default:
            # 将其他默认配置设为非默认
            FeeConfigModel._default_manager.filter(
                asset_type=self.asset_type,
                is_default=True
            ).exclude(id=self.id).update(is_default=False)
        super().save(*args, **kwargs)


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
    current_market_value = models.DecimalField("持仓市值", max_digits=15, decimal_places=2, default=0)
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

    def __str__(self):
        return f"{self.account.account_name} - {self.inspection_date} ({self.status})"

