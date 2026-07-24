"""Policy RSS ingestion orchestration contracts without network or ORM."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from apps.policy.application.rss_fetch_use_cases import FetchRSSInput, FetchRSSUseCase
from apps.policy.domain.entities import (
    AIClassificationResult,
    AuditStatus,
    InfoCategory,
    PolicyLevel,
    RiskImpact,
    RSSItem,
    StructuredPolicyData,
)


def _source(*, source_id: int = 1, active: bool = True, extract: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        id=source_id,
        name="contract-feed",
        url="https://feed.test/rss",
        category="macro",
        parser_type="feedparser",
        extract_content=extract,
        is_active=active,
        fetch_interval_hours=1,
        timeout_seconds=5,
        retry_times=1,
        proxy_enabled=False,
        proxy_host="",
        proxy_port=0,
        proxy_username="",
        proxy_password="",
        proxy_type="http",
        rsshub_enabled=False,
        rsshub_route_path="",
        rsshub_use_global_config=True,
        rsshub_custom_base_url="",
        rsshub_custom_access_key="",
        rsshub_format="",
        get_effective_url=lambda: "https://feed.test/rss",
    )


class _RSSRepo:
    def __init__(self, sources: list[SimpleNamespace]) -> None:
        self.sources = sources
        self.logs: list[dict[str, object]] = []
        self.existing = False

    def get_source_by_id(self, source_id: int) -> SimpleNamespace | None:
        return next((item for item in self.sources if item.id == source_id), None)

    def get_active_sources(self) -> list[SimpleNamespace]:
        return [item for item in self.sources if item.is_active]

    def get_active_keyword_rules(self, category: str) -> list[object]:
        return []

    def is_item_exists(self, link: str, guid: str | None) -> bool:
        return self.existing

    def save_fetch_log(self, **kwargs: object) -> None:
        self.logs.append(dict(kwargs))

    def update_source_last_fetch(self, *args: object, **kwargs: object) -> None:
        return None


class _PolicyRepo:
    def __init__(self) -> None:
        self.created: list[dict[str, object]] = []
        self.updated: list[dict[str, object]] = []
        self.queued: list[dict[str, object]] = []

    def create_raw_rss_policy_log(self, **kwargs: object) -> dict[str, object]:
        record = {"id": len(self.created) + 1, **kwargs}
        self.created.append(record)
        return record

    def update_policy_log_fields(self, record_id: int, **kwargs: object) -> None:
        self.updated.append({"id": record_id, **kwargs})

    def ensure_audit_queue_item(self, **kwargs: object) -> dict[str, bool]:
        self.queued.append(dict(kwargs))
        return {"created": True}

    def append_policy_log_processing_metadata(
        self,
        record_id: int,
        metadata: dict[str, object],
    ) -> None:
        self.updated.append({"id": record_id, "processing_metadata": metadata})


class _Alert:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def send_alert(self, **kwargs: str) -> bool:
        self.calls.append(kwargs)
        return True


def _item() -> RSSItem:
    return RSSItem(
        title="央行宣布降准",
        link="https://item.test/1",
        guid="item-1",
        pub_date=datetime(2026, 7, 24, tzinfo=UTC),
        description="支持实体经济",
    )


def _use_case(
    rss_repo: _RSSRepo,
    policy_repo: _PolicyRepo,
    *,
    classifier: object | None = None,
    alert: _Alert | None = None,
) -> FetchRSSUseCase:
    use_case = FetchRSSUseCase(
        rss_repository=rss_repo,
        policy_repository=policy_repo,
        ai_classifier=classifier,
        alert_service=alert,
    )
    use_case._adapter_factory = {"feedparser": SimpleNamespace(fetch=lambda config: [_item()])}
    use_case._matcher_class = lambda rules: SimpleNamespace(match=lambda item: PolicyLevel.P1)
    return use_case


def test_execute_rejects_missing_disabled_and_empty_sources() -> None:
    """Source selection fails closed before any fetch side effect."""
    empty = _use_case(_RSSRepo([]), _PolicyRepo())
    assert empty.execute(FetchRSSInput()).errors == ["没有启用的RSS源"]
    assert "不存在" in empty.execute(FetchRSSInput(source_id=99)).errors[0]

    disabled = _use_case(_RSSRepo([_source(active=False)]), _PolicyRepo())
    assert "已停用" in disabled.execute(FetchRSSInput(source_id=1)).errors[0]


def test_fetch_ai_classification_extraction_queue_and_alert_paths() -> None:
    """Successful AI classification persists evidence, queues review, and alerts P2."""
    rss_repo = _RSSRepo([_source(extract=True)])
    policy_repo = _PolicyRepo()
    alert = _Alert()
    classification = AIClassificationResult(
        success=True,
        info_category=InfoCategory.MACRO,
        audit_status=AuditStatus.PENDING_REVIEW,
        ai_confidence=0.8,
        policy_level=PolicyLevel.P2,
        structured_data=StructuredPolicyData(
            summary="降准支持实体经济",
            affected_sectors=["银行"],
            sentiment="positive",
        ),
        risk_impact=RiskImpact.HIGH_RISK,
        processing_metadata={"provider": "fake"},
    )
    classifier = SimpleNamespace(classify_rss_item=lambda item, content=None: classification)
    use_case = _use_case(
        rss_repo,
        policy_repo,
        classifier=classifier,
        alert=alert,
    )
    use_case._extractor_factory = {
        "hybrid": SimpleNamespace(extract=lambda **kwargs: "完整正文" * 100)
    }
    output = use_case.execute(FetchRSSInput(source_id=1))
    assert output.success is True
    assert output.new_policy_events == 1
    assert policy_repo.updated[0]["level"] == "P2"
    assert policy_repo.updated[0]["description"].startswith("完整正文")
    assert policy_repo.queued[0]["priority"] == "urgent"
    assert alert.calls[0]["level"] == "warning"


def test_fetch_duplicate_empty_feed_and_keyword_fallback_statuses() -> None:
    """Fetch status distinguishes duplicates, empty feeds, and keyword fallback."""
    rss_repo = _RSSRepo([_source()])
    policy_repo = _PolicyRepo()
    use_case = _use_case(rss_repo, policy_repo)
    rss_repo.existing = True
    duplicate = use_case._fetch_single_source(_source(), force_refetch=False)
    assert duplicate["status"] == "partial"

    use_case._adapter_factory["feedparser"] = SimpleNamespace(fetch=lambda config: [])
    empty = use_case._fetch_single_source(_source(), force_refetch=False)
    assert empty["status"] == "error"

    rss_repo.existing = False
    use_case._adapter_factory["feedparser"] = SimpleNamespace(fetch=lambda config: [_item()])
    success = use_case._fetch_single_source(_source(), force_refetch=False)
    assert success["status"] == "success"
    assert policy_repo.updated[-1]["level"] == "P1"
    assert policy_repo.queued[-1]["priority"] == "normal"
