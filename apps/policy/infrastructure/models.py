"""
ORM Models for Policy Events.
"""

from django.contrib.auth.models import User
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class PolicyLog(models.Model):
    """政策事件日志"""

    POLICY_LEVELS = [
        ('PX', 'PX - 待分类'),
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

    # ========== 工作台扩展字段 ==========
    EVENT_TYPE_CHOICES = [
        ('policy', '政策事件'),
        ('hotspot', '热点事件'),
        ('sentiment', '情绪事件'),
        ('mixed', '混合事件'),
    ]
    event_type = models.CharField(
        max_length=20,
        choices=EVENT_TYPE_CHOICES,
        default='policy',
        db_index=True,
        verbose_name="事件类型",
        help_text="区分政策事件与热点情绪事件"
    )

    ASSET_CLASS_CHOICES = [
        ('equity', '股票'),
        ('bond', '债券'),
        ('commodity', '商品'),
        ('fx', '外汇'),
        ('crypto', '加密货币'),
        ('all', '全资产'),
    ]
    asset_class = models.CharField(
        max_length=20,
        choices=ASSET_CLASS_CHOICES,
        blank=True,
        null=True,
        db_index=True,
        verbose_name="资产分类",
        help_text="按资产类约束"
    )
    asset_scope = models.JSONField(
        default=list,
        blank=True,
        verbose_name="受影响资产范围",
        help_text="JSON数组，如 ['ASSET_CODE_1', 'ASSET_CODE_2']"
    )

    # ========== 热点情绪评分 ==========
    heat_score = models.FloatField(
        null=True,
        blank=True,
        verbose_name="热度评分",
        help_text="0-100，数值越高热度越高",
        validators=[
            MinValueValidator(0),
            MaxValueValidator(100)
        ]
    )
    sentiment_score = models.FloatField(
        null=True,
        blank=True,
        verbose_name="情绪评分",
        help_text="-1.0 ~ +1.0，负值悲观，正值乐观",
        validators=[
            MinValueValidator(-1.0),
            MaxValueValidator(1.0)
        ]
    )

    # ========== 闸门等级与生效状态 ==========
    GATE_LEVEL_CHOICES = [
        ('L0', 'L0 - 正常'),
        ('L1', 'L1 - 关注'),
        ('L2', 'L2 - 警戒'),
        ('L3', 'L3 - 严控'),
    ]
    gate_level = models.CharField(
        max_length=2,
        choices=GATE_LEVEL_CHOICES,
        blank=True,
        null=True,
        db_index=True,
        verbose_name="闸门等级",
        help_text="热点情绪闸门等级 L0-L3"
    )
    gate_effective = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name="闸门已生效",
        help_text="是否已审核通过并生效"
    )
    effective_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="生效时间"
    )
    effective_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='effected_policies',
        verbose_name="生效操作人"
    )
    rollback_reason = models.TextField(
        blank=True,
        verbose_name="回滚原因",
        help_text="回滚生效时填写的原因"
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
            # 工作台新增索引
            models.Index(fields=['event_type', '-event_date']),
            models.Index(fields=['gate_effective', 'event_type']),
            models.Index(fields=['asset_class', 'gate_level']),
        ]

    def __str__(self):
        return f"{self.event_date}: {self.level} - {self.title}"


