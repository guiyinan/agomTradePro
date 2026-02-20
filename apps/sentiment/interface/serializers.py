"""
Sentiment 模块 - Interface 层序列化器

本模块包含 DRF 序列化器，用于 API 数据格式化。
"""

from rest_framework import serializers
from typing import List, Optional


class SentimentAnalysisRequestSerializer(serializers.Serializer):
    """情感分析请求序列化器"""
    text = serializers.CharField(
        max_length=5000,
        help_text="待分析的文本内容"
    )
    use_cache = serializers.BooleanField(
        default=True,
        help_text="是否使用缓存"
    )


class SentimentAnalysisResponseSerializer(serializers.Serializer):
    """情感分析响应序列化器"""
    text = serializers.CharField(help_text="原始文本（可能截断）")
    sentiment_score = serializers.FloatField(help_text="情感评分 (-3.0 ~ +3.0)")
    confidence = serializers.FloatField(help_text="置信度 (0.0 ~ 1.0)")
    category = serializers.CharField(help_text="情感分类: POSITIVE/NEGATIVE/NEUTRAL")
    keywords = serializers.ListField(
        child=serializers.CharField(),
        help_text="关键词列表"
    )
    analyzed_at = serializers.DateTimeField(help_text="分析时间")


class SentimentIndexSerializer(serializers.Serializer):
    """情绪指数序列化器"""
    date = serializers.CharField(help_text="指数日期")
    index = serializers.DictField(help_text="各项指数值")
    level = serializers.CharField(help_text="情绪等级描述")
    confidence = serializers.FloatField(help_text="置信度")
    sector_sentiment = serializers.DictField(help_text="行业情绪分布")
    sources = serializers.DictField(help_text="数据来源统计")


class SentimentIndexListSerializer(serializers.Serializer):
    """情绪指数列表序列化器"""
    indices = SentimentIndexSerializer(many=True)
    total = serializers.IntegerField()


class BatchAnalysisRequestSerializer(serializers.Serializer):
    """批量分析请求序列化器"""
    texts = serializers.ListField(
        child=serializers.CharField(max_length=5000),
        max_length=50,
        help_text="待分析的文本列表（最多50条）"
    )


class BatchAnalysisResponseSerializer(serializers.Serializer):
    """批量分析响应序列化器"""
    results = SentimentAnalysisResponseSerializer(many=True)
    total = serializers.IntegerField()


class SentimentIndexRangeRequestSerializer(serializers.Serializer):
    """日期范围查询请求序列化器"""
    start_date = serializers.DateField(help_text="开始日期 (YYYY-MM-DD)")
    end_date = serializers.DateField(help_text="结束日期 (YYYY-MM-DD)")


class SentimentHealthResponseSerializer(serializers.Serializer):
    """健康检查响应序列化器"""
    status = serializers.CharField(help_text="服务状态")
    ai_provider_available = serializers.BooleanField(help_text="AI 提供商是否可用")
    cache_count = serializers.IntegerField(help_text="缓存数量")
    latest_index_date = serializers.CharField(
        allow_null=True,
        help_text="最新指数日期"
    )
