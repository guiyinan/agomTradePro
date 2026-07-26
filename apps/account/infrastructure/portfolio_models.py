"""
投资组合、持仓与交易 ORM 模型

包含投资组合、持仓记录、交易记录、券商导入批次、
持仓信号日志、组合日快照与资金流水。
"""

from decimal import Decimal

from django.contrib.auth.models import User
from django.db import models
from django.db.models import Sum

from .classification_models import AssetMetadataModel

__all__ = [
    "BrokerTradeImportBatchModel",
    "CapitalFlowModel",
    "PortfolioDailySnapshotModel",
    "PortfolioModel",
    "PositionModel",
    "PositionSignalLogModel",
    "TransactionModel",
]


# 账户与组合模型


class PortfolioModel(models.Model):
    """
    投资组合表

    用户可以有多个投资组合（如：实盘、模拟盘、策略A、策略B）。
    """

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="portfolios", verbose_name="用户"
    )

    name = models.CharField(max_length=100, default="默认组合", verbose_name="组合名称")
    base_currency = models.ForeignKey(
        "CurrencyModel",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="portfolios",
        verbose_name="基准货币",
    )

    is_active = models.BooleanField(default=True, verbose_name="是否激活")

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = "portfolio"
        verbose_name = "投资组合"
        verbose_name_plural = "投资组合"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.user.username} - {self.name}"

    @property
    def total_value(self) -> Decimal:
        """总市值"""
        from django.db.models import Sum

        result = self.positions.filter(is_closed=False).aggregate(total=Sum("market_value"))[
            "total"
        ]
        return Decimal(str(result or 0))

    @property
    def total_cost(self) -> Decimal:
        """总成本"""
        from django.db.models import DecimalField, F

        result = self.positions.filter(is_closed=False).aggregate(
            total=Sum(F("shares") * F("avg_cost"), output_field=DecimalField())
        )["total"]
        return Decimal(str(result or 0))

    @property
    def total_pnl(self) -> Decimal:
        """总盈亏"""
        return self.total_value - self.total_cost

    @property
    def total_pnl_pct(self) -> float:
        """总盈亏百分比"""
        if self.total_cost > 0:
            return float((self.total_pnl / self.total_cost) * 100)
        return 0.0

    @property
    def position_count(self) -> int:
        """持仓数量"""
        return int(self.positions.filter(is_closed=False).count())


# 持仓与交易模型


class PositionModel(models.Model):
    """
    持仓记录表

    记录用户在某个投资组合中的持仓信息。
    """

    portfolio = models.ForeignKey(
        PortfolioModel, on_delete=models.CASCADE, related_name="positions", verbose_name="投资组合"
    )

    asset_code = models.CharField(max_length=20, db_index=True, verbose_name="资产代码")

    # 资产分类和币种（新增）
    category = models.ForeignKey(
        "AssetCategoryModel",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="positions",
        verbose_name="资产分类",
    )
    currency = models.ForeignKey(
        "CurrencyModel",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="positions",
        verbose_name="币种",
    )

    # 冗余分类字段（从 AssetMetadata 同步，用于快速查询）
    asset_class = models.CharField(
        max_length=20, choices=AssetMetadataModel.ASSET_CLASS_CHOICES, verbose_name="资产大类"
    )
    region = models.CharField(
        max_length=10, choices=AssetMetadataModel.REGION_CHOICES, verbose_name="地区"
    )
    cross_border = models.CharField(
        max_length=20, choices=AssetMetadataModel.CROSS_BORDER_CHOICES, verbose_name="跨境标识"
    )

    # 持仓信息
    shares = models.FloatField(verbose_name="持仓数量")
    avg_cost = models.DecimalField(max_digits=20, decimal_places=4, verbose_name="平均成本价")
    current_price = models.DecimalField(
        max_digits=20, decimal_places=4, null=True, verbose_name="当前市价"
    )

    # 盈亏信息（冗余，便于查询）
    market_value = models.DecimalField(
        max_digits=20, decimal_places=2, default=0, verbose_name="市值"
    )
    unrealized_pnl = models.DecimalField(
        max_digits=20, decimal_places=2, default=0, verbose_name="未实现盈亏"
    )
    unrealized_pnl_pct = models.FloatField(default=0, verbose_name="未实现盈亏百分比")

    # 来源追踪
    SOURCE_CHOICES = [
        ("manual", "手动录入"),
        ("signal", "投资信号"),
        ("backtest", "回测结果"),
    ]
    source = models.CharField(
        max_length=20, choices=SOURCE_CHOICES, default="manual", verbose_name="来源"
    )
    source_id = models.IntegerField(
        null=True, blank=True, verbose_name="来源ID"
    )  # signal_id 或 backtest_id

    # 状态
    is_closed = models.BooleanField(default=False, verbose_name="是否已平仓")
    opened_at = models.DateTimeField(auto_now_add=True, verbose_name="开仓时间")
    closed_at = models.DateTimeField(null=True, blank=True, verbose_name="平仓时间")

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = "position"
        verbose_name = "持仓记录"
        verbose_name_plural = "持仓记录"
        indexes = [
            models.Index(fields=["portfolio", "asset_code"]),
            models.Index(fields=["source", "source_id"]),
            models.Index(fields=["asset_class", "region"]),
            models.Index(fields=["is_closed"]),
        ]

    def __str__(self) -> str:
        return f"{self.portfolio.name} - {self.asset_code} - {self.shares}股"


