"""DRF serializers for the Sentiment API."""

from collections.abc import Mapping
from datetime import date
from typing import Any, cast

from rest_framework import serializers


class StrictFieldsSerializer(serializers.Serializer[dict[str, Any]]):
    """Reject fields outside a published Sentiment request contract."""

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        """Validate the request key set before normal field conversion."""

        if not isinstance(data, Mapping):
            raise serializers.ValidationError("Expected an object payload.")
        unknown_fields = sorted(set(data) - set(self.fields))
        if unknown_fields:
            raise serializers.ValidationError(
                {"non_field_errors": [f"Unknown fields: {', '.join(unknown_fields)}"]}
            )
        return cast(dict[str, Any], super().to_internal_value(data))


class SentimentAnalysisRequestSerializer(StrictFieldsSerializer):
    """Validate a single-text analysis request."""

    text = serializers.CharField(
        max_length=5000,
        help_text="待分析的文本内容",
    )
    use_cache = serializers.BooleanField(
        default=True,
        help_text="是否使用缓存",
    )


class SentimentAnalysisResponseSerializer(serializers.Serializer[dict[str, Any]]):
    """Serialize a sentiment-analysis result."""

    text = serializers.CharField(help_text="原始文本（可能截断）")
    sentiment_score = serializers.FloatField(help_text="情感评分 (-3.0 ~ +3.0)")
    confidence = serializers.FloatField(help_text="置信度 (0.0 ~ 1.0)")
    category = serializers.CharField(help_text="情感分类: POSITIVE/NEGATIVE/NEUTRAL")
    keywords = serializers.ListField(
        child=serializers.CharField(),
        help_text="关键词列表",
    )
    analyzed_at = serializers.DateTimeField(help_text="分析时间")


class SentimentIndexSerializer(serializers.Serializer[dict[str, Any]]):
    """Serialize one canonical sentiment index."""

    date = serializers.CharField(help_text="指数日期")
    index = serializers.DictField(help_text="各项指数值")
    level = serializers.CharField(help_text="情绪等级描述")
    confidence = serializers.FloatField(help_text="置信度")
    data_sufficient = serializers.BooleanField(help_text="数据是否充足（区分无数据和中性情绪）")
    sector_sentiment = serializers.DictField(help_text="行业情绪分布")
    sources = serializers.DictField(help_text="数据来源统计")


class SentimentIndexListSerializer(serializers.Serializer[dict[str, Any]]):
    """Serialize a canonical sentiment-index collection."""

    indices = SentimentIndexSerializer(many=True)
    total = serializers.IntegerField()


class BatchAnalysisRequestSerializer(StrictFieldsSerializer):
    """Validate a bounded, non-empty batch analysis request."""

    texts = serializers.ListField(
        child=serializers.CharField(max_length=5000),
        min_length=1,
        max_length=50,
        help_text="待分析的文本列表（1至50条）",
    )

    def validate_texts(self, value: list[str]) -> list[str]:
        """Reject duplicate texts that would repeat paid AI work."""

        normalized = [text.strip() for text in value]
        if len(set(normalized)) != len(normalized):
            raise serializers.ValidationError("Duplicate texts are not allowed.")
        return normalized


class BatchAnalysisResponseSerializer(serializers.Serializer[dict[str, Any]]):
    """Serialize a batch-analysis response."""

    results = SentimentAnalysisResponseSerializer(many=True)
    total = serializers.IntegerField()


class SentimentIndexQuerySerializer(StrictFieldsSerializer):
    """Validate the optional single-index date query."""

    date = serializers.DateField(required=False, help_text="指数日期 (YYYY-MM-DD)")


class SentimentIndexRangeRequestSerializer(StrictFieldsSerializer):
    """Validate an inclusive sentiment-index date range."""

    start_date = serializers.DateField(help_text="开始日期 (YYYY-MM-DD)")
    end_date = serializers.DateField(help_text="结束日期 (YYYY-MM-DD)")

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Reject inverted date ranges before repository access."""

        start_date = cast(date, attrs["start_date"])
        end_date = cast(date, attrs["end_date"])
        if start_date > end_date:
            raise serializers.ValidationError(
                {"end_date": ["Must be greater than or equal to start_date."]}
            )
        return attrs


class SentimentIndexRecentRequestSerializer(StrictFieldsSerializer):
    """Validate the bounded recent-index query."""

    days = serializers.IntegerField(
        required=False,
        default=30,
        min_value=1,
        max_value=365,
    )


class SentimentHealthResponseSerializer(serializers.Serializer[dict[str, Any]]):
    """Serialize the sentiment service health payload."""

    status = serializers.CharField(help_text="服务状态")
    ai_provider_available = serializers.BooleanField(help_text="AI 提供商是否可用")
    cache_count = serializers.IntegerField(help_text="缓存数量")
    latest_index_date = serializers.CharField(
        allow_null=True,
        help_text="最新指数日期",
    )
