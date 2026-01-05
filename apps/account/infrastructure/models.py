"""
Account Infrastructure Models

Django ORM 模型定义，负责数据持久化。
将 Domain 层实体映射到数据库表。
"""

from django.db import models
from django.db.models import Sum, F
from django.contrib.auth.models import User
from decimal import Decimal


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
    asset_code = models.CharField(max_length=50, unique=True, db_index=True, verbose_name="资产代码")
    name = models.CharField(max_length=200, verbose_name="资产名称")
    description = models.TextField(blank=True, verbose_name="描述")

    # 预定义分类（枚举）
    ASSET_CLASS_CHOICES = [
        ('equity', '股票'),
        ('fixed_income', '固定收益'),
        ('commodity', '商品'),
        ('currency', '外汇'),
        ('cash', '现金'),
        ('fund', '基金'),
        ('derivative', '衍生品'),
        ('other', '其他'),
    ]
    asset_class = models.CharField(max_length=20, choices=ASSET_CLASS_CHOICES, verbose_name="资产大类")

    REGION_CHOICES = [
        ('CN', '中国境内'),
        ('US', '美国'),
        ('EU', '欧洲'),
        ('JP', '日本'),
        ('EM', '新兴市场'),
        ('GLOBAL', '全球'),
        ('OTHER', '其他'),
    ]
    region = models.CharField(max_length=10, choices=REGION_CHOICES, verbose_name="地区")

    CROSS_BORDER_CHOICES = [
        ('domestic', '境内资产'),
        ('qdii', 'QDII基金'),
        ('direct_foreign', '直接境外投资'),
    ]
    cross_border = models.CharField(max_length=20, choices=CROSS_BORDER_CHOICES, default='domestic', verbose_name="跨境标识")

    STYLE_CHOICES = [
        ('growth', '成长'),
        ('value', '价值'),
        ('blend', '混合'),
        ('cyclical', '周期'),
        ('defensive', '防御'),
        ('quality', '质量'),
        ('momentum', '动量'),
        ('unknown', '未知/不适用'),
    ]
    style = models.CharField(max_length=20, choices=STYLE_CHOICES, default='unknown', verbose_name="投资风格")

    # 用户可自定义分类
    sector = models.CharField(max_length=50, blank=True, verbose_name="行业板块")
    sub_class = models.CharField(max_length=50, blank=True, verbose_name="子类")

    # 元数据
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'asset_metadata'
        verbose_name = '资产元数据'
        verbose_name_plural = '资产元数据'
        indexes = [
            models.Index(fields=['asset_code']),
            models.Index(fields=['asset_class', 'region']),
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
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='account_profile', verbose_name="用户")

    display_name = models.CharField(max_length=100, verbose_name="显示名称")

    initial_capital = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=Decimal('1000000.00'),
        verbose_name="初始资金"
    )

    RISK_TOLERANCE_CHOICES = [
        ('conservative', '保守型'),
        ('moderate', '稳健型'),
        ('aggressive', '激进型'),
    ]
    risk_tolerance = models.CharField(
        max_length=20,
        choices=RISK_TOLERANCE_CHOICES,
        default='moderate',
        verbose_name="风险偏好"
    )

    # 波动率目标配置
    target_volatility = models.FloatField(
        default=0.15,
        verbose_name="目标波动率",
        help_text="年化波动率目标，如0.15表示15%"
    )

    volatility_tolerance = models.FloatField(
        default=0.2,
        verbose_name="波动率容忍度",
        help_text="超过目标波动率多少比例触发降仓，如0.2表示20%"
    )

    max_volatility_reduction = models.FloatField(
        default=0.5,
        verbose_name="最大降仓幅度",
        help_text="波动率超标时最大降仓比例，如0.5表示最多降50%"
    )

    # 用户协议和审批相关字段
    user_agreement_accepted = models.BooleanField(
        default=False,
        verbose_name="用户协议已接受"
    )
    risk_warning_acknowledged = models.BooleanField(
        default=False,
        verbose_name="风险提示已确认"
    )
    agreement_accepted_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="协议接受时间"
    )
    agreement_ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        verbose_name="协议接受IP"
    )

    # 用户审批状态（⭐新增）
    APPROVAL_STATUS_CHOICES = [
        ('pending', '待审批'),
        ('approved', '已批准'),
        ('rejected', '已拒绝'),
        ('auto_approved', '自动批准'),
    ]
    approval_status = models.CharField(
        max_length=20,
        choices=APPROVAL_STATUS_CHOICES,
        default='pending',
        verbose_name="审批状态"
    )
    approved_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="批准时间"
    )
    approved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_users',
        verbose_name="审批人"
    )
    rejection_reason = models.TextField(
        blank=True,
        verbose_name="拒绝原因"
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = 'account_profile'
        verbose_name = '账户配置'
        verbose_name_plural = '账户配置'

    def __str__(self):
        return f"{self.user.username} - {self.display_name}"


class PortfolioModel(models.Model):
    """
    投资组合表

    用户可以有多个投资组合（如：实盘、模拟盘、策略A、策略B）。
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='portfolios', verbose_name="用户")

    name = models.CharField(max_length=100, default='默认组合', verbose_name="组合名称")
    base_currency = models.ForeignKey(
        'CurrencyModel',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='portfolios',
        verbose_name="基准货币"
    )

    is_active = models.BooleanField(default=True, verbose_name="是否激活")

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = 'portfolio'
        verbose_name = '投资组合'
        verbose_name_plural = '投资组合'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username} - {self.name}"

    @property
    def total_value(self):
        """总市值"""
        from django.db.models import Sum
        result = self.positions.filter(is_closed=False).aggregate(
            total=Sum('market_value')
        )['total']
        return result or Decimal('0')

    @property
    def total_cost(self):
        """总成本"""
        from django.db.models import F, DecimalField
        result = self.positions.filter(is_closed=False).aggregate(
            total=Sum(F('shares') * F('avg_cost'), output_field=DecimalField())
        )['total']
        return result or Decimal('0')

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
        PortfolioModel,
        on_delete=models.CASCADE,
        related_name='positions',
        verbose_name="投资组合"
    )

    asset_code = models.CharField(max_length=20, db_index=True, verbose_name="资产代码")

    # 资产分类和币种（新增）
    category = models.ForeignKey(
        'AssetCategoryModel',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='positions',
        verbose_name="资产分类"
    )
    currency = models.ForeignKey(
        'CurrencyModel',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='positions',
        verbose_name="币种"
    )

    # 冗余分类字段（从 AssetMetadata 同步，用于快速查询）
    asset_class = models.CharField(max_length=20, choices=AssetMetadataModel.ASSET_CLASS_CHOICES, verbose_name="资产大类")
    region = models.CharField(max_length=10, choices=AssetMetadataModel.REGION_CHOICES, verbose_name="地区")
    cross_border = models.CharField(max_length=20, choices=AssetMetadataModel.CROSS_BORDER_CHOICES, verbose_name="跨境标识")

    # 持仓信息
    shares = models.FloatField(verbose_name="持仓数量")
    avg_cost = models.DecimalField(max_digits=20, decimal_places=4, verbose_name="平均成本价")
    current_price = models.DecimalField(max_digits=20, decimal_places=4, null=True, verbose_name="当前市价")

    # 盈亏信息（冗余，便于查询）
    market_value = models.DecimalField(max_digits=20, decimal_places=2, default=0, verbose_name="市值")
    unrealized_pnl = models.DecimalField(max_digits=20, decimal_places=2, default=0, verbose_name="未实现盈亏")
    unrealized_pnl_pct = models.FloatField(default=0, verbose_name="未实现盈亏百分比")

    # 来源追踪
    SOURCE_CHOICES = [
        ('manual', '手动录入'),
        ('signal', '投资信号'),
        ('backtest', '回测结果'),
    ]
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='manual', verbose_name="来源")
    source_id = models.IntegerField(null=True, blank=True, verbose_name="来源ID")  # signal_id 或 backtest_id

    # 状态
    is_closed = models.BooleanField(default=False, verbose_name="是否已平仓")
    opened_at = models.DateTimeField(auto_now_add=True, verbose_name="开仓时间")
    closed_at = models.DateTimeField(null=True, blank=True, verbose_name="平仓时间")

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = 'position'
        verbose_name = '持仓记录'
        verbose_name_plural = '持仓记录'
        indexes = [
            models.Index(fields=['portfolio', 'asset_code']),
            models.Index(fields=['source', 'source_id']),
            models.Index(fields=['asset_class', 'region']),
            models.Index(fields=['is_closed']),
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
        related_name='transactions',
        verbose_name="投资组合"
    )

    position = models.ForeignKey(
        PositionModel,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transactions',
        verbose_name="关联持仓"
    )

    ACTION_CHOICES = [
        ('buy', '买入'),
        ('sell', '卖出'),
    ]
    action = models.CharField(max_length=10, choices=ACTION_CHOICES, verbose_name="交易方向")

    asset_code = models.CharField(max_length=20, verbose_name="资产代码")
    shares = models.FloatField(verbose_name="交易数量")
    price = models.DecimalField(max_digits=20, decimal_places=4, verbose_name="成交价格")
    notional = models.DecimalField(max_digits=20, decimal_places=2, verbose_name="成交金额")

    # 成本明细
    commission = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="手续费")
    slippage = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="滑点成本")
    stamp_duty = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="印花税")
    transfer_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="过户费")

    # 成本预估（交易前）
    estimated_cost = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="预估成本"
    )
    estimated_cost_ratio = models.FloatField(
        null=True,
        blank=True,
        verbose_name="预估成本比例"
    )

    # 成本对比
    cost_variance = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="成本差异",
        help_text="实际成本 - 预估成本"
    )
    cost_variance_pct = models.FloatField(
        null=True,
        blank=True,
        verbose_name="成本差异百分比"
    )

    traded_at = models.DateTimeField(verbose_name="交易时间")
    notes = models.TextField(blank=True, verbose_name="备注")

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        db_table = 'transaction'
        verbose_name = '交易记录'
        verbose_name_plural = '交易记录'
        ordering = ['-traded_at']
        indexes = [
            models.Index(fields=['portfolio', 'traded_at']),
            models.Index(fields=['asset_code']),
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
        PositionModel,
        on_delete=models.CASCADE,
        related_name='signal_logs',
        verbose_name="持仓"
    )

    executed_at = models.DateTimeField(auto_now_add=True, verbose_name="执行时间")
    notes = models.TextField(blank=True, verbose_name="备注")

    class Meta:
        db_table = 'position_signal_log'
        verbose_name = '持仓信号日志'
        verbose_name_plural = '持仓信号日志'


class PortfolioDailySnapshotModel(models.Model):
    """
    投资组合日快照表

    记录每个投资组合在每个交易日的总资产，用于计算回溯收益率。
    """
    portfolio = models.ForeignKey(
        PortfolioModel,
        on_delete=models.CASCADE,
        related_name='daily_snapshots',
        verbose_name="投资组合"
    )

    snapshot_date = models.DateField(db_index=True, verbose_name="快照日期")

    total_value = models.DecimalField(max_digits=20, decimal_places=2, verbose_name="总资产")

    cash_balance = models.DecimalField(max_digits=20, decimal_places=2, default=0, verbose_name="现金余额")

    invested_value = models.DecimalField(max_digits=20, decimal_places=2, default=0, verbose_name="投资市值")

    position_count = models.IntegerField(default=0, verbose_name="持仓数量")

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        db_table = 'portfolio_daily_snapshot'
        unique_together = [['portfolio', 'snapshot_date']]
        ordering = ['-snapshot_date']
        indexes = [
            models.Index(fields=['portfolio', '-snapshot_date']),
        ]
        verbose_name = '投资组合日快照'
        verbose_name_plural = '投资组合日快照'

    def __str__(self):
        return f"{self.portfolio.name} @ {self.snapshot_date}: ¥{self.total_value}"


class InvestmentRuleModel(models.Model):
    """
    投资规则配置表

    存储系统生成的投资建议规则，支持动态配置。
    """
    RULE_TYPE_CHOICES = [
        ('regime_advice', 'Regime环境建议'),
        ('position_advice', '仓位建议'),
        ('match_advice', 'Regime匹配度建议'),
        ('signal_advice', '投资信号建议'),
        ('risk_alert', '风险提示'),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='investment_rules',
        null=True,
        blank=True,
        verbose_name="用户（null表示全局默认规则）"
    )

    name = models.CharField(max_length=100, verbose_name="规则名称")

    rule_type = models.CharField(
        max_length=20,
        choices=RULE_TYPE_CHOICES,
        verbose_name="规则类型"
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
        db_table = 'investment_rule'
        ordering = ['priority', 'id']
        verbose_name = '投资规则'
        verbose_name_plural = '投资规则'
        indexes = [
            models.Index(fields=['user', 'rule_type', 'is_active']),
        ]

    def __str__(self):
        return f"{self.name} ({self.get_rule_type_display()})"


class CapitalFlowModel(models.Model):
    """
    资金流水表

    记录用户的入金/出金操作，用于计算累计投入和收益率。
    """
    FLOW_TYPE_CHOICES = [
        ('deposit', '入金'),
        ('withdraw', '出金'),
        ('dividend', '分红'),
        ('interest', '利息'),
        ('adjustment', '调整'),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='capital_flows',
        verbose_name="用户"
    )

    portfolio = models.ForeignKey(
        PortfolioModel,
        on_delete=models.CASCADE,
        related_name='capital_flows',
        verbose_name="投资组合"
    )

    flow_type = models.CharField(
        max_length=20,
        choices=FLOW_TYPE_CHOICES,
        verbose_name="流水类型"
    )

    amount = models.DecimalField(max_digits=20, decimal_places=2, verbose_name="金额")

    flow_date = models.DateField(db_index=True, verbose_name="流水日期")

    notes = models.TextField(blank=True, verbose_name="备注")

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        db_table = 'capital_flow'
        ordering = ['-flow_date', '-created_at']
        verbose_name = '资金流水'
        verbose_name_plural = '资金流水'
        indexes = [
            models.Index(fields=['user', 'flow_type', '-flow_date']),
        ]

    def __str__(self):
        return f"{self.get_flow_type_display()} {self.amount} ({self.flow_date})"


class DocumentationModel(models.Model):
    """
    文档表

    存储系统文档，支持 Markdown 格式。
    """
    CATEGORY_CHOICES = [
        ('user_guide', '用户指南'),
        ('concept', '概念说明'),
        ('api', 'API 文档'),
        ('development', '开发文档'),
        ('other', '其他'),
    ]

    title = models.CharField(max_length=200, verbose_name="标题")
    slug = models.SlugField(max_length=100, unique=True, db_index=True, verbose_name="URL标识")
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='user_guide', verbose_name="分类")
    content = models.TextField(verbose_name="内容（Markdown）")
    summary = models.TextField(blank=True, verbose_name="摘要")
    order = models.IntegerField(default=0, verbose_name="排序（数字越小越靠前）")
    is_published = models.BooleanField(default=True, verbose_name="是否发布")

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = 'documentation'
        ordering = ['order', '-created_at']
        verbose_name = '文档'
        verbose_name_plural = '文档'
        indexes = [
            models.Index(fields=['slug', 'is_published']),
            models.Index(fields=['category', 'is_published']),
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
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='children',
        verbose_name="父分类"
    )

    level = models.IntegerField(default=1, verbose_name="层级")  # 1=一级, 2=二级, etc.
    path = models.CharField(max_length=200, verbose_name="分类路径")  # 例如：基金/股票基金

    description = models.TextField(blank=True, verbose_name="描述")
    is_active = models.BooleanField(default=True, verbose_name="是否启用")
    sort_order = models.IntegerField(default=0, verbose_name="排序")

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = 'asset_category'
        verbose_name = '资产分类'
        verbose_name_plural = '资产分类'
        ordering = ['path', 'sort_order']
        indexes = [
            models.Index(fields=['code']),
            models.Index(fields=['parent']),
            models.Index(fields=['level']),
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

    code = models.CharField(max_length=10, unique=True, verbose_name="币种代码")  # CNY, USD, EUR, HKD
    name = models.CharField(max_length=50, verbose_name="币种名称")  # 人民币, 美元, 欧元, 港币
    symbol = models.CharField(max_length=10, verbose_name="货币符号")  # ¥, $, €, HK$

    is_base = models.BooleanField(default=False, verbose_name="是否基准货币")
    is_active = models.BooleanField(default=True, verbose_name="是否启用")

    # 精度设置
    precision = models.IntegerField(default=2, verbose_name="小数位数")  # CNY通常2位，JPY可能0位

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = 'currency'
        verbose_name = '币种'
        verbose_name_plural = '币种'
        ordering = ['-is_base', 'code']

    def __str__(self):
        return f"{self.code} - {self.name} ({self.symbol})"

    @classmethod
    def get_base_currency(cls):
        """获取基准货币"""
        return cls.objects.filter(is_base=True).first() or cls.objects.filter(code='CNY').first()


# ============================================================
# 汇率模型
# ============================================================

class ExchangeRateModel(models.Model):
    """
    汇率模型

    存储历史汇率数据，支持汇率换算。
    """

    from_currency = models.ForeignKey(
        CurrencyModel,
        on_delete=models.CASCADE,
        related_name='rates_from',
        verbose_name="源币种"
    )
    to_currency = models.ForeignKey(
        CurrencyModel,
        on_delete=models.CASCADE,
        related_name='rates_to',
        verbose_name="目标币种"
    )

    rate = models.DecimalField(max_digits=20, decimal_places=6, verbose_name="汇率")
    effective_date = models.DateField(db_index=True, verbose_name="生效日期")

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        db_table = 'exchange_rate'
        verbose_name = '汇率'
        verbose_name_plural = '汇率'
        ordering = ['-effective_date']
        unique_together = [['from_currency', 'to_currency', 'effective_date']]
        indexes = [
            models.Index(fields=['from_currency', 'to_currency', 'effective_date']),
        ]

    def __str__(self):
        return f"{self.from_currency.code} -> {self.to_currency.code}: {self.rate} ({self.effective_date})"

    def convert(self, amount: Decimal) -> Decimal:
        """将金额从源币种转换为目标币种"""
        return amount * self.rate

    @classmethod
    def get_latest_rate(cls, from_code: str, to_code: str) -> 'ExchangeRateModel':
        """获取最新汇率"""
        return cls.objects.filter(
            from_currency__code=from_code,
            to_currency__code=to_code
        ).order_by('-effective_date').first()

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

        queryset = cls.objects.filter(
            from_currency__code=from_code,
            to_currency__code=to_code
        )

        if date:
            queryset = queryset.filter(effective_date__lte=date).order_by('-effective_date')
        else:
            queryset = queryset.order_by('-effective_date')

        rate = queryset.first()
        if not rate:
            raise ValueError(f"No exchange rate found for {from_code} -> {to_code}")

        return rate.convert(amount)


# ============================================================
# 止损止盈模型
# ============================================================

class StopLossConfigModel(models.Model):
    """
    止损配置表

    为每个持仓配置止损规则。
    """

    STOP_LOSS_TYPE_CHOICES = [
        ('fixed', '固定止损'),
        ('trailing', '移动止损'),
        ('time_based', '时间止损'),
    ]

    STATUS_CHOICES = [
        ('active', '激活中'),
        ('triggered', '已触发'),
        ('cancelled', '已取消'),
        ('expired', '已过期'),
    ]

    position = models.OneToOneField(
        PositionModel,
        on_delete=models.CASCADE,
        related_name='stop_loss_config',
        verbose_name="关联持仓"
    )

    stop_loss_type = models.CharField(
        max_length=20,
        choices=STOP_LOSS_TYPE_CHOICES,
        default='fixed',
        verbose_name="止损类型"
    )

    stop_loss_pct = models.FloatField(
        verbose_name="止损百分比",
        help_text="如 -0.10 表示 -10%"
    )

    trailing_stop_pct = models.FloatField(
        null=True,
        blank=True,
        verbose_name="移动止损百分比",
        help_text="移动止损时使用，如 -0.10"
    )

    max_holding_days = models.IntegerField(
        null=True,
        blank=True,
        verbose_name="最大持仓天数",
        help_text="时间止损时使用"
    )

    # 追踪最高价（用于移动止损）
    highest_price = models.DecimalField(
        max_digits=20,
        decimal_places=4,
        null=True,
        blank=True,
        verbose_name="持仓期间最高价"
    )

    highest_price_updated_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="最高价更新时间"
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='active',
        verbose_name="状态"
    )

    activated_at = models.DateTimeField(auto_now_add=True, verbose_name="激活时间")
    triggered_at = models.DateTimeField(null=True, blank=True, verbose_name="触发时间")

    notes = models.TextField(blank=True, verbose_name="备注")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = 'stop_loss_config'
        verbose_name = '止损配置'
        verbose_name_plural = '止损配置'
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['position', 'status']),
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
        related_name='take_profit_config',
        verbose_name="关联持仓"
    )

    take_profit_pct = models.FloatField(
        verbose_name="止盈百分比",
        help_text="如 0.20 表示 +20%"
    )

    # 分批止盈配置
    partial_profit_levels = models.JSONField(
        null=True,
        blank=True,
        verbose_name="分批止盈点位",
        help_text="如 [0.10, 0.20, 0.30] 表示在10%, 20%, 30%时各止盈一部分"
    )

    is_active = models.BooleanField(default=True, verbose_name="是否激活")
    notes = models.TextField(blank=True, verbose_name="备注")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = 'take_profit_config'
        verbose_name = '止盈配置'
        verbose_name_plural = '止盈配置'
        indexes = [
            models.Index(fields=['is_active']),
            models.Index(fields=['position', 'is_active']),
        ]

    def __str__(self):
        return f"{self.position.asset_code} - 止盈 {self.take_profit_pct:.2%}"


class StopLossTriggerModel(models.Model):
    """
    止损触发记录表

    记录所有止损触发的详细信息，用于审计和分析。
    """

    TRIGGER_TYPE_CHOICES = [
        ('fixed', '固定止损'),
        ('trailing', '移动止损'),
        ('time_based', '时间止损'),
    ]

    position = models.ForeignKey(
        PositionModel,
        on_delete=models.CASCADE,
        related_name='stop_loss_triggers',
        verbose_name="关联持仓"
    )

    trigger_type = models.CharField(
        max_length=20,
        choices=TRIGGER_TYPE_CHOICES,
        verbose_name="触发类型"
    )

    trigger_price = models.DecimalField(max_digits=20, decimal_places=4, verbose_name="触发价格")
    trigger_time = models.DateTimeField(verbose_name="触发时间")
    trigger_reason = models.TextField(verbose_name="触发原因")

    pnl = models.DecimalField(max_digits=20, decimal_places=2, verbose_name="盈亏金额")
    pnl_pct = models.FloatField(verbose_name="盈亏百分比")

    notes = models.TextField(blank=True, verbose_name="备注")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        db_table = 'stop_loss_trigger'
        verbose_name = '止损触发记录'
        verbose_name_plural = '止损触发记录'
        ordering = ['-trigger_time']
        indexes = [
            models.Index(fields=['position', '-trigger_time']),
            models.Index(fields=['trigger_type']),
        ]

    def __str__(self):
        return f"{self.position.asset_code} - {self.get_trigger_type_display()} @ {self.trigger_price}"


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
        default=True,
        verbose_name="需要管理员审批新用户",
        help_text="关闭后新用户注册将自动批准"
    )

    auto_approve_first_admin = models.BooleanField(
        default=True,
        verbose_name="自动批准首个管理员用户",
        help_text="系统无管理员时，首个注册的用户自动成为管理员并获得批准"
    )

    # 用户协议内容配置
    user_agreement_content = models.TextField(
        blank=True,
        verbose_name="用户协议内容",
        help_text="用户注册时需要同意的协议内容，支持HTML"
    )

    risk_warning_content = models.TextField(
        blank=True,
        verbose_name="风险提示内容",
        help_text="用户注册时需要确认的风险提示内容，支持HTML"
    )

    # 默认值说明
    notes = models.TextField(
        blank=True,
        verbose_name="备注"
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = 'system_settings'
        verbose_name = '系统配置'
        verbose_name_plural = '系统配置'

    def __str__(self):
        return f"系统配置 (审批:{'开启' if self.require_user_approval else '关闭'})"

    @classmethod
    def get_settings(cls):
        """获取系统配置（单例模式）"""
        settings, created = cls.objects.get_or_create(
            pk=1,
            defaults={
                'require_user_approval': True,
                'auto_approve_first_admin': True,
                'user_agreement_content': cls._get_default_agreement(),
                'risk_warning_content': cls._get_default_risk_warning(),
            }
        )
        return settings

    @staticmethod
    def _get_default_agreement():
        """默认用户协议内容"""
        return """
<h2>AgomSAAF 用户服务协议</h2>
<p>欢迎使用 AgomSAAF（宏观环境准入系统）！在使用本系统前，请仔细阅读以下条款：</p>

<h3>一、服务说明</h3>
<p>AgomSAAF 是一个辅助投资决策工具，通过宏观环境分析和策略回测帮助用户制定投资计划。本系统提供的所有信息仅供参考，不构成任何投资建议。</p>

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
    def _get_default_risk_warning():
        """默认风险提示内容"""
        return """
<h2>投资风险提示书</h2>
<p>在使用 AgomSAAF 进行投资决策前，请充分了解以下风险：</p>

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
