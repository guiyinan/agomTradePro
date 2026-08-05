"""Deterministic Policy adapter and AI-classification contracts."""

from __future__ import annotations

import json
import time
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from apps.data_center.infrastructure import rss_gateway
from apps.policy.domain.entities import (
    AuditStatus,
    PolicyLevel,
    RSSItem,
    RSSSourceConfig,
)
from apps.policy.infrastructure.adapters import feedparser_adapter
from apps.policy.infrastructure.adapters.ai_policy_classifier import AIPolicyClassifier
from apps.policy.infrastructure.adapters.base import (
    PolicyAdapterError,
    PolicySourceUnavailableError,
)
from apps.policy.infrastructure.adapters.content_extractor import (
    BaseContentExtractor,
    ContentExtractorError,
    HybridContentExtractor,
    create_content_extractor,
)
from apps.policy.infrastructure.adapters.news_adapter import (
    NewsPolicyAdapter,
    NewsSourceConfig,
    RSSPolicyAdapter,
)
from apps.policy.infrastructure.adapters.rss_adapter import RSSFetchError


def test_content_extractor_cleans_builds_proxy_falls_back_and_validates_factory() -> None:
    """Extractor utilities normalize text and preserve the declared fallback order."""
    base = BaseContentExtractor()
    assert base._clean_text(" A\n\tB\x00 ") == "A B"
    assert base._build_proxies(None) is None
    assert base._build_proxies({"host": "localhost", "port": 8080}) == "http://localhost:8080"
    assert (
        base._build_proxies(
            {
                "proxy_type": "https",
                "host": "proxy",
                "port": 443,
                "username": "u",
                "password": "p",
            }
        )
        == "https://u:p@proxy:443"
    )
    with pytest.raises(NotImplementedError):
        base.extract("https://example.test")

    hybrid = HybridContentExtractor()
    hybrid.readability_extractor = SimpleNamespace(
        extract=lambda *args: (_ for _ in ()).throw(ContentExtractorError("unavailable"))
    )
    hybrid.bs4_extractor = SimpleNamespace(extract=lambda *args: "fallback body")
    assert hybrid.extract("https://example.test") == "fallback body"
    hybrid.bs4_extractor = SimpleNamespace(
        extract=lambda *args: (_ for _ in ()).throw(ContentExtractorError("unavailable"))
    )
    with pytest.raises(ContentExtractorError, match="All extraction methods"):
        hybrid.extract("https://example.test")

    assert create_content_extractor("bs4").source_name == "beautifulsoup"
    assert create_content_extractor("hybrid").source_name == "hybrid"
    with pytest.raises(ValueError, match="Unsupported extractor"):
        create_content_extractor("unknown")


def test_news_adapter_availability_classification_date_parsing_and_fetch(monkeypatch) -> None:
    """News adapter maps deterministic items to the highest applicable policy level."""
    adapter = NewsPolicyAdapter(NewsSourceConfig("fake", "https://news.test"))
    adapter.session = SimpleNamespace(get=lambda *args, **kwargs: SimpleNamespace(status_code=200))
    assert adapter.is_available() is True
    assert adapter.get_source_name() == "fake"
    assert adapter._classify_policy_level("紧急救市并降息") == PolicyLevel.P3
    assert adapter._classify_policy_level("央行降准") == PolicyLevel.P2
    assert adapter._classify_policy_level("研究政策预期") == PolicyLevel.P1
    assert adapter._classify_policy_level("普通新闻") == PolicyLevel.P0
    assert adapter._parse_date("2026/07/24") == date(2026, 7, 24)
    assert adapter._parse_date("2026年07月24日") == date(2026, 7, 24)
    assert adapter._parse_date("bad") is None
    assert adapter._parse_date("") is None
    assert adapter._parse_news_to_event({"title": "missing date"}) is None

    monkeypatch.setattr(
        adapter,
        "_search_policy_news",
        lambda start, end: [
            {
                "title": "央行降准",
                "content": "财政刺激" * 60,
                "url": "https://evidence.test",
                "pub_date": "2026-07-24",
            },
            {"title": "bad", "pub_date": "invalid"},
        ],
    )
    events = adapter.fetch_policy_events()
    assert len(events) == 1
    assert events[0].level == PolicyLevel.P2
    assert events[0].description.endswith("...")

    adapter.session = SimpleNamespace(
        get=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("offline"))
    )
    assert adapter.is_available() is False


