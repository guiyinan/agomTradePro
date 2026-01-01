"""
ORM Models for Policy Events.
"""

from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User


class PolicyLog(models.Model):
    """政策事件日志"""

    POLICY_LEVELS = [
        ('P0', 'P0 - 常态'),
        ('P1', 'P1 - 预警'),
        ('P2', 'P2 - 干预'),
        ('P3', 'P3 - 危机'),
    ]

    # ========== 原有字段 ==========
    event_date = models.DateField(db_index=True)
    level = models.CharField(max_length=2, choices=POLICY_LEVELS)
    title = models.CharField(max_length=200)
    description = models.TextField()
    evidence_url = models.URLField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)

    # ========== 信息分类 ==========
    INFO_CATEGORY_CHOICES = [
        ('macro', '宏观政策'),
        ('sector', '板块政策'),
        ('individual', '个股舆情'),
        ('sentiment', '市场情绪'),
        ('other', '其他'),
    ]
    info_category = models.CharField(
        max_length=20,
        choices=INFO_CATEGORY_CHOICES,
        default='macro',
        db_index=True,
        verbose_name="信息分类"
    )

    # ========== 审核工作流 ==========
    AUDIT_STATUS_CHOICES = [
        ('pending_review', '待审核'),
        ('auto_approved', 'AI自动通过'),
        ('manual_approved', '人工通过'),
        ('rejected', '已拒绝'),
    ]
    audit_status = models.CharField(
        max_length=20,
        choices=AUDIT_STATUS_CHOICES,
        default='pending_review',
        db_index=True,
        verbose_name="审核状态"
    )
    ai_confidence = models.FloatField(
        null=True,
        blank=True,
        verbose_name="AI置信度",
        help_text="0.0-1.0，高于阈值自动通过"
    )
    reviewed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_policies',
        verbose_name="审核人"
    )
    reviewed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="审核时间"
    )
    review_notes = models.TextField(
        blank=True,
        verbose_name="审核备注"
    )

    # ========== AI提取的结构化数据 ==========
    structured_data = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="结构化数据",
        help_text="""
        {
            "policy_subject": "政策主体",
            "policy_object": "政策客体",
            "effective_date": "YYYY-MM-DD",
            "expiry_date": "YYYY-MM-DD",
            "conditions": ["条件1", "条件2"],
            "impact_scope": "national|regional|sector|specific",
            "affected_sectors": ["板块1", "板块2"],
            "affected_stocks": ["股票代码1", "股票代码2"],
            "sentiment": "positive|negative|neutral",
            "sentiment_score": -1.0到1.0,
            "keywords": ["关键词1", "关键词2"],
            "summary": "政策摘要"
        }
        """
    )

    # ========== RSS来源追踪 ==========
    rss_source = models.ForeignKey(
        'RSSSourceConfigModel',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='policy_logs',
        verbose_name="RSS来源"
    )
    rss_item_guid = models.CharField(
        max_length=500,
        blank=True,
        db_index=True,
        verbose_name="RSS条目GUID"
    )

    # ========== 风险控制 ==========
    RISK_IMPACT_CHOICES = [
        ('high_risk', '高风险'),
        ('medium_risk', '中风险'),
        ('low_risk', '低风险'),
        ('unknown', '未知'),
    ]
    risk_impact = models.CharField(
        max_length=20,
        choices=RISK_IMPACT_CHOICES,
        default='unknown',
        verbose_name="风险影响"
    )
    is_blacklist = models.BooleanField(
        default=False,
        verbose_name="黑名单标记",
        help_text="标记为黑名单的政策"
    )
    is_whitelist = models.BooleanField(
        default=False,
        verbose_name="白名单标记",
        help_text="标记为白名单的政策"
    )

    # ========== 处理元数据 ==========
    processing_metadata = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="处理元数据",
        help_text="""
        {
            "ai_model_used": "gpt-4",
            "ai_processing_time_ms": 1234,
            "ai_tokens_used": 1500,
            "extraction_method": "ai|keyword"
        }
        """
    )

    class Meta:
        db_table = 'policy_log'
        ordering = ['-event_date']
        indexes = [
            models.Index(fields=['-event_date']),
            models.Index(fields=['level', '-event_date']),
            models.Index(fields=['info_category']),
            models.Index(fields=['audit_status']),
            models.Index(fields=['rss_item_guid']),
        ]

    def __str__(self):
        return f"{self.event_date}: {self.level} - {self.title}"


