"""
Account Infrastructure Models

Django ORM 模型定义，负责数据持久化。
将 Domain 层实体映射到数据库表。
"""

import base64
import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timezone
from decimal import Decimal

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Sum

from apps.account.application.rbac import ROLE_CHOICES


def _build_app_fernet() -> Fernet:
    secret = getattr(settings, "AGOMTRADEPRO_ENCRYPTION_KEY", "") or getattr(
        settings, "SECRET_KEY", ""
    )
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


# ============================================================
# 资产元数据模型
# ============================================================


class AssetMetadataModel(models.Model):
    """
    资产元数据表

    存储每个资产代码的完整分类信息。
    由管理员维护，用户查看。
    """

    # 基础信息
    asset_code = models.CharField(
        max_length=50, unique=True, db_index=True, verbose_name="资产代码"
    )
    name = models.CharField(max_length=200, verbose_name="资产名称")
    description = models.TextField(blank=True, verbose_name="描述")

    # 预定义分类（枚举）
    ASSET_CLASS_CHOICES = [
        ("equity", "股票"),
        ("fixed_income", "固定收益"),
        ("commodity", "商品"),
        ("currency", "外汇"),
        ("cash", "现金"),
        ("fund", "基金"),
        ("derivative", "衍生品"),
        ("other", "其他"),
    ]
    asset_class = models.CharField(
        max_length=20, choices=ASSET_CLASS_CHOICES, verbose_name="资产大类"
    )

    REGION_CHOICES = [
        ("CN", "中国境内"),
        ("US", "美国"),
        ("EU", "欧洲"),
        ("JP", "日本"),
        ("EM", "新兴市场"),
        ("GLOBAL", "全球"),
        ("OTHER", "其他"),
    ]
    region = models.CharField(max_length=10, choices=REGION_CHOICES, verbose_name="地区")

    CROSS_BORDER_CHOICES = [
        ("domestic", "境内资产"),
        ("qdii", "QDII基金"),
        ("direct_foreign", "直接境外投资"),
    ]
    cross_border = models.CharField(
        max_length=20, choices=CROSS_BORDER_CHOICES, default="domestic", verbose_name="跨境标识"
    )

    STYLE_CHOICES = [
        ("growth", "成长"),
        ("value", "价值"),
        ("blend", "混合"),
        ("cyclical", "周期"),
        ("defensive", "防御"),
        ("quality", "质量"),
        ("momentum", "动量"),
        ("unknown", "未知/不适用"),
    ]
    style = models.CharField(
        max_length=20, choices=STYLE_CHOICES, default="unknown", verbose_name="投资风格"
    )

    # 用户可自定义分类
    sector = models.CharField(max_length=50, blank=True, verbose_name="行业板块")
    sub_class = models.CharField(max_length=50, blank=True, verbose_name="子类")

    # 元数据
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "asset_metadata"
        verbose_name = "资产元数据"
        verbose_name_plural = "资产元数据"
        indexes = [
            models.Index(fields=["asset_code"]),
            models.Index(fields=["asset_class", "region"]),
        ]

    def __str__(self):
        return f"{self.asset_code} - {self.name}"


# ============================================================
# 账户与组合模型
# ============================================================


class AccountProfileModel(models.Model):
    """
    用户账户配置表

    扩展 Django User 模型，存储投资偏好和初始资金。

    ⭐ 重构说明（2026-01-04）：
    - 删除了 real_account 和 simulated_account 外键
    - 用户投资组合统一由 SimulatedAccountModel 管理
    - 通过 user.investment_accounts 查询所有投资组合
    """

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="account_profile", verbose_name="用户"
    )

    display_name = models.CharField(max_length=100, verbose_name="显示名称")

    initial_capital = models.DecimalField(
        max_digits=20, decimal_places=2, default=Decimal("1000000.00"), verbose_name="初始资金"
    )

    RISK_TOLERANCE_CHOICES = [
        ("conservative", "保守型"),
        ("moderate", "稳健型"),
        ("aggressive", "激进型"),
    ]
    risk_tolerance = models.CharField(
        max_length=20, choices=RISK_TOLERANCE_CHOICES, default="moderate", verbose_name="风险偏好"
    )

    rbac_role = models.CharField(
        max_length=32,
        choices=ROLE_CHOICES,
        default="owner",
        verbose_name="RBAC角色",
        help_text="系统统一角色（与 MCP 对齐）",
    )

    mcp_enabled = models.BooleanField(
        default=True,
        verbose_name="允许 MCP/SDK 访问",
        help_text="关闭后，该用户所有 MCP/SDK Token 将立即失效",
    )

    # 波动率目标配置
    target_volatility = models.FloatField(
        default=0.15, verbose_name="目标波动率", help_text="年化波动率目标，如0.15表示15%"
    )

    volatility_tolerance = models.FloatField(
        default=0.2,
        verbose_name="波动率容忍度",
        help_text="超过目标波动率多少比例触发降仓，如0.2表示20%",
    )

    max_volatility_reduction = models.FloatField(
        default=0.5,
        verbose_name="最大降仓幅度",
        help_text="波动率超标时最大降仓比例，如0.5表示最多降50%",
    )

    # 用户协议和审批相关字段
    user_agreement_accepted = models.BooleanField(default=False, verbose_name="用户协议已接受")
    risk_warning_acknowledged = models.BooleanField(default=False, verbose_name="风险提示已确认")
    agreement_accepted_at = models.DateTimeField(null=True, blank=True, verbose_name="协议接受时间")
    agreement_ip_address = models.GenericIPAddressField(
        null=True, blank=True, verbose_name="协议接受IP"
    )

    # 用户审批状态（⭐新增）
    APPROVAL_STATUS_CHOICES = [
        ("pending", "待审批"),
        ("approved", "已批准"),
        ("rejected", "已拒绝"),
        ("auto_approved", "自动批准"),
    ]
    approval_status = models.CharField(
        max_length=20, choices=APPROVAL_STATUS_CHOICES, default="pending", verbose_name="审批状态"
    )
    approved_at = models.DateTimeField(null=True, blank=True, verbose_name="批准时间")
    approved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_users",
        verbose_name="审批人",
    )
    rejection_reason = models.TextField(blank=True, verbose_name="拒绝原因")

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = "account_profile"
        verbose_name = "账户配置"
        verbose_name_plural = "账户配置"

    def __str__(self):
        return f"{self.user.username} - {self.display_name}"


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

    def __str__(self):
        return f"{self.user.username} - {self.name}"

    @property
    def total_value(self):
        """总市值"""
        from django.db.models import Sum

        result = self.positions.filter(is_closed=False).aggregate(total=Sum("market_value"))[
            "total"
        ]
        return result or Decimal("0")

    @property
    def total_cost(self):
        """总成本"""
        from django.db.models import DecimalField, F

        result = self.positions.filter(is_closed=False).aggregate(
            total=Sum(F("shares") * F("avg_cost"), output_field=DecimalField())
        )["total"]
        return result or Decimal("0")

    @property
    def total_pnl(self):
        """总盈亏"""
        return self.total_value - self.total_cost

    @property
    def total_pnl_pct(self):
        """总盈亏百分比"""
        if self.total_cost > 0:
            return float((self.total_pnl / self.total_cost) * 100)
        return 0.0

    @property
    def position_count(self):
        """持仓数量"""
        return self.positions.filter(is_closed=False).count()