def test_news_adapter_rejects_unsafe_config_and_redacts_provider_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider credentials and exception details must not escape the adapter boundary."""
    with pytest.raises(ValueError, match="must not contain credentials"):
        NewsSourceConfig("unsafe", "https://user:secret@news.test")
    with pytest.raises(ValueError, match="request_timeout"):
        NewsSourceConfig("slow", "https://news.test", request_timeout=0)

    adapter = NewsPolicyAdapter(NewsSourceConfig("fake", "https://news.test"))
    monkeypatch.setattr(adapter, "is_available", lambda: True)
    monkeypatch.setattr(
        adapter,
        "_search_policy_news",
        lambda *args: (_ for _ in ()).throw(RuntimeError("postgres://user:secret@db")),
    )

    with pytest.raises(PolicyAdapterError, match="^policy_news_fetch_failed$") as error:
        adapter.fetch_policy_events()
    assert "secret" not in str(error.value)


def test_news_adapter_unavailable_search_and_malformed_item_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """News ingestion rejects unavailable sources and wraps search failures consistently."""
    adapter = NewsPolicyAdapter(NewsSourceConfig("fake", "https://news.test"))
    monkeypatch.setattr(adapter, "is_available", lambda: False)
    with pytest.raises(PolicySourceUnavailableError, match="unavailable"):
        adapter.fetch_policy_events()

    monkeypatch.setattr(adapter, "is_available", lambda: True)
    monkeypatch.setattr(
        adapter,
        "_search_policy_news",
        lambda start, end: (_ for _ in ()).throw(RuntimeError("search API offline")),
    )
    with pytest.raises(PolicyAdapterError, match="^policy_news_fetch_failed$"):
        adapter.fetch_policy_events()

    class _MalformedItem(dict[str, object]):
        def get(self, key: str, default: object = None) -> object:
            raise TypeError("malformed item")

    assert adapter._parse_news_to_event(_MalformedItem()) is None
    fresh_adapter = NewsPolicyAdapter(NewsSourceConfig("fresh", "https://news.test"))
    assert fresh_adapter._search_policy_news(date(2026, 7, 1), date(2026, 7, 24)) == []


def test_rss_policy_adapter_maps_unknown_levels_and_reports_repository_availability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RSS pipeline reads bounded events and maps unknown stored levels fail-closed."""
    from apps.policy.infrastructure import models as policy_models

    rows = [
        SimpleNamespace(
            event_date=date(2026, 7, 24),
            level="P2",
            title="valid",
            description="valid event",
            evidence_url="https://evidence.test/valid",
        ),
        SimpleNamespace(
            event_date=date(2026, 7, 23),
            level="legacy-unknown",
            title="unknown",
            description="legacy event",
            evidence_url="https://evidence.test/unknown",
        ),
    ]

    class _Query(list[SimpleNamespace]):
        def order_by(self, *args: str) -> _Query:
            return self

    manager = SimpleNamespace(
        filter=lambda **kwargs: _Query(rows),
        exists=lambda: True,
    )
    monkeypatch.setattr(
        policy_models,
        "PolicyLog",
        SimpleNamespace(_default_manager=manager),
    )
    adapter = RSSPolicyAdapter()
    events = adapter.fetch_policy_events()
    assert [event.level for event in events] == [PolicyLevel.P2, PolicyLevel.P0]
    assert adapter.is_available() is True
    assert adapter.get_source_name() == "RSS Pipeline (PolicyLog)"

    monkeypatch.setattr(
        policy_models,
        "PolicyLog",
        SimpleNamespace(
            _default_manager=SimpleNamespace(
                exists=lambda: (_ for _ in ()).throw(RuntimeError("table missing"))
            )
        ),
    )
    assert adapter.is_available() is False


def _rss_item() -> RSSItem:
    return RSSItem(
        title="央行宣布降准",
        link="https://policy.test/item",
        pub_date=datetime(2026, 7, 24, tzinfo=UTC),
        description="支持实体经济",
    )


def test_ai_classifier_success_thresholds_failures_and_response_parsing(monkeypatch) -> None:
    """AI classification maps confidence to audit status and fails closed on bad enums."""
    payload = {
        "info_category": "macro",
        "confidence": 0.8,
        "risk_impact": "medium_risk",
        "policy_level": "P2",
        "structured_data": {
            "policy_subject": "央行",
            "affected_sectors": ["银行"],
            "summary": "降准",
        },
    }
    helper = SimpleNamespace(
        chat_completion_with_failover=lambda **kwargs: {
            "status": "success",
            "content": json.dumps(payload),
            "model": "fake-model",
            "provider_used": "",
            "total_tokens": 10,
        }
    )
    classifier = AIPolicyClassifier(helper)
    monkeypatch.setattr(
        type(classifier),
        "auto_approve_threshold",
        property(lambda self: 0.75),
    )
    monkeypatch.setattr(
        type(classifier),
        "auto_reject_threshold",
        property(lambda self: 0.3),
    )
    approved = classifier.classify_rss_item(_rss_item(), "完整政策正文")
    assert approved.success is True
    assert approved.audit_status == AuditStatus.AUTO_APPROVED
    assert approved.policy_level == PolicyLevel.P2
    assert approved.structured_data is not None
    assert approved.structured_data.policy_subject == "央行"

    helper.chat_completion_with_failover = lambda **kwargs: {
        "status": "error",
        "error_message": "timeout",
        "model": "fake-model",
    }
    failed = classifier.classify_rss_item(_rss_item())
    assert failed.success is False
    assert failed.error_message == "AI policy classification unavailable"
    assert "timeout" not in failed.error_message
    assert failed.processing_metadata["error_code"] == "ai_policy_provider_unavailable"

    assert classifier._parse_ai_response('```json\n{"confidence": 0.5}\n```') == {"confidence": 0.5}
    assert classifier._parse_ai_response('prefix {"confidence": 0.4} suffix') == {"confidence": 0.4}
    with pytest.raises(ValueError, match="not valid JSON"):
        classifier._parse_ai_response("not-json")
    assert len(classifier.batch_classify([(_rss_item(), None)])) == 1


