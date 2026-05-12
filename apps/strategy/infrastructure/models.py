"""
Django ORM Models for Strategy System

Infrastructure层:
- 使用Django ORM定义数据表
- 对应Domain层的实体
- 包含索引优化和约束
"""
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class StrategyModel(models.Model):
    """策略主表"""

    # 基本信息
    name = models.CharField("策略名称", max_length=200)
    description = models.TextField("策略描述", blank=True)

    # 策略类型
    strategy_type = models.CharField(
        "策略类型",
        max_length=20,
        choices=[
            ('rule_based', '规则驱动'),
            ('script_based', '脚本驱动'),
            ('hybrid', '混合模式'),
            ('ai_driven', 'AI驱动')
        ],
        db_index=True
    )

    # 版本控制
    version = models.PositiveIntegerField("版本号", default=1)
    is_active = models.BooleanField("是否激活", default=True, db_index=True)

    # 风控参数（策略级别）
    max_position_pct = models.FloatField(
        "单资产最大持仓比例(%)",
        default=20.0,
        validators=[MinValueValidator(0.0), MaxValueValidator(100.0)]
    )
    max_total_position_pct = models.FloatField(
        "总持仓比例上限(%)",
        default=95.0,
        validators=[MinValueValidator(0.0), MaxValueValidator(100.0)]
    )
    stop_loss_pct = models.FloatField(
        "止损比例(%)",
        null=True,
        blank=True,
        validators=[MinValueValidator(0.0), MaxValueValidator(100.0)]
    )

    # 元数据
    created_by = models.ForeignKey(
        'account.AccountProfileModel',
        on_delete=models.CASCADE,
        verbose_name="创建者",
        db_index=True
    )
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        db_table = 'strategy'
        verbose_name = "投资策略"
        verbose_name_plural = "投资策略"
        unique_together = [['name', 'version', 'created_by']]
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['strategy_type', 'is_active']),
            models.Index(fields=['created_by', '-created_at']),
        ]

    def __str__(self):
        return f"{self.name} v{self.version} ({self.get_strategy_type_display()})"


class PositionManagementRuleModel(models.Model):
    """仓位管理规则（数据库驱动，不在代码中硬编码价格规则）"""

    strategy = models.OneToOneField(
        StrategyModel,
        on_delete=models.CASCADE,
        related_name='position_management_rule',
        verbose_name="所属策略",
    )
    name = models.CharField("规则名称", max_length=200)
    description = models.TextField("规则描述", blank=True)
    is_active = models.BooleanField("是否启用", default=True, db_index=True)
    price_precision = models.PositiveSmallIntegerField(
        "价格精度",
        default=2,
        validators=[MinValueValidator(0), MaxValueValidator(8)],
    )

    # 变量定义（用于文档和前端引导），例如:
    # [{"name":"current_price","type":"number","required":true}]
    variables_schema = models.JSONField(default=list, blank=True)

    # 条件表达式（返回 bool）
    buy_condition_expr = models.TextField(
        "买入触发条件表达式",
        blank=True,
        help_text="示例: current_price <= support_price and volume_ratio >= 1.2",
    )
    sell_condition_expr = models.TextField(
        "卖出触发条件表达式",
        blank=True,
        help_text="示例: current_price >= resistance_price or regime_score < 0.4",
    )

    # 价格/仓位表达式（返回 number）
    buy_price_expr = models.TextField(
        "建议买入价表达式",
        help_text="示例: breakout_price * (1 + slippage_pct)",
    )
    sell_price_expr = models.TextField(
        "建议卖出价表达式",
        help_text="示例: buy_price * (1 + target_return_pct)",
    )
    stop_loss_expr = models.TextField(
        "止损价表达式",
        help_text="示例: min(structure_low, buy_price - 2 * atr)",
    )
    take_profit_expr = models.TextField(
        "止盈价表达式",
        help_text="示例: buy_price + 2 * (buy_price - stop_loss_price)",
    )
    position_size_expr = models.TextField(
        "仓位计算表达式",
        help_text=(
            "示例: (account_equity * risk_per_trade_pct) / "
            "abs(buy_price - stop_loss_price)"
        ),
    )

    metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        db_table = 'position_management_rule'
        verbose_name = "仓位管理规则"
        verbose_name_plural = "仓位管理规则"
        ordering = ['-updated_at']
        indexes = [
            models.Index(fields=['strategy', 'is_active']),
            models.Index(fields=['is_active', '-updated_at']),
        ]

    def __str__(self):
        return f"{self.strategy.name} - {self.name}"