# ============================================================
# 持仓与交易模型
# ============================================================


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

    def __str__(self):
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

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        db_table = "transaction"
        verbose_name = "交易记录"
        verbose_name_plural = "交易记录"
        ordering = ["-traded_at"]
        indexes = [
            models.Index(fields=["portfolio", "traded_at"]),
            models.Index(fields=["asset_code"]),
        ]

    def __str__(self):
        return f"{self.action.upper()} {self.asset_code} {self.shares}@{self.price}"


# ============================================================
# 信号扩展（关联到持仓）
# ============================================================


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

    def __str__(self):
        return f"{self.portfolio.name} @ {self.snapshot_date}: ¥{self.total_value}"


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

    def __str__(self):
        return f"{self.name} ({self.get_rule_type_display()})"


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

    def __str__(self):
        return f"{self.get_flow_type_display()} {self.amount} ({self.flow_date})"


class DocumentationModel(models.Model):
    """
    文档表

    存储系统文档，支持 Markdown 格式。
    """

    CATEGORY_CHOICES = [
        ("user_guide", "用户指南"),
        ("concept", "概念说明"),
        ("api", "API 文档"),
        ("development", "开发文档"),
        ("other", "其他"),
    ]

    title = models.CharField(max_length=200, verbose_name="标题")
    slug = models.SlugField(max_length=100, unique=True, db_index=True, verbose_name="URL标识")
    category = models.CharField(
        max_length=20, choices=CATEGORY_CHOICES, default="user_guide", verbose_name="分类"
    )
    content = models.TextField(verbose_name="内容（Markdown）")
    summary = models.TextField(blank=True, verbose_name="摘要")
    order = models.IntegerField(default=0, verbose_name="排序（数字越小越靠前）")
    is_published = models.BooleanField(default=True, verbose_name="是否发布")

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = "documentation"
        ordering = ["order", "-created_at"]
        verbose_name = "文档"
        verbose_name_plural = "文档"
        indexes = [
            models.Index(fields=["slug", "is_published"]),
            models.Index(fields=["category", "is_published"]),
        ]

    def __str__(self):
        return self.title


# ============================================================
# 资产分类体系（多级分类）
# ============================================================


class AssetCategoryModel(models.Model):
    """
    资产分类模型

    支持树形结构的分类体系，例如：
    - 基金
      - 债券基金
      - 股票基金
      - 混合基金
      - 商品基金
    - 理财
    - 存款
    """

    code = models.CharField(max_length=50, unique=True, db_index=True, verbose_name="分类代码")
    name = models.CharField(max_length=100, verbose_name="分类名称")

    # 树形结构
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="children",
        verbose_name="父分类",
    )

    level = models.IntegerField(default=1, verbose_name="层级")  # 1=一级, 2=二级, etc.
    path = models.CharField(max_length=200, verbose_name="分类路径")  # 例如：基金/股票基金

    description = models.TextField(blank=True, verbose_name="描述")
    is_active = models.BooleanField(default=True, verbose_name="是否启用")
    sort_order = models.IntegerField(default=0, verbose_name="排序")

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = "asset_category"
        verbose_name = "资产分类"
        verbose_name_plural = "资产分类"
        ordering = ["path", "sort_order"]
        indexes = [
            models.Index(fields=["code"]),
            models.Index(fields=["parent"]),
            models.Index(fields=["level"]),
        ]

    def __str__(self):
        return f"{self.path} - {self.name}"

    def get_ancestors(self):
        """获取所有父级分类"""
        if self.parent:
            return self.parent.get_ancestors() + [self.parent]
        return []

    def get_full_path(self):
        """获取完整分类路径"""
        ancestors = self.get_ancestors()
        path_parts = [a.name for a in ancestors]
        path_parts.append(self.name)
        return " / ".join(path_parts)


# ============================================================
# 币种模型
# ============================================================


class CurrencyModel(models.Model):
    """
    币种模型

    支持多币种，包括人民币、美元、欧元、港币等。
    """

    code = models.CharField(
        max_length=10, unique=True, verbose_name="币种代码"
    )  # CNY, USD, EUR, HKD
    name = models.CharField(max_length=50, verbose_name="币种名称")  # 人民币, 美元, 欧元, 港币
    symbol = models.CharField(max_length=10, verbose_name="货币符号")  # ¥, $, €, HK$

    is_base = models.BooleanField(default=False, verbose_name="是否基准货币")
    is_active = models.BooleanField(default=True, verbose_name="是否启用")

    # 精度设置
    precision = models.IntegerField(default=2, verbose_name="小数位数")  # CNY通常2位，JPY可能0位

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = "currency"
        verbose_name = "币种"
        verbose_name_plural = "币种"
        ordering = ["-is_base", "code"]

    def __str__(self):
        return f"{self.code} - {self.name} ({self.symbol})"

    @classmethod
    def get_base_currency(cls):
        """获取基准货币"""
        return cls.objects.filter(is_base=True).first() or cls.objects.filter(code="CNY").first()


