"""Policy content-adapter and event-use-case boundary contracts."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest
from django.db import DatabaseError

from apps.policy.application.event_use_cases import (
    CreatePolicyEventInput,
    CreatePolicyEventUseCase,
    GetCurrentPolicyUseCase,
    GetPolicyStatusUseCase,
)
from apps.policy.application.services import (
    PolicyLevelMatcher,
    extract_policy_level_from_title,
)
from apps.policy.domain.entities import PolicyEvent, PolicyLevel, PolicyLevelKeywordRule, RSSItem
from apps.policy.infrastructure.adapters import content_extractor as module


class _Response:
    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        return None


class _Client:
    response_text = ""

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs

    def __enter__(self) -> _Client:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def get(self, url: str, headers: dict[str, str]) -> _Response:
        return _Response(self.response_text)


def test_content_extractors_clean_proxy_select_fallback_and_custom_paths(monkeypatch) -> None:
    """HTML extraction removes noise, supports proxies, and falls back deterministically."""
    base = module.BaseContentExtractor()
    assert base._clean_text("  hello\n\x00 world ") == "hello world"
    assert base._build_proxies(None) is None
    assert (
        base._build_proxies(
            {
                "proxy_type": "https",
                "username": "u",
                "password": "p",
                "host": "proxy",
                "port": 8443,
            }
        )
        == "https://u:p@proxy:8443"
    )
    with pytest.raises(NotImplementedError):
        base.extract("https://example.test")

    _Client.response_text = (
        "<html><script>noise</script><article>"
        + ("policy intervention evidence " * 20)
        + "</article></html>"
    )
    monkeypatch.setattr(module.httpx, "Client", _Client)
    extracted = module.BeautifulSoupExtractor().extract("https://example.test")
    assert len(extracted) > 200
    assert "noise" not in extracted

    _Client.response_text = '<html><meta name="description" content="short policy summary"></html>'
    assert module.BeautifulSoupExtractor().extract("https://example.test") == "short policy summary"

    _Client.response_text = '<html><div class="target">custom policy text</div></html>'
    assert (
        module.BeautifulSoupExtractor().extract_with_custom_selector(
            "https://example.test",
            ".target",
        )
        == "custom policy text"
    )
    with pytest.raises(module.ContentExtractorError, match="All extraction"):
        hybrid = module.HybridContentExtractor()
        monkeypatch.setattr(
            hybrid.readability_extractor,
            "extract",
            lambda *args: (_ for _ in ()).throw(module.ContentExtractorError("first")),
        )
        monkeypatch.setattr(
            hybrid.bs4_extractor,
            "extract",
            lambda *args: (_ for _ in ()).throw(module.ContentExtractorError("second")),
        )
        hybrid.extract("https://example.test")

    assert isinstance(module.create_content_extractor("bs4"), module.BeautifulSoupExtractor)
    assert isinstance(module.create_content_extractor("hybrid"), module.HybridContentExtractor)
    with pytest.raises(ValueError, match="Unsupported"):
        module.create_content_extractor("unknown")


def test_readability_extractor_handles_optional_dependencies_fallback_and_http_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Readability extraction has explicit dependency, HTML fallback, and HTTP failures."""
    extractor = module.ReadabilityExtractor()
    with monkeypatch.context() as scoped:
        scoped.setattr(module, "Document", None)
        with pytest.raises(module.ContentExtractorError, match="readability-lxml"):
            extractor.extract("https://example.test")

    class _Document:
        def __init__(self, html: str) -> None:
            self.html = html

        def summary(self) -> str:
            return "<article>policy evidence body</article>"

    _Client.response_text = "<html>source</html>"
    monkeypatch.setattr(module, "Document", _Document)
    monkeypatch.setattr(module.httpx, "Client", _Client)
    with monkeypatch.context() as scoped:
        scoped.setattr(module, "BeautifulSoup", None)
        assert extractor.extract("https://example.test") == "policy evidence body"

    class _HTTPFailureClient(_Client):
        def get(self, url: str, headers: dict[str, str]) -> _Response:
            raise module.httpx.HTTPError("upstream timeout")

    monkeypatch.setattr(module.httpx, "Client", _HTTPFailureClient)
    with pytest.raises(module.ContentExtractorError, match="HTTP error"):
        extractor.extract("https://example.test")

    monkeypatch.setattr(module.httpx, "Client", _Client)
    monkeypatch.setattr(
        module,
        "Document",
        lambda html: (_ for _ in ()).throw(ValueError("malformed document")),
    )
    with pytest.raises(module.ContentExtractorError, match="Failed to extract"):
        extractor.extract("https://example.test")


