import uuid
from datetime import datetime

import pytest

from apps.policy.application.use_cases import FetchRSSUseCase
from apps.policy.domain.entities import PolicyLevel, RSSItem
from apps.policy.infrastructure.models import PolicyLog, RSSSourceConfigModel
from apps.policy.infrastructure.repositories import DjangoPolicyRepository


class _DummyAdapter:
    def __init__(self, items):
        self._items = items

    def fetch(self, _source_config):
        return self._items


class _DummyRSSRepo:
    def __init__(self):
        self.fetch_logs = []
        self.updated_sources = []

    def is_item_exists(self, link, guid):
        return False

    def get_active_keyword_rules(self, category=None):
        return []

    def save_fetch_log(self, **kwargs):
        self.fetch_logs.append(kwargs)

    def update_source_last_fetch(self, source_id, status, error_msg=None):
        self.updated_sources.append((source_id, status, error_msg))


class _MatcherP1:
    def __init__(self, _rules):
        pass

    def match(self, _item):
        return PolicyLevel.P1


class _MatcherRaises:
    def __init__(self, _rules):
        pass

    def match(self, _item):
        raise RuntimeError("forced matcher error")


@pytest.mark.django_db
def test_fetch_single_source_two_phase_success_updates_existing_raw_record():
    unique = uuid.uuid4().hex[:8]
    title = f"rss-success-{unique}"
    link = f"https://example.com/{unique}"
    guid = f"guid-{unique}"

    source = RSSSourceConfigModel.objects.create(
        name=f"source-{unique}",
        url=f"https://source.example.com/{unique}.xml",
        category="other",
        parser_type="feedparser",
        extract_content=False,
        is_active=True,
    )

    rss_repo = _DummyRSSRepo()
    use_case = FetchRSSUseCase(
        rss_repository=rss_repo,
        policy_repository=DjangoPolicyRepository(),
        ai_classifier=None,
    )
    use_case._matcher_class = _MatcherP1
    use_case._adapter_factory = {
        "feedparser": _DummyAdapter([
            RSSItem(
                title=title,
                link=link,
                guid=guid,
                pub_date=datetime.now(),
                description="desc",
            )
        ])
    }

    result = use_case._fetch_single_source(source, force_refetch=False)

    assert result["new_events_count"] == 1
    saved = PolicyLog.objects.get(rss_item_guid=guid)
    assert saved.level == "P1"
    assert saved.audit_status == "pending_review"
    assert saved.processing_metadata.get("processing_stage") == "processed"


@pytest.mark.django_db
def test_fetch_single_source_two_phase_failure_keeps_pending_raw_record():
    unique = uuid.uuid4().hex[:8]
    title = f"rss-fail-{unique}"
    link = f"https://example.com/{unique}"
    guid = f"guid-{unique}"

    source = RSSSourceConfigModel.objects.create(
        name=f"source-fail-{unique}",
        url=f"https://source.example.com/{unique}.xml",
        category="other",
        parser_type="feedparser",
        extract_content=False,
        is_active=True,
    )

    rss_repo = _DummyRSSRepo()
    use_case = FetchRSSUseCase(
        rss_repository=rss_repo,
        policy_repository=DjangoPolicyRepository(),
        ai_classifier=None,
    )
    use_case._matcher_class = _MatcherRaises
    use_case._adapter_factory = {
        "feedparser": _DummyAdapter([
            RSSItem(
                title=title,
                link=link,
                guid=guid,
                pub_date=datetime.now(),
                description="desc",
            )
        ])
    }

    result = use_case._fetch_single_source(source, force_refetch=False)

    assert result["new_events_count"] == 1
    saved = PolicyLog.objects.get(rss_item_guid=guid)
    assert saved.level == "PX"
    assert saved.audit_status == "pending_review"
    assert saved.processing_metadata.get("saved_as_pending") is True
    assert saved.processing_metadata.get("processing_stage") == "failed"
