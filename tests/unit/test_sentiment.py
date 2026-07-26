"""
Sentiment 模块单元测试
"""

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from apps.sentiment.application.services import (
    SentimentIndexCalculator,
)
from apps.sentiment.application.tasks import (
    _normalize_news_sentiment_score,
    analyze_policy_event_sentiment,
    batch_analyze_texts,
    calculate_daily_sentiment_index,
    check_sentiment_data_freshness,
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
from core.exceptions import AIServiceError


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
        expected = (1 * 1 + 2 * 2 + 3 * 3) / 6
        assert abs(result - expected) < 0.01


class TestSentimentDailyTask:
    """Tests for the daily sentiment calculation task."""

    def test_normalize_news_sentiment_score_scales_data_center_range(self):
        assert _normalize_news_sentiment_score(0.5) == 1.5
        assert _normalize_news_sentiment_score(-2.0) == -2.0
        assert _normalize_news_sentiment_score(9.0) == 3.0

    @pytest.mark.parametrize("score", [float("nan"), float("inf"), float("-inf"), True])
    def test_normalize_news_sentiment_score_rejects_non_finite_values(self, score):
        with pytest.raises(ValueError, match="finite number"):
            _normalize_news_sentiment_score(score)

    def test_calculate_daily_sentiment_index_uses_market_news_scores(self, monkeypatch):
        saved = {}

        class _PolicyRepo:
            @staticmethod
            def get_events_in_range(_start, _end):
                return []

        class _IndexRepo:
            @staticmethod
            def save(index):
                saved["index"] = index

        class _Analyzer:
            def __init__(self, _repo):
                pass

            def analyze_text(self, _text):
                raise AssertionError("stored news sentiment should avoid AI calls")

        monkeypatch.setattr(
            "apps.policy.application.repository_provider.get_current_policy_repository",
            lambda: _PolicyRepo(),
        )
        monkeypatch.setattr(
            "apps.ai_provider.application.repository_provider.get_ai_provider_repository",
            lambda: object(),
        )
        monkeypatch.setattr(
            "apps.sentiment.application.repository_provider.get_market_news_for_sentiment",
            lambda _target_date, limit=50: [
                SimpleNamespace(
                    title="利好新闻",
                    summary="",
                    sentiment_score=0.5,
                    external_id="n1",
                    url="",
                ),
                SimpleNamespace(
                    title="偏负面新闻",
                    summary="",
                    sentiment_score=-0.25,
                    external_id="n2",
                    url="",
                ),
            ],
        )
        monkeypatch.setattr(
            "apps.sentiment.application.repository_provider.get_sentiment_index_repository",
            lambda: _IndexRepo(),
        )
        monkeypatch.setattr(
            "apps.sentiment.application.services.SentimentAnalyzer",
            _Analyzer,
        )

        result = calculate_daily_sentiment_index.run(target_date="2026-06-26")

        assert result["status"] == "success"
        assert result["news_count"] == 2
        assert result["policy_events"] == 0
        assert saved["index"].news_count == 2
        assert saved["index"].data_sufficient is True

    def test_invalid_target_date_fails_without_retry(self, monkeypatch):
        monkeypatch.setattr(
            calculate_daily_sentiment_index,
            "retry",
            lambda **_kwargs: pytest.fail("permanent input errors must not retry"),
        )

        with pytest.raises(ValueError, match="YYYY-MM-DD"):
            calculate_daily_sentiment_index.run(target_date="2026-02-30")

    def test_policy_analysis_runtime_failure_requests_retry(self, monkeypatch):
        class _FailingPolicyRepo:
            @staticmethod
            def get_event_by_id(_event_id):
                raise TimeoutError("policy repository timed out")

        retry_error = RuntimeError("retry requested")
        observed = {}

        def _retry(*, exc, countdown):
            observed["exc"] = exc
            observed["countdown"] = countdown
            return retry_error

        monkeypatch.setattr(
            "apps.policy.application.repository_provider.get_current_policy_repository",
            lambda: _FailingPolicyRepo(),
        )
        monkeypatch.setattr(analyze_policy_event_sentiment, "retry", _retry)

        with pytest.raises(RuntimeError, match="retry requested"):
            analyze_policy_event_sentiment.run(event_id=7)

        assert isinstance(observed["exc"], TimeoutError)
        assert observed["countdown"] == 60

    def test_daily_ai_failure_retries_without_persisting_false_neutral_index(
        self,
        monkeypatch,
    ):
        saved = []

        class _PolicyRepo:
            @staticmethod
            def get_events_in_range(_start, _end):
                return []

        class _IndexRepo:
            @staticmethod
            def save(index):
                saved.append(index)

        class _Analyzer:
            def __init__(self, _repo):
                pass

            @staticmethod
            def analyze_text(_text):
                raise RuntimeError("provider unavailable")

        retry_error = RuntimeError("retry requested")
        observed = {}

        def _retry(*, exc, countdown):
            observed["exc"] = exc
            observed["countdown"] = countdown
            return retry_error

        monkeypatch.setattr(
            "apps.policy.application.repository_provider.get_current_policy_repository",
            lambda: _PolicyRepo(),
        )
        monkeypatch.setattr(
            "apps.ai_provider.application.repository_provider.get_ai_provider_repository",
            lambda: object(),
        )
        monkeypatch.setattr(
            "apps.sentiment.application.repository_provider.get_market_news_for_sentiment",
            lambda _target_date, limit=50: [
                SimpleNamespace(
                    title="待分析新闻",
                    summary="正文",
                    sentiment_score=None,
                    external_id="failed-news",
                    url="",
                )
            ],
        )
        monkeypatch.setattr(
            "apps.sentiment.application.repository_provider.get_sentiment_index_repository",
            lambda: _IndexRepo(),
        )
        monkeypatch.setattr(
            "apps.sentiment.application.services.SentimentAnalyzer",
            _Analyzer,
        )
        monkeypatch.setattr(calculate_daily_sentiment_index, "retry", _retry)

        with pytest.raises(RuntimeError, match="retry requested"):
            calculate_daily_sentiment_index.run(target_date="2026-06-26")

        assert isinstance(observed["exc"], AIServiceError)
        assert observed["countdown"] == 300
        assert saved == []

    def test_freshness_repository_failure_requests_retry(self, monkeypatch):
        class _FailingIndexRepo:
            @staticmethod
            def get_latest():
                raise ConnectionError("database unavailable")

        retry_error = RuntimeError("retry requested")
        observed = {}

        def _retry(*, exc, countdown):
            observed["exc"] = exc
            observed["countdown"] = countdown
            return retry_error

        monkeypatch.setattr(
            "apps.sentiment.application.repository_provider.get_sentiment_index_repository",
            lambda: _FailingIndexRepo(),
        )
        monkeypatch.setattr(check_sentiment_data_freshness, "retry", _retry)

        with pytest.raises(RuntimeError, match="retry requested"):
            check_sentiment_data_freshness.run()

        assert isinstance(observed["exc"], ConnectionError)
        assert observed["countdown"] == 60

    def test_batch_ai_failure_reaches_celery_autoretry_boundary(self, monkeypatch):
        class _Analyzer:
            def __init__(self, _repo):
                pass

            @staticmethod
            def analyze_text(text):
                return SentimentAnalysisResult(
                    text=text,
                    sentiment_score=0.0,
                    confidence=0.0,
                    category=SentimentCategory.NEUTRAL,
                    error_message="AI 调用失败: unavailable",
                )

        monkeypatch.setattr(
            "apps.ai_provider.application.repository_provider.get_ai_provider_repository",
            lambda: object(),
        )
        monkeypatch.setattr(
            "apps.sentiment.application.services.SentimentAnalyzer",
            _Analyzer,
        )

        with pytest.raises(AIServiceError, match="batch sentiment analysis failed"):
            batch_analyze_texts.run(texts=["待分析文本"])


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
        model = type(
            "MockModel",
            (),
            {
                "index_date": date(2026, 1, 1),
                "news_sentiment": 0.5,
                "policy_sentiment": 1.0,
                "composite_index": 0.8,
                "confidence_level": 0.75,
                "data_sufficient": True,  # 添加新字段
                "sector_sentiment": {"金融": 0.5},
                "news_count": 10,
                "policy_events_count": 5,
                "created_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
            },
        )()

        repo = SentimentIndexRepository()
        entity = repo._to_entity(model)

        assert entity.composite_index == 0.8
        assert entity.news_count == 10
        assert entity.sector_sentiment == {"金融": 0.5}
        assert entity.data_sufficient is True  # 验证新字段
        assert entity.index_date.tzinfo is UTC


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

    def test_parse_sentiment_score_rejects_malformed_output(self):
        """Malformed provider output cannot be recorded as neutral sentiment."""
        from apps.sentiment.application.services import SentimentAnalyzer

        class MockRepo:
            pass

        analyzer = SentimentAnalyzer(MockRepo())

        assert analyzer._parse_sentiment_score('{"reasoning": "missing score"}') is None
        assert analyzer._parse_sentiment_score('{"score": "NaN"}') is None

    def test_categorize_sentiment(self):
        """测试情感分类"""
        from apps.sentiment.application.services import SentimentAnalyzer

        class MockRepo:
            pass

        analyzer = SentimentAnalyzer(MockRepo())

        assert analyzer._categorize_sentiment(1.5) == SentimentCategory.POSITIVE
        assert analyzer._categorize_sentiment(-1.5) == SentimentCategory.NEGATIVE
        assert analyzer._categorize_sentiment(0.0) == SentimentCategory.NEUTRAL

    def test_extract_keywords_discards_non_string_values(self):
        from apps.sentiment.application.services import SentimentAnalyzer

        class MockRepo:
            pass

        analyzer = SentimentAnalyzer(MockRepo())
        response = '{"keywords": [" 降息 ", 7, null, "", "宽松"]}'

        assert analyzer._extract_keywords("测试", response) == ["降息", "宽松"]

    def test_analyze_text_preserves_adapter_error_message(self, monkeypatch):
        from apps.sentiment.application.services import SentimentAnalyzer

        class MockRepo:
            pass

        class _Adapter:
            @staticmethod
            def chat_completion(**_kwargs):
                return {
                    "status": "timeout",
                    "error_message": "upstream timed out",
                }

        analyzer = SentimentAnalyzer(MockRepo())
        monkeypatch.setattr(analyzer, "_get_ai_adapter", lambda: _Adapter())
        monkeypatch.setattr(analyzer, "_send_ai_failure_alert", lambda *_args: None)

        result = analyzer.analyze_text("测试")

        assert result.error_message == "AI provider request failed"
        assert result.confidence == 0.0


def test_interface_service_does_not_cache_or_return_failed_ai_analysis(monkeypatch):
    from apps.sentiment.application import interface_services

    cached = []
    logged = []

    class _CacheRepo:
        @staticmethod
        def get(_text):
            return None

        @staticmethod
        def set(text, result):
            cached.append((text, result))

    class _LogRepo:
        @staticmethod
        def log(**payload):
            logged.append(payload)

    class _Analyzer:
        def __init__(self, provider_repository):
            pass

        @staticmethod
        def analyze_text(text):
            return SentimentAnalysisResult(
                text=text,
                sentiment_score=0.0,
                confidence=0.0,
                category=SentimentCategory.NEUTRAL,
                error_message="AI 调用失败: unavailable",
            )

    monkeypatch.setattr(interface_services, "get_sentiment_cache_repository", lambda: _CacheRepo())
    monkeypatch.setattr(
        interface_services,
        "get_sentiment_analysis_log_repository",
        lambda: _LogRepo(),
    )
    monkeypatch.setattr(interface_services, "get_ai_provider_repository", lambda: object())
    monkeypatch.setattr(interface_services, "SentimentAnalyzer", _Analyzer)

    with pytest.raises(AIServiceError, match="暂时不可用"):
        interface_services.analyze_sentiment_text(text="测试", use_cache=True)

    assert cached == []
    assert len(logged) == 1