class RSSSourceConfigModel(models.Model):
    """RSS源配置ORM"""

    CATEGORY_CHOICES = [
        ('gov_docs', '政府文件库'),
        ('central_bank', '央行公告'),
        ('mof', '财政部'),
        ('csrc', '证监会'),
        ('media', '财经媒体'),
        ('other', '其他'),
    ]

    PROXY_TYPE_CHOICES = [
        ('http', 'HTTP'),
        ('https', 'HTTPS'),
        ('socks5', 'SOCKS5'),
    ]

    PARSER_TYPE_CHOICES = [
        ('feedparser', 'feedparser'),
        ('httpx', 'httpx+manual'),
    ]

    # 基本配置
    name = models.CharField(max_length=100, unique=True, verbose_name="源名称")
    url = models.URLField(max_length=500, verbose_name="RSS URL")
    category = models.CharField(
        max_length=20,
        choices=CATEGORY_CHOICES,
        default='other',
        verbose_name="分类"
    )
    is_active = models.BooleanField(default=True, verbose_name="是否启用")
    fetch_interval_hours = models.IntegerField(default=6, verbose_name="抓取间隔(小时)")

    # 内容提取配置
    extract_content = models.BooleanField(
        default=False,
        verbose_name="提取完整内容",
        help_text="是否从RSS链接中提取文章正文内容"
    )

    # 代理配置
    proxy_enabled = models.BooleanField(default=False, verbose_name="启用代理")
    proxy_host = models.CharField(max_length=200, blank=True, verbose_name="代理主机")
    proxy_port = models.IntegerField(null=True, blank=True, verbose_name="代理端口")
    proxy_username = models.CharField(max_length=100, blank=True, verbose_name="代理用户名")
    proxy_password = models.CharField(max_length=200, blank=True, verbose_name="代理密码")
    proxy_type = models.CharField(
        max_length=10,
        choices=PROXY_TYPE_CHOICES,
        default='http',
        verbose_name="代理类型"
    )

    # RSS解析器配置
    parser_type = models.CharField(
        max_length=20,
        choices=PARSER_TYPE_CHOICES,
        default='feedparser',
        verbose_name="解析器类型"
    )
    timeout_seconds = models.IntegerField(default=30, verbose_name="超时时间(秒)")
    retry_times = models.IntegerField(default=3, verbose_name="重试次数")

    # 状态监控
    last_fetch_at = models.DateTimeField(null=True, blank=True, verbose_name="最后抓取时间")
    last_fetch_status = models.CharField(max_length=20, blank=True, verbose_name="最后抓取状态")
    last_error_message = models.TextField(blank=True, verbose_name="最后错误信息")

    # 时间戳
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = 'rss_source_config'
        verbose_name = "RSS源配置"
        verbose_name_plural = "RSS源配置"
        ordering = ['category', 'name']
        indexes = [
            models.Index(fields=['is_active', 'category']),
        ]

    def __str__(self):
        return f"{self.name} ({self.get_category_display()})"


class PolicyLevelKeywordModel(models.Model):
    """政策档位关键词规则ORM"""

    POLICY_LEVELS = [
        ('P0', 'P0 - 常态'),
        ('P1', 'P1 - 预警'),
        ('P2', 'P2 - 干预'),
        ('P3', 'P3 - 危机'),
    ]

    level = models.CharField(max_length=2, choices=POLICY_LEVELS, verbose_name="政策档位")
    keywords = models.JSONField(verbose_name="关键词列表", help_text="JSON数组格式的关键词列表")
    weight = models.IntegerField(default=1, verbose_name="权重")
    category = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        verbose_name="适用分类",
        help_text="留空表示适用于所有RSS源分类"
    )
    is_active = models.BooleanField(default=True, verbose_name="是否启用")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = 'policy_level_keywords'
        verbose_name = "政策档位关键词规则"
        verbose_name_plural = "政策档位关键词规则"
        ordering = ['-weight', 'level']
        indexes = [
            models.Index(fields=['is_active', 'level']),
            models.Index(fields=['category']),
        ]

    def __str__(self):
        keywords_str = ', '.join(self.keywords[:3])  # 显示前3个关键词
        if len(self.keywords) > 3:
            keywords_str += f" ... (+{len(self.keywords) - 3})"
        return f"{self.level} - {keywords_str}"


class RSSFetchLog(models.Model):
    """RSS抓取日志"""

    STATUS_CHOICES = [
        ('success', '成功'),
        ('error', '失败'),
        ('partial', '部分成功'),
    ]

    source = models.ForeignKey(
        RSSSourceConfigModel,
        on_delete=models.CASCADE,
        related_name='fetch_logs',
        verbose_name="RSS源"
    )
    fetched_at = models.DateTimeField(auto_now_add=True, verbose_name="抓取时间", db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, verbose_name="状态")
    items_count = models.IntegerField(default=0, verbose_name="条目总数")
    new_items_count = models.IntegerField(default=0, verbose_name="新增条目数")
    error_message = models.TextField(blank=True, verbose_name="错误信息")
    fetch_duration_seconds = models.FloatField(null=True, blank=True, verbose_name="耗时(秒)")

    class Meta:
        db_table = 'rss_fetch_log'
        verbose_name = "RSS抓取日志"
        verbose_name_plural = "RSS抓取日志"
        ordering = ['-fetched_at']
        indexes = [
            models.Index(fields=['-fetched_at']),
            models.Index(fields=['source', 'status']),
        ]

    def __str__(self):
        return f"{self.source.name} - {self.fetched_at.strftime('%Y-%m-%d %H:%M')} - {self.get_status_display()}"