def test_beautifulsoup_extractor_reports_missing_dependencies_content_and_selector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BeautifulSoup extraction distinguishes dependency and content failures."""
    extractor = module.BeautifulSoupExtractor()
    with monkeypatch.context() as scoped:
        scoped.setattr(module, "BeautifulSoup", None)
        with pytest.raises(module.ContentExtractorError, match="beautifulsoup4"):
            extractor.extract("https://example.test")

    with monkeypatch.context() as scoped:
        scoped.setattr(module, "httpx", None)
        with pytest.raises(module.ContentExtractorError, match="httpx"):
            extractor.extract("https://example.test")
        with pytest.raises(module.ContentExtractorError, match="httpx"):
            extractor.extract_with_custom_selector("https://example.test", ".article")

    _Client.response_text = "<html><body><div>short</div></body></html>"
    monkeypatch.setattr(module.httpx, "Client", _Client)
    with pytest.raises(module.ContentExtractorError, match="Could not extract"):
        extractor.extract("https://example.test")
    with pytest.raises(module.ContentExtractorError, match="Element not found"):
        extractor.extract_with_custom_selector("https://example.test", ".missing")

    class _HTTPFailureClient(_Client):
        def get(self, url: str, headers: dict[str, str]) -> _Response:
            raise module.httpx.HTTPError("upstream timeout")

    monkeypatch.setattr(module.httpx, "Client", _HTTPFailureClient)
    with pytest.raises(module.ContentExtractorError, match="HTTP error"):
        extractor.extract("https://example.test")
    with pytest.raises(module.ContentExtractorError, match="HTTP error"):
        extractor.extract_with_custom_selector("https://example.test", ".article")


def _event(level: PolicyLevel = PolicyLevel.P1) -> PolicyEvent:
    return PolicyEvent(
        event_date=date(2026, 7, 24),
        level=level,
        title="Policy transition",
        description="Evidence-backed policy intervention description",
        evidence_url="https://evidence.test/policy",
    )


def test_create_policy_event_validates_saves_transitions_and_alerts(monkeypatch) -> None:
    """Creation validates input, persists once, and emits high-risk alert evidence."""
    saved: list[PolicyEvent] = []
    store = SimpleNamespace(
        get_latest_event=lambda before_date=None: _event(PolicyLevel.P1),
        save_event=lambda event: saved.append(event) or event,
    )
    alerts: list[dict[str, object]] = []
    alert_service = SimpleNamespace(send_alert=lambda **kwargs: alerts.append(kwargs) or True)
    use_case = CreatePolicyEventUseCase(store, alert_service)
    output = use_case.execute(
        CreatePolicyEventInput(
            event_date=date(2026, 7, 24),
            level=PolicyLevel.P3,
            title="Emergency intervention",
            description="Emergency liquidity intervention with formal evidence",
            evidence_url="https://evidence.test/emergency",
        )
    )
    assert output.success is True
    assert output.alert_triggered is True
    assert saved[0].level == PolicyLevel.P3
    assert alerts[0]["level"] == "critical"
    assert any("档位升级" in warning for warning in output.warnings)

    invalid = use_case.execute(
        CreatePolicyEventInput(
            event_date=date(2026, 7, 24),
            level=PolicyLevel.P1,
            title="",
            description="",
            evidence_url="bad",
        )
    )
    assert invalid.success is False
    assert invalid.errors


def test_policy_queries_return_default_status_and_recoverable_errors(monkeypatch) -> None:
    """Generic stores default to P0 and current-level errors remain explicit."""
    generic = SimpleNamespace(get_latest_event=lambda before_date=None: None)
    status = GetPolicyStatusUseCase(generic).execute(date(2026, 7, 24))
    assert status.current_level == PolicyLevel.P0
    assert status.is_intervention_active is False
    assert status.is_crisis_mode is False

    current = GetCurrentPolicyUseCase(
        SimpleNamespace(get_current_policy_level=lambda as_of: PolicyLevel.P2)
    ).execute()
    assert current.success is True
    assert current.policy_level == PolicyLevel.P2

    failed = GetCurrentPolicyUseCase(
        SimpleNamespace(
            get_current_policy_level=lambda as_of: (_ for _ in ()).throw(
                ValueError("invalid state")
            )
        )
    ).execute()
    assert failed.success is False
    assert failed.error == "policy_state_unavailable"


def test_create_policy_event_redacts_persistence_failures() -> None:
    store = SimpleNamespace(
        get_latest_event=lambda before_date=None: None,
        save_event=lambda event: (_ for _ in ()).throw(DatabaseError("database-secret-detail")),
    )
    output = CreatePolicyEventUseCase(store).execute(
        CreatePolicyEventInput(
            event_date=date(2026, 7, 24),
            level=PolicyLevel.P2,
            title="Formal intervention",
            description="Evidence-backed policy intervention description",
            evidence_url="https://evidence.test/intervention",
        )
    )

    assert output.success is False
    assert output.errors == ["政策事件保存失败"]
    assert "database-secret-detail" not in " ".join(output.errors)


def test_policy_level_matcher_scores_keywords_and_returns_explainable_details() -> None:
    """Keyword weights select the highest risk level and expose matched evidence."""
    rules = [
        PolicyLevelKeywordRule(
            level=PolicyLevel.P1,
            keywords=["关注", "预期"],
            weight=1,
        ),
        PolicyLevelKeywordRule(
            level=PolicyLevel.P2,
            keywords=["降准", "支持"],
            weight=3,
        ),
        PolicyLevelKeywordRule(
            level=PolicyLevel.P3,
            keywords=["紧急"],
            weight=10,
        ),
    ]
    matcher = PolicyLevelMatcher(rules)
    item = RSSItem(
        title="央行紧急降准支持市场",
        link="https://policy.test",
        pub_date=datetime(2026, 7, 24, tzinfo=UTC),
    )
    assert matcher.match(item) == PolicyLevel.P3
    level, details = matcher.match_with_details(item)
    assert level == PolicyLevel.P3
    assert details["score"] == 10
    assert details["matched_keywords"] == ["紧急"]
    assert details["all_scores"]["P2"] == 6
    unmatched = RSSItem(
        title="普通行业新闻",
        link="https://policy.test/ordinary",
        pub_date=datetime(2026, 7, 24, tzinfo=UTC),
    )
    assert matcher.match(unmatched) is None
    assert extract_policy_level_from_title("央行降准", rules) == PolicyLevel.P2


def test_policy_level_matcher_uses_higher_severity_for_equal_scores() -> None:
    rules = [
        PolicyLevelKeywordRule(PolicyLevel.P1, ["预期"], 1),
        PolicyLevelKeywordRule(PolicyLevel.P3, ["紧急"], 1),
    ]

    assert extract_policy_level_from_title("紧急政策预期", rules) == PolicyLevel.P3


def test_policy_level_matcher_rejects_invalid_rules_and_deduplicates_keywords() -> None:
    with pytest.raises(ValueError, match="blank"):
        PolicyLevelMatcher([PolicyLevelKeywordRule(PolicyLevel.P1, [""], 1)])
    with pytest.raises(ValueError, match="positive"):
        PolicyLevelMatcher([PolicyLevelKeywordRule(PolicyLevel.P2, ["降准"], 0)])
    with pytest.raises(ValueError, match="P1, P2, or P3"):
        PolicyLevelMatcher([PolicyLevelKeywordRule(PolicyLevel.P0, ["常态"], 1)])

    matcher = PolicyLevelMatcher([PolicyLevelKeywordRule(PolicyLevel.P2, ["降准", " 降准 "], 3)])
    item = RSSItem(
        title="央行降准",
        link="https://policy.test/deduplicated",
        pub_date=datetime(2026, 7, 24, tzinfo=UTC),
    )
    level, details = matcher.match_with_details(item)
    assert level == PolicyLevel.P2
    assert details["score"] == 3
    assert details["matched_keywords"] == ["降准"]