class TransactionModel(models.Model):
    """
    交易记录表

    记录每一笔买入/卖出交易的详细信息。
    """

    portfolio = models.ForeignKey(
        PortfolioModel,
        on_delete=models.CASCADE,
        related_name="transactions",
        verbose_name="投资组合",
    )

    position = models.ForeignKey(
        PositionModel,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transactions",
        verbose_name="关联持仓",
    )

    ACTION_CHOICES = [
        ("buy", "买入"),
        ("sell", "卖出"),
    ]
    action = models.CharField(max_length=10, choices=ACTION_CHOICES, verbose_name="交易方向")

    asset_code = models.CharField(max_length=20, verbose_name="资产代码")
    shares = models.FloatField(verbose_name="交易数量")
    price = models.DecimalField(max_digits=20, decimal_places=4, verbose_name="成交价格")
    notional = models.DecimalField(max_digits=20, decimal_places=2, verbose_name="成交金额")

    # 成本明细
    commission = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, verbose_name="手续费"
    )
    slippage = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, verbose_name="滑点成本"
    )
    stamp_duty = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, verbose_name="印花税"
    )
    transfer_fee = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, verbose_name="过户费"
    )

    # 成本预估（交易前）
    estimated_cost = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="预估成本"
    )
    estimated_cost_ratio = models.FloatField(null=True, blank=True, verbose_name="预估成本比例")

    # 成本对比
    cost_variance = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="成本差异",
        help_text="实际成本 - 预估成本",
    )
    cost_variance_pct = models.FloatField(null=True, blank=True, verbose_name="成本差异百分比")

    traded_at = models.DateTimeField(verbose_name="交易时间")
    notes = models.TextField(blank=True, verbose_name="备注")

    # Manual broker import metadata.
    broker_name = models.CharField(max_length=64, blank=True, default="", verbose_name="券商名称")
    external_trade_id = models.CharField(
        max_length=128,
        blank=True,
        default="",
        verbose_name="外部成交编号",
    )
    broker_trade_key = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        unique=True,
        db_index=True,
        verbose_name="券商成交去重键",
    )
    raw_payload = models.JSONField(default=dict, blank=True, verbose_name="原始导入行")
    import_batch = models.ForeignKey(
        "BrokerTradeImportBatchModel",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transactions",
        verbose_name="导入批次",
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        db_table = "transaction"
        verbose_name = "交易记录"
        verbose_name_plural = "交易记录"
        ordering = ["-traded_at"]
        indexes = [
            models.Index(fields=["portfolio", "traded_at"]),
            models.Index(fields=["asset_code"]),
            models.Index(fields=["broker_name", "external_trade_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.action.upper()} {self.asset_code} {self.shares}@{self.price}"


class BrokerTradeImportBatchModel(models.Model):
    """One manual broker trade import attempt."""

    STATUS_CHOICES = [
        ("previewed", "已预览"),
        ("completed", "已完成"),
        ("completed_with_errors", "完成但有错误"),
        ("failed", "失败"),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="broker_trade_import_batches",
        verbose_name="用户",
    )
    portfolio = models.ForeignKey(
        PortfolioModel,
        on_delete=models.CASCADE,
        related_name="broker_trade_import_batches",
        verbose_name="投资组合",
    )
    broker_name = models.CharField(max_length=64, default="manual", verbose_name="券商名称")
    source_filename = models.CharField(
        max_length=255, blank=True, default="", verbose_name="文件名"
    )
    file_hash = models.CharField(max_length=64, db_index=True, verbose_name="文件哈希")
    status = models.CharField(
        max_length=32,
        choices=STATUS_CHOICES,
        default="previewed",
        db_index=True,
        verbose_name="状态",
    )
    total_rows = models.IntegerField(default=0, verbose_name="总行数")
    imported_rows = models.IntegerField(default=0, verbose_name="导入行数")
    skipped_rows = models.IntegerField(default=0, verbose_name="跳过行数")
    error_rows = models.IntegerField(default=0, verbose_name="错误行数")
    errors = models.JSONField(default=list, blank=True, verbose_name="错误详情")
    preview_rows = models.JSONField(default=list, blank=True, verbose_name="预览行")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = "broker_trade_import_batch"
        verbose_name = "券商交易导入批次"
        verbose_name_plural = "券商交易导入批次"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "portfolio", "file_hash"],
                name="uq_broker_import_user_portfolio_hash",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "-created_at"], name="idx_broker_import_user_time"),
            models.Index(fields=["portfolio", "-created_at"], name="idx_broker_import_pf_time"),
        ]

    def __str__(self) -> str:
        return f"{self.broker_name} {self.source_filename} ({self.status})"