@pytest.mark.parametrize(
    "override",
    [
        {"confidence": float("nan")},
        {"confidence": 1.1},
        {"info_category": "invented"},
        {"risk_impact": "invented"},
        {"structured_data": []},
        {"structured_data": {"affected_sectors": ["银行", 1]}},
        {"structured_data": {"sentiment_score": float("inf")}},
    ],
)
def test_ai_classifier_rejects_untrusted_model_output(override: dict[str, object]) -> None:
    """Malformed model output must not create a successful policy classification."""
    payload: dict[str, object] = {
        "info_category": "macro",
        "confidence": 0.8,
        "risk_impact": "medium_risk",
        "structured_data": {},
    }
    payload.update(override)
    helper = SimpleNamespace(
        chat_completion_with_failover=lambda **kwargs: {
            "status": "success",
            "content": json.dumps(payload),
            "model": "fake-model",
        }
    )

    result = AIPolicyClassifier(helper).classify_rss_item(_rss_item())

    assert result.success is False
    assert result.error_message == "AI policy response invalid"
    assert result.processing_metadata["error_code"] == "ai_policy_response_invalid"
    assert "raw_response" not in result.processing_metadata


class _FeedEntry(dict[str, object]):
    published_parsed: time.struct_time | None
    updated_parsed: time.struct_time | None

    def __init__(self, payload: dict[str, object], published: time.struct_time | None) -> None:
        super().__init__(payload)
        self.published_parsed = published
        self.updated_parsed = None


def test_feedparser_adapter_fetches_parses_skips_and_retries(monkeypatch) -> None:
    """Feed parsing keeps valid items, skips malformed entries, and bounds retries."""
    adapter = feedparser_adapter.FeedparserAdapter()
    config = RSSSourceConfig(
        name="central-bank",
        url="https://rss.test/feed",
        category="central_bank",
        is_active=True,
        fetch_interval_hours=1,
        extract_content=False,
        timeout_seconds=5,
        retry_times=2,
    )
    response = SimpleNamespace(
        content=b"<rss/>",
        raise_for_status=lambda: None,
    )
    monkeypatch.setattr(rss_gateway.requests, "get", lambda *args, **kwargs: response)
    published = time.gmtime(1_721_779_200)
    valid = _FeedEntry(
        {
            "title": "央行政策",
            "link": "https://policy.test/item",
            "description": "支持实体经济",
            "guid": "guid-1",
            "author": "PBOC",
        },
        published,
    )
    missing_title = _FeedEntry({"link": "https://policy.test/bad"}, published)
    monkeypatch.setattr(
        rss_gateway,
        "import_module",
        lambda name: SimpleNamespace(
            parse=lambda content: SimpleNamespace(
                bozo=True,
                bozo_exception=ValueError("minor warning"),
                entries=[valid, missing_title],
            )
        ),
    )
    items = adapter.fetch(config)
    assert len(items) == 1
    assert items[0].guid == "guid-1"
    assert items[0].pub_date.tzinfo is not None

    attempts: list[int] = []

    def _timeout(*args: object, **kwargs: object) -> object:
        attempts.append(1)
        raise rss_gateway.requests.Timeout("slow")

    monkeypatch.setattr(rss_gateway.requests, "get", _timeout)
    monkeypatch.setattr(rss_gateway, "sleep", lambda seconds: None)
    with pytest.raises(RSSFetchError, match="2 retries"):
        adapter.fetch(
            RSSSourceConfig(
                name=config.name,
                url=config.url,
                category=config.category,
                is_active=True,
                fetch_interval_hours=1,
                extract_content=False,
                timeout_seconds=1,
                retry_times=2,
            )
        )
    assert len(attempts) == 2

    no_date = _FeedEntry(
        {"title": "Fallback date", "link": "https://policy.test/fallback"},
        None,
    )
    assert adapter._parse_pub_date(no_date).tzinfo is not None
