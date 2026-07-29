"""Policy RSS ingestion orchestration contracts without network or ORM."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from apps.policy.application.repository_provider import ContentExtractorError
from apps.policy.application.rss_fetch_use_cases import FetchRSSInput, FetchRSSUseCase
from apps.policy.domain.entities import (
    AIClassificationResult,
    AuditStatus,
    InfoCategory,
    PolicyEvent,
    PolicyLevel,
    RiskImpact,
    RSSItem,
    StructuredPolicyData,
)
from core.exceptions import AIServiceError, DataFetchError


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


def test_execute_isolates_external_configuration_and_recoverable_source_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One broken feed cannot abort other feeds or be counted as processed."""
    sources = [
        _source(source_id=1),
        _source(source_id=2),
        _source(source_id=3),
    ]
    sources[0].name = "external"
    sources[1].name = "configuration"
    sources[2].name = "recoverable"
    use_case = _use_case(_RSSRepo(sources), _PolicyRepo())
    failures = iter(
        (
            DataFetchError("provider offline"),
            ValueError("bad parser"),
            RuntimeError("unexpected processing failure"),
        )
    )
    monkeypatch.setattr(
        use_case,
        "_fetch_single_source",
        lambda source, force: (_ for _ in ()).throw(next(failures)),
    )

    output = use_case.execute(FetchRSSInput())

    assert output.success is False
    assert output.sources_processed == 0
    assert len(output.errors) == 3
    assert "外部服务" in output.errors[0]
    assert "配置错误" in output.errors[1]
    assert "未预期" in output.errors[2]


def test_unknown_parser_is_rejected_before_fetch_side_effect() -> None:
    """Unsupported parser types are configuration errors, not empty successful feeds."""
    source = _source()
    source.parser_type = "unknown"
    use_case = _use_case(_RSSRepo([source]), _PolicyRepo())
    with pytest.raises(ValueError, match="Unknown parser type"):
        use_case._fetch_single_source(source, force_refetch=False)


def test_failed_ai_classification_retries_with_content_and_keeps_pending_level() -> None:
    """Failed first-pass AI can enrich metadata after extraction without inventing a level."""
    rss_repo = _RSSRepo([_source(extract=True)])
    policy_repo = _PolicyRepo()
    failed = AIClassificationResult(
        success=False,
        error_message="insufficient context",
    )
    enriched = AIClassificationResult(
        success=True,
        info_category=InfoCategory.SECTOR,
        audit_status=AuditStatus.PENDING_REVIEW,
        ai_confidence=0.7,
        risk_impact=RiskImpact.HIGH_RISK,
    )
    results = iter((failed, enriched))
    classifier = SimpleNamespace(classify_rss_item=lambda *args, **kwargs: next(results))
    use_case = _use_case(
        rss_repo,
        policy_repo,
        classifier=classifier,
    )
    use_case._matcher_class = lambda rules: SimpleNamespace(match=lambda item: None)
    use_case._extractor_factory = {
        "hybrid": SimpleNamespace(extract=lambda **kwargs: "full policy content")
    }

    output = use_case.execute(FetchRSSInput(source_id=1))

    assert output.success is True
    assert policy_repo.updated[0]["level"] == PolicyLevel.PENDING.value
    assert policy_repo.updated[0]["info_category"] == InfoCategory.SECTOR.value
    assert policy_repo.updated[0]["risk_impact"] == RiskImpact.HIGH_RISK.value
    assert policy_repo.queued[0]["priority"] == "high"


@pytest.mark.parametrize(
    "exception",
    [
        AIServiceError("classifier timeout"),
        RuntimeError("classifier malformed response"),
    ],
)
def test_ai_classification_failures_fall_back_to_keyword_rules(exception: Exception) -> None:
    """AI boundary failures remain recoverable and preserve deterministic keyword fallback."""
    rss_repo = _RSSRepo([_source()])
    policy_repo = _PolicyRepo()
    classifier = SimpleNamespace(
        classify_rss_item=lambda *args, **kwargs: (_ for _ in ()).throw(exception)
    )
    output = _use_case(
        rss_repo,
        policy_repo,
        classifier=classifier,
    ).execute(FetchRSSInput(source_id=1))
    assert output.success is True
    assert policy_repo.updated[0]["level"] == PolicyLevel.P1.value