# ============================================================
# 汇率模型
# ============================================================


class ExchangeRateModel(models.Model):
    """
    汇率模型

    存储历史汇率数据，支持汇率换算。
    """

    from_currency = models.ForeignKey(
        CurrencyModel, on_delete=models.CASCADE, related_name="rates_from", verbose_name="源币种"
    )
    to_currency = models.ForeignKey(
        CurrencyModel, on_delete=models.CASCADE, related_name="rates_to", verbose_name="目标币种"
    )

    rate = models.DecimalField(max_digits=20, decimal_places=6, verbose_name="汇率")
    effective_date = models.DateField(db_index=True, verbose_name="生效日期")

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        db_table = "exchange_rate"
        verbose_name = "汇率"
        verbose_name_plural = "汇率"
        ordering = ["-effective_date"]
        unique_together = [["from_currency", "to_currency", "effective_date"]]
        indexes = [
            models.Index(fields=["from_currency", "to_currency", "effective_date"]),
        ]

    def __str__(self):
        return f"{self.from_currency.code} -> {self.to_currency.code}: {self.rate} ({self.effective_date})"

    def convert(self, amount: Decimal) -> Decimal:
        """将金额从源币种转换为目标币种"""
        return amount * self.rate

    @classmethod
    def get_latest_rate(cls, from_code: str, to_code: str) -> "ExchangeRateModel":
        """获取最新汇率"""
        return (
            cls.objects.filter(from_currency__code=from_code, to_currency__code=to_code)
            .order_by("-effective_date")
            .first()
        )

    @classmethod
    def convert_amount(cls, amount: Decimal, from_code: str, to_code: str, date=None) -> Decimal:
        """
        转换金额

        Args:
            amount: 金额
            from_code: 源币种代码
            to_code: 目标币种代码
            date: 指定日期（可选）

        Returns:
            转换后的金额
        """
        if from_code == to_code:
            return amount

        queryset = cls.objects.filter(from_currency__code=from_code, to_currency__code=to_code)

        if date:
            queryset = queryset.filter(effective_date__lte=date).order_by("-effective_date")
        else:
            queryset = queryset.order_by("-effective_date")

        rate = queryset.first()
        if not rate:
            raise ValueError(f"No exchange rate found for {from_code} -> {to_code}")

        return rate.convert(amount)


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
        default=5.0, verbose_name="最低佣金（元）", help_text="单笔佣金不足此金额按此收取"
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

    def __str__(self):
        return f"{self.portfolio.name} - 佣金{self.commission_rate:.5%}"

    def to_domain(self):
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

    stop_loss_pct = models.FloatField(verbose_name="止损百分比", help_text="如 -0.10 表示 -10%")

    trailing_stop_pct = models.FloatField(
        null=True, blank=True, verbose_name="移动止损百分比", help_text="移动止损时使用，如 -0.10"
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

    def __str__(self):
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

    def __str__(self):
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

    def __str__(self):
        return (
            f"{self.position.asset_code} - {self.get_trigger_type_display()} @ {self.trigger_price}"
        )


# ============================================================
# 系统配置模型
# ============================================================


class SystemSettingsModel(models.Model):
    """
    系统配置表

    存储全局系统配置，如用户审批开关等。
    使用单例模式，只有一条记录。
    """

    # 用户审批配置
    require_user_approval = models.BooleanField(
        default=True, verbose_name="需要管理员审批新用户", help_text="关闭后新用户注册将自动批准"
    )

    auto_approve_first_admin = models.BooleanField(
        default=True,
        verbose_name="自动批准首个管理员用户",
        help_text="系统无管理员时，首个注册的用户自动成为管理员并获得批准",
    )

    default_mcp_enabled = models.BooleanField(
        default=True,
        verbose_name="新用户默认开启 MCP/SDK",
        help_text="新注册或新批准用户默认是否允许 MCP/SDK 访问，由管理员决定",
    )

    MARKET_COLOR_CONVENTION_CHOICES = [
        ("cn_a_share", "A股红涨绿跌"),
        ("us_market", "美股绿涨红跌"),
    ]

    market_color_convention = models.CharField(
        max_length=32,
        default="cn_a_share",
        choices=MARKET_COLOR_CONVENTION_CHOICES,
        verbose_name="市场颜色约定",
        help_text="统一控制涨跌、资金流入流出的语义颜色映射。",
    )

    allow_token_plaintext_view = models.BooleanField(
        default=True,
        verbose_name="允许查看 Token 明文",
        help_text="关闭后，生成后不再显示完整 Token，历史 Token 也不可明文查看",
    )

    # 用户协议内容配置
    user_agreement_content = models.TextField(
        blank=True, verbose_name="用户协议内容", help_text="用户注册时需要同意的协议内容，支持HTML"
    )

    risk_warning_content = models.TextField(
        blank=True,
        verbose_name="风险提示内容",
        help_text="用户注册时需要确认的风险提示内容，支持HTML",
    )

    # 默认值说明
    notes = models.TextField(blank=True, verbose_name="备注")

    benchmark_code_map = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="基准代码映射",
        help_text="系统运行时使用的基准/默认指数代码映射",
    )

    asset_proxy_code_map = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="资产代理代码映射",
        help_text="资产类别到实际交易/价格代理代码的映射",
    )

    macro_index_catalog = models.JSONField(
        default=list,
        blank=True,
        verbose_name="宏观指数目录",
        help_text="宏观模块使用的指数代码、名称、单位和发布时间配置",
    )

    backup_email = models.EmailField(
        blank=True,
        verbose_name="数据库备份接收邮箱",
        help_text="启用后按周期发送数据库全量备份下载链接到该邮箱",
    )

    backup_app_base_url = models.URLField(
        blank=True,
        verbose_name="备份下载站点地址",
        help_text="用于生成邮件中的绝对下载链接，如 https://example.com",
    )

    backup_mail_from_email = models.EmailField(
        blank=True, verbose_name="备份邮件发件人", help_text="留空则回退到系统默认发件人"
    )

    backup_smtp_host = models.CharField(max_length=255, blank=True, verbose_name="SMTP 主机")

    backup_smtp_port = models.PositiveIntegerField(default=587, verbose_name="SMTP 端口")

    backup_smtp_username = models.CharField(max_length=255, blank=True, verbose_name="SMTP 用户名")

    backup_smtp_password_encrypted = models.TextField(
        blank=True, verbose_name="SMTP 密码（密文）", help_text="系统内部加密存储"
    )

    backup_smtp_use_tls = models.BooleanField(default=True, verbose_name="SMTP 使用 TLS")

    backup_smtp_use_ssl = models.BooleanField(default=False, verbose_name="SMTP 使用 SSL")

    backup_enabled = models.BooleanField(
        default=False,
        verbose_name="启用数据库备份邮件",
        help_text="开启后系统会按设定周期发送备份下载链接",
    )

    backup_interval_days = models.PositiveIntegerField(
        default=7, verbose_name="备份周期（天）", help_text="每隔多少天发送一次数据库备份下载链接"
    )

    backup_link_ttl_days = models.PositiveIntegerField(
        default=3, verbose_name="下载链接有效期（天）", help_text="邮件中的备份下载链接有效天数"
    )

    backup_password_encrypted = models.TextField(
        blank=True,
        verbose_name="备份压缩密码（密文）",
        help_text="系统内部加密存储，用于生成加密备份文件",
    )

    backup_password_hint = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="备份密码提示",
        help_text="可选，用于管理员识别当前使用的备份密码",
    )

    backup_last_sent_at = models.DateTimeField(
        null=True, blank=True, verbose_name="上次备份邮件发送时间"
    )

    # ========== Qlib 配置 ==========
    qlib_enabled = models.BooleanField(
        default=False, verbose_name="启用 Qlib", help_text="开启后系统将使用 Qlib 进行量化分析"
    )

    qlib_provider_uri = models.CharField(
        max_length=500,
        blank=True,
        default="",
        verbose_name="Qlib 数据目录",
        help_text="Qlib 数据存储路径，如 D:/qlib_data/cn_data 或 /var/lib/qlib/cn_data",
    )

    qlib_region = models.CharField(
        max_length=10,
        default="CN",
        verbose_name="Qlib 区域",
        help_text="市场区域，如 CN（中国）、US（美国）",
    )

    qlib_model_path = models.CharField(
        max_length=500,
        blank=True,
        default="",
        verbose_name="Qlib 模型目录",
        help_text="Qlib 模型存储路径，留空使用默认路径",
    )

    # ========== Alpha 配置 ==========
    ALPHA_PROVIDER_CHOICES = [
        ("", "自动降级（默认）"),
        ("qlib", "仅使用 Qlib"),
        ("cache", "仅使用缓存"),
        ("simple", "仅使用 Simple"),
        ("etf", "仅使用 ETF"),
    ]

    ALPHA_POOL_MODE_STRICT_VALUATION = "strict_valuation"
    ALPHA_POOL_MODE_MARKET = "market"
    ALPHA_POOL_MODE_PRICE_COVERED = "price_covered"

    ALPHA_POOL_MODE_CHOICES = [
        (ALPHA_POOL_MODE_STRICT_VALUATION, "严格估值覆盖池"),
        (ALPHA_POOL_MODE_MARKET, "市场可交易池"),
        (ALPHA_POOL_MODE_PRICE_COVERED, "价格覆盖池"),
    ]

    alpha_fixed_provider = models.CharField(
        max_length=20,
        blank=True,
        default="",
        choices=ALPHA_PROVIDER_CHOICES,
        verbose_name="固定 Alpha Provider",
        help_text="强制使用指定的 Provider（禁用自动降级），留空则启用自动降级",
    )

    alpha_pool_mode = models.CharField(
        max_length=32,
        default=ALPHA_POOL_MODE_STRICT_VALUATION,
        choices=ALPHA_POOL_MODE_CHOICES,
        verbose_name="Alpha 默认股票池模式",
        help_text="控制首页 Alpha 和实时推理默认使用哪个候选股票集合",
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = "system_settings"
        verbose_name = "系统配置"
        verbose_name_plural = "系统配置"

    def __str__(self):
        return f"系统配置 (审批:{'开启' if self.require_user_approval else '关闭'})"

    def clean(self):
        super().clean()
        if self.backup_enabled:
            if not self.backup_email:
                raise ValidationError({"backup_email": "启用数据库备份邮件时必须配置接收邮箱。"})
            if not self.backup_password_encrypted:
                raise ValidationError(
                    {"backup_password_encrypted": "启用数据库备份邮件时必须设置备份密码。"}
                )
            if not self.backup_app_base_url:
                raise ValidationError(
                    {"backup_app_base_url": "启用数据库备份邮件时必须配置下载站点地址。"}
                )
            if not self.backup_smtp_host:
                raise ValidationError(
                    {"backup_smtp_host": "启用数据库备份邮件时必须配置 SMTP 主机。"}
                )
            if not self.backup_smtp_port:
                raise ValidationError(
                    {"backup_smtp_port": "启用数据库备份邮件时必须配置 SMTP 端口。"}
                )
            if not self.backup_mail_from_email:
                raise ValidationError(
                    {"backup_mail_from_email": "启用数据库备份邮件时必须配置发件人邮箱。"}
                )
            if not self.get_backup_smtp_password():
                raise ValidationError(
                    {"backup_smtp_password_encrypted": "启用数据库备份邮件时必须设置 SMTP 密码。"}
                )
        if self.backup_smtp_use_tls and self.backup_smtp_use_ssl:
            raise ValidationError("SMTP TLS 和 SSL 不能同时开启。")
        if self.backup_interval_days < 1:
            raise ValidationError({"backup_interval_days": "备份周期必须大于等于 1 天。"})
        if self.backup_link_ttl_days < 1:
            raise ValidationError({"backup_link_ttl_days": "下载链接有效期必须大于等于 1 天。"})

    @classmethod
    def get_settings(cls):
        """获取系统配置（单例模式）"""
        settings, created = cls.objects.get_or_create(
            pk=1,
            defaults={
                "require_user_approval": True,
                "auto_approve_first_admin": True,
                "user_agreement_content": cls._get_default_agreement(),
                "risk_warning_content": cls._get_default_risk_warning(),
                "benchmark_code_map": cls._get_default_benchmark_code_map(),
                "asset_proxy_code_map": cls._get_default_asset_proxy_code_map(),
                "macro_index_catalog": cls._get_default_macro_index_catalog(),
            },
        )
        update_fields = []
        if not settings.benchmark_code_map:
            settings.benchmark_code_map = cls._get_default_benchmark_code_map()
            update_fields.append("benchmark_code_map")
        if not settings.asset_proxy_code_map:
            settings.asset_proxy_code_map = cls._get_default_asset_proxy_code_map()
            update_fields.append("asset_proxy_code_map")
        if not settings.macro_index_catalog:
            settings.macro_index_catalog = cls._get_default_macro_index_catalog()
            update_fields.append("macro_index_catalog")
        if update_fields:
            update_fields.append("updated_at")
            settings.save(update_fields=update_fields)
        return settings

    @staticmethod
    def _get_secret_fernet() -> Fernet:
        return _build_app_fernet()

    def set_backup_password(self, raw_password: str):
        raw_password = (raw_password or "").strip()
        if not raw_password:
            self.backup_password_encrypted = ""
            return
        self.backup_password_encrypted = (
            self._get_secret_fernet().encrypt(raw_password.encode("utf-8")).decode("utf-8")
        )

    def get_backup_password(self) -> str:
        if not self.backup_password_encrypted:
            return ""
        try:
            return (
                self._get_secret_fernet()
                .decrypt(self.backup_password_encrypted.encode("utf-8"))
                .decode("utf-8")
            )
        except (InvalidToken, ValueError, TypeError):
            return ""

    def set_backup_smtp_password(self, raw_password: str):
        raw_password = (raw_password or "").strip()
        if not raw_password:
            self.backup_smtp_password_encrypted = ""
            return
        self.backup_smtp_password_encrypted = (
            self._get_secret_fernet().encrypt(raw_password.encode("utf-8")).decode("utf-8")
        )

    def get_backup_smtp_password(self) -> str:
        if not self.backup_smtp_password_encrypted:
            return ""
        try:
            return (
                self._get_secret_fernet()
                .decrypt(self.backup_smtp_password_encrypted.encode("utf-8"))
                .decode("utf-8")
            )
        except (InvalidToken, ValueError, TypeError):
            return ""

    def is_backup_due(self, now=None) -> bool:
        if not self.backup_enabled or not self.backup_email or not self.get_backup_password():
            return False
        now = now or datetime.now(UTC)
        if self.backup_last_sent_at is None:
            return True
        return (now - self.backup_last_sent_at).days >= self.backup_interval_days

    def get_benchmark_code(self, key: str, default: str = "") -> str:
        """读取基准/默认指数代码配置。"""
        value = (self.benchmark_code_map or {}).get(key, default)
        return value if isinstance(value, str) else default

    def get_market_visual_tokens(self) -> dict[str, str]:
        """返回市场语义颜色 token 配置。"""
        palettes = {
            "cn_a_share": {
                "rise": "var(--color-error)",
                "fall": "var(--color-success)",
                "rise_soft": "var(--color-error-light)",
                "fall_soft": "var(--color-success-light)",
                "rise_strong": "var(--color-error-dark)",
                "fall_strong": "var(--color-success-dark)",
                "inflow": "var(--color-error)",
                "outflow": "var(--color-success)",
                "convention": "cn_a_share",
                "label": "A股红涨绿跌",
            },
            "us_market": {
                "rise": "var(--color-success)",
                "fall": "var(--color-error)",
                "rise_soft": "var(--color-success-light)",
                "fall_soft": "var(--color-error-light)",
                "rise_strong": "var(--color-success-dark)",
                "fall_strong": "var(--color-error-dark)",
                "inflow": "var(--color-success)",
                "outflow": "var(--color-error)",
                "convention": "us_market",
                "label": "美股绿涨红跌",
            },
        }
        return palettes.get(self.market_color_convention, palettes["cn_a_share"]).copy()

    def get_asset_proxy_code(self, asset_class: str, default: str = "") -> str:
        """读取资产类别代理代码配置。"""
        value = (self.asset_proxy_code_map or {}).get(asset_class, default)
        return value if isinstance(value, str) else default

    def get_macro_index_configs(self) -> list[dict]:
        """返回宏观指数配置列表。"""
        configs = self.macro_index_catalog or []
        return [item for item in configs if isinstance(item, dict) and item.get("code")]

    def get_macro_index_codes(self) -> list[str]:
        """返回已配置的宏观指数代码列表。"""
        return [item["code"] for item in self.get_macro_index_configs()]

    def get_macro_index_metadata_map(self) -> dict:
        """返回按代码索引的宏观指数元数据。"""
        metadata = {}
        for item in self.get_macro_index_configs():
            metadata[item["code"]] = {
                "name": item.get("name", item["code"]),
                "name_en": item.get("name_en", item["code"]),
                "category": item.get("category", "股票"),
                "unit": item.get("unit", ""),
                "description": item.get("description", ""),
                "publication_lag_days": int(item.get("publication_lag_days", 0) or 0),
            }
        return metadata

    def get_macro_publication_lags(self) -> dict:
        """返回宏观指数发布时间延迟配置。"""
        return {
            code: {
                "days": item.get("publication_lag_days", 0),
                "description": item.get("publication_lag_description", "实时"),
            }
            for code, item in self.get_macro_index_metadata_map().items()
        }

    @classmethod
    def get_runtime_benchmark_code(cls, key: str, default: str = "") -> str:
        return cls.get_settings().get_benchmark_code(key, default)

    @classmethod
    def get_runtime_asset_proxy_code(cls, asset_class: str, default: str = "") -> str:
        return cls.get_settings().get_asset_proxy_code(asset_class, default)

    @classmethod
    def get_runtime_market_visual_tokens(cls) -> dict[str, str]:
        return cls.get_settings().get_market_visual_tokens()

    @classmethod
    def get_runtime_asset_proxy_map(cls) -> dict:
        return cls.get_settings().asset_proxy_code_map or {}

    @classmethod
    def get_runtime_macro_index_configs(cls) -> list[dict]:
        return cls.get_settings().get_macro_index_configs()

    @classmethod
    def get_runtime_macro_index_metadata_map(cls) -> dict:
        return cls.get_settings().get_macro_index_metadata_map()

    @classmethod
    def get_runtime_macro_publication_lags(cls) -> dict:
        return cls.get_settings().get_macro_publication_lags()

    # ========== Qlib 配置获取方法 ==========
    def get_qlib_provider_uri(self) -> str:
        """获取 Qlib 数据目录，如果数据库未配置则回退到 settings.QLIB_SETTINGS"""
        from django.conf import settings
        from pathlib import Path

        default_uri = settings.QLIB_SETTINGS.get("provider_uri", "~/.qlib/qlib_data/cn_data")
        if self.qlib_provider_uri:
            configured_path = Path(self.qlib_provider_uri).expanduser()
            if configured_path.exists():
                return self.qlib_provider_uri
            default_path = Path(default_uri).expanduser()
            if default_path.exists():
                return str(default_path)
            return self.qlib_provider_uri

        return default_uri

    def get_qlib_region(self) -> str:
        """获取 Qlib 区域配置"""
        if self.qlib_region:
            return self.qlib_region
        from django.conf import settings

        return settings.QLIB_SETTINGS.get("region", "CN")

    def get_qlib_model_path(self) -> str:
        """获取 Qlib 模型目录"""
        from django.conf import settings
        from pathlib import Path

        default_path = settings.QLIB_SETTINGS.get("model_path", "/models/qlib")
        if self.qlib_model_path:
            configured_path = Path(self.qlib_model_path).expanduser()
            if configured_path.exists():
                return self.qlib_model_path
            fallback_path = Path(default_path).expanduser()
            if fallback_path.exists():
                return str(fallback_path)
            return self.qlib_model_path

        return default_path

    def is_qlib_configured(self) -> bool:
        """检查 Qlib 是否已配置且数据目录存在"""
        if not self.qlib_enabled:
            return False
        provider_uri = self.get_qlib_provider_uri()
        if not provider_uri:
            return False
        from pathlib import Path

        return Path(provider_uri).expanduser().exists()

    @classmethod
    def get_runtime_qlib_config(cls) -> dict:
        """获取运行时 Qlib 配置（类方法，便于调用）"""
        settings_obj = cls.get_settings()
        return {
            "enabled": settings_obj.qlib_enabled,
            "provider_uri": settings_obj.get_qlib_provider_uri(),
            "region": settings_obj.get_qlib_region(),
            "model_path": settings_obj.get_qlib_model_path(),
            "is_configured": settings_obj.is_qlib_configured(),
        }

    @classmethod
    def get_runtime_alpha_fixed_provider(cls) -> str:
        """获取运行时 Alpha 固定 Provider 配置（类方法，便于调用）"""
        settings_obj = cls.get_settings()
        return settings_obj.alpha_fixed_provider or ""

    @classmethod
    def get_runtime_alpha_pool_mode(cls) -> str:
        """获取运行时 Alpha 股票池模式（类方法，便于调用）"""
        settings_obj = cls.get_settings()
        return settings_obj.alpha_pool_mode or cls.ALPHA_POOL_MODE_STRICT_VALUATION

    @staticmethod
    def _get_default_agreement():
        """默认用户协议内容"""
        return """
<h2>AgomTradePro 用户服务协议</h2>
<p>欢迎使用 AgomTradePro（个人投研平台）！在使用本系统前，请仔细阅读以下条款：</p>

<h3>一、服务说明</h3>
<p>AgomTradePro 是一个辅助投资决策工具，通过宏观环境分析和策略回测帮助用户制定投资计划。本系统提供的所有信息仅供参考，不构成任何投资建议。</p>

<h3>二、用户责任</h3>
<ul>
    <li>用户应妥善保管账户和密码，对账户下的所有行为负责</li>
    <li>用户不得利用本系统进行任何违法或不当活动</li>
    <li>用户应确保提供的信息真实、准确、完整</li>
</ul>

<h3>三、免责声明</h3>
<ul>
    <li>本系统基于历史数据分析，历史业绩不代表未来表现</li>
    <li>投资有风险，决策需谨慎。本系统不对任何投资损失承担责任</li>
    <li>系统可能因技术故障、数据延迟等原因出现误差</li>
    <li>本系统保留随时修改或中断服务的权利</li>
</ul>

<h3>四、隐私保护</h3>
<p>我们将严格保护用户隐私，不会向第三方泄露用户个人信息（法律法规另有规定的除外）。</p>

<h3>五、协议修改</h3>
<p>本系统有权随时修改本协议，修改后的协议一经公布即生效。</p>
"""

    @staticmethod
    def _get_default_benchmark_code_map():
        return {
            "equity_default_index": "000300.SH",
            "equity_market_benchmark": "000300.SH",
            "factor_beta_benchmark": "000300.SH",
        }

    @staticmethod
    def _get_default_asset_proxy_code_map():
        return {
            "A_SHARE_GROWTH": "000300.SH",
            "A_SHARE_VALUE": "000905.SH",
            "CHINA_BOND": "TS01.CS",
            "GOLD": "AU9999.SGE",
            "COMMODITY": "NHCI.NH",
            "CASH": "CASH",
            "a_share_growth": "000300.SH",
            "a_share_value": "000905.SH",
            "china_bond": "TS01.CS",
            "gold": "AU9999.SGE",
            "commodity": "NHCI.NH",
            "cash": "CASH",
        }

    @staticmethod
    def _get_default_macro_index_catalog():
        return [
            {
                "code": "000001.SH",
                "name": "上证指数",
                "name_en": "SSE Composite",
                "category": "股票",
                "unit": "点",
                "description": "上海证券交易所综合指数",
                "publication_lag_days": 0,
                "publication_lag_description": "实时",
            },
            {
                "code": "399001.SZ",
                "name": "深证成指",
                "name_en": "SZSE Component",
                "category": "股票",
                "unit": "点",
                "description": "深圳证券交易所成分指数",
                "publication_lag_days": 0,
                "publication_lag_description": "实时",
            },
            {
                "code": "000300.SH",
                "name": "沪深300",
                "name_en": "CSI 300",
                "category": "股票",
                "unit": "点",
                "description": "沪深300指数",
                "publication_lag_days": 0,
                "publication_lag_description": "实时",
            },
            {
                "code": "000905.SH",
                "name": "中证500",
                "name_en": "CSI 500",
                "category": "股票",
                "unit": "点",
                "description": "中证500指数",
                "publication_lag_days": 0,
                "publication_lag_description": "实时",
            },
        ]

    @staticmethod
    def _get_default_risk_warning():
        """默认风险提示内容"""
        return """
<h2>投资风险提示书</h2>
<p>在使用 AgomTradePro 进行投资决策前，请充分了解以下风险：</p>

<h3>一、市场风险</h3>
<ul>
    <li><strong>价格波动风险：</strong>资产价格可能因市场变化而大幅波动，导致投资损失</li>
    <li><strong>流动性风险：</strong>某些资产可能在特定时期难以以合理价格买卖</li>
    <li><strong>系统性风险：</strong>宏观经济、政策变化等因素可能导致市场整体下跌</li>
</ul>

<h3>二、模型风险</h3>
<ul>
    <li><strong>历史局限性：</strong>本系统基于历史数据分析，历史规律未必在未来重复</li>
    <li><strong>模型偏差：</strong>任何模型都有其适用范围和局限性，可能产生错误信号</li>
    <li><strong>数据风险：</strong>数据来源、延迟、错误等因素可能影响分析结果</li>
</ul>

<h3>三、操作风险</h3>
<ul>
    <li><strong>执行偏差：</strong>实际交易可能与系统建议存在偏差</li>
    <li><strong>过度依赖：</strong>过度依赖系统信号而忽视基本面分析可能导致损失</li>
</ul>

<h3>四、特别提示</h3>
<ul>
    <li>模拟交易收益不代表实际交易收益</li>
    <li>回测结果是理想状态下的表现，实际交易存在滑点、手续费等成本</li>
    <li>投资决策应综合考虑个人风险承受能力、投资目标等因素</li>
    <li>建议在投资前咨询专业的投资顾问</li>
</ul>

<h3>五、风险自担</h3>
<p><strong>我已充分了解投资风险，理解本系统提供的所有信息仅供参考，将自行承担所有投资决策带来的风险和损失。</strong></p>
        """


class UserAccessTokenModel(models.Model):
    """支持多 Token 的 MCP/SDK 访问凭证。"""

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="access_tokens",
        verbose_name="所属用户",
    )
    name = models.CharField(
        max_length=100,
        default="default",
        verbose_name="Token名称",
        help_text="例如：Claude Desktop / Local SDK / VPS Script",
    )
    key = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        verbose_name="Token Key",
    )
    key_encrypted = models.TextField(
        blank=True,
        verbose_name="Token密文",
        help_text="用于按系统配置决定是否允许明文查看",
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_access_tokens",
        verbose_name="创建人",
    )
    last_used_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="最后使用时间",
    )
    revoked_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="撤销时间",
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="是否有效",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = "user_access_token"
        verbose_name = "用户访问Token"
        verbose_name_plural = "用户访问Token"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "name"],
                condition=models.Q(is_active=True),
                name="uniq_active_access_token_name_per_user",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "is_active"]),
            models.Index(fields=["key"]),
        ]

    def __str__(self):
        return f"{self.user.username}:{self.name}"

    @property
    def preview(self) -> str:
        if not self.key:
            return "-"
        return f"{self.key[:8]}...{self.key[-6:]}"

    @classmethod
    def generate_key(cls) -> str:
        return secrets.token_hex(20)

    @classmethod
    def create_token(cls, *, user: User, name: str, created_by: User | None = None):
        raw_name = (name or "").strip() or f"token-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
        raw_key = cls.generate_key()
        token = cls._default_manager.create(
            user=user,
            name=raw_name,
            key=raw_key,
            key_encrypted=_build_app_fernet().encrypt(raw_key.encode("utf-8")).decode("utf-8"),
            created_by=created_by,
        )
        return token, raw_key

    def reveal_key(self) -> str:
        if not self.key_encrypted:
            return ""
        try:
            return _build_app_fernet().decrypt(self.key_encrypted.encode("utf-8")).decode("utf-8")
        except (InvalidToken, ValueError, TypeError):
            return ""

    def revoke(self):
        self.is_active = False
        self.revoked_at = datetime.now(UTC)
        self.save(update_fields=["is_active", "revoked_at", "updated_at"])


