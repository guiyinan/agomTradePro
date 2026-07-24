"""Policy admin presentation and bulk-action contracts."""

from __future__ import annotations

from types import SimpleNamespace

from django.contrib.admin.sites import AdminSite

from apps.policy.interface import admin as module


class _Query:
    def __init__(self, ids: list[int]) -> None:
        self.ids = ids

    def values_list(self, *args: object, **kwargs: object) -> list[int]:
        return self.ids

    def update(self, **kwargs: object) -> int:
        return len(self.ids)

    def count(self) -> int:
        return len(self.ids)

    def __iter__(self):
        return iter([])


def test_policy_admin_badges_render_all_risk_and_evidence_states(monkeypatch) -> None:
    """Admin columns make policy risk, review status, and evidence visible."""
    admin = module.PolicyLogAdmin(module.PolicyLog, AdminSite())
    base = {
        "level": "P3",
        "info_category": "macro",
        "audit_status": "manual_approved",
        "get_level_display": lambda: "危机",
        "get_info_category_display": lambda: "宏观",
        "get_audit_status_display": lambda: "人工通过",
        "evidence_url": "https://evidence.test",
    }
    high = SimpleNamespace(**base, ai_confidence=0.9)
    medium = SimpleNamespace(**base, ai_confidence=0.6)
    low = SimpleNamespace(**base, ai_confidence=0.2)
    missing = SimpleNamespace(**base, ai_confidence=None)
    assert "危机" in str(admin.level_badge(high))
    assert "宏观" in str(admin.category_badge(high))
    assert "人工通过" in str(admin.audit_status_badge(high))
    assert "0.90" in str(admin.ai_confidence_display(high))
    assert "0.60" in str(admin.ai_confidence_display(medium))
    assert "0.20" in str(admin.ai_confidence_display(low))
    assert admin.ai_confidence_display(missing) == "-"
    assert "https://evidence.test" in str(admin.evidence_link(high))
    no_evidence = SimpleNamespace(**{**base, "evidence_url": ""}, ai_confidence=0.5)
    assert admin.evidence_link(no_evidence) == "-"


def test_policy_admin_bulk_level_and_list_actions_delegate_to_service(monkeypatch) -> None:
    """Bulk actions pass exact IDs and mutually exclusive list flags."""
    calls: list[tuple[str, object]] = []
    service = SimpleNamespace(
        mark_policy_logs_level=lambda ids, level: calls.append((level, ids)) or len(ids),
        set_policy_list_flags=lambda ids, **flags: calls.append(("flags", flags)) or len(ids),
    )
    monkeypatch.setattr(module, "_policy_admin_service", lambda: service)
    admin = module.PolicyLogAdmin(module.PolicyLog, AdminSite())
    monkeypatch.setattr(admin, "message_user", lambda *args, **kwargs: None)
    query = _Query([1, 2])
    request = SimpleNamespace(user=SimpleNamespace())
    admin.mark_as_p0(request, query)
    admin.mark_as_p1(request, query)
    admin.mark_as_p2(request, query)
    admin.mark_as_p3(request, query)
    admin.add_to_whitelist(request, query)
    admin.add_to_blacklist(request, query)
    assert [call[0] for call in calls[:4]] == ["P0", "P1", "P2", "P3"]
    assert calls[4][1] == {"is_whitelist": True, "is_blacklist": False}
    assert calls[5][1] == {"is_whitelist": False, "is_blacklist": True}


def test_rss_keyword_fetch_and_audit_admin_columns_cover_boundaries(monkeypatch) -> None:
    """RSS and audit queue columns handle enabled, empty, slow, and truncated values."""
    site = AdminSite()
    rss_config_admin = module.RSSHubGlobalConfigAdmin(module.RSSHubGlobalConfig, site)
    assert "已启用" in str(rss_config_admin.enabled_badge(SimpleNamespace(enabled=True)))
    assert "未启用" in str(rss_config_admin.enabled_badge(SimpleNamespace(enabled=False)))
    assert "已配置" in str(rss_config_admin.has_key_badge(SimpleNamespace(access_key="secret")))
    assert "未配置" in str(rss_config_admin.has_key_badge(SimpleNamespace(access_key="")))

    source_admin = module.RSSSourceConfigAdmin(module.RSSSourceConfigModel, site)
    source = SimpleNamespace(
        category="csrc",
        get_category_display=lambda: "证监会",
        rsshub_enabled=True,
        get_effective_url=lambda: "https://example.test/" + "x" * 120,
        last_fetch_status="success",
    )
    assert "证监会" in str(source_admin.category_badge(source))
    assert "RSSHub" in str(source_admin.rsshub_badge(source))
    assert "..." in str(source_admin.effective_url_display(source))
    assert "SUCCESS" in str(source_admin.last_fetch_status_badge(source))
    source.last_fetch_status = ""
    assert source_admin.last_fetch_status_badge(source) == "-"

    keyword_admin = module.PolicyLevelKeywordAdmin(module.PolicyLevelKeywordModel, site)
    keyword = SimpleNamespace(
        level="P2",
        get_level_display=lambda: "干预",
        keywords=["a", "b", "c", "d", "e", "f"],
    )
    assert "干预" in str(keyword_admin.level_badge(keyword))
    assert "(+1)" in keyword_admin.keywords_preview(keyword)

    fetch_admin = module.RSSFetchLogAdmin(module.RSSFetchLog, site)
    assert fetch_admin.duration_badge(SimpleNamespace(fetch_duration_seconds=None)) == "-"
    assert "500ms" in str(fetch_admin.duration_badge(SimpleNamespace(fetch_duration_seconds=0.5)))
    assert "2.0s" in str(fetch_admin.duration_badge(SimpleNamespace(fetch_duration_seconds=2.0)))
    assert "8.0s" in str(fetch_admin.duration_badge(SimpleNamespace(fetch_duration_seconds=8.0)))

    queue_admin = module.PolicyAuditQueueAdmin(module.PolicyAuditQueue, site)
    policy = SimpleNamespace(
        title="x" * 60,
        level="P3",
        get_info_category_display=lambda: "宏观",
    )
    item = SimpleNamespace(
        policy_log=policy,
        priority="urgent",
        get_priority_display=lambda: "紧急",
    )
    assert queue_admin.policy_title(item).endswith("...")
    assert "P3" in str(queue_admin.policy_level(item))
    assert queue_admin.policy_category(item) == "宏观"
    assert "紧急" in str(queue_admin.priority_badge(item))
