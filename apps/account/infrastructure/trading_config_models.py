"""
交易配置与投资规则 ORM 模型

包含投资规则、组合级/市场级交易成本配置、止损止盈配置与触发记录、
宏观感知仓位系数配置。
"""

from decimal import Decimal
from typing import Any

from django.contrib.auth.models import User
from django.db import models

from .portfolio_models import PortfolioModel, PositionModel

__all__ = [
    "InvestmentRuleModel",
    "MacroSizingConfigModel",
    "StopLossConfigModel",
    "StopLossTriggerModel",
    "TakeProfitConfigModel",
    "TradingCostConfigModel",
    "TransactionCostConfigModel",
]


class InvestmentRuleModel(models.Model):
    """
    投资规则配置表

    存储系统生成的投资建议规则，支持动态配置。

    易用性改进 - AI助手降级增强：
    - 新增组合规则类型（regime_policy_combo, match_position_combo等）
    - 支持Policy档位建议
    - 支持静态保底规则
    """

    RULE_TYPE_CHOICES = [
        # 组合规则（最高优先级）
        ("regime_policy_combo", "Regime+Policy组合"),
        ("match_position_combo", "匹配度+仓位组合"),
        ("regime_position_combo", "Regime+仓位组合"),
        # 单维度规则
        ("regime_advice", "Regime环境建议"),
        ("policy_advice", "Policy档位建议"),
        ("position_advice", "仓位建议"),
        ("match_advice", "Regime匹配度建议"),
        ("signal_advice", "投资信号建议"),
        ("risk_alert", "风险提示"),
        # 静态保底规则
        ("static_advice", "静态建议"),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="investment_rules",
        null=True,
        blank=True,
        verbose_name="用户（null表示全局默认规则）",
    )

    name = models.CharField(max_length=100, verbose_name="规则名称")

    rule_type = models.CharField(
        max_length=30,  # 易用性改进：增加到30以支持新的规则类型
        choices=RULE_TYPE_CHOICES,
        verbose_name="规则类型",
    )

    priority = models.IntegerField(default=100, verbose_name="优先级（数字越小越优先）")

    is_active = models.BooleanField(default=True, verbose_name="是否启用")

    # 规则条件（JSON格式存储，支持复杂条件）
    # 例如：{"regime": "Recovery", "min_invested_ratio": 0.7}
    conditions = models.JSONField(default=dict, verbose_name="触发条件")

    # 建议模板（支持变量替换）
    # 例如：当前处于【{regime}】象限，建议增加权益仓位至{target_ratio}以上
    advice_template = models.TextField(verbose_name="建议模板")

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = "investment_rule"
        ordering = ["priority", "id"]
        verbose_name = "投资规则"
        verbose_name_plural = "投资规则"
        indexes = [
            models.Index(fields=["user", "rule_type", "is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.get_rule_type_display()})"


# ============================================================
# 止损止盈模型
# ============================================================


class TradingCostConfigModel(models.Model):
    """
    交易费率配置表

    每个投资组合可独立配置交易费率。
    """

    portfolio = models.OneToOneField(
        PortfolioModel,
        on_delete=models.CASCADE,
        related_name="trading_cost_config",
        verbose_name="投资组合",
    )

    commission_rate = models.FloatField(
        default=0.00025, verbose_name="佣金率", help_text="默认万2.5，如 0.00025"
    )
    min_commission = models.FloatField(
        verbose_name="最低佣金（元）", help_text="单笔佣金不足此金额按此收取"
    )
    stamp_duty_rate = models.FloatField(
        default=0.001, verbose_name="印花税率", help_text="卖出时收取，默认千1，如 0.001"
    )
    transfer_fee_rate = models.FloatField(
        default=0.00002,
        verbose_name="过户费率",
        help_text="沪市股票双向收取，默认万0.2，如 0.00002",
    )
    is_active = models.BooleanField(default=True, verbose_name="是否启用")

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = "trading_cost_config"
        verbose_name = "交易费率配置"
        verbose_name_plural = "交易费率配置"

    def __str__(self) -> str:
        return f"{self.portfolio.name} - 佣金{self.commission_rate:.5%}"

    def to_domain(self) -> Any:
        """转换为Domain实体"""
        from apps.account.domain.entities import TradingCostConfig

        return TradingCostConfig(
            id=self.id,
            portfolio_id=self.portfolio_id,
            commission_rate=self.commission_rate,
            min_commission=self.min_commission,
            stamp_duty_rate=self.stamp_duty_rate,
            transfer_fee_rate=self.transfer_fee_rate,
            is_active=self.is_active,
        )


class StopLossConfigModel(models.Model):
    """
    止损配置表

    为每个持仓配置止损规则。
    """

    STOP_LOSS_TYPE_CHOICES = [
        ("fixed", "固定止损"),
        ("trailing", "移动止损"),
        ("time_based", "时间止损"),
    ]

    STATUS_CHOICES = [
        ("active", "激活中"),
        ("triggered", "已触发"),
        ("cancelled", "已取消"),
        ("expired", "已过期"),
    ]

    position = models.OneToOneField(
        PositionModel,
        on_delete=models.CASCADE,
        related_name="stop_loss_config",
        verbose_name="关联持仓",
    )

    stop_loss_type = models.CharField(
        max_length=20, choices=STOP_LOSS_TYPE_CHOICES, default="fixed", verbose_name="止损类型"
    )

    stop_loss_pct = models.FloatField(verbose_name="止损百分比", help_text="如 0.10 表示 10% 止损")

    trailing_stop_pct = models.FloatField(
        null=True, blank=True, verbose_name="移动止损百分比", help_text="移动止损时使用，如 0.10"
    )

    max_holding_days = models.IntegerField(
        null=True, blank=True, verbose_name="最大持仓天数", help_text="时间止损时使用"
    )

    # 追踪最高价（用于移动止损）
    highest_price = models.DecimalField(
        max_digits=20, decimal_places=4, null=True, blank=True, verbose_name="持仓期间最高价"
    )

    highest_price_updated_at = models.DateTimeField(
        null=True, blank=True, verbose_name="最高价更新时间"
    )

    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="active", verbose_name="状态"
    )

    activated_at = models.DateTimeField(auto_now_add=True, verbose_name="激活时间")
    triggered_at = models.DateTimeField(null=True, blank=True, verbose_name="触发时间")

    notes = models.TextField(blank=True, verbose_name="备注")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = "stop_loss_config"
        verbose_name = "止损配置"
        verbose_name_plural = "止损配置"
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["position", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.position.asset_code} - {self.get_stop_loss_type_display()} ({self.stop_loss_pct:.2%})"


class TakeProfitConfigModel(models.Model):
    """
    止盈配置表

    为每个持仓配置止盈规则。
    """

    position = models.OneToOneField(
        PositionModel,
        on_delete=models.CASCADE,
        related_name="take_profit_config",
        verbose_name="关联持仓",
    )

    take_profit_pct = models.FloatField(verbose_name="止盈百分比", help_text="如 0.20 表示 +20%")

    # 分批止盈配置
    partial_profit_levels = models.JSONField(
        null=True,
        blank=True,
        verbose_name="分批止盈点位",
        help_text="如 [0.10, 0.20, 0.30] 表示在10%, 20%, 30%时各止盈一部分",
    )

    is_active = models.BooleanField(default=True, verbose_name="是否激活")
    notes = models.TextField(blank=True, verbose_name="备注")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = "take_profit_config"
        verbose_name = "止盈配置"
        verbose_name_plural = "止盈配置"
        indexes = [
            models.Index(fields=["is_active"]),
            models.Index(fields=["position", "is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.position.asset_code} - 止盈 {self.take_profit_pct:.2%}"


class StopLossTriggerModel(models.Model):
    """
    止损触发记录表

    记录所有止损触发的详细信息，用于审计和分析。
    """

    TRIGGER_TYPE_CHOICES = [
        ("fixed", "固定止损"),
        ("trailing", "移动止损"),
        ("time_based", "时间止损"),
    ]

    position = models.ForeignKey(
        PositionModel,
        on_delete=models.CASCADE,
        related_name="stop_loss_triggers",
        verbose_name="关联持仓",
    )

    trigger_type = models.CharField(
        max_length=20, choices=TRIGGER_TYPE_CHOICES, verbose_name="触发类型"
    )

    trigger_price = models.DecimalField(max_digits=20, decimal_places=4, verbose_name="触发价格")
    trigger_time = models.DateTimeField(verbose_name="触发时间")
    trigger_reason = models.TextField(verbose_name="触发原因")

    pnl = models.DecimalField(max_digits=20, decimal_places=2, verbose_name="盈亏金额")
    pnl_pct = models.FloatField(verbose_name="盈亏百分比")

    notes = models.TextField(blank=True, verbose_name="备注")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        db_table = "stop_loss_trigger"
        verbose_name = "止损触发记录"
        verbose_name_plural = "止损触发记录"
        ordering = ["-trigger_time"]
        indexes = [
            models.Index(fields=["position", "-trigger_time"]),
            models.Index(fields=["trigger_type"]),
        ]

    def __str__(self) -> str:
        return (
            f"{self.position.asset_code} - {self.get_trigger_type_display()} @ {self.trigger_price}"
        )


# ============================================================
# 宏观感知仓位系数配置
# ============================================================


class MacroSizingConfigModel(models.Model):
    """
    宏观感知仓位系数配置持久化模型。
    支持多版本配置，is_active=True 且 version 最大的一条为生效配置。
    """

    regime_tiers_json = models.JSONField(
        help_text='格式：[{"min_confidence": 0.6, "factor": 1.0}, ...]，按 min_confidence 降序'
    )
    pulse_tiers_json = models.JSONField(
        help_text='格式：[{"min_composite": 0.3, "max_composite": 99, "factor": 1.0}, ...]'
    )
    warning_factor = models.FloatField(
        default=0.5, help_text="Pulse 转折预警时的系数覆盖值（0.0-1.0），优先于 pulse_tiers"
    )
    market_temperature_cold_factor = models.FloatField(
        default=1.0,
        help_text="市场温度 cold 分段对应的仓位系数。",
    )
    market_temperature_warm_factor = models.FloatField(
        default=1.0,
        help_text="市场温度 warm 分段对应的仓位系数。",
    )
    market_temperature_hot_factor = models.FloatField(
        default=0.9,
        help_text="市场温度 hot 分段对应的仓位系数。",
    )
    market_temperature_overheat_factor = models.FloatField(
        default=0.75,
        help_text="市场温度 overheat 分段对应的仓位系数。",
    )
    market_temperature_extreme_factor = models.FloatField(
        default=0.35,
        help_text="市场温度 extreme 分段对应的仓位系数。",
    )
    block_new_position_on_extreme = models.BooleanField(
        default=True,
        help_text="当市场温度进入 extreme 时是否阻断新增仓位建议。",
    )
    drawdown_tiers_json = models.JSONField(
        help_text='格式：[{"min_drawdown": 0.15, "factor": 0.0}, ...]，按 min_drawdown 降序'
    )
    version = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=True)
    description = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "account"
        ordering = ["-version"]
        verbose_name = "宏观仓位系数配置"
        verbose_name_plural = "宏观仓位系数配置"
        constraints = [
            models.UniqueConstraint(
                fields=["is_active"],
                condition=models.Q(is_active=True),
                name="account_one_active_macro_sizing",
            ),
        ]

    def __str__(self) -> str:
        return f"MacroSizingConfig v{self.version} (active={self.is_active})"


# Shared configuration models repatriated from shared.infrastructure.models


class TransactionCostConfigModel(models.Model):
    """
    交易成本配置表

    存储不同市场和资产类别的交易成本参数。
    """

    MARKET_CHOICES = [
        ("CN_A_SHARE", "A股"),
        ("CN_HK_STOCK", "港股"),
        ("US_STOCK", "美股"),
        ("CN_FUND", "基金"),
        ("CN_FUTURES", "期货"),
        ("CRYPTO", "加密货币"),
        ("other", "其他"),
    ]

    ASSET_CLASS_CHOICES = [
        ("equity", "股票"),
        ("fixed_income", "债券"),
        ("fund", "基金"),
        ("derivative", "衍生品"),
        ("other", "其他"),
    ]

    market = models.CharField(max_length=20, choices=MARKET_CHOICES, verbose_name="市场")

    asset_class = models.CharField(
        max_length=20, choices=ASSET_CLASS_CHOICES, verbose_name="资产类别"
    )

    # 成本参数（均为百分比，如 0.0003 表示 0.03%）
    commission_rate = models.FloatField(
        default=0.0003, verbose_name="佣金费率", help_text="如 0.0003 表示万分之三"
    )

    slippage_rate = models.FloatField(
        default=0.0002, verbose_name="滑点费率", help_text="如 0.0002 表示万分之二"
    )

    stamp_duty_rate = models.FloatField(
        default=0.001, verbose_name="印花税率", help_text="仅卖出时收取，如 0.001 表示千分之一"
    )

    # 其他费用
    transfer_fee_rate = models.FloatField(
        default=0.00001, verbose_name="过户费率", help_text="如 0.00001 表示万分之一"
    )

    # 最小费用
    min_commission = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name="最低佣金",
        help_text="单笔交易最低佣金（元）",
    )

    # 成本阈值
    cost_warning_threshold = models.FloatField(
        default=0.005,
        verbose_name="成本预警阈值",
        help_text="成本占交易额比例超过此值时预警，如 0.005 表示 0.5%",
    )

    is_active = models.BooleanField(default=True, verbose_name="是否启用")
    notes = models.TextField(blank=True, verbose_name="备注")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = "transaction_cost_config"
        verbose_name = "交易成本配置"
        verbose_name_plural = "交易成本配置"
        unique_together = [["market", "asset_class"]]
        indexes = [
            models.Index(fields=["market", "asset_class"]),
            models.Index(fields=["is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.get_market_display()} - {self.get_asset_class_display()}"

    def calculate_total_cost(
        self,
        trade_value: Decimal,
        is_buy: bool = True,
    ) -> dict[str, Decimal]:
        """
        计算交易总成本

        Args:
            trade_value: 交易金额
            is_buy: 是否买入（印花税仅在卖出时收取）

        Returns:
            成本明细字典
        """
        from decimal import Decimal

        trade_value_float = float(trade_value)

        # 佣金
        commission = max(
            Decimal(str(trade_value_float * self.commission_rate)), self.min_commission
        )

        # 滑点
        slippage = Decimal(str(trade_value_float * self.slippage_rate))

        # 印花税（仅卖出）
        stamp_duty = (
            Decimal("0") if is_buy else Decimal(str(trade_value_float * self.stamp_duty_rate))
        )

        # 过户费
        transfer_fee = Decimal(str(trade_value_float * self.transfer_fee_rate))

        # 总成本
        total_cost = commission + slippage + stamp_duty + transfer_fee

        return {
            "commission": commission,
            "slippage": slippage,
            "stamp_duty": stamp_duty,
            "transfer_fee": transfer_fee,
            "total_cost": total_cost,
            "cost_ratio": total_cost / trade_value if trade_value > 0 else Decimal("0"),
        }