class RSSHubGlobalConfig(models.Model):
    """
    RSSHub 全局配置模型（单例模式）

    存储默认的 RSSHub 基址和访问密钥。
    通过 Django Admin 或 API 进行配置。
    """
    # 单例约束：数据库中只应有一条记录
    singleton_id = models.AutoField(primary_key=True, verbose_name="单例ID")

    # RSSHub 基础配置
    base_url = models.URLField(
        max_length=500,
        default='http://127.0.0.1:1200',
        verbose_name="RSSHub 基址",
        help_text="本地 RSSHub 服务的基址，如 http://127.0.0.1:1200"
    )
    access_key = models.CharField(
        max_length=200,
        blank=True,
        verbose_name="访问密钥",
        help_text="RSSHub 的 ACCESS_KEY，留空表示不使用鉴权"
    )
    enabled = models.BooleanField(
        default=False,
        verbose_name="启用 RSSHub",
        help_text="是否启用 RSSHub 全局配置"
    )

    # 默认参数配置
    default_format = models.CharField(
        max_length=20,
        choices=[('rss', 'RSS 2.0'), ('atom', 'Atom'), ('json', 'JSON Feed')],
        default='rss',
        verbose_name="默认输出格式",
        help_text="RSSHub 默认输出格式"
    )

    # 时间戳
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = 'rsshub_global_config'
        verbose_name = "RSSHub 全局配置"
        verbose_name_plural = "RSSHub 全局配置"

    def __str__(self):
        status = "启用" if self.enabled else "禁用"
        has_key = "有密钥" if self.access_key else "无密钥"
        return f"RSSHub 全局配置 [{status}] - {self.base_url} ({has_key})"

    @classmethod
    def get_config(cls):
        """
        获取全局 RSSHub 配置（单例模式）

        Returns:
            RSSHubGlobalConfig: 全局配置对象，如果不存在则创建默认配置
        """
        config, created = cls.objects.get_or_create(
            singleton_id=1,
            defaults={
                'base_url': 'http://127.0.0.1:1200',
                'access_key': '',
                'enabled': False,
            }
        )
        return config

    def get_full_url(self, route_path: str, format: str = None) -> str:
        """
        构建完整的 RSSHub URL

        Args:
            route_path: 路由路径，如 /csrc/news/bwj
            format: 输出格式，默认使用 default_format

        Returns:
            str: 完整的 RSSHub URL

        Examples:
            >>> config = RSSHubGlobalConfig.get_config()
            >>> config.get_full_url('/csrc/news/bwj')
            'http://127.0.0.1:1200/csrc/news/bwj?key=xxxx&format=rss'
        """
        from urllib.parse import urlencode

        # 构建查询参数
        params = {}
        if self.access_key:
            params['key'] = self.access_key
        if format:
            params['format'] = format
        elif self.default_format != 'rss':
            params['format'] = self.default_format

        # 构建完整 URL
        url = f"{self.base_url.rstrip('/')}{route_path}"
        if params:
            url += f"?{urlencode(params)}"

        return url


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

    # ========== RSSHub 配置 ==========
    rsshub_enabled = models.BooleanField(
        default=False,
        verbose_name="使用 RSSHub",
        help_text="是否使用 RSSHub 模式（启用后将忽略 URL 字段，使用路由路径）"
    )
    rsshub_route_path = models.CharField(
        max_length=500,
        blank=True,
        verbose_name="RSSHub 路由路径",
        help_text="如 /csrc/news/bwj，完整 URL 将自动构建为: 基址 + 路由 + key"
    )
    rsshub_use_global_config = models.BooleanField(
        default=True,
        verbose_name="使用全局 RSSHub 配置",
        help_text="是否使用全局 RSSHub 配置（基址和密钥）。取消勾选后可自定义配置。"
    )
    rsshub_custom_base_url = models.URLField(
        max_length=500,
        blank=True,
        verbose_name="自定义 RSSHub 基址",
        help_text="仅在「不使用全局配置」时生效"
    )
    rsshub_custom_access_key = models.CharField(
        max_length=200,
        blank=True,
        verbose_name="自定义访问密钥",
        help_text="仅在「不使用全局配置」时生效"
    )
    rsshub_format = models.CharField(
        max_length=20,
        choices=[('', '默认'), ('rss', 'RSS 2.0'), ('atom', 'Atom'), ('json', 'JSON Feed')],
        default='',
        blank=True,
        verbose_name="输出格式",
        help_text="留空则使用全局配置的默认格式"
    )

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

    def get_effective_url(self) -> str:
        """
        获取有效的 RSS URL

        如果启用 RSSHub 模式，则自动构建完整的 RSSHub URL。
        否则返回原有的 url 字段。

        Returns:
            str: 完整的 RSS URL

        Examples:
            >>> source = RSSSourceConfigModel._default_manager.get(name='证监会新闻')
            >>> source.get_effective_url()
            'http://127.0.0.1:1200/csrc/news/bwj?key=xxxx&format=rss'
        """
        if not self.rsshub_enabled:
            # 普通模式，直接返回 URL
            return self.url

        # RSSHub 模式，构建完整 URL
        from urllib.parse import urlencode

        # 确定基址和密钥
        if self.rsshub_use_global_config:
            # 使用全局配置
            global_config = RSSHubGlobalConfig.get_config()
            base_url = global_config.base_url
            access_key = global_config.access_key
            format = self.rsshub_format or global_config.default_format
        else:
            # 使用自定义配置
            base_url = self.rsshub_custom_base_url
            access_key = self.rsshub_custom_access_key
            format = self.rsshub_format or 'rss'

        # 构建查询参数
        params = {}
        if access_key:
            params['key'] = access_key
        if format and format != '':
            params['format'] = format

        # 构建完整 URL
        route = self.rsshub_route_path or ''
        url = f"{base_url.rstrip('/')}{route}"
        if params:
            url += f"?{urlencode(params)}"

        return url