# 信号扩展（关联到持仓）


class PositionSignalLogModel(models.Model):
    """
    持仓信号关联表

    记录哪些投资信号被执行成了持仓，以及执行情况。
    """

    signal_id = models.IntegerField(verbose_name="信号ID")
    position = models.ForeignKey(
        PositionModel, on_delete=models.CASCADE, related_name="signal_logs", verbose_name="持仓"
    )

    executed_at = models.DateTimeField(auto_now_add=True, verbose_name="执行时间")
    notes = models.TextField(blank=True, verbose_name="备注")

    class Meta:
        db_table = "position_signal_log"
        verbose_name = "持仓信号日志"
        verbose_name_plural = "持仓信号日志"


class PortfolioDailySnapshotModel(models.Model):
    """
    投资组合日快照表

    记录每个投资组合在每个交易日的总资产，用于计算回溯收益率。
    """

    portfolio = models.ForeignKey(
        PortfolioModel,
        on_delete=models.CASCADE,
        related_name="daily_snapshots",
        verbose_name="投资组合",
    )

    snapshot_date = models.DateField(db_index=True, verbose_name="快照日期")

    total_value = models.DecimalField(max_digits=20, decimal_places=2, verbose_name="总资产")

    cash_balance = models.DecimalField(
        max_digits=20, decimal_places=2, default=0, verbose_name="现金余额"
    )

    invested_value = models.DecimalField(
        max_digits=20, decimal_places=2, default=0, verbose_name="投资市值"
    )

    position_count = models.IntegerField(default=0, verbose_name="持仓数量")

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        db_table = "portfolio_daily_snapshot"
        unique_together = [["portfolio", "snapshot_date"]]
        ordering = ["-snapshot_date"]
        indexes = [
            models.Index(fields=["portfolio", "-snapshot_date"]),
        ]
        verbose_name = "投资组合日快照"
        verbose_name_plural = "投资组合日快照"

    def __str__(self) -> str:
        return f"{self.portfolio.name} @ {self.snapshot_date}: ¥{self.total_value}"


class CapitalFlowModel(models.Model):
    """
    资金流水表

    记录用户的入金/出金操作，用于计算累计投入和收益率。
    """

    FLOW_TYPE_CHOICES = [
        ("deposit", "入金"),
        ("withdraw", "出金"),
        ("dividend", "分红"),
        ("interest", "利息"),
        ("adjustment", "调整"),
    ]

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="capital_flows", verbose_name="用户"
    )

    portfolio = models.ForeignKey(
        PortfolioModel,
        on_delete=models.CASCADE,
        related_name="capital_flows",
        verbose_name="投资组合",
    )

    flow_type = models.CharField(max_length=20, choices=FLOW_TYPE_CHOICES, verbose_name="流水类型")

    amount = models.DecimalField(max_digits=20, decimal_places=2, verbose_name="金额")

    flow_date = models.DateField(db_index=True, verbose_name="流水日期")

    notes = models.TextField(blank=True, verbose_name="备注")

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        db_table = "capital_flow"
        ordering = ["-flow_date", "-created_at"]
        verbose_name = "资金流水"
        verbose_name_plural = "资金流水"
        indexes = [
            models.Index(fields=["user", "flow_type", "-flow_date"]),
        ]

    def __str__(self) -> str:
        return f"{self.get_flow_type_display()} {self.amount} ({self.flow_date})"
