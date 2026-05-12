"""
Sentiment 模块单元测试
"""

from datetime import date, datetime

import pytest

from apps.sentiment.application.services import (
    SentimentIndexCalculator,
)
from apps.sentiment.domain.entities import (
    SentimentAnalysisResult,
    SentimentCategory,
    SentimentIndex,
    SentimentSource,
)
from apps.sentiment.infrastructure.repositories import (
    SentimentCacheRepository,
    SentimentIndexRepository,
)


class TestSentimentAnalysisResult:
    """测试情感分析结果实体"""

    def test_create_result(self):
        """测试创建结果"""
        result = SentimentAnalysisResult(
            text="测试文本",
            sentiment_score=1.5,
            confidence=0.8,
            category=SentimentCategory.POSITIVE,
            keywords=["利好", "上涨"],
        )
        assert result.text == "测试文本"
        assert result.sentiment_score == 1.5
        assert result.category == SentimentCategory.POSITIVE

    def test_score_validation(self):
        """测试评分验证"""
        # 超出范围
        with pytest.raises(ValueError):
            SentimentAnalysisResult(
                text="测试",
                sentiment_score=5.0,  # 超出范围
                confidence=0.8,
                category=SentimentCategory.POSITIVE,
            )

    def test_confidence_validation(self):
        """测试置信度验证"""
        with pytest.raises(ValueError):
            SentimentAnalysisResult(
                text="测试",
                sentiment_score=0.0,
                confidence=1.5,  # 超出范围
                category=SentimentCategory.NEUTRAL,
            )

    def test_to_dict(self):
        """测试转换为字典"""
        result = SentimentAnalysisResult(
            text="这是一个非常长的文本内容，应该被截断显示，因为超过了一百个字符的限制" * 2,
            sentiment_score=1.5,
            confidence=0.8,
            category=SentimentCategory.POSITIVE,
            keywords=["利好"],
        )
        d = result.to_dict()
        assert len(d["text"]) <= 103  # 100 + "..."
        assert d["category"] == "POSITIVE"


class TestSentimentIndex:
    """测试情绪指数实体"""

    def test_create_index(self):
        """测试创建指数"""
        index = SentimentIndex(
            index_date=datetime(2026, 1, 1),
            news_sentiment=0.5,
            policy_sentiment=1.0,
            composite_index=0.8,
            confidence_level=0.75,
            news_count=10,
            policy_events_count=5,
        )
        assert index.composite_index == 0.8
        assert index.news_count == 10

    def test_sentiment_level(self):
        """测试情绪等级"""
        # 极度乐观
        index1 = SentimentIndex(
            index_date=datetime.now(),
            composite_index=2.0,
        )
        assert index1._get_sentiment_level() == "极度乐观"

        # 乐观
        index2 = SentimentIndex(
            index_date=datetime.now(),
            composite_index=1.0,
        )
        assert index2._get_sentiment_level() == "乐观"

        # 中性
        index3 = SentimentIndex(
            index_date=datetime.now(),
            composite_index=0.0,
        )
        assert index3._get_sentiment_level() == "中性"

        # 悲观
        index4 = SentimentIndex(
            index_date=datetime.now(),
            composite_index=-1.0,
        )
        assert index4._get_sentiment_level() == "悲观"

        # 极度悲观
        index5 = SentimentIndex(
            index_date=datetime.now(),
            composite_index=-2.0,
        )
        assert index5._get_sentiment_level() == "极度悲观"

    def test_to_dict(self):
        """测试转换为字典"""
        index = SentimentIndex(
            index_date=datetime(2026, 1, 1),
            composite_index=0.5,
            news_sentiment=0.3,
            policy_sentiment=0.7,
            confidence_level=0.8,
            data_sufficient=True,  # 添加数据充足标记
        )
        d = index.to_dict()
        assert d["date"] == "2026-01-01"
        assert d["index"]["composite"] == 0.5
        assert d["level"] == "乐观"
        assert d["data_sufficient"] is True  # 验证新字段


class TestSentimentSource:
    """测试情感数据源实体"""

    def test_create_source(self):
        """测试创建数据源"""
        source = SentimentSource(
            source_type="news",
            source_id="123",
            title="测试标题",
            content="测试内容",
            published_at=datetime.now(),
        )
        assert source.source_type == "news"
        assert source.to_text() == "测试标题\n测试内容"

    def test_validation(self):
        """测试验证"""
        # 缺少 title 和 content
        with pytest.raises(ValueError):
            SentimentSource(
                source_type="news",
                source_id="123",
                title="",
                content="",
                published_at=datetime.now(),
            )