class PolicyLevelKeywordModel(models.Model):
    """政策档位关键词规则ORM"""

    POLICY_LEVELS = [
        ('PX', 'PX - 待分类'),
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

import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

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
        old_level = PolicyLog._default_manager.filter(
            event_date__lt=instance.event_date
        ).order_by('-event_date').first()

        if old_level and old_level.level != instance.level:
            # 档位变化，触发信号重评
            from apps.policy.application.tasks import trigger_signal_reevaluation

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


# ============================================================
# 工作台配置模型
# ============================================================

class PolicyIngestionConfig(models.Model):
    """
    政策摄入配置（单例模式）

    控制自动审核、SLA 等工作台行为。
    """

    # 单例约束
    singleton_id = models.AutoField(primary_key=True, verbose_name="单例ID")

    # 自动生效配置
    auto_approve_enabled = models.BooleanField(
        default=False,
        verbose_name="启用自动生效",
        help_text="是否启用高置信度事件自动生效"
    )
    auto_approve_min_level = models.CharField(
        max_length=2,
        choices=[
            ('P0', 'P0 - 常态'),
            ('P1', 'P1 - 预警'),
            ('P2', 'P2 - 干预'),
            ('P3', 'P3 - 危机'),
        ],
        default='P2',
        verbose_name="自动生效最低档位",
        help_text="P2 表示 P2/P3 可自动生效，P0 表示所有档位"
    )
    auto_approve_threshold = models.FloatField(
        default=0.85,
        verbose_name="自动生效置信度阈值",
        help_text="AI 置信度达到此阈值才可自动生效（0.0-1.0）"
    )

    # SLA 配置
    p23_sla_hours = models.IntegerField(
        default=2,
        verbose_name="P2/P3 SLA（小时）",
        help_text="P2/P3 事件审核超时时间"
    )
    normal_sla_hours = models.IntegerField(
        default=24,
        verbose_name="普通 SLA（小时）",
        help_text="P0/P1 事件审核超时时间"
    )

    # 版本控制
    version = models.IntegerField(default=1, verbose_name="配置版本")
    updated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="更新人"
    )
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        db_table = 'policy_ingestion_config'
        verbose_name = "政策摄入配置"
        verbose_name_plural = "政策摄入配置"

    def __str__(self):
        status = "启用" if self.auto_approve_enabled else "禁用"
        return f"政策摄入配置 [{status}] v{self.version}"

    @classmethod
    def get_config(cls):
        """
        获取配置（单例模式）
        """
        config, created = cls.objects.get_or_create(
            singleton_id=1,
            defaults={
                'auto_approve_enabled': False,
                'auto_approve_threshold': 0.85,
                'p23_sla_hours': 2,
                'normal_sla_hours': 24,
            }
        )
        return config


class SentimentGateConfig(models.Model):
    """
    热点情绪闸门配置（按资产类）

    定义各资产类的热点情绪阈值和约束。
    """

    ASSET_CLASS_CHOICES = [
        ('equity', '股票'),
        ('bond', '债券'),
        ('commodity', '商品'),
        ('fx', '外汇'),
        ('crypto', '加密货币'),
        ('all', '全资产'),
    ]

    asset_class = models.CharField(
        max_length=20,
        choices=ASSET_CLASS_CHOICES,
        unique=True,
        verbose_name="资产分类"
    )

    # 热度阈值
    heat_l1_threshold = models.FloatField(
        default=30.0,
        verbose_name="热度 L1 阈值",
        help_text="热度达到此值触发 L1 关注"
    )
    heat_l2_threshold = models.FloatField(
        default=60.0,
        verbose_name="热度 L2 阈值",
        help_text="热度达到此值触发 L2 警戒"
    )
    heat_l3_threshold = models.FloatField(
        default=85.0,
        verbose_name="热度 L3 阈值",
        help_text="热度达到此值触发 L3 严控"
    )

    # 情绪阈值（负值，绝对值越大越悲观）
    sentiment_l1_threshold = models.FloatField(
        default=-0.3,
        verbose_name="情绪 L1 阈值",
        help_text="情绪低于此值触发 L1 关注（如 -0.3）"
    )
    sentiment_l2_threshold = models.FloatField(
        default=-0.6,
        verbose_name="情绪 L2 阈值",
        help_text="情绪低于此值触发 L2 警戒"
    )
    sentiment_l3_threshold = models.FloatField(
        default=-0.8,
        verbose_name="情绪 L3 阈值",
        help_text="情绪低于此值触发 L3 严控"
    )

    # 仓位约束
    max_position_cap_l2 = models.FloatField(
        default=0.7,
        verbose_name="L2 最大仓位上限",
        help_text="L2 警戒时最大仓位比例（0.7 表示 70%）"
    )
    max_position_cap_l3 = models.FloatField(
        default=0.3,
        verbose_name="L3 最大仓位上限",
        help_text="L3 严控时最大仓位比例（0.3 表示 30%）"
    )

    # 状态与版本
    enabled = models.BooleanField(default=True, verbose_name="启用")
    version = models.IntegerField(default=1, verbose_name="配置版本")
    updated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="更新人"
    )
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        db_table = 'sentiment_gate_config'
        verbose_name = "热点情绪闸门配置"
        verbose_name_plural = "热点情绪闸门配置"
        ordering = ['asset_class']

    def __str__(self):
        status = "启用" if self.enabled else "禁用"
        return f"{self.get_asset_class_display()} 闸门配置 [{status}] v{self.version}"