# ============================================================
# Portfolio Observer Grant Model
# ============================================================


class PortfolioObserverGrantModel(models.Model):
    """
    投资组合观察员授权表

    记录用户 A 授权用户 B 查看其投资组合的记录。
    支持授权范围、状态管理和过期时间。
    """

    # 主键
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, verbose_name="授权ID")

    # 授权关系
    owner_user_id = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="granted_observers", verbose_name="账户拥有者"
    )
    observer_user_id = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="observed_portfolios", verbose_name="观察员"
    )

    # 授权范围（首版固定为 portfolio_read）
    SCOPE_CHOICES = [
        ("portfolio_read", "查看投资组合"),
    ]
    scope = models.CharField(
        max_length=50, choices=SCOPE_CHOICES, default="portfolio_read", verbose_name="授权范围"
    )

    # 状态枚举
    STATUS_CHOICES = [
        ("active", "激活"),
        ("revoked", "已撤销"),
        ("expired", "已过期"),
    ]
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="active", verbose_name="状态"
    )

    # 过期时间（可选）
    expires_at = models.DateTimeField(null=True, blank=True, verbose_name="过期时间")

    # 审计字段
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_observer_grants",
        verbose_name="创建者",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    revoked_at = models.DateTimeField(null=True, blank=True, verbose_name="撤销时间")
    revoked_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="revoked_observer_grants",
        verbose_name="撤销者",
    )

    class Meta:
        db_table = "portfolio_observer_grant"
        verbose_name = "投资组合观察员授权"
        verbose_name_plural = "投资组合观察员授权"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["owner_user_id", "observer_user_id"], name="idx_owner_observer"),
            models.Index(fields=["observer_user_id", "status"], name="idx_observer_status"),
            models.Index(fields=["status", "expires_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["owner_user_id", "observer_user_id"],
                condition=models.Q(status="active"),
                name="unique_active_grant",
            )
        ]

    def __str__(self):
        return f"{self.owner_user_id.username} -> {self.observer_user_id.username} ({self.get_status_display()})"

    def clean(self):
        """验证约束条件"""
        # 不能授权给自己
        if self.owner_user_id == self.observer_user_id:
            raise ValidationError({"observer_user_id": "不能授权给自己"})

        # 检查是否已存在 active 授权
        if self.status == "active":
            existing = PortfolioObserverGrantModel.objects.filter(
                owner_user_id=self.owner_user_id,
                observer_user_id=self.observer_user_id,
                status="active",
            ).exclude(id=self.id)
            if existing.exists():
                raise ValidationError(
                    {
                        "owner_user_id": "该用户已被授权为观察员",
                        "observer_user_id": "该用户已被授权为观察员",
                    }
                )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def is_valid(self):
        """检查授权是否有效"""
        if self.status != "active":
            return False
        if self.expires_at and self.expires_at < datetime.now(UTC):
            return False
        return True

    def is_expired(self):
        """检查授权是否已过期"""
        if self.expires_at is None:
            return False
        return self.expires_at < datetime.now(UTC)

    def revoke(self, revoked_by_user):
        """撤销授权"""
        self.status = "revoked"
        self.revoked_at = datetime.now(UTC)
        self.revoked_by = revoked_by_user
        self.save()


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

    def __str__(self) -> str:
        return f"MacroSizingConfig v{self.version} (active={self.is_active})"