class TestSentimentIndexCalculator:
    """测试情绪指数计算器"""

    def test_calculate_index(self):
        """测试计算指数"""
        calculator = SentimentIndexCalculator()

        news_scores = [0.5, 1.0, 0.3]
        policy_scores = [1.5, 2.0, 1.0]

        index = calculator.calculate_index(
            news_scores=news_scores,
            policy_scores=policy_scores,
        )

        # 验证计算结果
        assert -3.0 <= index.composite_index <= 3.0
        assert index.news_count == 3
        assert index.policy_events_count == 3
        assert 0.0 <= index.confidence_level <= 1.0
        # 有数据时应该标记为 True
        assert index.data_sufficient is True

    def test_calculate_empty(self):
        """测试空数据计算"""
        calculator = SentimentIndexCalculator()

        index = calculator.calculate_index(
            news_scores=[],
            policy_scores=[],
        )

        assert index.composite_index == 0.0
        assert index.news_count == 0
        assert index.policy_events_count == 0
        assert index.confidence_level == 0.0
        # 数据不足时应该标记为 False
        assert index.data_sufficient is False

    def test_calculate_with_only_news_data(self):
        """测试只有新闻数据的计算"""
        calculator = SentimentIndexCalculator()

        index = calculator.calculate_index(
            news_scores=[0.5, 1.0],
            policy_scores=[],
        )

        # 有新闻数据时应该标记为 True
        assert index.data_sufficient is True
        assert index.news_count == 2
        assert index.policy_events_count == 0

    def test_calculate_with_only_policy_data(self):
        """测试只有政策数据的计算"""
        calculator = SentimentIndexCalculator()

        index = calculator.calculate_index(
            news_scores=[],
            policy_scores=[1.5, -0.5],
        )

        # 有政策数据时应该标记为 True
        assert index.data_sufficient is True
        assert index.news_count == 0
        assert index.policy_events_count == 2

    def test_sentiment_level_with_insufficient_data(self):
        """测试数据不足时的情绪等级"""
        index = SentimentIndex(
            index_date=datetime.now(),
            composite_index=0.0,
            data_sufficient=False,  # 数据不足
        )
        # 数据不足时应该返回"数据不足"
        assert index.to_dict()["level"] == "数据不足"

    def test_sentiment_level_with_sufficient_data(self):
        """测试数据充足时的情绪等级"""
        index = SentimentIndex(
            index_date=datetime.now(),
            composite_index=0.0,
            data_sufficient=True,  # 数据充足
        )
        # 数据充足且指数为 0 时应该是"中性"
        assert index.to_dict()["level"] == "中性"

    def test_weighted_average(self):
        """测试加权平均"""
        calculator = SentimentIndexCalculator()

        # 测试线性加权：最新的权重更高
        scores = [1.0, 2.0, 3.0]
        result = calculator._weighted_average(scores)

        # 权重: [1, 2, 3]
        # 计算: (1*1 + 2*2 + 3*3) / (1 + 2 + 3) = 14/6 ≈ 2.33
        expected = (1*1 + 2*2 + 3*3) / 6
        assert abs(result - expected) < 0.01


class TestSentimentCacheRepository:
    """测试情感缓存仓储"""

    def test_hash_computation(self):
        """测试哈希计算"""
        repo = SentimentCacheRepository()

        text1 = "测试文本"
        text2 = "测试文本"
        text3 = "不同文本"

        hash1 = repo._compute_hash(text1)
        hash2 = repo._compute_hash(text2)
        hash3 = repo._compute_hash(text3)

        # 相同文本应该有相同哈希
        assert hash1 == hash2
        # 不同文本应该有不同哈希
        assert hash1 != hash3
        # 哈希应该是 64 字符（SHA256）
        assert len(hash1) == 64


class TestSentimentIndexRepository:
    """测试情绪指数仓储"""

    def test_to_entity(self):
        """测试 ORM 转实体"""

        # 创建模拟模型
        model = type('MockModel', (), {
            'index_date': date(2026, 1, 1),
            'news_sentiment': 0.5,
            'policy_sentiment': 1.0,
            'composite_index': 0.8,
            'confidence_level': 0.75,
            'data_sufficient': True,  # 添加新字段
            'sector_sentiment': {"金融": 0.5},
            'news_count': 10,
            'policy_events_count': 5,
            'created_at': datetime.now(),
            'updated_at': datetime.now(),
        })()

        repo = SentimentIndexRepository()
        entity = repo._to_entity(model)

        assert entity.composite_index == 0.8
        assert entity.news_count == 10
        assert entity.sector_sentiment == {"金融": 0.5}
        assert entity.data_sufficient is True  # 验证新字段


class TestSentimentAnalyzer:
    """测试情感分析器（需要 mock AI）"""

    def test_parse_sentiment_score_json(self):
        """测试解析 JSON 格式的 AI 响应"""
        from apps.sentiment.application.services import SentimentAnalyzer

        # Mock AI provider repo
        class MockRepo:
            pass

        analyzer = SentimentAnalyzer(MockRepo())

        # JSON 格式响应
        json_response = '{"score": 1.5, "reasoning": "利好消息", "keywords": ["降息", "宽松"]}'

        score = analyzer._parse_sentiment_score(json_response)
        assert score == 1.5

    def test_parse_sentiment_score_plain(self):
        """测试解析纯数字响应"""
        from apps.sentiment.application.services import SentimentAnalyzer

        class MockRepo:
            pass

        analyzer = SentimentAnalyzer(MockRepo())

        # 纯数字响应
        plain_response = "评分：2.0 分"
        score = analyzer._parse_sentiment_score(plain_response)
        assert score == 2.0

    def test_categorize_sentiment(self):
        """测试情感分类"""
        from apps.sentiment.application.services import SentimentAnalyzer

        class MockRepo:
            pass

        analyzer = SentimentAnalyzer(MockRepo())

        assert analyzer._categorize_sentiment(1.5) == SentimentCategory.POSITIVE
        assert analyzer._categorize_sentiment(-1.5) == SentimentCategory.NEGATIVE
        assert analyzer._categorize_sentiment(0.0) == SentimentCategory.NEUTRAL