class GateActionAuditLog(models.Model):
    """
    闸门操作审计日志

    记录所有审核、拒绝、回滚、豁免操作的完整历史。
    """

    ACTION_CHOICES = [
        ('approve', '审核通过'),
        ('reject', '审核拒绝'),
        ('rollback', '回滚生效'),
        ('override', '临时豁免'),
        ('auto_approve', '自动生效'),
        ('level_change', '档位变更'),
    ]

    event = models.ForeignKey(
        PolicyLog,
        on_delete=models.CASCADE,
        related_name='audit_logs',
        verbose_name="关联事件"
    )
    action = models.CharField(
        max_length=20,
        choices=ACTION_CHOICES,
        verbose_name="操作类型"
    )
    operator = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="操作人"
    )

    # 状态快照
    before_state = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="操作前状态",
        help_text="操作前的关键字段快照"
    )
    after_state = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="操作后状态",
        help_text="操作后的关键字段快照"
    )

    # 原因与版本
    reason = models.TextField(
        blank=True,
        verbose_name="操作原因",
        help_text="拒绝/回滚/豁免时填写的原因"
    )
    rule_version = models.CharField(
        max_length=50,
        blank=True,
        verbose_name="规则版本",
        help_text="执行时的规则版本号"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        db_table = 'gate_action_audit_log'
        verbose_name = "闸门操作审计日志"
        verbose_name_plural = "闸门操作审计日志"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['event', '-created_at']),
            models.Index(fields=['action']),
            models.Index(fields=['operator']),
        ]

    def __str__(self):
        return f"{self.event.title} - {self.get_action_display()} ({self.created_at.strftime('%Y-%m-%d %H:%M')})"


# ============================================================
# 通知相关模型
# ============================================================

class InAppNotification(models.Model):
    """
    站内通知模型

    存储发送给用户的通知消息，供界面展示。
    """

    PRIORITY_CHOICES = [
        ('low', '低'),
        ('normal', '普通'),
        ('high', '高'),
        ('critical', '紧急'),
    ]

    CHANNEL_CHOICES = [
        ('email', '邮件'),
        ('in_app', '站内信'),
        ('webhook', 'Webhook'),
    ]

    # 通知内容
    title = models.CharField(max_length=200, verbose_name="标题")
    content = models.TextField(verbose_name="内容")

    # 通知属性
    channel = models.CharField(
        max_length=20,
        choices=CHANNEL_CHOICES,
        default='in_app',
        verbose_name="通知渠道"
    )
    priority = models.CharField(
        max_length=20,
        choices=PRIORITY_CHOICES,
        default='normal',
        verbose_name="优先级",
        db_index=True
    )

    # 收件人
    recipient_username = models.CharField(
        max_length=150,
        blank=True,
        null=True,
        verbose_name="收件人用户名",
        help_text="留空表示全局通知"
    )
    is_global = models.BooleanField(
        default=False,
        verbose_name="全局通知",
        help_text="是否为全局通知（所有用户可见）"
    )

    # 读取状态
    is_read = models.BooleanField(default=False, verbose_name="已读")
    read_at = models.DateTimeField(null=True, blank=True, verbose_name="读取时间")

    # 元数据
    metadata = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="元数据",
        help_text="额外的结构化信息"
    )

    # 时间戳
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间", db_index=True)

    class Meta:
        db_table = 'in_app_notification'
        verbose_name = "站内通知"
        verbose_name_plural = "站内通知"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['recipient_username', '-created_at']),
            models.Index(fields=['is_read', 'priority']),
            models.Index(fields=['is_global', '-created_at']),
        ]

    def __str__(self):
        recipient = self.recipient_username or "全局"
        status = "已读" if self.is_read else "未读"
        return f"[{recipient}] {self.title} ({status})"
