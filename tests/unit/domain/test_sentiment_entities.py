"""
Unit tests for Sentiment Domain Entities.

Pure Domain layer tests using only Python standard library.
"""

import pytest
from datetime import datetime
from apps.sentiment.domain.entities import (
    SentimentCategory,
    SentimentAnalysisResult,
    SentimentIndex,
    SentimentSource,
)


class TestSentimentAnalysisResult:
    """Tests for SentimentAnalysisResult entity"""

    def test_create_valid_result(self):
        """Test creating a valid sentiment analysis result"""
        result = SentimentAnalysisResult(
            text="测试文本",
            sentiment_score=1.5,
            confidence=0.8,
            category=SentimentCategory.POSITIVE,
            keywords=["测试", "正面"],
        )
        assert result.text == "测试文本"
        assert result.sentiment_score == 1.5
        assert result.confidence == 0.8
        assert result.category == SentimentCategory.POSITIVE
        assert result.keywords == ["测试", "正面"]

    def test_sentiment_score_boundary_positive(self):
        """Test maximum sentiment score boundary"""
        result = SentimentAnalysisResult(
            text="测试",
            sentiment_score=3.0,
            confidence=0.9,
            category=SentimentCategory.POSITIVE,
        )
        assert result.sentiment_score == 3.0

    def test_sentiment_score_boundary_negative(self):
        """Test minimum sentiment score boundary"""
        result = SentimentAnalysisResult(
            text="测试",
            sentiment_score=-3.0,
            confidence=0.9,
            category=SentimentCategory.NEGATIVE,
        )
        assert result.sentiment_score == -3.0

    def test_sentiment_score_out_of_range_high(self):
        """Test sentiment score above maximum raises error"""
        with pytest.raises(ValueError):
            SentimentAnalysisResult(
                text="测试",
                sentiment_score=3.1,
                confidence=0.9,
                category=SentimentCategory.POSITIVE,
            )

    def test_sentiment_score_out_of_range_low(self):
        """Test sentiment score below minimum raises error"""
        with pytest.raises(ValueError):
            SentimentAnalysisResult(
                text="测试",
                sentiment_score=-3.1,
                confidence=0.9,
                category=SentimentCategory.NEGATIVE,
            )

    def test_confidence_boundary_max(self):
        """Test maximum confidence boundary"""
        result = SentimentAnalysisResult(
            text="测试",
            sentiment_score=1.0,
            confidence=1.0,
            category=SentimentCategory.NEUTRAL,
        )
        assert result.confidence == 1.0

    def test_confidence_boundary_min(self):
        """Test minimum confidence boundary"""
        result = SentimentAnalysisResult(
            text="测试",
            sentiment_score=0.0,
            confidence=0.0,
            category=SentimentCategory.NEUTRAL,
        )
        assert result.confidence == 0.0

    def test_confidence_out_of_range_high(self):
        """Test confidence above maximum raises error"""
        with pytest.raises(ValueError, match="confidence 必须在 0.0 到 1.0 之间"):
            SentimentAnalysisResult(
                text="测试",
                sentiment_score=1.0,
                confidence=1.1,
                category=SentimentCategory.NEUTRAL,
            )

    def test_confidence_out_of_range_low(self):
        """Test confidence below minimum raises error"""
        with pytest.raises(ValueError, match="confidence 必须在 0.0 到 1.0 之间"):
            SentimentAnalysisResult(
                text="测试",
                sentiment_score=1.0,
                confidence=-0.1,
                category=SentimentCategory.NEUTRAL,
            )

    def test_to_dict_truncates_long_text(self):
        """Test to_dict truncates text longer than 100 characters"""
        long_text = "a" * 150
        result = SentimentAnalysisResult(
            text=long_text,
            sentiment_score=1.0,
            confidence=0.8,
            category=SentimentCategory.POSITIVE,
        )
        result_dict = result.to_dict()
        assert len(result_dict["text"]) == 103  # 100 + "..."
        assert result_dict["text"].endswith("...")

    def test_to_dict_short_text_unchanged(self):
        """Test to_dict preserves short text"""
        result = SentimentAnalysisResult(
            text="短文本",
            sentiment_score=1.0,
            confidence=0.8,
            category=SentimentCategory.POSITIVE,
        )
        result_dict = result.to_dict()
        assert result_dict["text"] == "短文本"

    def test_to_dict_includes_all_fields(self):
        """Test to_dict includes all relevant fields"""
        now = datetime(2024, 1, 1, 12, 0, 0)
        result = SentimentAnalysisResult(
            text="测试",
            sentiment_score=1.5,
            confidence=0.8,
            category=SentimentCategory.POSITIVE,
            keywords=["测试", "正面"],
            analyzed_at=now,
        )
        result_dict = result.to_dict()
        assert result_dict["text"] == "测试"
        assert result_dict["sentiment_score"] == 1.5
        assert result_dict["confidence"] == 0.8
        assert result_dict["category"] == "POSITIVE"
        assert result_dict["keywords"] == ["测试", "正面"]
        assert "analyzed_at" in result_dict

    def test_frozen_dataclass(self):
        """Test that SentimentAnalysisResult is frozen"""
        result = SentimentAnalysisResult(
            text="测试",
            sentiment_score=1.0,
            confidence=0.8,
            category=SentimentCategory.POSITIVE,
        )
        with pytest.raises(Exception):  # FrozenInstanceError
            result.sentiment_score = 2.0