def test_content_extraction_failure_preserves_original_description() -> None:
    """Extractor failure does not erase or replace the original RSS evidence."""
    rss_repo = _RSSRepo([_source(extract=True)])
    policy_repo = _PolicyRepo()
    use_case = _use_case(rss_repo, policy_repo)
    use_case._extractor_factory = {
        "hybrid": SimpleNamespace(
            extract=lambda **kwargs: (_ for _ in ()).throw(ContentExtractorError("article blocked"))
        )
    }
    output = use_case.execute(FetchRSSInput(source_id=1))
    assert output.success is True
    assert policy_repo.updated[0]["description"] == "支持实体经济"


def test_early_item_failure_saves_pending_raw_record_and_survives_save_failure() -> None:
    """Two-phase persistence retains failed items where possible and isolates save failure."""

    class _EarlyFailurePolicyRepo(_PolicyRepo):
        def __init__(self, *, fail_recovery: bool = False) -> None:
            super().__init__()
            self.calls = 0
            self.fail_recovery = fail_recovery

        def create_raw_rss_policy_log(self, **kwargs: object) -> dict[str, object]:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("initial persistence failed")
            if self.fail_recovery:
                raise RuntimeError("recovery persistence failed")
            return super().create_raw_rss_policy_log(**kwargs)

    rss_repo = _RSSRepo([_source()])
    recovered_repo = _EarlyFailurePolicyRepo()
    recovered = _use_case(rss_repo, recovered_repo).execute(FetchRSSInput(source_id=1))
    assert recovered.success is True
    assert recovered.new_policy_events == 1
    assert recovered_repo.created[0]["processing_metadata"]["saved_as_pending"] is True

    failed_repo = _EarlyFailurePolicyRepo(fail_recovery=True)
    isolated = _use_case(_RSSRepo([_source()]), failed_repo).execute(FetchRSSInput(source_id=1))
    assert isolated.success is True
    assert isolated.new_policy_events == 0


def test_proxy_config_and_alert_helpers_cover_absent_and_failed_delivery() -> None:
    """Proxy credentials normalize and notification failures never abort ingestion."""
    source = _source()
    source.proxy_enabled = True
    source.proxy_host = "proxy"
    source.proxy_port = 8080
    source.proxy_username = "user"
    source.proxy_password = "secret"
    source.proxy_type = "https"
    use_case = _use_case(_RSSRepo([source]), _PolicyRepo())
    config = use_case._orm_to_domain_config(source)
    assert config.proxy_config is not None
    assert config.proxy_config.host == "proxy"
    assert config.proxy_config.username == "user"

    event = PolicyEvent(
        event_date=date(2026, 7, 24),
        level=PolicyLevel.P2,
        title="policy",
        description="description",
        evidence_url="https://evidence.test",
    )
    assert use_case._send_alert_for_rss_event(event) is False
    assert (
        use_case._send_alert_for_rss_event_enhanced(
            level=PolicyLevel.P2,
            title="policy",
            description="description",
            event_date=event.event_date,
            evidence_url=event.evidence_url,
            info_category=InfoCategory.MACRO,
            risk_impact=RiskImpact.HIGH_RISK,
        )
        is False
    )

    use_case.alert_service = SimpleNamespace(
        send_alert=lambda **kwargs: (_ for _ in ()).throw(RuntimeError("notification offline"))
    )
    assert use_case._send_alert_for_rss_event(event) is False
    assert (
        use_case._send_alert_for_rss_event_enhanced(
            level=PolicyLevel.P3,
            title="policy",
            description="description",
            event_date=event.event_date,
            evidence_url=event.evidence_url,
            info_category=InfoCategory.MACRO,
            risk_impact=RiskImpact.HIGH_RISK,
            structured_data={
                "summary": "summary",
                "affected_sectors": ["bank"],
                "sentiment": "negative",
            },
        )
        is False
    )