class RuleConditionModel(models.Model):
    """规则条件（用于 rule_based 策略）"""

    # 关联策略
    strategy = models.ForeignKey(
        StrategyModel,
        on_delete=models.CASCADE,
        related_name='rules',
        verbose_name="所属策略"
    )

    # 规则标识
    rule_name = models.CharField("规则名称", max_length=200)
    rule_type = models.CharField(
        "规则类型",
        max_length=50,
        choices=[
            ('macro', '宏观指标'),
            ('regime', 'Regime判定'),
            ('signal', '投资信号'),
            ('technical', '技术指标'),
            ('composite', '组合条件')
        ]
    )

    # JSON 格式存储规则条件
    condition_json = models.JSONField(
        verbose_name="条件表达式",
        help_text="JSON格式: 支持AND/OR/NOT、比较运算、趋势判断"
    )

    # 触发动作
    action = models.CharField(
        "动作",
        max_length=50,
        choices=[
            ('buy', '买入'),
            ('sell', '卖出'),
            ('hold', '持有'),
            ('weight', '设置权重')
        ]
    )

    # 目标配置
    weight = models.FloatField(
        "目标权重",
        null=True,
        blank=True,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)]
    )
    target_assets = models.JSONField(
        default=list,
        blank=True,
        help_text="空列表表示所有可投资产"
    )

    # 优先级和控制
    priority = models.IntegerField("优先级", default=0, db_index=True)
    is_enabled = models.BooleanField("是否启用", default=True)

    # 元数据
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        db_table = 'rule_condition'
        verbose_name = "规则条件"
        verbose_name_plural = "规则条件"
        ordering = ['-priority', '-created_at']
        indexes = [
            models.Index(fields=['strategy', '-priority']),
            models.Index(fields=['rule_type', 'is_enabled']),
        ]

    def __str__(self):
        return f"{self.rule_name} ({self.get_rule_type_display()})"


class ScriptConfigModel(models.Model):
    """脚本配置（用于 script_based 策略）"""

    # 一对一关联策略
    strategy = models.OneToOneField(
        StrategyModel,
        on_delete=models.CASCADE,
        related_name='script_config',
        verbose_name="所属策略"
    )

    # 脚本语言
    script_language = models.CharField(
        "脚本语言",
        max_length=20,
        choices=[('python', 'Python受限')],
        default='python'
    )

    # 脚本代码
    script_code = models.TextField("脚本代码")
    script_hash = models.CharField(
        "脚本哈希",
        max_length=64,
        db_index=True,
        help_text="SHA256哈希，用于检测脚本变更"
    )

    # 沙箱配置
    sandbox_config = models.JSONField(
        default=dict,
        help_text="沙箱安全策略配置"
    )
    allowed_modules = models.JSONField(
        default=list,
        help_text="允许导入的模块白名单"
    )

    # 版本控制
    version = models.CharField("版本号", max_length=20, default="1.0")
    is_active = models.BooleanField("是否激活", default=True)

    # 元数据
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        db_table = 'script_config'
        verbose_name = "脚本配置"
        verbose_name_plural = "脚本配置"

    def __str__(self):
        return f"{self.strategy.name} 脚本配置 v{self.version}"


