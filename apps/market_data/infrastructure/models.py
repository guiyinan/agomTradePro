"""
Market Data 模块 - Infrastructure 层 ORM 模型

资金流向表、股票新闻表、原始 payload 存储表。
"""

from django.db import models


class StockCapitalFlowModel(models.Model):
    """个股资金流向表"""

    stock_code = models.CharField(
        max_length=10, db_index=True, verbose_name="股票代码"
    )
    trade_date = models.DateField(db_index=True, verbose_name="交易日期")

    # 主力资金
    main_net_inflow = models.FloatField(verbose_name="主力净流入（元）")
    main_net_ratio = models.FloatField(verbose_name="主力净流入占比（%）")

    # 分级资金
    super_large_net_inflow = models.FloatField(
        null=True, blank=True, verbose_name="超大单净流入（元）"
    )
    large_net_inflow = models.FloatField(
        null=True, blank=True, verbose_name="大单净流入（元）"
    )
    medium_net_inflow = models.FloatField(
        null=True, blank=True, verbose_name="中单净流入（元）"
    )
    small_net_inflow = models.FloatField(
        null=True, blank=True, verbose_name="小单净流入（元）"
    )

    # 元信息
    source = models.CharField(max_length=50, default="eastmoney", verbose_name="数据源")
    schema_version = models.CharField(
        max_length=50, blank=True, default="", verbose_name="字段映射版本"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        db_table = "market_data_capital_flow"
        verbose_name = "个股资金流向"
        verbose_name_plural = "个股资金流向"
        unique_together = [["stock_code", "trade_date", "source"]]
        indexes = [
            models.Index(fields=["stock_code", "trade_date"]),
            models.Index(fields=["trade_date"]),
        ]
        ordering = ["-trade_date"]

    def __str__(self) -> str:
        return f"{self.stock_code} {self.trade_date} 主力净流入={self.main_net_inflow}"


class StockNewsModel(models.Model):
    """股票新闻表

    保留原始新闻，便于去重和重跑情绪分析。
    """

    stock_code = models.CharField(
        max_length=10, db_index=True, verbose_name="股票代码"
    )
    news_id = models.CharField(
        max_length=100, unique=True, verbose_name="新闻唯一ID"
    )
    title = models.CharField(max_length=500, verbose_name="标题")
    content = models.TextField(blank=True, default="", verbose_name="正文")
    published_at = models.DateTimeField(db_index=True, verbose_name="发布时间")
    url = models.URLField(blank=True, default="", verbose_name="原文链接")
    source = models.CharField(max_length=50, default="eastmoney", verbose_name="数据源")
    payload = models.JSONField(default=dict, blank=True, verbose_name="原始字段")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        db_table = "market_data_stock_news"
        verbose_name = "股票新闻"
        verbose_name_plural = "股票新闻"
        indexes = [
            models.Index(fields=["stock_code", "-published_at"]),
            models.Index(fields=["-published_at"]),
        ]
        ordering = ["-published_at"]

    def __str__(self) -> str:
        return f"{self.stock_code} {self.title[:30]}"


class RawPayloadModel(models.Model):
    """原始 payload 存储表

    保留外部采集源的原始响应，便于站点变更后排查。
    """

    request_type = models.CharField(
        max_length=50, db_index=True, verbose_name="请求类型"
    )
    stock_code = models.CharField(
        max_length=10, db_index=True, verbose_name="股票代码"
    )
    provider_name = models.CharField(
        max_length=50, db_index=True, verbose_name="Provider 名称"
    )
    payload = models.JSONField(default=dict, verbose_name="原始响应")
    parse_status = models.CharField(
        max_length=20,
        default="success",
        choices=[
            ("success", "成功"),
            ("partial", "部分成功"),
            ("failed", "失败"),
        ],
        verbose_name="解析状态",
    )
    error_message = models.TextField(blank=True, default="", verbose_name="错误信息")
    fetched_at = models.DateTimeField(auto_now_add=True, verbose_name="采集时间")

    class Meta:
        db_table = "market_data_raw_payload"
        verbose_name = "原始数据载荷"
        verbose_name_plural = "原始数据载荷"
        indexes = [
            models.Index(fields=["request_type", "stock_code", "-fetched_at"]),
            models.Index(fields=["-fetched_at"]),
        ]
        ordering = ["-fetched_at"]

    def __str__(self) -> str:
        return f"{self.request_type} {self.stock_code} [{self.parse_status}]"


class StockSentimentModel(models.Model):
    """个股情绪指数表

    存储股票级别的情绪分析聚合结果。
    """

    stock_code = models.CharField(
        max_length=10, db_index=True, verbose_name="股票代码"
    )
    index_date = models.DateField(db_index=True, verbose_name="指数日期")

    # 情绪指数（-3.0 ~ +3.0）
    sentiment_score = models.FloatField(default=0.0, verbose_name="情绪评分")
    confidence = models.FloatField(default=0.0, verbose_name="置信度")
    news_count = models.IntegerField(default=0, verbose_name="分析新闻数")
    data_sufficient = models.BooleanField(
        default=False,
        verbose_name="数据充足性",
        help_text="True 表示新闻数量达标",
    )

    # 元信息
    source = models.CharField(max_length=50, default="eastmoney", verbose_name="数据源")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = "market_data_stock_sentiment"
        verbose_name = "个股情绪指数"
        verbose_name_plural = "个股情绪指数"
        unique_together = [["stock_code", "index_date"]]
        indexes = [
            models.Index(fields=["stock_code", "-index_date"]),
        ]
        ordering = ["-index_date"]

    def __str__(self) -> str:
        return f"{self.stock_code} {self.index_date} score={self.sentiment_score:.2f}"