# Shared configuration models repatriated from shared.infrastructure.models

class TransactionCostConfigModel(models.Model):
    """
    交易成本配置表

    存储不同市场和资产类别的交易成本参数。
    """

    MARKET_CHOICES = [
        ('CN_A_SHARE', 'A股'),
        ('CN_HK_STOCK', '港股'),
        ('US_STOCK', '美股'),
        ('CN_FUND', '基金'),
        ('CN_FUTURES', '期货'),
        ('CRYPTO', '加密货币'),
        ('other', '其他'),
    ]

    ASSET_CLASS_CHOICES = [
        ('equity', '股票'),
        ('fixed_income', '债券'),
        ('fund', '基金'),
        ('derivative', '衍生品'),
        ('other', '其他'),
    ]

    market = models.CharField(
        max_length=20,
        choices=MARKET_CHOICES,
        verbose_name="市场"
    )

    asset_class = models.CharField(
        max_length=20,
        choices=ASSET_CLASS_CHOICES,
        verbose_name="资产类别"
    )

    # 成本参数（均为百分比，如 0.0003 表示 0.03%）
    commission_rate = models.FloatField(
        default=0.0003,
        verbose_name="佣金费率",
        help_text="如 0.0003 表示万分之三"
    )

    slippage_rate = models.FloatField(
        default=0.0002,
        verbose_name="滑点费率",
        help_text="如 0.0002 表示万分之二"
    )

    stamp_duty_rate = models.FloatField(
        default=0.001,
        verbose_name="印花税率",
        help_text="仅卖出时收取，如 0.001 表示千分之一"
    )

    # 其他费用
    transfer_fee_rate = models.FloatField(
        default=0.00001,
        verbose_name="过户费率",
        help_text="如 0.00001 表示万分之一"
    )

    # 最小费用
    min_commission = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=5.00,
        verbose_name="最低佣金",
        help_text="单笔交易最低佣金（元）"
    )

    # 成本阈值
    cost_warning_threshold = models.FloatField(
        default=0.005,
        verbose_name="成本预警阈值",
        help_text="成本占交易额比例超过此值时预警，如 0.005 表示 0.5%"
    )

    is_active = models.BooleanField(default=True, verbose_name="是否启用")
    notes = models.TextField(blank=True, verbose_name="备注")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = 'transaction_cost_config'
        verbose_name = '交易成本配置'
        verbose_name_plural = '交易成本配置'
        unique_together = [['market', 'asset_class']]
        indexes = [
            models.Index(fields=['market', 'asset_class']),
            models.Index(fields=['is_active']),
        ]

    def __str__(self):
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
            Decimal(str(trade_value_float * self.commission_rate)),
            self.min_commission
        )

        # 滑点
        slippage = Decimal(str(trade_value_float * self.slippage_rate))

        # 印花税（仅卖出）
        stamp_duty = Decimal('0') if is_buy else Decimal(str(trade_value_float * self.stamp_duty_rate))

        # 过户费
        transfer_fee = Decimal(str(trade_value_float * self.transfer_fee_rate))

        # 总成本
        total_cost = commission + slippage + stamp_duty + transfer_fee

        return {
            'commission': commission,
            'slippage': slippage,
            'stamp_duty': stamp_duty,
            'transfer_fee': transfer_fee,
            'total_cost': total_cost,
            'cost_ratio': float(total_cost) / trade_value_float if trade_value_float > 0 else 0,
        }