class AIStrategyConfigModel(models.Model):
    """AI 策略配置"""

    # 一对一关联策略
    strategy = models.OneToOneField(
        StrategyModel,
        on_delete=models.CASCADE,
        related_name='ai_config',
        verbose_name="所属策略"
    )

    # Prompt 和 Chain 配置（引用现有系统）
    prompt_template = models.ForeignKey(
        'prompt.PromptTemplateORM',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ai_strategies',
        verbose_name="Prompt模板"
    )

    chain_config = models.ForeignKey(
        'prompt.ChainConfigORM',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ai_strategies',
        verbose_name="链配置"
    )

    # AI 服务商配置
    ai_provider = models.ForeignKey(
        'ai_provider.AIProviderConfig',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ai_strategies',
        verbose_name="AI服务商"
    )

    # AI 参数
    temperature = models.FloatField(
        "温度参数",
        default=0.7,
        validators=[MinValueValidator(0.0), MaxValueValidator(2.0)]
    )
    max_tokens = models.IntegerField(
        "最大Token数",
        default=2000,
        validators=[MinValueValidator(1)]
    )

    # 审核模式（关键设计）
    approval_mode = models.CharField(
        "审核模式",
        max_length=20,
        choices=[
            ('always', '必须人工审核'),
            ('conditional', '条件审核（基于置信度）'),
            ('auto', '自动执行+监控')
        ],
        default='conditional'
    )

    confidence_threshold = models.FloatField(
        "自动执行置信度阈值",
        default=0.8,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
        help_text="置信度高于此值时自动执行"
    )

    # 元数据
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        db_table = 'ai_strategy_config'
        verbose_name = "AI策略配置"
        verbose_name_plural = "AI策略配置"

    def __str__(self):
        provider_name = self.ai_provider.name if self.ai_provider else "未配置"
        return f"{self.strategy.name} AI配置 ({provider_name})"


class PortfolioStrategyAssignmentModel(models.Model):
    """投资组合与策略的关联"""

    # 关联投资组合（引用现有系统）
    portfolio = models.ForeignKey(
        'simulated_trading.SimulatedAccountModel',
        on_delete=models.CASCADE,
        related_name='strategy_assignments',
        verbose_name="投资组合"
    )

    # 关联策略
    strategy = models.ForeignKey(
        StrategyModel,
        on_delete=models.CASCADE,
        related_name='portfolio_assignments',
        verbose_name="策略"
    )

    # 分配信息
    assigned_at = models.DateTimeField("分配时间", auto_now_add=True)
    assigned_by = models.ForeignKey(
        'account.AccountProfileModel',
        on_delete=models.CASCADE,
        verbose_name="分配者"
    )
    is_active = models.BooleanField("是否激活", default=True, db_index=True)

    # 覆盖策略的默认风控参数（可选）
    override_max_position_pct = models.FloatField(
        "覆盖单资产最大持仓比例(%)",
        null=True,
        blank=True,
        validators=[MinValueValidator(0.0), MaxValueValidator(100.0)]
    )
    override_stop_loss_pct = models.FloatField(
        "覆盖止损比例(%)",
        null=True,
        blank=True,
        validators=[MinValueValidator(0.0), MaxValueValidator(100.0)]
    )

    # 元数据
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        db_table = 'portfolio_strategy_assignment'
        verbose_name = "投资组合策略关联"
        verbose_name_plural = "投资组合策略关联"
        unique_together = [['portfolio', 'strategy']]
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['portfolio', 'is_active']),
            models.Index(fields=['strategy', 'is_active']),
        ]

    def __str__(self):
        status = "激活" if self.is_active else "未激活"
        return f"{self.portfolio.account_name} → {self.strategy.name} ({status})"


class StrategyExecutionLogModel(models.Model):
    """策略执行日志"""

    # 关联
    strategy = models.ForeignKey(
        StrategyModel,
        on_delete=models.CASCADE,
        related_name='execution_logs',
        verbose_name="策略"
    )
    portfolio = models.ForeignKey(
        'simulated_trading.SimulatedAccountModel',
        on_delete=models.CASCADE,
        related_name='strategy_execution_logs',
        verbose_name="投资组合"
    )

    # 执行信息
    execution_time = models.DateTimeField("执行时间", auto_now_add=True, db_index=True)
    execution_duration_ms = models.IntegerField("执行时长(ms)")

    # 执行结果
    execution_result = models.JSONField(help_text="详细执行信息")
    signals_generated = models.JSONField(
        default=list,
        help_text="信号列表"
    )

    # 错误处理
    error_message = models.TextField("错误信息", blank=True)
    error_traceback = models.TextField("错误堆栈", blank=True)

    # 性能指标
    is_success = models.BooleanField("是否成功", default=True, db_index=True)

    class Meta:
        db_table = 'strategy_execution_log'
        verbose_name = "策略执行日志"
        verbose_name_plural = "策略执行日志"
        ordering = ['-execution_time']
        indexes = [
            models.Index(fields=['strategy', '-execution_time']),
            models.Index(fields=['portfolio', '-execution_time']),
            models.Index(fields=['is_success', '-execution_time']),
        ]

    def __str__(self):
        status = "成功" if self.is_success else "失败"
        return f"{self.strategy.name} @ {self.portfolio.account_name} - {status}"