class TestSentimentIndex:
    """Tests for SentimentIndex entity"""

    def test_create_valid_index(self):
        """Test creating a valid sentiment index"""
        index = SentimentIndex(
            index_date=datetime(2024, 1, 1),
            news_sentiment=0.5,
            policy_sentiment=0.3,
            composite_index=0.4,
            confidence_level=0.7,
        )
        assert index.news_sentiment == 0.5
        assert index.policy_sentiment == 0.3
        assert index.composite_index == 0.4

    def test_default_values(self):
        """Test default values for optional fields"""
        index = SentimentIndex(
            index_date=datetime(2024, 1, 1),
        )
        assert index.news_sentiment == 0.0
        assert index.policy_sentiment == 0.0
        assert index.composite_index == 0.0
        assert index.confidence_level == 0.0
        assert index.news_count == 0
        assert index.policy_events_count == 0
        assert index.sector_sentiment == {}

    def test_news_sentiment_boundary(self):
        """Test news sentiment score boundaries"""
        index = SentimentIndex(
            index_date=datetime(2024, 1, 1),
            news_sentiment=3.0,
        )
        assert index.news_sentiment == 3.0

        index2 = SentimentIndex(
            index_date=datetime(2024, 1, 1),
            news_sentiment=-3.0,
        )
        assert index2.news_sentiment == -3.0

    def test_news_sentiment_out_of_range(self):
        """Test news sentiment score out of range raises error"""
        with pytest.raises(ValueError, match="news_sentiment 必须在 -3.0 到"):
            SentimentIndex(
                index_date=datetime(2024, 1, 1),
                news_sentiment=3.1,
            )

    def test_policy_sentiment_out_of_range(self):
        """Test policy sentiment score out of range raises error"""
        with pytest.raises(ValueError, match="policy_sentiment 必须在 -3.0 到"):
            SentimentIndex(
                index_date=datetime(2024, 1, 1),
                policy_sentiment=-3.1,
            )

    def test_composite_index_out_of_range(self):
        """Test composite index out of range raises error"""
        with pytest.raises(ValueError, match="composite_index 必须在 -3.0 到"):
            SentimentIndex(
                index_date=datetime(2024, 1, 1),
                composite_index=4.0,
            )

    def test_get_sentiment_level_extremely_optimistic(self):
        """Test sentiment level for extremely optimistic score"""
        index = SentimentIndex(
            index_date=datetime(2024, 1, 1),
            composite_index=2.0,
        )
        assert index._get_sentiment_level() == "极度乐观"

    def test_get_sentiment_level_optimistic(self):
        """Test sentiment level for optimistic score"""
        index = SentimentIndex(
            index_date=datetime(2024, 1, 1),
            composite_index=1.0,
        )
        assert index._get_sentiment_level() == "乐观"

    def test_get_sentiment_level_neutral(self):
        """Test sentiment level for neutral score"""
        index = SentimentIndex(
            index_date=datetime(2024, 1, 1),
            composite_index=0.0,
        )
        assert index._get_sentiment_level() == "中性"

    def test_get_sentiment_level_pessimistic(self):
        """Test sentiment level for pessimistic score"""
        index = SentimentIndex(
            index_date=datetime(2024, 1, 1),
            composite_index=-1.0,
        )
        assert index._get_sentiment_level() == "悲观"

    def test_get_sentiment_level_extremely_pessimistic(self):
        """Test sentiment level for extremely pessimistic score"""
        index = SentimentIndex(
            index_date=datetime(2024, 1, 1),
            composite_index=-2.0,
        )
        assert index._get_sentiment_level() == "极度悲观"

    def test_to_dict_includes_all_fields(self):
        """Test to_dict includes all fields"""
        index = SentimentIndex(
            index_date=datetime(2024, 1, 1),
            news_sentiment=0.5,
            policy_sentiment=0.3,
            composite_index=0.4,
            confidence_level=0.7,
            sector_sentiment={"科技": 0.8, "金融": 0.2},
            news_count=10,
            policy_events_count=2,
        )
        result_dict = index.to_dict()
        assert result_dict["date"] == "2024-01-01"
        assert result_dict["index"]["composite"] == 0.4
        assert result_dict["index"]["news"] == 0.5
        assert result_dict["index"]["policy"] == 0.3
        assert result_dict["level"] == "中性"
        assert result_dict["confidence"] == 0.7
        assert result_dict["sector_sentiment"] == {"科技": 0.8, "金融": 0.2}
        assert result_dict["sources"]["news_count"] == 10
        assert result_dict["sources"]["policy_events_count"] == 2