class PolicyAuditQueue(models.Model):
    """政策审核队列"""

    PRIORITY_CHOICES = [
        ('urgent', '紧急'),
        ('high', '高'),
        ('normal', '普通'),
        ('low', '低'),
    ]

    policy_log = models.OneToOneField(
        PolicyLog,
        on_delete=models.CASCADE,
        related_name='audit_queue',
        verbose_name="关联政策日志"
    )
    priority = models.CharField(
        max_length=20,
        choices=PRIORITY_CHOICES,
        default='normal',
        verbose_name="优先级"
    )
    assigned_to = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_audits',
        verbose_name="分配给"
    )
    assigned_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="分配时间"
    )
    due_date = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="期望完成时间"
    )
    auto_rejection_reason = models.TextField(
        blank=True,
        verbose_name="自动拒绝原因"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        db_table = 'policy_audit_queue'
        verbose_name = "政策审核队列"
        verbose_name_plural = "政策审核队列"
        ordering = ['priority', '-created_at']
        indexes = [
            models.Index(fields=['priority', '-created_at']),
            models.Index(fields=['assigned_to']),
        ]

    def __str__(self):
        assigned = f" -> {self.assigned_to.username}" if self.assigned_to else ""
        return f"{self.policy_log.title} [{self.priority}]{assigned}"


# ========== Django Signals ==========

from django.db.models.signals import post_save
from django.dispatch import receiver
import logging

logger = logging.getLogger(__name__)


@receiver(post_save, sender=PolicyLog)
def on_policy_level_change(sender, instance, created, **kwargs):
    """
    政策档位变化时触发信号重评

    当 PolicyLog 被保存且档位发生变化时，触发异步任务重新评估所有活跃信号。
    """
    # 只在非新建且审核通过的情况下触发
    if created:
        return

    # 检查审核状态
    if instance.audit_status not in ['auto_approved', 'manual_approved']:
        return

    # 获取上一个档位
    try:
        old_level = PolicyLog.objects.filter(
            event_date__lt=instance.event_date
        ).order_by('-event_date').first()

        if old_level and old_level.level != instance.level:
            # 档位变化，触发信号重评
            from .tasks import trigger_signal_reevaluation

            # 解析档位 (P1 -> 1)
            new_level = int(instance.level[1])

            logger.info(
                f"Policy level changed from {old_level.level} to {instance.level}, "
                f"triggering signal reevaluation"
            )

            # 异步触发信号重评
            trigger_signal_reevaluation.delay(
                new_level=new_level,
                event_date=instance.event_date.isoformat()
            )

    except Exception as e:
        logger.error(f"Failed to trigger signal reevaluation: {e}")


# ============================================================
# 对冲持仓模型
# ============================================================

class HedgePositionModel(models.Model):
    """
    对冲持仓记录表

    记录投资组合的对冲操作和持仓状态。
    """

    STATUS_CHOICES = [
        ('pending', '待执行'),
        ('executed', '已执行'),
        ('closed', '已平仓'),
        ('expired', '已过期'),
        ('failed', '执行失败'),
    ]

    portfolio = models.ForeignKey(
        'account.PortfolioModel',
        on_delete=models.CASCADE,
        related_name='hedge_positions',
        verbose_name="投资组合"
    )

    instrument_code = models.CharField(max_length=50, verbose_name="对冲工具代码")
    instrument_type = models.CharField(max_length=20, verbose_name="工具类型")

    # 对冲参数
    hedge_ratio = models.FloatField(verbose_name="对冲比例")
    hedge_value = models.DecimalField(max_digits=20, decimal_places=2, verbose_name="对冲金额")
    policy_level = models.CharField(max_length=10, verbose_name="触发政策档位")

    # 执行信息
    execution_price = models.DecimalField(
        max_digits=20,
        decimal_places=4,
        null=True,
        blank=True,
        verbose_name="执行价格"
    )
    executed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="执行时间"
    )

    # 状态
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        verbose_name="状态"
    )

    # 成本与效果
    opening_cost = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="开仓成本"
    )
    closing_cost = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="平仓成本"
    )
    total_cost = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="总成本"
    )

    # 效果评估
    beta_before = models.FloatField(
        null=True,
        blank=True,
        verbose_name="对冲前Beta"
    )
    beta_after = models.FloatField(
        null=True,
        blank=True,
        verbose_name="对冲后Beta"
    )
    hedge_profit = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="对冲盈亏"
    )

    notes = models.TextField(blank=True, verbose_name="备注")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = 'hedge_position'
        verbose_name = '对冲持仓记录'
        verbose_name_plural = '对冲持仓记录'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['portfolio', '-created_at']),
            models.Index(fields=['status']),
            models.Index(fields=['policy_level']),
        ]

    def __str__(self):
        return f"{self.portfolio.name} - {self.instrument_code} ({self.get_status_display()})"