class StrategyParamVersionModel(models.Model):
    """策略参数版本配置（支持参数回滚）"""

    # 关联策略
    strategy = models.ForeignKey(
        StrategyModel,
        on_delete=models.CASCADE,
        related_name='param_versions',
        verbose_name="所属策略"
    )

    # 版本号（每个策略从1开始递增）
    version = models.PositiveIntegerField("版本号", db_index=True)

    # 参数配置（JSON格式存储）
    params_json = models.JSONField(
        verbose_name="参数配置",
        help_text="策略参数的JSON序列化"
    )

    # 版本状态
    is_active = models.BooleanField(
        "是否激活",
        default=False,
        db_index=True,
        help_text="同一策略只能有一个激活版本"
    )

    # 变更说明
    change_description = models.TextField(
        "变更说明",
        blank=True,
        help_text="记录本次参数变更的原因和内容"
    )

    # 变更者
    changed_by = models.ForeignKey(
        'account.AccountProfileModel',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="变更者"
    )

    # 元数据
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        db_table = 'strategy_param_version'
        verbose_name = "策略参数版本"
        verbose_name_plural = "策略参数版本"
        unique_together = [['strategy', 'version']]
        ordering = ['-version']
        indexes = [
            models.Index(fields=['strategy', '-version']),
            models.Index(fields=['strategy', 'is_active']),
            models.Index(fields=['-created_at']),
        ]

    def __str__(self):
        status = "激活" if self.is_active else "未激活"
        return f"{self.strategy.name} 参数版本 v{self.version} ({status})"


class OrderIntentModel(models.Model):
    """订单意图持久化模型（M0/M2 幂等与审计链路）"""

    intent_id = models.CharField("意图ID", max_length=64, unique=True, db_index=True)
    idempotency_key = models.CharField("幂等键", max_length=128, unique=True, db_index=True)

    strategy = models.ForeignKey(
        StrategyModel,
        on_delete=models.CASCADE,
        related_name='order_intents',
        verbose_name="策略"
    )
    portfolio = models.ForeignKey(
        'simulated_trading.SimulatedAccountModel',
        on_delete=models.CASCADE,
        related_name='strategy_order_intents',
        verbose_name="投资组合"
    )

    symbol = models.CharField("资产代码", max_length=32, db_index=True)
    side = models.CharField(
        "方向",
        max_length=8,
        choices=[('buy', '买入'), ('sell', '卖出')],
    )
    qty = models.PositiveIntegerField("数量")
    limit_price = models.FloatField("限价", null=True, blank=True)
    time_in_force = models.CharField(
        "订单时效",
        max_length=8,
        default='day',
        choices=[('day', 'DAY'), ('gtc', 'GTC'), ('ioc', 'IOC'), ('fok', 'FOK')],
    )
    reason = models.TextField("原因", blank=True)
    status = models.CharField(
        "状态",
        max_length=32,
        default='draft',
        db_index=True,
        choices=[
            ('draft', '草稿'),
            ('pending_approval', '待审批'),
            ('approved', '已批准'),
            ('rejected', '已拒绝'),
            ('sent', '已发送'),
            ('partial_filled', '部分成交'),
            ('filled', '已成交'),
            ('canceled', '已取消'),
            ('failed', '失败'),
        ],
    )

    decision_json = models.JSONField("决策快照", default=dict)
    sizing_json = models.JSONField("仓位快照", default=dict)
    risk_snapshot_json = models.JSONField("风控快照", default=dict)

    created_at = models.DateTimeField("创建时间", default=timezone.now, db_index=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        db_table = 'order_intent'
        verbose_name = "订单意图"
        verbose_name_plural = "订单意图"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['portfolio', 'status']),
            models.Index(fields=['strategy', '-created_at']),
            models.Index(fields=['symbol', '-created_at']),
        ]

    def __str__(self):
        return f"{self.intent_id} {self.symbol} {self.side} {self.qty} ({self.status})"