class TestSentimentSource:
    """Tests for SentimentSource entity"""

    def test_create_valid_source_with_title_only(self):
        """Test creating source with title only"""
        source = SentimentSource(
            source_type="news",
            source_id="123",
            title="测试标题",
            content="",
            published_at=datetime(2024, 1, 1),
        )
        assert source.title == "测试标题"
        assert source.content == ""

    def test_create_valid_source_with_content_only(self):
        """Test creating source with content only"""
        source = SentimentSource(
            source_type="news",
            source_id="123",
            title="",
            content="测试内容",
            published_at=datetime(2024, 1, 1),
        )
        assert source.title == ""
        assert source.content == "测试内容"

    def test_source_type_cannot_be_empty(self):
        """Test source type cannot be empty"""
        with pytest.raises(ValueError, match="source_type 不能为空"):
            SentimentSource(
                source_type="",
                source_id="123",
                title="测试标题",
                content="测试内容",
                published_at=datetime(2024, 1, 1),
            )

    def test_title_and_content_both_empty_raises_error(self):
        """Test both title and content empty raises error"""
        with pytest.raises(ValueError, match="title 和 content 至少需要一个"):
            SentimentSource(
                source_type="news",
                source_id="123",
                title="",
                content="",
                published_at=datetime(2024, 1, 1),
            )

    def test_to_text_with_both_title_and_content(self):
        """Test to_text combines title and content"""
        source = SentimentSource(
            source_type="news",
            source_id="123",
            title="标题",
            content="内容",
            published_at=datetime(2024, 1, 1),
        )
        assert source.to_text() == "标题\n内容"

    def test_to_text_with_title_only(self):
        """Test to_text with only title returns title"""
        source = SentimentSource(
            source_type="news",
            source_id="123",
            title="标题",
            content="",
            published_at=datetime(2024, 1, 1),
        )
        assert source.to_text() == "标题"

    def test_default_metadata(self):
        """Test default metadata is empty dict"""
        source = SentimentSource(
            source_type="news",
            source_id="123",
            title="标题",
            content="内容",
            published_at=datetime(2024, 1, 1),
        )
        assert source.metadata == {}

    def test_metadata_can_be_set(self):
        """Test metadata can be set"""
        metadata = {"author": "测试", "source": "测试来源"}
        source = SentimentSource(
            source_type="news",
            source_id="123",
            title="标题",
            content="内容",
            published_at=datetime(2024, 1, 1),
            metadata=metadata,
        )
        assert source.metadata == metadata

    def test_url_optional(self):
        """Test URL is optional"""
        source = SentimentSource(
            source_type="news",
            source_id="123",
            title="标题",
            content="内容",
            published_at=datetime(2024, 1, 1),
        )
        assert source.url is None

    def test_url_can_be_set(self):
        """Test URL can be set"""
        source = SentimentSource(
            source_type="news",
            source_id="123",
            title="标题",
            content="内容",
            published_at=datetime(2024, 1, 1),
            url="https://example.com",
        )
        assert source.url == "https://example.com"


class TestSentimentCategory:
    """Tests for SentimentCategory enum"""

    def test_category_values(self):
        """Test sentiment category enum values"""
        assert SentimentCategory.POSITIVE.value == "POSITIVE"
        assert SentimentCategory.NEGATIVE.value == "NEGATIVE"
        assert SentimentCategory.NEUTRAL.value == "NEUTRAL"

    def test_category_creation_from_value(self):
        """Test creating category from string value"""
        assert SentimentCategory("POSITIVE") == SentimentCategory.POSITIVE
        assert SentimentCategory("NEGATIVE") == SentimentCategory.NEGATIVE
        assert SentimentCategory("NEUTRAL") == SentimentCategory.NEUTRAL

    def test_invalid_category_value(self):
        """Test invalid category value raises error"""
        with pytest.raises(ValueError):
            SentimentCategory("INVALID")
